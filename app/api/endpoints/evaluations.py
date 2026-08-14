"""
Módulo de Evaluación Socioeconómica y Categorización de Beneficiarios.

- El beneficiario llena y sube evidencias de su propia evaluación desde el
  autoregistro (endpoints `/me`), sin poder ver ni tocar las de otros.
- SUPER_ADMIN y EVALUADOR_SOCIAL revisan, avalan o rechazan las evaluaciones
  enviadas (endpoints staff).
"""
import calendar
from datetime import date, datetime, timezone
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
# MOTOR DE CATEGORIZACIÓN — Capacidad Financiera Neta Residual (CFNR)
#
# CFNR = Ingresos Totales del Hogar
#        - (Canasta Básica Familiar + Vivienda y Servicios + Transporte y Deudas)
#
# Fuente: criterio proporcionado por la Fundación (Base Bolivia 2026). Los
# montos de agua, luz, gas domiciliario, internet, transporte y la cuota de
# deuda se declaran en el formulario (el monto de cada servicio solo entra
# al cálculo si el hogar marcó que cuenta con él); el resto de los rubros
# (canasta básica escalada por tamaño de hogar, mantenimiento de vivienda
# propia, salud/educación por dependiente) son estimaciones fijas dentro de
# los rangos de referencia dados, ya que no se piden como preguntas
# individuales.
# ==============================================================================

CANASTA_BASE_1_PERSONA = 1000.0
CANASTA_INCREMENTO_2DA_PERSONA = 800.0  # 1 persona=1000, 2 personas=1800
CANASTA_INCREMENTO_PERSONA_ADICIONAL = 700.0  # desde la 3ra persona en adelante (4 personas=3200)

MANTENIMIENTO_VIVIENDA_PROPIA = 225.0  # estimado, rango 150-300 Bs
COSTO_SALUD_EDUCACION_POR_DEPENDIENTE = 275.0  # estimado, rango 150-400 Bs

CFNR_UMBRAL_ALTA = 0.0  # CFNR <= 0 → Vulnerabilidad Alta (déficit)
CFNR_UMBRAL_BAJA = 1500.0  # CFNR > 1500 → Vulnerabilidad Baja/Nula


def _canasta_familiar(integrantes_hogar: int) -> float:
    """Costo de la canasta básica familiar, escalado por economía de escala."""
    n = max(integrantes_hogar, 1)
    if n == 1:
        return CANASTA_BASE_1_PERSONA
    return (
        CANASTA_BASE_1_PERSONA
        + CANASTA_INCREMENTO_2DA_PERSONA
        + CANASTA_INCREMENTO_PERSONA_ADICIONAL * (n - 2)
    )


def _costo_vivienda(tipo_vivienda: str, monto_alquiler: float) -> float:
    """Alquiler/anticrético declarado, o mantenimiento estimado si la vivienda es propia."""
    if (tipo_vivienda or "").strip().lower() == "propia":
        return MANTENIMIENTO_VIVIENDA_PROPIA
    return monto_alquiler or 0.0


def _monto_servicio(data: dict, flag_key: str, monto_key: str) -> float:
    """El monto de un servicio solo entra al CFNR si el hogar declaró contar con él."""
    if not data.get(flag_key):
        return 0.0
    return data.get(monto_key) or 0.0


