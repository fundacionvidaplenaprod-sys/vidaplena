"""
Módulo de Evaluación Socioeconómica y Categorización de Beneficiarios.

- El beneficiario llena y sube evidencias de su propia evaluación desde el
  autoregistro (endpoints `/me`), sin poder ver ni tocar las de otros.
- SUPER_ADMIN y EVALUADOR_SOCIAL revisan, avalan o rechazan las evaluaciones
  enviadas (endpoints staff).
"""
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app import models, schemas
from app.core.firebase import upload_file_to_firebase
from app.db import get_db
from app.api import deps

router = APIRouter()

MAX_FILE_SIZE_MB = 5
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/jpg"]

# ==============================================================================
# MOTOR DE CATEGORIZACIÓN
# ==============================================================================

CATEGORIA_A_MAX_PER_CAPITA = 500.0
CATEGORIA_B_MAX_PER_CAPITA = 1200.0
CATEGORIA_C_MAX_PER_CAPITA = 2250.0


def _calcular_categoria(ingreso_per_capita: float, tiene_seguro: bool) -> str:
    """
    Aplica las reglas de negocio para asignar la categoría:
      - Categoría A: Per cápita < 500 Bs. y SIN seguro médico.
      - Categoría B: Per cápita entre 500 Bs. y 1200 Bs.
      - Categoría C: Per cápita entre 1201 Bs. y 2250 Bs.
      - Categoría N: Per cápita > 2250 Bs. (No elegible para beneficios prioritarios).
    """
    if ingreso_per_capita < CATEGORIA_A_MAX_PER_CAPITA and not tiene_seguro:
        return "A"
    elif ingreso_per_capita <= CATEGORIA_B_MAX_PER_CAPITA:
        return "B"
    elif ingreso_per_capita <= CATEGORIA_C_MAX_PER_CAPITA:
        return "C"
    else:
        return "N"


def _evaluar_fraude(
    ingreso_total: float,
    tiene_seguro: bool,
    categoria: str,
    tipo_vivienda: str,
    monto_alquiler: float,
) -> str:
    """
    Módulo Anti-Fraude: detecta inconsistencias que requieren revisión manual.

    Casos de alerta:
      1. Ingresos declarados = 0 Bs, PERO tiene seguro médico activo.
         (Si no tiene ingresos, ¿cómo paga el seguro?)
      2. Categoría A (extrema pobreza), PERO la vivienda es propia y sin alquiler.
         (Inconsistencia: ser propietario de vivienda no corresponde con la pobreza extrema).
    """
    if ingreso_total == 0.0 and tiene_seguro:
        return "REVISIÓN MANUAL URGENTE"

    if (
        categoria == "A"
        and tipo_vivienda.strip().lower() == "propia"
        and monto_alquiler == 0.0
    ):
        return "REVISIÓN MANUAL URGENTE"

    return "NORMAL"


# ==============================================================================
# DEPENDENCIA DE AUTORIZACIÓN COMBINADA
# ==============================================================================

async def get_evaluator_or_admin(
    current_user: models.User = Depends(deps.get_current_active_user),
) -> models.User:
    """Permite el acceso a SUPER_ADMIN y EVALUADOR_SOCIAL."""
    if current_user.role not in ("SUPER_ADMIN", "EVALUADOR_SOCIAL"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido a evaluadores sociales y administradores.",
        )
    return current_user


# ==============================================================================
# LÓGICA COMPARTIDA DE UPSERT (usada por el endpoint staff y el de autoservicio)
# ==============================================================================

def _build_categorization(data: dict) -> dict:
    """A partir de los campos crudos, calcula ingreso_per_capita, categoria_asignada y estado_alerta."""
    ingreso_total = data["ingreso_titular"] + data["ingreso_conyuge"]
    integrantes = max(data["integrantes_hogar"], 1)
    ingreso_per_capita = round(ingreso_total / integrantes, 2)
    categoria = _calcular_categoria(ingreso_per_capita, data["tiene_seguro"])
    estado_alerta = _evaluar_fraude(
        ingreso_total=ingreso_total,
        tiene_seguro=data["tiene_seguro"],
        categoria=categoria,
        tipo_vivienda=data["tipo_vivienda"],
        monto_alquiler=data["monto_alquiler"],
    )
    return {
        "ingreso_per_capita": ingreso_per_capita,
        "categoria_asignada": categoria,
        "estado_alerta": estado_alerta,
    }


