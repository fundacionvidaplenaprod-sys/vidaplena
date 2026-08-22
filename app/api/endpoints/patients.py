import io
import uuid
import random
import string
from typing import List, Optional
from datetime import date, timedelta
import textwrap
import hashlib
from app.core.config import settings
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form, Query
from fastapi.responses import StreamingResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import or_, delete, func
from sqlalchemy.exc import IntegrityError

# ReportLab para PDFs
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_LEFT

from app import models, schemas
from app.api import deps
from app.db import get_db
from app.core.security import hash_password, create_access_token
from app.core.firebase import upload_file_to_firebase, delete_file_from_firebase_by_url
from app.core.text_normalize import normalize_name

router = APIRouter()

# --- Constantes ---
MAX_FILE_SIZE_MB = 2
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/jpg"]
WHATSAPP_CONTACTO = "+59172966106"

# doc_type -> (subcarpeta en Firebase, prefijo de archivo, columna en Patient)
DOCUMENT_STRUCTURE_MAP = {
    "ci":         ("legal/identidad",   "ci_paciente",        "url_ci_paciente"),
    "medico":     ("legal/medico",      "cert_medico",        "url_certificado_medico"),
    "foto":       ("legal/fotos",       "foto_paciente",      "url_foto_paciente"),
    "compromiso": ("legal/compromisos", "declaracion_aporte", "url_declaracion_aporte"),
    "ci_tutor":   ("legal/identidad",   "ci_tutor",           "url_ci_tutor"),
    "foto_tutor": ("legal/fotos",       "foto_tutor",         "url_foto_tutor"),
}

# --- Funciones Auxiliares ---

def calculate_age(born: date):
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

async def _collect_patient_document_urls(db: AsyncSession, patient: models.Patient) -> List[str]:
    """
    Junta todas las URLs de documentos de un paciente (propios y los de su
    evaluación socioeconómica, si tiene) para poder borrarlos de Firebase
    Storage antes de eliminar al paciente.

    IMPORTANTE: la evaluación se consulta aparte (no vía `patient.social_evaluation`)
    a propósito. Si esa relación queda cargada en el objeto `patient` antes de
    `db.delete(patient)`, SQLAlchemy intenta desasociarla poniendo su
    `patient_id` en NULL como parte del cascade de guardado por defecto —y
    falla, porque esa columna es NOT NULL. Al consultarla por separado sin
    tocar el atributo de relación, el `ON DELETE CASCADE` de la base de
    datos se encarga solo, sin que el ORM interfiera.
    """
    urls = [
        patient.url_ci_paciente,
        patient.url_certificado_medico,
        patient.url_foto_paciente,
        patient.url_declaracion_aporte,
        patient.url_ci_tutor,
        patient.url_foto_tutor,
    ]

    eval_result = await db.execute(
        select(models.SocialEvaluation).where(models.SocialEvaluation.patient_id == patient.id)
    )
    evaluation = eval_result.scalar_one_or_none()
    if evaluation is not None:
        urls.extend([
            evaluation.foto_ci_url,
            evaluation.foto_fachada_url,
            evaluation.foto_sala_url,
            evaluation.foto_dormitorio_url,
        ])

    return [u for u in urls if u]


def _delete_storage_urls(urls: List[str]) -> None:
    """
    Borra de Firebase Storage cada URL dada. Es un "mejor esfuerzo": si una
    URL no se puede mapear a un archivo, o el archivo ya no existe, se
    ignora esa URL puntual y se continúa con las demás. Debe llamarse
    después de que el borrado del registro en BD ya haya sido confirmado
    (commit), nunca antes — si la transacción de BD fallara, no queremos
    haber borrado ya los archivos.
    """
    for url in urls:
        try:
            delete_file_from_firebase_by_url(url)
        except Exception as e:
            print(f"Error al borrar documento de Firebase ({url}): {e}")


def _validate_insulin_treatment_payload(treatments: List[schemas.PatientTreatmentCreate]) -> None:
    """
    Validación defensiva de tratamientos para evitar guardar dosis inválidas.
    """
    if treatments is None:
        return

    for tx in treatments:
        nombre = (tx.nombre or "").strip()
        if not nombre:
            raise HTTPException(status_code=400, detail="Cada tratamiento debe tener un nombre válido.")

        daily_dose = tx.dosis_diaria
        if daily_dose is not None and daily_dose < 0:
            raise HTTPException(
                status_code=400,
                detail=f"La dosis diaria no puede ser negativa para el tratamiento '{nombre}'.",
            )

def _get_missing_activation_fields(patient: models.Patient) -> List[str]:
    """
    Devuelve la lista de campos faltantes para activar al paciente.
    Para menores de edad, valida que el tutor tenga email y CI.
    """
    missing_fields: List[str] = []

    # Verificar si es menor de edad
    is_minor = patient.edad_calc < 18

    if is_minor:
        # Para menores: las credenciales son del tutor
        if not patient.tutor:
            missing_fields.append("tutor (obligatorio para menor de edad)")
        else:
            if not patient.tutor.email or not patient.tutor.email.strip():
                missing_fields.append("tutor.email (necesario para crear credenciales del menor)")
            if not patient.tutor.ci or not patient.tutor.ci.strip():
                missing_fields.append("tutor.ci (se usará como contraseña inicial)")
    else:
        # Para mayores: credenciales propias
        required_fields = {
            "ci": patient.ci,
            "nombres": patient.nombres,
            "ap_paterno": patient.ap_paterno,
            "fecha_nac": patient.fecha_nac,
            "email": patient.email,
            "direccion": patient.direccion,
            "tel_contacto": patient.tel_contacto,
        }
        for field_name, value in required_fields.items():
            if value is None or (isinstance(value, str) and not value.strip()):
                missing_fields.append(field_name)

    return missing_fields

def _log_audit_event(
    *,
    db: AsyncSession,
    actor_id: int,
    entidad: str,
    entidad_id: int,
    accion: str,
    payload: Optional[dict] = None,
) -> None:
    db.add(
        models.AuditLog(
            actor_id=actor_id,
            entidad=entidad,
            entidad_id=entidad_id,
            accion=accion,
            payload=payload,
        )
    )


def numero_a_letras(monto: float) -> str:
    UNIDADES = ["", "UN ", "DOS ", "TRES ", "CUATRO ", "CINCO ", "SEIS ", "SIETE ", "OCHO ", "NUEVE ", "DIEZ ", "ONCE ", "DOCE ", "TRECE ", "CATORCE ", "QUINCE ", "DIECISEIS ", "DIECISIETE ", "DIECIOCHO ", "DIECINUEVE ", "VEINTE "]
    DECENAS = ["UNKNOWN", "DIEZ", "VEINTI", "TREINTA ", "CUARENTA ", "CINCUENTA ", "SESENTA ", "SETENTA ", "OCHENTA ", "NOVENTA "]
    CENTENAS = ["", "CIENTO ", "DOSCIENTOS ", "TRESCIENTOS ", "CUATROCIENTOS ", "QUINIENTOS ", "SEISCIENTOS ", "SETECIENTOS ", "OCHOCIENTOS ", "NOVECIENTOS "]

    def _convertir(entero: int) -> str:
        if entero == 0: return ""
        elif entero == 100: return "CIEN "
        elif entero < 21: return UNIDADES[entero]
        elif entero < 30: return DECENAS[2] + UNIDADES[entero - 20]
        elif entero < 100: return DECENAS[int(entero / 10)] + ("Y " if entero % 10 > 0 else "") + UNIDADES[entero % 10]
        elif entero < 1000: return CENTENAS[int(entero / 100)] + _convertir(entero % 100)
        elif entero < 2000: return "MIL " + _convertir(entero % 1000)
        elif entero < 1000000:
            texto = _convertir(int(entero / 1000)).replace("UN ", "UN MIL ") + _convertir(entero % 1000)
            if texto.startswith("UN MIL"): texto = texto[3:]
            return texto
        return ""

    entero = int(monto)
    decimal = int(round((monto - entero) * 100))
    
    texto = "CERO " if entero == 0 else _convertir(entero)
    return f"({texto.strip()} {decimal:02d}/100 BOLIVIANOS)"

# --- Endpoints Principales ---