def _calcular_categoria_cfnr(cfnr: float) -> str:
    """
    Clasifica según la Capacidad Financiera Neta Residual (CFNR):
      - ALTA:  CFNR <= 0 Bs. (déficit o saldo cero; no cubre canasta ni servicios).
      - MEDIA: 0 < CFNR <= 1500 Bs. (cubre necesidades básicas, con margen acotado).
      - BAJA:  CFNR > 1500 Bs. (situación acomodada, sin necesidad de apoyo).
    """
    if cfnr <= CFNR_UMBRAL_ALTA:
        return "ALTA"
    if cfnr <= CFNR_UMBRAL_BAJA:
        return "MEDIA"
    return "BAJA"


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
      2. Vulnerabilidad Alta (déficit), PERO la vivienda es propia y sin alquiler.
         (Inconsistencia: ser propietario de vivienda no corresponde con el déficit declarado).
    """
    if ingreso_total == 0.0 and tiene_seguro:
        return "REVISIÓN MANUAL URGENTE"

    if (
        categoria == "ALTA"
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
    """
    A partir de los campos crudos, calcula la Capacidad Financiera Neta
    Residual (CFNR) y clasifica el hogar en ALTA/MEDIA/BAJA vulnerabilidad.
    """
    ingreso_total = (
        data["ingreso_titular"] + data["ingreso_conyuge"] + (data.get("ingreso_otros_familiares") or 0.0)
    )
    integrantes = max(data["integrantes_hogar"], 1)

    canasta = _canasta_familiar(integrantes)
    vivienda = _costo_vivienda(data["tipo_vivienda"], data["monto_alquiler"])
    servicios = (
        _monto_servicio(data, "tiene_agua", "monto_agua")
        + _monto_servicio(data, "tiene_luz", "monto_luz")
        + _monto_servicio(data, "tiene_gas_domiciliario", "monto_gas_domiciliario")
        + _monto_servicio(data, "tiene_internet", "monto_internet")
    )
    salud_educacion = data.get("dependientes", 0) * COSTO_SALUD_EDUCACION_POR_DEPENDIENTE
    transporte = data.get("monto_transporte") or 0.0
    # El monto de deuda solo se descuenta si se declaró explícitamente que las
    # deudas comprometen sus ingresos (evita que un monto quede "colgado" si
    # el beneficiario luego marca 'No').
    deuda = (data.get("monto_deuda_mensual") or 0.0) if data.get("tiene_deudas_comprometen_ingresos") else 0.0

    costo_vida_estimado = round(canasta + vivienda + servicios + salud_educacion + transporte + deuda, 2)
    cfnr = round(ingreso_total - costo_vida_estimado, 2)

    categoria = _calcular_categoria_cfnr(cfnr)
    estado_alerta = _evaluar_fraude(
        ingreso_total=ingreso_total,
        tiene_seguro=data["tiene_seguro"],
        categoria=categoria,
        tipo_vivienda=data["tipo_vivienda"],
        monto_alquiler=data["monto_alquiler"],
    )
    return {
        # Dato de referencia; ya no determina la categoría por sí solo.
        "ingreso_per_capita": round(ingreso_total / integrantes, 2),
        "costo_vida_estimado": costo_vida_estimado,
        "cfnr": cfnr,
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
# BLOQUEO EN DOS NIVELES TRAS UN RECHAZO
#
#   Nivel 1 (RECHAZADO, estándar): cooldown temporal de N meses
#     (patient.evaluacion_bloqueada_hasta).
#   Nivel 2 (RECHAZADO_FRAUDE, falsedad/depuración): suspensión permanente
#     (patient.estado_beneficio = "SUSPENDIDO") — solo un SUPER_ADMIN puede
#     reactivar (ver PUT /{patient_id}/reactivate).
# ==============================================================================

RECHAZO_ESTANDAR_COOLDOWN_MESES = 6


def _agregar_meses(fecha: date, meses: int) -> date:
    mes_total = fecha.month - 1 + meses
    anio = fecha.year + mes_total // 12
    mes = mes_total % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return date(anio, mes, dia)


def _evaluar_elegibilidad(patient: models.Patient) -> schemas.SocialEvaluationEligibility:
    """Determina si el beneficiario puede enviar una nueva evaluación socioeconómica."""
    if patient.estado_beneficio == "SUSPENDIDO":
        return schemas.SocialEvaluationEligibility(
            puede_evaluar=False,
            suspendido=True,
            motivo=(
                "Su acceso a evaluaciones socioeconómicas fue suspendido. "
                "Comuníquese con la Fundación para más información."
            ),
        )
    if patient.evaluacion_bloqueada_hasta and date.today() < patient.evaluacion_bloqueada_hasta:
        fecha_texto = patient.evaluacion_bloqueada_hasta.strftime("%d/%m/%Y")
        return schemas.SocialEvaluationEligibility(
            puede_evaluar=False,
            bloqueado_hasta=patient.evaluacion_bloqueada_hasta,
            motivo=f"Su solicitud fue denegada. Podrá volver a someterse a evaluación a partir del {fecha_texto}.",
        )
    return schemas.SocialEvaluationEligibility(puede_evaluar=True)


def _exigir_elegibilidad(patient: models.Patient) -> None:
    elegibilidad = _evaluar_elegibilidad(patient)
    if not elegibilidad.puede_evaluar:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=elegibilidad.motivo)


async def _archivar_veredicto(
    db: AsyncSession,
    evaluation: models.SocialEvaluation,
    patient: models.Patient,
    actor_id: int,
    decision: str,
) -> None:
    """
    Guarda una copia inmutable del veredicto (aprobación/rechazo) en AuditLog
    antes de que un futuro reenvío del beneficiario sobreescriba la fila de
    `social_evaluations` (relación 1:1). Permite mantener un historial
    completo por beneficiario aunque la evaluación "actual" cambie.
    """
    snapshot = {
        "departamento": evaluation.departamento,
        "integrantes_hogar": evaluation.integrantes_hogar,
        "dependientes": evaluation.dependientes,
        "tipo_vivienda": evaluation.tipo_vivienda,
        "monto_alquiler": evaluation.monto_alquiler,
        "tiene_seguro": evaluation.tiene_seguro,
        "condicion_laboral": evaluation.condicion_laboral,
        "ingreso_titular": evaluation.ingreso_titular,
        "ingreso_conyuge": evaluation.ingreso_conyuge,
        "ingreso_otros_familiares": evaluation.ingreso_otros_familiares,
        "recibe_ayuda_otra_institucion": evaluation.recibe_ayuda_otra_institucion,
        "nombre_institucion_ayuda": evaluation.nombre_institucion_ayuda,
        "tiene_deudas_comprometen_ingresos": evaluation.tiene_deudas_comprometen_ingresos,
        "monto_deuda_mensual": evaluation.monto_deuda_mensual,
        "tiene_agua": evaluation.tiene_agua,
        "monto_agua": evaluation.monto_agua,
        "tiene_luz": evaluation.tiene_luz,
        "monto_luz": evaluation.monto_luz,
        "tiene_gas_domiciliario": evaluation.tiene_gas_domiciliario,
        "monto_gas_domiciliario": evaluation.monto_gas_domiciliario,
        "tiene_internet": evaluation.tiene_internet,
        "monto_internet": evaluation.monto_internet,
        "monto_transporte": evaluation.monto_transporte,
        "ingreso_per_capita": evaluation.ingreso_per_capita,
        "costo_vida_estimado": evaluation.costo_vida_estimado,
        "cfnr": evaluation.cfnr,
        "categoria_asignada": evaluation.categoria_asignada,
        "categoria_final": evaluation.categoria_final,
        "estado_alerta": evaluation.estado_alerta,
        "decision": decision,
        "motivo_rechazo": evaluation.motivo_rechazo,
        "entrevista_fecha": evaluation.entrevista_fecha.isoformat() if evaluation.entrevista_fecha else None,
        "entrevista_notas": evaluation.entrevista_notas,
    }
    db.add(
        models.AuditLog(
            actor_id=actor_id,
            entidad="social_evaluation",
            entidad_id=patient.id,
            accion=decision,
            payload=snapshot,
        )
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
    _exigir_elegibilidad(patient)

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
    _exigir_elegibilidad(patient)

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


@router.get(
    "/me/eligibility",
    response_model=schemas.SocialEvaluationEligibility,
    summary="El beneficiario verifica si puede enviar una nueva evaluación socioeconómica",
)
async def get_my_evaluation_eligibility(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Se consulta antes de mostrar el formulario de evaluación: si el
    beneficiario está en cooldown (rechazo estándar) o suspendido (rechazo
    por falsedad), `puede_evaluar` viene en `false` con el motivo/fecha.
    """
    patient = await _get_own_patient(db, current_user)
    return _evaluar_elegibilidad(patient)