async def _upsert_evaluation(
    db: AsyncSession,
    patient: models.Patient,
    base_data: dict,
    extra_fields: dict,
) -> models.SocialEvaluation:
    """Crea o actualiza (upsert 1:1 con patient) la evaluación socioeconómica."""
    existing_q = await db.execute(
        select(models.SocialEvaluation).where(
            models.SocialEvaluation.patient_id == patient.id
        )
    )
    db_evaluation = existing_q.scalars().first()

    data = dict(base_data)
    data.update(_build_categorization(data))
    data.update(extra_fields)

    if db_evaluation:
        for field, value in data.items():
            setattr(db_evaluation, field, value)
    else:
        db_evaluation = models.SocialEvaluation(patient_id=patient.id, **data)
        db.add(db_evaluation)

    try:
        await db.commit()
        await db.refresh(db_evaluation)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al guardar la evaluación: {str(e)}",
        )

    db_evaluation.patient_nombre = f"{patient.nombres} {patient.ap_paterno or ''}".strip()
    db_evaluation.patient_ci = patient.ci
    return db_evaluation


async def _get_own_patient(db: AsyncSession, current_user: models.User) -> models.Patient:
    """Resuelve la ficha de Patient del beneficiario autenticado (rol PACIENTE)."""
    if current_user.role != "PACIENTE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este recurso es exclusivo para beneficiarios.",
        )
    result = await db.execute(
        select(models.Patient).where(models.Patient.user_id == current_user.id)
    )
    patient = result.scalars().first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró ficha de paciente asociada a este usuario.",
        )
    return patient


def _attach_patient_info(evaluation: models.SocialEvaluation) -> models.SocialEvaluation:
    """Adjunta nombre/CI del paciente (para listados/detalle del staff)."""
    if evaluation.patient:
        evaluation.patient_nombre = f"{evaluation.patient.nombres} {evaluation.patient.ap_paterno or ''}".strip()
        evaluation.patient_ci = evaluation.patient.ci
    return evaluation


def _validar_consentimientos(evaluation_in) -> None:
    if not evaluation_in.habeas_data_accepted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El consentimiento de Habeas Data (Art. 130 CPE / Ley 164) es obligatorio para continuar.",
        )
    if not evaluation_in.imagen_consent_accepted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El consentimiento para el uso de imágenes en auditoría es obligatorio para continuar.",
        )


# ==============================================================================
# ENDPOINTS — STAFF (SUPER_ADMIN / EVALUADOR_SOCIAL)
# ==============================================================================

@router.post(
    "/",
    response_model=schemas.SocialEvaluationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear o actualizar evaluación socioeconómica de un paciente",
)
async def create_or_update_social_evaluation(
    evaluation_in: schemas.SocialEvaluationCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_evaluator_or_admin),
):
    """
    Registra la evaluación socioeconómica de un beneficiario en nombre del staff.
    - Valida que se hayan aceptado los consentimientos legales requeridos.
    - Si el paciente ya tiene una evaluación previa, la sobreescribe (upsert).
    - Ejecuta automáticamente el motor de categorización (A, B, C, N) y el
      módulo anti-fraude.
    - Registra IP y User-Agent de quien envía para trazabilidad legal (Art. 130 CPE).
    """
    _validar_consentimientos(evaluation_in)

    client_ip = request.client.host if request.client else "desconocida"
    user_agent = request.headers.get("user-agent", "desconocido")[:300]

    patient_q = await db.execute(
        select(models.Patient).where(models.Patient.id == evaluation_in.patient_id)
    )
    patient = patient_q.scalars().first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Paciente con ID {evaluation_in.patient_id} no encontrado.",
        )

    base_data = evaluation_in.model_dump(exclude={"patient_id"})
    db_evaluation = await _upsert_evaluation(
        db,
        patient,
        base_data,
        extra_fields={
            "evaluator_id": current_user.id,
            "ip_address": client_ip,
            "user_agent": user_agent,
        },
    )
    return db_evaluation


# ==============================================================================
# ENDPOINTS — AUTOSERVICIO DEL BENEFICIARIO (rol PACIENTE)
#
# IMPORTANTE: deben registrarse ANTES de las rutas staff con "/{patient_id}"
# — FastAPI/Starlette hace match por orden de registro, así que si
# "/{patient_id}" estuviera primero, "GET /social-evaluations/me" sería
# capturado por esa ruta dinámica (con patient_id="me") en vez de llegar
# al endpoint de autoservicio.
# ==============================================================================