@router.post("/", response_model=schemas.PatientResponse, status_code=status.HTTP_201_CREATED)
async def create_patient(
    patient_in: schemas.PatientFullCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    print(f"📦 DEBUG CREATE: Recibido payload para {patient_in.nombres}")
    print(f"📦 DEBUG CREATE: Datos del tutor recibidos: {patient_in.tutor}")

    # 1. Validación de Edad
    age = calculate_age(patient_in.fecha_nac)
    if age < 18 and not patient_in.tutor:
        raise HTTPException(
            status_code=400, 
            detail=f"El paciente es menor ({age} años). Es OBLIGATORIO registrar Tutor."
        )

    try:
        # 2. Crear Objeto Paciente (Sin relaciones anidadas)
        # Excluimos todo lo que sean objetos relacionados para insertarlos manualmente
        patient_data = patient_in.model_dump(exclude={'tutor', 'medical', 'treatments', 'complications'})
        patient_data['estado'] = "PENDIENTE_DOC" 
        
        db_patient = models.Patient(**patient_data)
        db.add(db_patient)
        await db.flush() # Obtenemos el ID del paciente

        # 3. Crear Tutor (SI EXISTE)
        if patient_in.tutor:
            print("✅ Creando registro de Tutor...")
            tutor_data = patient_in.tutor.model_dump()
            db_tutor = models.Tutor(**tutor_data, patient_id=db_patient.id)
            db.add(db_tutor)
        else:
            print("⚠️ No se recibió información de tutor (tutor is None)")

        # 4. Crear Datos Médicos
        if patient_in.medical:
            medical_data = patient_in.medical.model_dump()
            db_medical = models.PatientMedical(**medical_data, patient_id=db_patient.id)
            db.add(db_medical)

        # 5. Tratamientos
        if patient_in.treatments:
            for treatment in patient_in.treatments:
                t_data = treatment.model_dump()
                db_treatment = models.PatientTreatment(**t_data, patient_id=db_patient.id)
                db.add(db_treatment)

        # 6. Complicaciones
        if patient_in.complications:
            for comp_in in patient_in.complications:
                # Validar código (simplificado)
                new_compl = models.PatientComplication(
                    patient_id=db_patient.id,
                    complication_code=comp_in.complication_code,
                    detalle=comp_in.detalle
                )
                db.add(new_compl)

        await db.commit()
        
        # Recuperar objeto completo para respuesta
        query_final = (
            select(models.Patient)
            .where(models.Patient.id == db_patient.id)
            .options(
                selectinload(models.Patient.tutor),
                selectinload(models.Patient.medical),
                selectinload(models.Patient.treatments),
                selectinload(models.Patient.complications),
            )
        )
        result_final = await db.execute(query_final)
        return result_final.scalars().first()

    except Exception as e:
        await db.rollback()
        print(f"🔥 ERROR CREATE: {str(e)}")
        # Manejo de duplicados
        err_msg = str(e).lower()
        if "patients_ci_key" in err_msg:
            raise HTTPException(status_code=400, detail="Ya existe un paciente con este CI.")
        if "tutors_ci_key" in err_msg:
             raise HTTPException(status_code=400, detail="El CI del Tutor ya está registrado.")
        
        raise HTTPException(status_code=500, detail=f"Error creando paciente: {str(e)}")

async def _find_beneficiary_match(
    db: AsyncSession, nombres: str, ap_paterno: Optional[str], ap_materno: Optional[str]
) -> Optional[models.PreregisteredBeneficiary]:
    """
    Busca en el padrón precargado (pacientes.csv) un beneficiario cuyo nombre
    coincida de forma tolerante (sin tildes/mayúsculas) con los datos dados.
    """
    norm_nombres = normalize_name(nombres)
    norm_ap_paterno = normalize_name(ap_paterno)
    norm_ap_materno = normalize_name(ap_materno)

    if not norm_nombres:
        return None

    result = await db.execute(select(models.PreregisteredBeneficiary))
    candidates = result.scalars().all()

    for candidate in candidates:
        if normalize_name(candidate.nombres) != norm_nombres:
            continue

        cand_ap_paterno = normalize_name(candidate.ap_paterno)
        if cand_ap_paterno and norm_ap_paterno and cand_ap_paterno != norm_ap_paterno:
            continue
        if cand_ap_paterno and not norm_ap_paterno:
            continue

        cand_ap_materno = normalize_name(candidate.ap_materno)
        if cand_ap_materno and norm_ap_materno and cand_ap_materno != norm_ap_materno:
            continue

        return candidate

    return None


@router.post("/check-beneficiary", response_model=schemas.BeneficiaryCheckResponse)
async def check_beneficiary(
    payload: schemas.BeneficiaryCheckRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Verifica (público, sin login) si un nombre coincide con la lista de
    beneficiarios ya conocidos por la Fundación. Usado por el autoregistro.
    """
    match = await _find_beneficiary_match(db, payload.nombres, payload.ap_paterno, payload.ap_materno)
    return {
        "match": match is not None,
        "already_registered": bool(match and match.matched_patient_id is not None),
    }


@router.get("/admin/beneficiaries", response_model=List[schemas.BeneficiaryAdminItem])
async def search_beneficiaries_admin(
    q: str = Query(..., min_length=2, max_length=120),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    Búsqueda administrativa (SUPER_ADMIN) del padrón precargado de beneficiarios,
    para corregir registros con nombres/apellidos incompletos que impiden que el
    autoregistro público encuentre la coincidencia. Herramienta temporal.
    """
    norm_q = normalize_name(q)
    result = await db.execute(select(models.PreregisteredBeneficiary))
    candidates = result.scalars().all()

    matches = [
        c for c in candidates
        if norm_q in normalize_name(" ".join(filter(None, [c.nombres, c.ap_paterno, c.ap_materno])))
    ]
    matches.sort(key=lambda c: (c.nombres or "", c.ap_paterno or ""))

    return [
        {
            "id": c.id,
            "nombres": c.nombres,
            "ap_paterno": c.ap_paterno,
            "ap_materno": c.ap_materno,
            "depto": c.depto,
            "already_registered": c.matched_patient_id is not None,
        }
        for c in matches[:50]
    ]


@router.get("/admin/beneficiaries/paginated", response_model=schemas.PaginatedBeneficiaryResponse)
async def list_beneficiaries_admin(
    skip: int = 0,
    limit: int = 20,
    search: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    Lista completa (paginada) del padrón precargado, con buscador opcional.
    A diferencia de /admin/beneficiaries (que exige q de al menos 2
    caracteres), este endpoint permite ver TODO el padrón para detectar y
    limpiar duplicados o registros incompletos de forma visual.
    """
    base_query = select(models.PreregisteredBeneficiary)

    if search:
        search_term = f"%{search}%"
        base_query = base_query.where(
            or_(
                models.PreregisteredBeneficiary.nombres.ilike(search_term),
                models.PreregisteredBeneficiary.ap_paterno.ilike(search_term),
                models.PreregisteredBeneficiary.ap_materno.ilike(search_term),
                models.PreregisteredBeneficiary.depto.ilike(search_term),
            )
        )

    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    items_query = (
        base_query
        .order_by(models.PreregisteredBeneficiary.nombres, models.PreregisteredBeneficiary.ap_paterno)
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(items_query)
    candidates = result.scalars().all()

    return {
        "total": total,
        "items": [
            {
                "id": c.id,
                "nombres": c.nombres,
                "ap_paterno": c.ap_paterno,
                "ap_materno": c.ap_materno,
                "depto": c.depto,
                "already_registered": c.matched_patient_id is not None,
            }
            for c in candidates
        ],
    }


@router.delete("/admin/beneficiaries/{beneficiary_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_beneficiary_admin(
    beneficiary_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    Borra permanentemente una entrada del padrón precargado (SUPER_ADMIN).
    Uso principal: eliminar duplicados (ej. "Fabiana" vs "Faviana") dejando
    solo el registro correcto. Si el beneficiario ya se autoregistró
    (matched_patient_id no nulo), se rechaza el borrado para no perder la
    trazabilidad del vínculo con su ficha de paciente real; en ese caso se
    debe corregir el registro en vez de borrarlo.
    """
    result = await db.execute(
        select(models.PreregisteredBeneficiary).where(models.PreregisteredBeneficiary.id == beneficiary_id)
    )
    beneficiary = result.scalar_one_or_none()
    if not beneficiary:
        raise HTTPException(status_code=404, detail="Beneficiario no encontrado en el padrón.")

    if beneficiary.matched_patient_id is not None:
        raise HTTPException(
            status_code=409,
            detail="No se puede borrar: este beneficiario ya está vinculado a un paciente registrado. Corrígelo en vez de borrarlo.",
        )

    await db.delete(beneficiary)
    await db.commit()
    return None


@router.post("/admin/beneficiaries", response_model=schemas.BeneficiaryAdminItem, status_code=status.HTTP_201_CREATED)
async def create_beneficiary_admin(
    payload: schemas.BeneficiaryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    Agrega un beneficiario nuevo al padrón precargado (SUPER_ADMIN), para
    pacientes que no forman parte del padrón original (pacientes.csv) y por
    tanto no pueden completar el autoregistro público sin esta entrada.
    """
    existing = await _find_beneficiary_match(db, payload.nombres, payload.ap_paterno, payload.ap_materno)
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Ya existe un beneficiario con ese nombre en el padrón. Corrígelo en vez de duplicarlo.",
        )

    beneficiary = models.PreregisteredBeneficiary(
        nombres=payload.nombres.strip(),
        ap_paterno=(payload.ap_paterno or "").strip() or None,
        ap_materno=(payload.ap_materno or "").strip() or None,
        depto=(payload.depto or "").strip() or None,
    )
    db.add(beneficiary)
    await db.commit()
    await db.refresh(beneficiary)

    return {
        "id": beneficiary.id,
        "nombres": beneficiary.nombres,
        "ap_paterno": beneficiary.ap_paterno,
        "ap_materno": beneficiary.ap_materno,
        "depto": beneficiary.depto,
        "already_registered": False,
    }


@router.put("/admin/beneficiaries/{beneficiary_id}", response_model=schemas.BeneficiaryAdminItem)
async def update_beneficiary_admin(
    beneficiary_id: int,
    payload: schemas.BeneficiaryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    Corrige nombres/apellidos/depto de un beneficiario del padrón precargado
    (SUPER_ADMIN). Herramienta temporal para resolver casos donde el padrón
    solo tiene un nombre/apellido y el paciente real tiene dos, impidiendo el
    autoregistro.
    """
    result = await db.execute(
        select(models.PreregisteredBeneficiary).where(models.PreregisteredBeneficiary.id == beneficiary_id)
    )
    beneficiary = result.scalar_one_or_none()
    if not beneficiary:
        raise HTTPException(status_code=404, detail="Beneficiario no encontrado en el padrón.")

    beneficiary.nombres = payload.nombres.strip()
    beneficiary.ap_paterno = (payload.ap_paterno or "").strip() or None
    beneficiary.ap_materno = (payload.ap_materno or "").strip() or None
    beneficiary.depto = (payload.depto or "").strip() or None

    await db.commit()
    await db.refresh(beneficiary)

    return {
        "id": beneficiary.id,
        "nombres": beneficiary.nombres,
        "ap_paterno": beneficiary.ap_paterno,
        "ap_materno": beneficiary.ap_materno,
        "depto": beneficiary.depto,
        "already_registered": beneficiary.matched_patient_id is not None,
    }


@router.post("/admin/beneficiaries/{beneficiary_id}/reset-registration", response_model=schemas.BeneficiaryAdminItem)
async def reset_beneficiary_registration(
    beneficiary_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    Herramienta temporal (pruebas): si este beneficiario del padrón fue
    reclamado por un paciente creado durante pruebas de autoregistro, borra
    ese paciente de prueba (junto con su usuario y datos médicos/documentos
    asociados) y libera el padrón para que un beneficiario real pueda
    autoregistrarse. No modifica nombres/apellidos/depto del padrón.
    """
    result = await db.execute(
        select(models.PreregisteredBeneficiary).where(models.PreregisteredBeneficiary.id == beneficiary_id)
    )
    beneficiary = result.scalar_one_or_none()
    if not beneficiary:
        raise HTTPException(status_code=404, detail="Beneficiario no encontrado en el padrón.")

    if beneficiary.matched_patient_id:
        patient_result = await db.execute(
            select(models.Patient).where(models.Patient.id == beneficiary.matched_patient_id)
        )
        patient = patient_result.scalar_one_or_none()
        if patient:
            user_id = patient.user_id
            document_urls = await _collect_patient_document_urls(db, patient)
            try:
                await db.delete(patient)
                if user_id:
                    user_result = await db.execute(select(models.User).where(models.User.id == user_id))
                    user = user_result.scalar_one_or_none()
                    if user:
                        await db.delete(user)
                await db.commit()
            except IntegrityError:
                await db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="No se pudo borrar el paciente/usuario de prueba: tiene otros registros asociados.",
                )

            # Solo se borran los archivos de Storage una vez que el paciente
            # ya fue eliminado exitosamente en BD (evita dejar el registro
            # con enlaces rotos si la transacción de arriba hubiera fallado).
            _delete_storage_urls(document_urls)

    beneficiary.matched_patient_id = None
    await db.commit()
    await db.refresh(beneficiary)

    return {
        "id": beneficiary.id,
        "nombres": beneficiary.nombres,
        "ap_paterno": beneficiary.ap_paterno,
        "ap_materno": beneficiary.ap_materno,
        "depto": beneficiary.depto,
        "already_registered": beneficiary.matched_patient_id is not None,
    }


@router.post("/self-register", response_model=schemas.Token, status_code=status.HTTP_201_CREATED)
async def self_register_patient(
    patient_in: schemas.PatientSelfRegisterCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Autoregistro público de beneficiarios desde el Login. Crea el usuario
    (rol PACIENTE) y la ficha del paciente en un solo paso, y devuelve un
    token de acceso para dejar al beneficiario logueado directamente en su
    portal de carga de documentos.
    """
    # 1. Revalidar coincidencia contra el padrón (nunca confiar solo en el frontend)
    match = await _find_beneficiary_match(db, patient_in.nombres, patient_in.ap_paterno, patient_in.ap_materno)
    if not match:
        raise HTTPException(
            status_code=400,
            detail="No encontramos este nombre en la base de datos de beneficiarios de la Fundación.",
        )
    if match.matched_patient_id is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Este beneficiario ya tiene una cuenta registrada en el sistema. "
                "Si crees que es un error o necesitas corregirla, comunícate al WhatsApp "
                f"{WHATSAPP_CONTACTO}."
            ),
        )

    # 2. Validar edad / CI
    age = calculate_age(patient_in.fecha_nac)
    is_minor = age < 18
    if is_minor and not patient_in.tutor:
        raise HTTPException(
            status_code=400,
            detail=f"El paciente es menor ({age} años). Es OBLIGATORIO registrar Tutor.",
        )
    if not is_minor and not (patient_in.ci and patient_in.ci.strip()):
        raise HTTPException(
            status_code=400,
            detail="El Carnet de Identidad (CI) es obligatorio para beneficiarios mayores de edad.",
        )

    # 3. Verificar el correo
    # Se permite que un tutor comparta su email para cuentas de menores (PACIENTE),
    # pero NO se permite si el email pertenece a un ADMIN/REGISTRADOR, ni si ya
    # existe una cuenta PACIENTE con exactamente la misma contraseña.
    existing_users_q = await db.execute(select(models.User).where(models.User.email == patient_in.email))
    existing_users = existing_users_q.scalars().all()

    if any(u.role != 'PACIENTE' for u in existing_users):
        raise HTTPException(
            status_code=400,
            detail="El correo electrónico ya está en uso por una cuenta de administración. Usa otro correo."
        )
    from app.core.security import verify_password as _vp
    if any(_vp(patient_in.password, u.password_hash) for u in existing_users):
        raise HTTPException(
            status_code=400,
            detail="Ya existe una cuenta con este correo y contraseña. Si es tuyo, inicia sesión directamente."
        )

    try:
        # 4. Crear Usuario
        db_user = models.User(
            email=patient_in.email,
            password_hash=hash_password(patient_in.password),
            role="PACIENTE",
            estado="ACTIVO",
        )
        db.add(db_user)
        await db.flush()

        # 5. Crear Paciente (misma lógica anidada que create_patient)
        patient_data = patient_in.model_dump(exclude={"tutor", "medical", "treatments", "complications", "password"})
        patient_data["estado"] = "PENDIENTE_DOC"
        patient_data["user_id"] = db_user.id

        db_patient = models.Patient(**patient_data)
        db.add(db_patient)
        await db.flush()

        if patient_in.tutor:
            db.add(models.Tutor(**patient_in.tutor.model_dump(), patient_id=db_patient.id))

        if patient_in.medical:
            db.add(models.PatientMedical(**patient_in.medical.model_dump(), patient_id=db_patient.id))

        for treatment in patient_in.treatments:
            db.add(models.PatientTreatment(**treatment.model_dump(), patient_id=db_patient.id))

        for comp_in in patient_in.complications:
            db.add(models.PatientComplication(
                patient_id=db_patient.id,
                complication_code=comp_in.complication_code,
                detalle=comp_in.detalle,
            ))

        match.matched_patient_id = db_patient.id

        await db.commit()
    except Exception as e:
        await db.rollback()
        err_msg = str(e).lower()
        if "users_email_key" in err_msg:
            raise HTTPException(status_code=400, detail="El correo electrónico ya está registrado.")
        if "patients_ci_key" in err_msg:
            raise HTTPException(status_code=400, detail="Ya existe un paciente con este CI.")
        if "tutors_ci_key" in err_msg:
            raise HTTPException(status_code=400, detail="El CI del Tutor ya está registrado.")
        raise HTTPException(status_code=500, detail=f"Error creando el registro: {str(e)}")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(subject=db_user.id, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=schemas.PatientDetailResponse)
async def read_patient_me(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Obtiene la ficha del paciente asociado al usuario logueado.
    """
    # Buscamos al paciente cuyo user_id coincida con el usuario actual
    query = (
        select(models.Patient)
        .where(models.Patient.user_id == current_user.id)
        # Cargamos relaciones para que no falle el esquema
        .options(
            selectinload(models.Patient.tutor),
            selectinload(models.Patient.medical),
            selectinload(models.Patient.treatments),
            selectinload(models.Patient.complications),
        )
    )
    result = await db.execute(query)
    patient = result.scalars().first()

    if not patient:
        # Si entra un ADMIN aquí, dará 404 (correcto, porque no es paciente)
        # Si entra un PACIENTE nuevo sin ficha, también dará 404
        raise HTTPException(status_code=404, detail="No se encontró ficha de paciente asociada a este usuario.")

    observations_query = (
        select(models.PatientStatusEvent)
        .where(
            models.PatientStatusEvent.patient_id == patient.id,
            models.PatientStatusEvent.new_state == "PENDIENTE_DOC",
        )
        .order_by(models.PatientStatusEvent.created_at.desc())
        .limit(1)
    )
    observations_result = await db.execute(observations_query)
    latest_event = observations_result.scalars().first()
    if latest_event and latest_event.payload:
        patient.observaciones_doc = latest_event.payload.get("observaciones")
    else:
        patient.observaciones_doc = None

    return patient

@router.get("/me")
async def get_my_patient_profile(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Devuelve perfil + FLAG si tiene tutor.
    """
    # 1. QUERY CORREGIDA: Usamos selectinload para traer al tutor (si existe)
    query = (
        select(models.Patient)
        .where(models.Patient.user_id == current_user.id)
        .options(
            selectinload(models.Patient.tutor) # 👈 ¡IMPORTANTE! Cargar la relación
        )
    )
    result = await db.execute(query)
    patient = result.scalars().first()

    if not patient:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")

    # 2. LOGICA CORREGIDA: Verificamos si el objeto 'tutor' existe
    has_tutor_linked = patient.tutor is not None

    observations_query = (
        select(models.PatientStatusEvent)
        .where(
            models.PatientStatusEvent.patient_id == patient.id,
            models.PatientStatusEvent.new_state == "PENDIENTE_DOC",
        )
        .order_by(models.PatientStatusEvent.created_at.desc())
        .limit(1)
    )
    observations_result = await db.execute(observations_query)
    latest_event = observations_result.scalars().first()
    observaciones_doc = None
    if latest_event and latest_event.payload:
        observaciones_doc = latest_event.payload.get("observaciones")

    return {
        "id": patient.id,
        "estado": patient.estado,
        "has_tutor": has_tutor_linked, # 👈 AQUI ESTABA EL ERROR
        "monto_aporte_comprometido": float(patient.monto_aporte_comprometido) if patient.monto_aporte_comprometido is not None else None,
        
        # Docs del Paciente
        "ci": patient.url_ci_paciente,
        "medico": patient.url_certificado_medico,
        "compromiso": patient.url_declaracion_aporte,
        "foto": patient.url_foto_paciente,
        
        # Docs del Tutor
        "ci_tutor": patient.url_ci_tutor,
        "foto_tutor": patient.url_foto_tutor,
        "observaciones_doc": observaciones_doc,
    }

@router.post("/me/upload-document")
async def upload_my_document(
    doc_type: str = Form(...), 
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Sube documento sobrescribiendo el anterior para no llenar la nube de basura.
    """
    query = select(models.Patient).where(models.Patient.user_id == current_user.id)
    result = await db.execute(query)
    patient = result.scalars().first()

    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    # 1. DEFINIR ESTRUCTURA
    if doc_type not in DOCUMENT_STRUCTURE_MAP:
        raise HTTPException(status_code=400, detail="Tipo de documento inválido.")

    subfolder, file_prefix, db_column = DOCUMENT_STRUCTURE_MAP[doc_type]

    # 2. VALIDAR TIPO Y TAMAÑO
    content_type = file.content_type or ""
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido.")

    # 3. NOMBRE FIJO (SIN UUID) PARA SOBRESCRIBIR
    # OJO: Esto funciona perfecto si siempre suben el mismo formato (ej. siempre PDF).
    # Si cambian de PDF a JPG, quedarán ambos, pero es un mal menor por ahora.
    file_extension = file.filename.split(".")[-1]
    
    # RUTA LIMPIA: pacientes/15/legal/identidad/ci_paciente.pdf
    firebase_path = f"pacientes/{patient.id}/{subfolder}/{file_prefix}.{file_extension}"
    
    try:
        file_content = await file.read()
        if len(file_content) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Archivo demasiado grande. Máximo {MAX_FILE_SIZE_MB}MB."
            )
        public_url = await run_in_threadpool(
            upload_file_to_firebase, file_content, firebase_path, file.content_type
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error subiendo: {str(e)}")

    # 3. GUARDAR URL
    setattr(patient, db_column, public_url)
    await db.commit()

    return {"msg": "Actualizado exitosamente", "url": public_url, "type": doc_type}


@router.post("/{patient_id}/upload-document")
async def upload_patient_document_admin(
    patient_id: int,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    Permite al SUPER_ADMIN subir o reemplazar un documento del paciente en su
    nombre (mismo mecanismo que /me/upload-document, sobrescribe el anterior).
    Cubre casos donde el beneficiario no puede volver a subir el archivo por
    su cuenta, o se registró sin un documento y lo envía después.
    """
    patient = await db.get(models.Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    if doc_type not in DOCUMENT_STRUCTURE_MAP:
        raise HTTPException(status_code=400, detail="Tipo de documento inválido.")

    subfolder, file_prefix, db_column = DOCUMENT_STRUCTURE_MAP[doc_type]

    content_type = file.content_type or ""
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido.")

    file_extension = file.filename.split(".")[-1]
    firebase_path = f"pacientes/{patient.id}/{subfolder}/{file_prefix}.{file_extension}"

    file_content = await file.read()
    if len(file_content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Archivo demasiado grande. Máximo {MAX_FILE_SIZE_MB}MB."
        )
    try:
        public_url = await run_in_threadpool(
            upload_file_to_firebase, file_content, firebase_path, file.content_type
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error subiendo: {str(e)}")

    setattr(patient, db_column, public_url)
    await db.commit()

    return {"msg": "Actualizado exitosamente", "url": public_url, "type": doc_type}


@router.put("/me/complete-registration")
async def complete_registration(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Cambia estado a HABILITADO.
    """
    query = select(models.Patient).where(models.Patient.user_id == current_user.id)
    result = await db.execute(query)
    patient = result.scalars().first()

    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    # AQUÍ PODRÍAS VALIDAR SI FALTA ALGO DEL TUTOR, PERO LO DEJAMOS AL FRONTEND POR AHORA
    patient.estado = "HABILITADO"
    
    await db.commit()
    return {"msg": "Carpeta enviada a revisión."}



@router.get("/", response_model=List[schemas.PatientResponse])
async def read_patients(
    skip: int = 0,
    limit: int = 10000,
    search: str = None,
    estado: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    query = (
        select(models.Patient)
        .options(
            selectinload(models.Patient.tutor),
            selectinload(models.Patient.medical),
            selectinload(models.Patient.treatments),
            selectinload(models.Patient.complications),
        )
        .order_by(models.Patient.created_at.desc()) # Ordenar por defecto
    )

    # Lógica de búsqueda
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                models.Patient.nombres.ilike(search_term),
                models.Patient.ap_paterno.ilike(search_term),
                models.Patient.ap_materno.ilike(search_term),
                models.Patient.ci.ilike(search_term)
            )
        )
    
    # Filtro por estado
    if estado:
        query = query.where(models.Patient.estado == estado)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()

@router.get("/paginated", response_model=schemas.PaginatedPatientResponse)
async def read_paginated_patients(
    skip: int = 0,
    limit: int = 20,
    search: str = None,
    estado: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    # "NO_REGISTRADO" no es un estado real de la tabla patients: son personas
    # que la Fundación ya conoce (padrón precargado de pacientes.csv, con
    # nombre/apellidos/depto) pero que nunca completaron el autoregistro, por
    # lo que no tienen fila en patients. Se listan aparte, desde el padrón.
    if estado == "NO_REGISTRADO":
        base_query = select(models.PreregisteredBeneficiary).where(
            models.PreregisteredBeneficiary.matched_patient_id.is_(None)
        )

        if search:
            search_term = f"%{search}%"
            base_query = base_query.where(
                or_(
                    models.PreregisteredBeneficiary.nombres.ilike(search_term),
                    models.PreregisteredBeneficiary.ap_paterno.ilike(search_term),
                    models.PreregisteredBeneficiary.ap_materno.ilike(search_term),
                    models.PreregisteredBeneficiary.depto.ilike(search_term),
                )
            )

        count_query = select(func.count()).select_from(base_query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar_one()

        items_query = (
            base_query
            .order_by(models.PreregisteredBeneficiary.nombres, models.PreregisteredBeneficiary.ap_paterno)
            .offset(skip)
            .limit(limit)
        )
        items_result = await db.execute(items_query)
        beneficiaries = items_result.scalars().all()

        items = [
            {
                "id": b.id,
                "tipo": "NO_REGISTRADO",
                "user_id": None,
                "nombres": b.nombres,
                "ap_paterno": b.ap_paterno,
                "ap_materno": b.ap_materno,
                "depto": b.depto,
                "estado": "NO_REGISTRADO",
                "created_at": b.created_at,
                "updated_at": b.created_at,
            }
            for b in beneficiaries
        ]
        return {"total": total, "items": items}

    base_query = select(models.Patient)

    if search:
        search_term = f"%{search}%"
        base_query = base_query.where(
            or_(
                models.Patient.nombres.ilike(search_term),
                models.Patient.ap_paterno.ilike(search_term),
                models.Patient.ap_materno.ilike(search_term),
                models.Patient.ci.ilike(search_term)
            )
        )

    if estado:
        base_query = base_query.where(models.Patient.estado == estado)

    # Count total
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Get items
    items_query = (
        base_query
        .options(
            selectinload(models.Patient.tutor),
            selectinload(models.Patient.medical),
            selectinload(models.Patient.treatments),
            selectinload(models.Patient.complications),
        )
        .order_by(models.Patient.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    items_result = await db.execute(items_query)
    items = items_result.scalars().all()

    return {"total": total, "items": items}

@router.put("/{patient_id}/activate", response_model=schemas.UserResponse)
async def activate_patient_user(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    Activa al paciente y genera su usuario automáticamente.
    - Mayor de edad: email del paciente, contraseña = CI del paciente.
    - Menor de edad: email del tutor, contraseña = CI del tutor.
    """
    # 0. Permisos
    if current_user.role not in ["SUPER_ADMIN", "REGISTRADOR"]:
        raise HTTPException(status_code=403, detail="No tiene permisos para generar credenciales.")
    # 1. Buscar Paciente
    query = (
        select(models.Patient)
        .where(models.Patient.id == patient_id)
        .options(
            selectinload(models.Patient.medical),
            selectinload(models.Patient.tutor),
        )
    )
    result = await db.execute(query)
    db_patient = result.scalars().first()

    if db_patient is None:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    if db_patient.user_id:
        raise HTTPException(status_code=400, detail="El paciente ya tiene un usuario asociado")

    # 2. Validar campos obligatorios
    missing_fields = _get_missing_activation_fields(db_patient)
    if missing_fields:
        detail = "Faltan datos obligatorios para activar: " + ", ".join(missing_fields)
        raise HTTPException(status_code=400, detail=detail)

    # 3. Determinar credenciales según edad
    is_minor = db_patient.edad_calc < 18

    if is_minor:
        # Menor de edad: credenciales del tutor
        username_email = db_patient.tutor.email.strip()
        hashed_password = hash_password(db_patient.tutor.ci)
        credential_note = f"Credenciales del TUTOR — Email: {username_email} | Contraseña inicial: CI del tutor"
    else:
        # Mayor de edad: credenciales propias
        username_email = db_patient.email.strip()
        hashed_password = hash_password(db_patient.ci)
        credential_note = f"Credenciales del paciente — Email: {username_email} | Contraseña inicial: CI del paciente"

    # 4. Crear Usuario
    db_user = models.User(
        email=username_email,
        password_hash=hashed_password,
        role="PACIENTE",
        estado="ACTIVO",
    )
    db.add(db_user)
    await db.flush()

    _log_audit_event(
        db=db,
        actor_id=current_user.id,
        entidad="patient",
        entidad_id=db_patient.id,
        accion="ACTIVAR_PACIENTE",
        payload={
            "es_menor": is_minor,
            "email_credencial": username_email,
            "nota": credential_note,
        },
    )

    # 5. Vincular y cambiar estado
    db_patient.user_id = db_user.id
    db_patient.estado = "PENDIENTE_DOC"

    try:
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback()
        if "users_email_key" in str(e):
            raise HTTPException(
                status_code=400,
                detail="El email ya está registrado. Verifique el email del paciente o del tutor."
            )
        raise HTTPException(status_code=500, detail=f"Error al generar credenciales: {e}")

@router.get("/{patient_id}", response_model=schemas.PatientDetailResponse)
async def get_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    query = (
        select(models.Patient)
        .where(models.Patient.id == patient_id)
        .options(
            selectinload(models.Patient.tutor),
            selectinload(models.Patient.medical),
            selectinload(models.Patient.treatments),
            selectinload(models.Patient.complications),
        )
    )
    result = await db.execute(query)
    db_patient = result.scalars().first()
    
    if db_patient is None:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    return db_patient

@router.put("/{patient_id}", response_model=schemas.PatientResponse)
async def update_patient(
    patient_id: int, 
    patient_in: schemas.PatientUpdate, 
    db: AsyncSession = Depends(get_db),
    # 👇 INYECTAMOS AL USUARIO PARA VER SU ROL
    current_user: models.User = Depends(deps.get_current_active_user)
):
    # 1. Definir permisos
    is_superuser = current_user.role == "SUPER_ADMIN"
    is_registrador = current_user.role == "REGISTRADOR"

    if not (is_superuser or is_registrador):
        raise HTTPException(status_code=403, detail="No tiene permisos para editar pacientes.")

    # 2. Buscar paciente existente
    query = (
        select(models.Patient)
        .where(models.Patient.id == patient_id)
        .options(
            selectinload(models.Patient.tutor),
            selectinload(models.Patient.medical)
        )
    )
    result = await db.execute(query)
    db_patient = result.scalars().first()
    
    if not db_patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    # =========================================================================
    # ZONA 1: DATOS GENERALES (Nombre, Dirección, Tutor)
    # ✅ Tanto Admin como Registrador pueden tocar esto
    # =========================================================================
    
    # Excluimos lo médico/complejo
    exclude_fields = {'tutor', 'medical_info', 'medical', 'treatments', 'complications'}
    update_data = patient_in.model_dump(exclude_unset=True, exclude=exclude_fields)

    for field, value in update_data.items():
        setattr(db_patient, field, value)

    # Actualizar Tutor (Permitido para ambos)
    if patient_in.tutor:
        if db_patient.tutor:
            tutor_data = patient_in.tutor.model_dump(exclude_unset=True)
            for field, value in tutor_data.items():
                setattr(db_patient.tutor, field, value)
        else:
            new_tutor_data = patient_in.tutor.model_dump()
            new_tutor = models.Tutor(**new_tutor_data, patient_id=patient_id)
            db.add(new_tutor)

    # =========================================================================
    # ZONA 2: DATOS MÉDICOS (Tratamientos, Complicaciones)
    # 🔒 SOLO SUPER ADMIN
    # =========================================================================
    
    if is_superuser:
        # A) Información Médica Básica (Tipo diabetes, tiempo)
        medical_payload = getattr(patient_in, 'medical', None) or getattr(patient_in, 'medical_info', None)
        if medical_payload:
            if db_patient.medical:
                medical_update = medical_payload.model_dump(exclude_unset=True)
                for field, value in medical_update.items():
                    setattr(db_patient.medical, field, value)
            else:
                medical_data = medical_payload.model_dump()
                new_medical = models.PatientMedical(**medical_data, patient_id=patient_id)
                db.add(new_medical)

        # B) Tratamientos (Borrar y Reescribir)
        if patient_in.treatments is not None:
            _validate_insulin_treatment_payload(patient_in.treatments)
            await db.execute(
                delete(models.PatientTreatment).where(models.PatientTreatment.patient_id == patient_id)
            )
            for t in patient_in.treatments:
                t_data = t.model_dump()
                new_t = models.PatientTreatment(**t_data, patient_id=patient_id)
                db.add(new_t)

        # C) Complicaciones (Borrar y Reescribir)
        if patient_in.complications is not None:
            await db.execute(
                delete(models.PatientComplication).where(models.PatientComplication.patient_id == patient_id)
            )
            for c in patient_in.complications:
                if c.complication_code == "OTRAS" and not c.detalle:
                     raise HTTPException(status_code=400, detail="Debe especificar el detalle para 'OTRAS'")
                
                new_c = models.PatientComplication(
                    patient_id=patient_id,
                    complication_code=c.complication_code,
                    detalle=c.detalle
                )
                db.add(new_c)
    
    else:
        # Si es REGISTRADOR, logueamos que intentó (o que se ignoró) la parte médica
        # Esto evita que el Registrador borre tratamientos por accidente
        print(f"👮‍♂️ AUDIT: Usuario {current_user.email} (Registrador) actualizó datos personales. Cambios médicos ignorados.")

    # =========================================================================
    # GUARDADO FINAL
    # =========================================================================
    try:
        await db.commit()
        
        # Refrescamos todo para devolver la foto completa
        query_final = (
            select(models.Patient)
            .where(models.Patient.id == patient_id)
            .options(
                selectinload(models.Patient.tutor),
                selectinload(models.Patient.medical),
                selectinload(models.Patient.treatments),
                selectinload(models.Patient.complications),
            )
        )
        res_final = await db.execute(query_final)
        return res_final.scalars().first()

    except Exception as e:
        await db.rollback()
        print(f"🔥 ERROR UPDATE: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al guardar cambios: {str(e)}")


@router.post("/{patient_id}/tutor", response_model=schemas.TutorResponse, status_code=status.HTTP_201_CREATED)
async def create_tutor(
    patient_id: int,
    tutor: schemas.TutorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    result = await db.execute(select(models.Patient).where(models.Patient.id == patient_id))
    db_patient = result.scalars().first()
    
    if db_patient is None:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    # Pydantic v2
    db_tutor = models.Tutor(**tutor.model_dump(), patient_id=patient_id)
    db.add(db_tutor)
    await db.commit()
    await db.refresh(db_tutor)
    return db_tutor

@router.put("/{patient_id}/tutor", response_model=schemas.TutorResponse)
async def update_tutor(
    patient_id: int,
    tutor: schemas.TutorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    result = await db.execute(select(models.Tutor).where(models.Tutor.patient_id == patient_id))
    db_tutor = result.scalars().first()
    
    if db_tutor is None:
        raise HTTPException(status_code=404, detail="Tutor no encontrado para este paciente")

    # Pydantic v2
    for field, value in tutor.model_dump(exclude_unset=True).items():
        setattr(db_tutor, field, value)

    await db.commit()
    await db.refresh(db_tutor)
    return db_tutor

@router.get("/{patient_id}/tutor", response_model=schemas.TutorResponse)
async def get_tutor_by_patient_id(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    result = await db.execute(select(models.Tutor).where(models.Tutor.patient_id == patient_id))
    db_tutor = result.scalars().first()
    
    if db_tutor is None:
        raise HTTPException(status_code=404, detail="Tutor no encontrado para este paciente")
    return db_tutor

@router.post("/{patient_id}/medical", response_model=schemas.PatientMedicalResponse, status_code=status.HTTP_201_CREATED)
async def create_patient_medical(
    patient_id: int,
    medical: schemas.PatientMedicalCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    result = await db.execute(select(models.Patient).where(models.Patient.id == patient_id))
    db_patient = result.scalars().first()
    
    if db_patient is None:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    # Pydantic v2
    db_medical = models.PatientMedical(**medical.model_dump(), patient_id=patient_id)
    db.add(db_medical)
    await db.commit()
    await db.refresh(db_medical)
    return db_medical

@router.put("/{patient_id}/medical", response_model=schemas.PatientMedicalResponse)
async def update_patient_medical(
    patient_id: int,
    medical: schemas.PatientMedicalUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    result = await db.execute(select(models.PatientMedical).where(models.PatientMedical.patient_id == patient_id))
    db_medical = result.scalars().first()
    
    if db_medical is None:
        raise HTTPException(status_code=404, detail="Información médica no encontrada para este paciente")

    # Pydantic v2
    for field, value in medical.model_dump(exclude_unset=True).items():
        setattr(db_medical, field, value)

    await db.commit()
    await db.refresh(db_medical)
    return db_medical

@router.post("/{patient_id}/complications", response_model=schemas.PatientComplicationResponse, status_code=status.HTTP_201_CREATED)
async def add_patient_complication(
    patient_id: int,
    complication: schemas.PatientComplicationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    result = await db.execute(select(models.Patient).where(models.Patient.id == patient_id))
    db_patient = result.scalars().first()
    
    if db_patient is None:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    
    q_type = select(models.ComplicationType).where(models.ComplicationType.code == complication.complication_code)
    res_type = await db.execute(q_type)
    db_comp_type = res_type.scalars().first()
    
    if db_comp_type is None:
        raise HTTPException(status_code=400, detail=f"Tipo de complicación '{complication.complication_code}' no válido")

    if complication.complication_code == "OTRAS" and not complication.detalle:
        raise HTTPException(status_code=400, detail="El detalle es obligatorio cuando el tipo de complicación es 'OTRA'")
    
    # Pydantic v2
    db_complication = models.PatientComplication(**complication.model_dump(), patient_id=patient_id)
    db.add(db_complication)
    await db.commit()
    await db.refresh(db_complication)
    return db_complication

@router.post("/{patient_id}/treatments", response_model=schemas.PatientTreatmentResponse, status_code=status.HTTP_201_CREATED)
async def add_patient_treatment(
    patient_id: int,
    treatment: schemas.PatientTreatmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    result = await db.execute(select(models.Patient).where(models.Patient.id == patient_id))
    db_patient = result.scalars().first()

    if db_patient is None:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    _validate_insulin_treatment_payload([treatment])

    # Pydantic v2
    db_treatment = models.PatientTreatment(**treatment.model_dump(), patient_id=patient_id)
    db.add(db_treatment)
    await db.commit()
    await db.refresh(db_treatment)
    return db_treatment


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    Elimina un paciente y toda su información asociada (Cascade), incluyendo
    sus documentos y evidencias en Firebase Storage. Solo SUPER_ADMIN.
    """
    query = select(models.Patient).where(models.Patient.id == patient_id)
    result = await db.execute(query)
    patient = result.scalars().first()

    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    document_urls = await _collect_patient_document_urls(db, patient)

    try:
        await db.delete(patient)
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar el paciente: {str(e)}")

    # Solo se borran los archivos de Storage una vez que el paciente ya fue
    # eliminado exitosamente en BD.
    _delete_storage_urls(document_urls)

    return None

# --- ENDPOINTS DE BORRADO ESPECÍFICO (HIJOS) ---

@router.delete("/{patient_id}/medical", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient_medical(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    query = select(models.PatientMedical).where(models.PatientMedical.patient_id == patient_id)
    result = await db.execute(query)
    medical = result.scalars().first()

    if not medical:
        raise HTTPException(status_code=404, detail="Ficha médica no encontrada")

    await db.delete(medical)
    await db.commit()
    return None

@router.delete("/{patient_id}/treatments/{treatment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient_treatment(
    patient_id: int,
    treatment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    query = select(models.PatientTreatment).where(
        models.PatientTreatment.id == treatment_id,
        models.PatientTreatment.patient_id == patient_id
    )
    result = await db.execute(query)
    treatment = result.scalars().first()

    if not treatment:
        raise HTTPException(status_code=404, detail="Tratamiento no encontrado o no pertenece a este paciente")

    await db.delete(treatment)
    await db.commit()
    return None

@router.delete("/{patient_id}/complications/{complication_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient_complication(
    patient_id: int,
    complication_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    query = select(models.PatientComplication).where(
        models.PatientComplication.id == complication_id,
        models.PatientComplication.patient_id == patient_id
    )
    result = await db.execute(query)
    complication = result.scalars().first()

    if not complication:
        raise HTTPException(status_code=404, detail="Complicación no encontrada o no pertenece a este paciente")

    await db.delete(complication)
    await db.commit()
    return None

@router.delete("/{patient_id}/tutor", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient_tutor(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    query = select(models.Tutor).where(models.Tutor.patient_id == patient_id)
    result = await db.execute(query)
    tutor = result.scalars().first()

    if not tutor:
        raise HTTPException(status_code=404, detail="Tutor no encontrado para este paciente")

    await db.delete(tutor)
    await db.commit()
    return None

# --- ENDPOINTS DE ACTUALIZACIÓN (PUT) PARA SUB-RECURSOS ---

@router.put("/{patient_id}/treatments/{treatment_id}", response_model=schemas.PatientTreatmentResponse)
async def update_patient_treatment(
    patient_id: int,
    treatment_id: int,
    treatment: schemas.PatientTreatmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    query = select(models.PatientTreatment).where(
        models.PatientTreatment.id == treatment_id,
        models.PatientTreatment.patient_id == patient_id
    )
    result = await db.execute(query)
    db_treatment = result.scalars().first()

    if not db_treatment:
        raise HTTPException(status_code=404, detail="Tratamiento no encontrado o no corresponde a este paciente")
    _validate_insulin_treatment_payload([treatment])

    # Pydantic v2
    for field, value in treatment.model_dump().items():
        setattr(db_treatment, field, value)

    try:
        await db.commit()
        await db.refresh(db_treatment)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al actualizar tratamiento: {str(e)}")

    return db_treatment

@router.put("/{patient_id}/complications/{complication_id}", response_model=schemas.PatientComplicationResponse)
async def update_patient_complication(
    patient_id: int,
    complication_id: int,
    complication: schemas.PatientComplicationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    query = select(models.PatientComplication).where(
        models.PatientComplication.id == complication_id,
        models.PatientComplication.patient_id == patient_id
    )
    result = await db.execute(query)
    db_complication = result.scalars().first()

    if not db_complication:
        raise HTTPException(status_code=404, detail="Complicación no encontrada o no corresponde a este paciente")

    if complication.complication_code != db_complication.complication_code:
        q_type = select(models.ComplicationType).where(models.ComplicationType.code == complication.complication_code)
        res_type = await db.execute(q_type)
        if not res_type.scalars().first():
             raise HTTPException(status_code=400, detail=f"Código de complicación '{complication.complication_code}' no válido")

    if complication.complication_code == "OTRAS" and not complication.detalle:
         raise HTTPException(status_code=400, detail="El detalle es obligatorio para 'OTRA'")

    # Pydantic v2
    for field, value in complication.model_dump().items():
        setattr(db_complication, field, value)

    try:
        await db.commit()
        await db.refresh(db_complication)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al actualizar complicación: {str(e)}")

    return db_complication

# --- SUBIDA DE ARCHIVOS ---

class PatientDocsUpdate(BaseModel):
    url_declaracion_jurada: str
    url_compromiso_firmado: str


class CommitmentResetRequest(BaseModel):
    observacion_admin: Optional[str] = None

@router.put("/me/documents", response_model=schemas.PatientResponse)
async def update_my_documents(
    # --- DOCUMENTOS PUNTO 5.2 y 5.3 DEL REGLAMENTO ---
    
    # 1. Documentos OBLIGATORIOS para TODOS
    ci_paciente: UploadFile = File(..., description="PDF Cédula de Identidad del Paciente"),
    certificado_medico: UploadFile = File(..., description="PDF Certificado Médico"),
    foto_paciente: UploadFile = File(..., description="Fotografía del Paciente"),
    declaracion_aporte: UploadFile = File(..., description="PDF Declaración Jurada de Aporte (Punto 5.3)"),

    # 2. Documentos CONDICIONALES (Solo si tiene Tutor / Menor de edad)
    ci_tutor: Optional[UploadFile] = File(None, description="PDF Cédula del Tutor (Si aplica)"),
    foto_tutor: Optional[UploadFile] = File(None, description="Fotografía del Tutor (Si aplica)"),
    
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    
    # 1. Obtener Paciente y Datos (CON CARGA COMPLETA DE RELACIONES)
    query = (
        select(models.Patient)
        .where(models.Patient.user_id == current_user.id)
        .options(
            selectinload(models.Patient.tutor),
            selectinload(models.Patient.medical),
            selectinload(models.Patient.complications),
            selectinload(models.Patient.treatments),
            # selectinload(models.Patient.contributions) # Descomentar si tu respuesta incluye aportes
        )
    )
    result = await db.execute(query)
    patient = result.scalars().first()

    if not patient:
        raise HTTPException(status_code=400, detail="Usuario sin ficha de paciente.")
    
    # 2. VALIDACIÓN DE REGLA DE NEGOCIO (Menores de edad)
    if patient.tutor:
        if not ci_tutor or not foto_tutor:
             raise HTTPException(
                status_code=400, 
                detail="Al tener un Tutor registrado, es OBLIGATORIO subir la Cédula y Foto del Tutor."
            )

    # --- FUNCIÓN DE SUBIDA (Lógica segura) ---
    async def process_upload(uploaded_file: UploadFile, subfolder: str, prefix: str) -> str:
        if not uploaded_file: return None
        
        if uploaded_file.content_type not in ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail=f"Formato inválido para {prefix}.")
        
        content = await uploaded_file.read()
        if len(content) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=400, detail=f"{prefix} excede los 2MB.")
            
        ext = uploaded_file.filename.split(".")[-1]
        path = f"pacientes/{patient.id}/legal/{subfolder}/{prefix}_{uuid.uuid4().hex[:8]}.{ext}"
        
        try:
            return upload_file_to_firebase(content, path, uploaded_file.content_type)
        except Exception:
            raise HTTPException(status_code=500, detail=f"Error al subir {prefix}")

    # 3. PROCESAR SUBIDAS
    url_ci_pac = await process_upload(ci_paciente, "identidad", "ci_paciente")
    url_medico = await process_upload(certificado_medico, "medico", "cert_medico")
    url_foto_pac = await process_upload(foto_paciente, "fotos", "foto_paciente")
    url_declaracion = await process_upload(declaracion_aporte, "compromisos", "declaracion_aporte")
    
    # Opcionales
    url_ci_tutor = None
    url_foto_tutor = None
    if ci_tutor:
        url_ci_tutor = await process_upload(ci_tutor, "identidad", "ci_tutor")
    if foto_tutor:
        url_foto_tutor = await process_upload(foto_tutor, "fotos", "foto_tutor")

    # 4. GUARDAR EN BD
    # Nota: Pydantic v2 en schemas.py ocultará estas URLs (exclude=True) 
    # y calculará los booleanos (tiene_ci, tiene_foto, etc.) automáticamente.
    patient.url_ci_paciente = url_ci_pac
    patient.url_certificado_medico = url_medico
    patient.url_foto_paciente = url_foto_pac
    patient.url_declaracion_aporte = url_declaracion
    
    if url_ci_tutor:
        patient.url_ci_tutor = url_ci_tutor
    if url_foto_tutor:
        patient.url_foto_tutor = url_foto_tutor
        
    db.add(patient)
    await db.commit()
    await db.refresh(patient)
    
    return patient

@router.get("/me/status", response_model=dict)
async def get_patient_warnings(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Semáforo del Paciente.
    """
    # 1. BUSCAR PACIENTE DE FORMA SEGURA (Sin Lazy Loading)
    query_patient = select(models.Patient).where(models.Patient.user_id == current_user.id)
    result_patient = await db.execute(query_patient)
    patient = result_patient.scalars().first()

    if not patient:
        raise HTTPException(status_code=400, detail="El usuario no tiene una ficha de paciente asociada.")
    
    # 2. VERIFICAR DOCUMENTACIÓN
    missing_docs = []
    
    if not patient.url_ci_paciente: missing_docs.append("Cédula de Identidad")
    if not patient.url_certificado_medico: missing_docs.append("Certificado Médico")
    if not patient.url_foto_paciente: missing_docs.append("Fotografía")
    if not patient.url_declaracion_aporte: missing_docs.append("Declaración de Aporte (Punto 5.3)")
    
    if hasattr(patient, "tutor_id") and patient.tutor_id: 
        if not patient.url_ci_tutor: missing_docs.append("Cédula del Tutor")
        if not patient.url_foto_tutor: missing_docs.append("Foto del Tutor")

    has_docs_warning = len(missing_docs) > 0

    # 3. VERIFICAR APORTE DEL MES ACTUAL
    today = date.today()
    current_period = f"{today.year}-{today.month:02d}"
    
    query_contrib = select(models.MonthlyContribution).where(
        models.MonthlyContribution.patient_id == patient.id,
        models.MonthlyContribution.periodo == current_period,
        models.MonthlyContribution.estado == "ACEPTADO" 
    )
    result_contrib = await db.execute(query_contrib)
    is_up_to_date = result_contrib.scalars().first() is not None
    
    has_payment_warning = not is_up_to_date

    # 4. CONSTRUIR RESPUESTA
    global_block_message = None
    if has_docs_warning:
        global_block_message = "Mientras no cargue todos los documentos obligatorios y el formulario de aporte voluntario firmado, no será sujeto a ningún beneficio de la fundación."

    return {
        "status_global": "INACTIVO" if (has_docs_warning or has_payment_warning) else "ACTIVO",
        "warnings": {
            "incomplete_registration": {
                "active": has_docs_warning,
                "missing_items": missing_docs,
                "message": "Advertencia de registro incompleto"
            },
            "payment_compliance": {
                "active": has_payment_warning,
                "current_period": current_period,
                "message": "Advertencia de incumplimiento de aportes"
            }
        },
        "block_message": global_block_message
    }

@router.get("/me/commitment-template")
async def download_commitment_template(
    monto_compromiso: float = Query(..., gt=0),
    current_user: models.User = Depends(deps.get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    # 1. Buscar paciente y tutor
    query = select(models.Patient).where(models.Patient.user_id == current_user.id).options(selectinload(models.Patient.tutor))
    result = await db.execute(query)
    patient = result.scalars().first()

    if not patient:
        raise HTTPException(status_code=400, detail="Sin datos de paciente.")

    # 2. Manejo de Monto Comprometido
    committed_amount = float(patient.monto_aporte_comprometido) if patient.monto_aporte_comprometido is not None else None
    if committed_amount is not None:
        if round(committed_amount, 2) != round(monto_compromiso, 2):
            raise HTTPException(
                status_code=400,
                detail=f"Su aporte comprometido ya está fijado en Bs. {committed_amount:.2f}.",
            )
    else:
        # Sin evaluación de por medio (o evaluación con categoría ALTA/BAJA,
        # que no fija un monto), rige el aporte estándar mínimo de Bs. 100.
        # Un monto menor solo es válido si lo fijó el evaluador en una
        # evaluación MEDIA (caso cubierto arriba, donde ya hay un
        # committed_amount previo distinto de None).
        if monto_compromiso < 100:
            raise HTTPException(
                status_code=400,
                detail="El aporte mínimo es de Bs. 100. Si no puede cubrirlo, solicite una evaluación socioeconómica.",
            )
        patient.monto_aporte_comprometido = monto_compromiso
        db.add(patient)
        await db.commit()
        committed_amount = monto_compromiso

    # 3. Generar Código de Integridad Determinista
    # Hacemos un hash de: ID + Monto + SecretKey
    raw_str = f"{patient.id}-{int(committed_amount)}-{settings.SECRET_KEY}"
    hash_suffix = hashlib.sha256(raw_str.encode()).hexdigest()[:4].upper()
    security_code = f"P{patient.id}-{int(committed_amount)}-{hash_suffix}"

    monto_str = f"{committed_amount:.2f}"
    monto_literal = numero_a_letras(committed_amount)
    
    tutor = patient.tutor
    full_name_patient = f"{patient.nombres} {patient.ap_paterno} {patient.ap_materno or ''}".strip().title()

    # 4. Iniciar PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=72, leftMargin=72,
        topMargin=52, bottomMargin=52
    )
    
    styles = getSampleStyleSheet()
    
    style_title = ParagraphStyle(
        'TitleStyle', parent=styles['Normal'], fontSize=12,
        leading=14, alignment=TA_CENTER, spaceAfter=20, fontName='Helvetica-Bold'
    )
    style_body = ParagraphStyle(
        'BodyStyle', parent=styles['Normal'], fontSize=11,
        leading=16, alignment=TA_JUSTIFY, spaceAfter=3
    )
    style_code = ParagraphStyle(
        'CodeStyle', parent=styles['Normal'], fontSize=10,
        alignment=TA_LEFT, fontName='Helvetica-Bold'
    )

    style_warning = ParagraphStyle(
        'WarnStyle', parent=styles['BodyText'], fontSize=10,
        alignment=TA_LEFT, fontName='Helvetica-Oblique'
    )

    story = []


    # TÍTULO
    story.append(Paragraph("DECLARACIÓN JURADA DE APORTE VOLUNTARIO Y COMPROMISO INSTITUCIONAL", style_title))
    # CÓDIGO DE SEGURIDAD
    story.append(Paragraph(f"CÓDIGO: {security_code}", style_code))
    story.append(Paragraph("(Válido únicamente si el código es legible y no presenta alteraciones)", style_warning))
    story.append(Spacer(1, 20))
    # TEXTO DINÁMICO
    if tutor:
        intro = f"Yo, <b>{tutor.nombres.title()} {tutor.apellidos.title()}</b>, con Cédula de Identidad Nº <b>{tutor.ci}</b>, en calidad de {tutor.parentesco or 'tutor'} del menor <b>{full_name_patient}</b>, mayor de edad y hábil por derecho, en pleno uso de mis facultades, declaro libre y voluntariamente lo siguiente:"
        clausula_1 = "<b>1. CALIDAD DE BENEFICIARIO:</b> Que acepto y ratifico la condición de beneficiario activo del menor en la <b>Fundación V.I.D.A. Plena</b>, declarando conocer y someterme a sus Estatutos Orgánicos y Reglamento Interno."
        firma_nombre = f"{tutor.nombres.title()} {tutor.apellidos.title()}"
        firma_ci = tutor.ci
    else:
        intro = f"Yo, <b>{full_name_patient}</b>, con Cédula de Identidad Nº <b>{patient.ci}</b>, mayor de edad y hábil por derecho, en pleno uso de mis facultades, declaro libre y voluntariamente lo siguiente:"
        clausula_1 = "<b>1. CALIDAD DE BENEFICIARIO:</b> Que acepto y ratifico mi condición de beneficiario activo de la <b>Fundación V.I.D.A. Plena</b>, declarando conocer y someterme a sus Estatutos Orgánicos y Reglamento Interno."
        firma_nombre = full_name_patient
        firma_ci = patient.ci

    story.append(Paragraph(intro, style_body))
    story.append(Paragraph(clausula_1, style_body))
    
    clausula_2 = f"<b>2. APORTE DE SOSTENIMIENTO:</b> De conformidad con el <b>Art. 58 y siguientes del Código Civil Boliviano</b> y la naturaleza no lucrativa de la entidad, me comprometo a realizar un aporte mensual de <b>Bs. {monto_str} {monto_literal}</b>. Este monto está destinado exclusivamente al fondo de sostenibilidad de los programas sociales, en cumplimiento del objeto social de la Fundación."
    story.append(Paragraph(clausula_2, style_body))

    clausula_3 = "<b>3. ORIGEN DE FONDOS:</b> Declaro que los fondos destinados a estos aportes provienen de actividades lícitas, liberando a la Fundación de cualquier responsabilidad conforme a la <b>Ley Nº 004 (Ley de Lucha contra la Corrupción, Enriquecimiento Ilícito e Investigación de Fortunas \"Marcelo Quiroga Santa Cruz\")</b>."
    story.append(Paragraph(clausula_3, style_body))

    clausula_4 = "<b>4. CUMPLIMIENTO Y REGLAMENTACIÓN:</b> Entiendo que, según el Reglamento Interno de la Fundación, el aporte es fundamental para la operatividad de los programas. El incumplimiento injustificado de mis deberes como beneficiario, incluida la falta de transparencia en la documentación o la desatención de los aportes de sostenibilidad acordados, dará lugar a la revisión de mi permanencia en el programa, previo proceso administrativo interno."
    story.append(Paragraph(clausula_4, style_body))

    clausula_5 = "<b>5. VERACIDAD:</b> Reconozco que la adulteración de este documento o la falsedad en la información proporcionada constituye una falta grave y causal de baja definitiva, sin perjuicio de las acciones legales previstas en el <b>Código Penal</b> por falsedad ideológica."
    story.append(Paragraph(clausula_5, style_body))

    # FECHA AUTOMÁTICA
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    hoy = date.today()
    fecha_texto = f"En conformidad, firmo la presente declaración a los {hoy.day} días del mes de {meses[hoy.month-1]} de {hoy.year}."
    story.append(Paragraph(fecha_texto, style_body))

    story.append(Spacer(1, 60))
    data_firma = [
        ["__________________________"],
        [firma_nombre],
        [f"C.I. {firma_ci}"]
    ]
    tabla_firma = Table(data_firma, colWidths=[200])
    tabla_firma.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,1), (0,1), 'Helvetica-Bold'),
    ]))
    story.append(tabla_firma)

    # Construir PDF
    doc.build(story)
    
    buffer.seek(0)
    return StreamingResponse(
        buffer, 
        media_type="application/pdf", 
        headers={"Content-Disposition": f'attachment; filename="Compromiso_{security_code}.pdf"'}
    )


@router.get("/validate-commitment-code/{code}")
async def validate_commitment_code(
    code: str,
    current_user: models.User = Depends(deps.get_current_super_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Valida un código de seguridad de la Carta de Compromiso (solo Super Admin).
    Formato esperado: P{id}-{monto}-{suffix}
    """
    try:
        # P5-150-A8F2 -> split('-') -> ['P5', '150', 'A8F2']
        parts = code.strip().upper().split('-')
        if len(parts) != 3 or not parts[0].startswith('P'):
            raise HTTPException(status_code=400, detail="Formato de código inválido.")
        
        patient_id = int(parts[0][1:])
        monto = int(parts[1])
        provided_suffix = parts[2]
        
        # Validar la firma matemática
        raw_str = f"{patient_id}-{monto}-{settings.SECRET_KEY}"
        expected_suffix = hashlib.sha256(raw_str.encode()).hexdigest()[:4].upper()
        
        if provided_suffix != expected_suffix:
            raise HTTPException(status_code=400, detail="Código inválido o adulterado (Firma incorrecta).")
        
        # Buscar el paciente en la base de datos
        query = select(models.Patient).where(models.Patient.id == patient_id)
        result = await db.execute(query)
        patient = result.scalars().first()
        
        if not patient:
            raise HTTPException(status_code=404, detail="Paciente no encontrado en el sistema.")
            
        # Verificar que el monto comprometido coincida
        if patient.monto_aporte_comprometido is None or int(patient.monto_aporte_comprometido) != monto:
            raise HTTPException(status_code=400, detail=f"El código es matemáticamente válido, pero el monto actual del paciente en sistema no coincide (Registrado: Bs. {patient.monto_aporte_comprometido}).")
            
        # Responder con la confirmación de validación
        return {
            "valid": True,
            "patient_name": f"{patient.nombres} {patient.ap_paterno} {patient.ap_materno or ''}".strip().title(),
            "ci": patient.ci,
            "monto": monto
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=400, detail="Error procesando el código de seguridad.")

@router.put("/{patient_id}/validate", response_model=schemas.PatientResponse)
async def validate_patient_registration(
    patient_id: int,
    status_update: schemas.PatientStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    El Admin revisa los documentos (URLs) y decide si ACTIVA al paciente.
    """
    # CORRECCIÓN: Usamos select + options(selectinload) en lugar de db.get()
    # para traer todas las relaciones requeridas por el Schema.
    query = (
        select(models.Patient)
        .where(models.Patient.id == patient_id)
        .options(
            selectinload(models.Patient.tutor),
            selectinload(models.Patient.medical),
            selectinload(models.Patient.treatments),
            selectinload(models.Patient.complications),
        )
    )
    result = await db.execute(query)
    patient = result.scalars().first()

    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    # Aplicar el cambio de estado
    old_status = patient.estado
    patient.estado = status_update.estado
    _log_audit_event(
        db=db,
        actor_id=current_user.id,
        entidad="patients",
        entidad_id=patient.id,
        accion="CAMBIAR_ESTADO_VALIDACION",
        payload={
            "old_state": old_status,
            "new_state": status_update.estado,
            "observacion_admin": status_update.observacion_admin,
            "observaciones": [
                obs.model_dump() for obs in (status_update.observaciones or [])
            ],
        },
    )
    
    db.add(patient)
    await db.commit()
    
    # Refresh para asegurar que tenemos los datos más frescos
    await db.refresh(patient)
    
    return patient

# En app/api/endpoints/patients.py

# En app/api/endpoints/patients.py - VERSIÓN FINAL Y SEGURA

@router.put("/{patient_id}/change-status", response_model=schemas.PatientDetailResponse)
async def change_patient_status(
    patient_id: int,
    status_data: schemas.PatientStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):

    allowed_roles = ["SUPER_ADMIN", "REGISTRADOR"]
    if current_user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="No tiene permisos para aprobar/rechazar documentos.")
    """
    Cambio manual de estado por parte del Administrador.
    """
    # 1. Búsqueda optimizada con relaciones
    query = (
        select(models.Patient)
        .where(models.Patient.id == patient_id)
        .options(
            selectinload(models.Patient.tutor),
            selectinload(models.Patient.medical),
            selectinload(models.Patient.treatments),
            selectinload(models.Patient.complications),
        )
    )
    result = await db.execute(query)
    patient = result.scalars().first()

    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    # 2. Intentar actualizar

    allowed_states = ["ACTIVO", "INACTIVO", "PENDIENTE_DOC", "PENDIENTE_APORTE", "HABILITADO"]
    
    if status_data.estado not in allowed_states:
         raise HTTPException(
            status_code=400, 
            detail=f"Estado inválido. Los permitidos son: {allowed_states}"
        )
    old_status = patient.estado
    new_status = status_data.estado
    patient.estado = new_status

    payload = None
    if new_status == "PENDIENTE_DOC" and status_data.observaciones:
        payload = {
            "observaciones": [
                obs.model_dump() for obs in status_data.observaciones
            ]
        }

    status_event = models.PatientStatusEvent(
        patient_id=patient.id,
        user_id=current_user.id,
        old_state=old_status,
        new_state=new_status,
        observacion=status_data.observacion_admin,
        payload=payload,
    )
    _log_audit_event(
        db=db,
        actor_id=current_user.id,
        entidad="patients",
        entidad_id=patient.id,
        accion="CAMBIAR_ESTADO_MANUAL",
        payload={
            "old_state": old_status,
            "new_state": new_status,
            "observacion_admin": status_data.observacion_admin,
            "observaciones": [
                obs.model_dump() for obs in (status_data.observaciones or [])
            ],
        },
    )

    try:
        db.add(patient)
        db.add(status_event)
        await db.commit()
        await db.refresh(patient)
        return patient
    except Exception as e:
        await db.rollback()
        # Si falla (ej. restricción de BD), devolvemos error 400 legible
        raise HTTPException(status_code=400, detail=f"La base de datos rechazó el estado '{status_data.estado}'. Verifique que exista en el catálogo.")


@router.post("/{patient_id}/reset-commitment", response_model=schemas.PatientDetailResponse)
async def reset_patient_commitment(
    patient_id: int,
    reset_data: CommitmentResetRequest,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    allowed_roles = ["SUPER_ADMIN", "REGISTRADOR"]
    if current_user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="No tiene permisos para actualizar compromisos.")

    query = (
        select(models.Patient)
        .where(models.Patient.id == patient_id)
        .options(
            selectinload(models.Patient.tutor),
            selectinload(models.Patient.medical),
            selectinload(models.Patient.treatments),
            selectinload(models.Patient.complications),
        )
    )
    result = await db.execute(query)
    patient = result.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    old_status = patient.estado
    patient.estado = "PENDIENTE_DOC"
    patient.url_declaracion_aporte = None
    patient.monto_aporte_comprometido = None

    admin_note = reset_data.observacion_admin or "Compromiso de aporte reabierto para actualización administrativa."
    status_event = models.PatientStatusEvent(
        patient_id=patient.id,
        user_id=current_user.id,
        old_state=old_status,
        new_state="PENDIENTE_DOC",
        observacion=admin_note,
        payload={"commitment_reset": True},
    )
    _log_audit_event(
        db=db,
        actor_id=current_user.id,
        entidad="patients",
        entidad_id=patient.id,
        accion="RESET_COMMITMENT",
        payload={
            "old_state": old_status,
            "new_state": "PENDIENTE_DOC",
            "observacion_admin": admin_note,
        },
    )

    try:
        db.add(patient)
        db.add(status_event)
        await db.commit()
        await db.refresh(patient)
        return patient
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="No se pudo reabrir el compromiso del paciente.")