@router.post(
    "/me/upload-document",
    summary="Sube una evidencia (foto) para la evaluación socioeconómica propia",
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
    "/{patient_id}/history",
    response_model=list[schemas.SocialEvaluationHistoryItem],
    summary="Historial de veredictos (aprobaciones/rechazos) pasados de un paciente",
)
async def get_social_evaluation_history(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_evaluator_or_admin),
):
    """
    Devuelve, del más reciente al más antiguo, cada veredicto (APROBADO /
    RECHAZADO / RECHAZADO_FRAUDE) que se haya registrado para este paciente
    a lo largo del tiempo — incluso si la evaluación "actual" ya fue
    sobreescrita por un reenvío posterior. Es el precedente a revisar antes
    de avalar una nueva postulación de alguien que ya fue rechazado antes.
    """
    result = await db.execute(
        select(models.AuditLog)
        .where(
            models.AuditLog.entidad == "social_evaluation",
            models.AuditLog.entidad_id == patient_id,
        )
        .order_by(models.AuditLog.created_at.desc())
    )
    return result.scalars().all()


@router.put(
    "/{patient_id}/reactivate",
    response_model=schemas.SocialEvaluationEligibility,
    summary="Reactivar a un beneficiario suspendido o levantar su cooldown (solo SUPER_ADMIN)",
)
async def reactivate_patient_evaluation(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    Levanta la suspensión permanente (rechazo por falsedad) o el cooldown
    temporal (rechazo estándar), permitiendo que el beneficiario vuelva a
    enviar una evaluación socioeconómica. Acción exclusiva de SUPER_ADMIN.
    """
    patient = await db.get(models.Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paciente no encontrado.")

    patient.estado_beneficio = "ACTIVO"
    patient.evaluacion_bloqueada_hasta = None
    db.add(
        models.AuditLog(
            actor_id=current_user.id,
            entidad="social_evaluation",
            entidad_id=patient.id,
            accion="REACTIVADO",
            payload={"nota": "Reactivado manualmente por SUPER_ADMIN."},
        )
    )
    await db.commit()

    return schemas.SocialEvaluationEligibility(puede_evaluar=True)


# TODO: ELIMINAR ENDPOINT AL TERMINAR QA (MODO PRUEBAS)
@router.delete(
    "/debug-delete/{patient_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="[QA] Borrado físico de una evaluación socioeconómica (solo SUPER_ADMIN)",
)
async def debug_delete_social_evaluation(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    Herramienta temporal de QA: borra físicamente la evaluación socioeconómica
    de un paciente para poder resetear su estado y volver a probar el flujo
    de autoservicio desde cero. No toca el historial en AuditLog ni el estado
    de bloqueo/suspensión del paciente (`estado_beneficio`,
    `evaluacion_bloqueada_hasta`) — si se necesita limpiar esos también, usar
    PUT /{patient_id}/reactivate por separado.
    """
    result = await db.execute(
        select(models.SocialEvaluation).where(models.SocialEvaluation.patient_id == patient_id)
    )
    evaluation = result.scalars().first()
    if evaluation:
        await db.delete(evaluation)
        await db.commit()


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
    Avala (APROBADO) o rechaza la evaluación socioeconómica de un paciente.
    Requiere que la entrevista virtual ya haya sido registrada
    (`entrevista_realizada`). Al aprobar, exonera al paciente del aporte
    solidario. El rechazo tiene dos niveles, ambos exigen motivo:
      - RECHAZADO (estándar): cooldown temporal (no puede reenviar por
        `RECHAZO_ESTANDAR_COOLDOWN_MESES` meses).
      - RECHAZADO_FRAUDE (falsedad/depuración): suspensión permanente,
        requiere reactivación explícita de un SUPER_ADMIN.
    En ambos casos de rechazo, y en la aprobación, se archiva un snapshot
    del veredicto en AuditLog (ver GET /{patient_id}/history), porque el
    reenvío posterior del beneficiario sobreescribe la fila de evaluación.
    """
    if review_in.decision in ("RECHAZADO", "RECHAZADO_FRAUDE") and not (review_in.motivo or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debe indicar el motivo del rechazo.",
        )
    if review_in.decision == "APROBADO" and not review_in.categoria_final:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debe elegir la categoría final (ALTA, MEDIA o BAJA) para aprobar.",
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
    evaluation.motivo_rechazo = review_in.motivo if review_in.decision != "APROBADO" else None
    evaluation.categoria_final = review_in.categoria_final if review_in.decision == "APROBADO" else None
    patient.exonerado_aporte = review_in.decision == "APROBADO"

    if review_in.decision == "RECHAZADO":
        patient.evaluacion_bloqueada_hasta = _agregar_meses(date.today(), RECHAZO_ESTANDAR_COOLDOWN_MESES)
    elif review_in.decision == "RECHAZADO_FRAUDE":
        patient.estado_beneficio = "SUSPENDIDO"
        patient.evaluacion_bloqueada_hasta = None
    else:  # APROBADO
        patient.evaluacion_bloqueada_hasta = None

    await _archivar_veredicto(db, evaluation, patient, current_user.id, review_in.decision)

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