@router.post(
    "/me",
    response_model=schemas.SocialEvaluationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="El beneficiario registra o actualiza su propia evaluación socioeconómica",
)
async def create_or_update_my_social_evaluation(
    evaluation_in: schemas.SocialEvaluationSelfCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Registra o actualiza (upsert) la evaluación socioeconómica del beneficiario
    autenticado. Las URLs de evidencias deben subirse antes con
    `/me/upload-document`. Si se reenvía tras un rechazo, vuelve a quedar
    `PENDIENTE` de revisión.
    """
    _validar_consentimientos(evaluation_in)

    patient = await _get_own_patient(db, current_user)

    client_ip = request.client.host if request.client else "desconocida"
    user_agent = request.headers.get("user-agent", "desconocido")[:300]

    base_data = evaluation_in.model_dump()
    db_evaluation = await _upsert_evaluation(
        db,
        patient,
        base_data,
        extra_fields={
            "evaluator_id": None,
            "ip_address": client_ip,
            "user_agent": user_agent,
            "estado_revision": "PENDIENTE",
            "reviewer_id": None,
            "revisado_at": None,
            "motivo_rechazo": None,
        },
    )
    return db_evaluation


@router.get(
    "/me",
    response_model=schemas.SocialEvaluationResponse,
    summary="El beneficiario consulta su propia evaluación socioeconómica",
)
async def get_my_social_evaluation(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    patient = await _get_own_patient(db, current_user)
    result = await db.execute(
        select(models.SocialEvaluation).where(
            models.SocialEvaluation.patient_id == patient.id
        )
    )
    evaluation = result.scalars().first()
    if not evaluation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aún no registra una evaluación socioeconómica.",
        )
    return evaluation


@router.post(
    "/me/upload-document",
    summary="Sube una evidencia (foto/firma) para la evaluación socioeconómica propia",
)
async def upload_my_evaluation_document(
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Sube una evidencia individual a Firebase Storage y devuelve su URL
    pública. No persiste ninguna fila en `social_evaluations` — el frontend
    debe incluir la URL devuelta en el payload final de `POST /me`.
    """
    patient = await _get_own_patient(db, current_user)

    structure_map = {
        "ci": ("evaluaciones/legal", "ci"),
        "fachada": ("evaluaciones/vivienda", "fachada"),
        "sala": ("evaluaciones/vivienda", "sala"),
        "dormitorio": ("evaluaciones/vivienda", "dormitorio"),
        "firma": ("evaluaciones/firma", "firma"),
    }
    if doc_type not in structure_map:
        raise HTTPException(status_code=400, detail="Tipo de documento inválido.")
    subfolder, file_prefix = structure_map[doc_type]

    content_type = file.content_type or ""
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido.")

    file_extension = file.filename.split(".")[-1]
    firebase_path = f"pacientes/{patient.id}/{subfolder}/{file_prefix}.{file_extension}"

    file_content = await file.read()
    if len(file_content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Archivo demasiado grande. Máximo {MAX_FILE_SIZE_MB}MB.",
        )

    try:
        public_url = await run_in_threadpool(
            upload_file_to_firebase, file_content, firebase_path, file.content_type
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error subiendo: {str(e)}")

    return {"msg": "Actualizado exitosamente", "url": public_url, "type": doc_type}


# ==============================================================================
# ENDPOINTS — STAFF CON PATIENT_ID DINÁMICO (deben ir después de "/me")
# ==============================================================================

@router.get(
    "/{patient_id}",
    response_model=schemas.SocialEvaluationResponse,
    summary="Obtener la evaluación socioeconómica de un paciente",
)
async def get_social_evaluation(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_evaluator_or_admin),
):
    """
    Retorna la evaluación socioeconómica más reciente del paciente indicado.
    """
    result = await db.execute(
        select(models.SocialEvaluation)
        .options(selectinload(models.SocialEvaluation.patient))
        .where(models.SocialEvaluation.patient_id == patient_id)
    )
    evaluation = result.scalars().first()

    if not evaluation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe evaluación socioeconómica para el paciente {patient_id}.",
        )

    return _attach_patient_info(evaluation)


@router.get(
    "/",
    response_model=list[schemas.SocialEvaluationResponse],
    summary="Listar todas las evaluaciones socioeconómicas",
)
async def list_social_evaluations(
    skip: int = 0,
    limit: int = 200,
    alerta_urgente: Optional[bool] = None,
    estado_revision: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_evaluator_or_admin),
):
    """
    Lista todas las evaluaciones. Accesible para SUPER_ADMIN y EVALUADOR_SOCIAL.
    Opcionalmente filtra por `alerta_urgente=true` para mostrar solo las que
    requieren revisión manual, y/o por `estado_revision` (PENDIENTE/APROBADO/RECHAZADO).
    """
    query = (
        select(models.SocialEvaluation)
        .options(selectinload(models.SocialEvaluation.patient))
        .order_by(models.SocialEvaluation.created_at.desc())
    )

    if alerta_urgente is True:
        query = query.where(
            models.SocialEvaluation.estado_alerta == "REVISIÓN MANUAL URGENTE"
        )
    elif alerta_urgente is False:
        query = query.where(
            models.SocialEvaluation.estado_alerta == "NORMAL"
        )

    if estado_revision:
        query = query.where(models.SocialEvaluation.estado_revision == estado_revision)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    evaluations = result.scalars().all()
    return [_attach_patient_info(ev) for ev in evaluations]


@router.put(
    "/{patient_id}/interview",
    response_model=schemas.SocialEvaluationResponse,
    summary="Registrar la entrevista virtual con el beneficiario",
)
async def register_evaluation_interview(
    patient_id: int,
    interview_in: schemas.SocialEvaluationInterviewUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_evaluator_or_admin),
):
    """
    Registra que el evaluador social se reunió con el beneficiario (por
    medios externos al sistema, ej. videollamada) antes de emitir un
    veredicto. Es un requisito obligatorio para `PUT /{patient_id}/review`.
    """
    result = await db.execute(
        select(models.SocialEvaluation)
        .options(selectinload(models.SocialEvaluation.patient))
        .where(models.SocialEvaluation.patient_id == patient_id)
    )
    evaluation = result.scalars().first()
    if not evaluation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe evaluación socioeconómica para el paciente {patient_id}.",
        )

    evaluation.entrevista_realizada = True
    evaluation.entrevista_fecha = datetime.now(timezone.utc)
    evaluation.entrevista_notas = interview_in.notas

    try:
        db.add(evaluation)
        await db.commit()
        await db.refresh(evaluation)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al registrar la entrevista: {str(e)}",
        )

    return _attach_patient_info(evaluation)


@router.put(
    "/{patient_id}/review",
    response_model=schemas.SocialEvaluationResponse,
    summary="Avalar o rechazar la evaluación socioeconómica de un paciente",
)
async def review_social_evaluation(
    patient_id: int,
    review_in: schemas.SocialEvaluationReviewUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_evaluator_or_admin),
):
    """
    Avala (APROBADO) o rechaza (RECHAZADO) la evaluación socioeconómica de un
    paciente. Requiere que la entrevista virtual ya haya sido registrada
    (`entrevista_realizada`). Al aprobar, exonera al paciente del aporte
    solidario (`patient.exonerado_aporte = True`); al rechazar exige un motivo.
    """
    if review_in.decision == "RECHAZADO" and not (review_in.motivo or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debe indicar el motivo del rechazo.",
        )

    result = await db.execute(
        select(models.SocialEvaluation).where(
            models.SocialEvaluation.patient_id == patient_id
        )
    )
    evaluation = result.scalars().first()
    if not evaluation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe evaluación socioeconómica para el paciente {patient_id}.",
        )

    if not evaluation.entrevista_realizada:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debe registrar la entrevista virtual con el beneficiario antes de emitir un veredicto.",
        )

    patient_q = await db.execute(
        select(models.Patient).where(models.Patient.id == patient_id)
    )
    patient = patient_q.scalars().first()
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paciente no encontrado.")

    evaluation.estado_revision = review_in.decision
    evaluation.reviewer_id = current_user.id
    evaluation.revisado_at = datetime.now(timezone.utc)
    evaluation.motivo_rechazo = review_in.motivo if review_in.decision == "RECHAZADO" else None
    patient.exonerado_aporte = review_in.decision == "APROBADO"

    try:
        db.add(evaluation)
        db.add(patient)
        await db.commit()
        await db.refresh(evaluation)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al guardar la revisión: {str(e)}",
        )

    evaluation.patient_nombre = f"{patient.nombres} {patient.ap_paterno or ''}".strip()
    evaluation.patient_ci = patient.ci
    return evaluation
