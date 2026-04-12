import io
import uuid
import random
import string
from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form, Query
from fastapi.responses import StreamingResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import or_, delete

# ReportLab para PDFs
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors

from app import models, schemas
from app.api import deps
from app.db import get_db
from app.core.security import hash_password
from app.core.firebase import upload_file_to_firebase

router = APIRouter()

# --- Constantes ---
MAX_FILE_SIZE_MB = 2
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/jpg"]

# --- Funciones Auxiliares ---

def calculate_age(born: date):
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

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
    La activación NO depende de la ficha médica porque en el flujo actual
    esos datos pueden completarse después.
    Asume que 'tutor' YA ESTÁ CARGADO en memoria.
    """
    required_fields = {
        "ci": patient.ci,
        "nombres": patient.nombres,
        "ap_paterno": patient.ap_paterno,
        "fecha_nac": patient.fecha_nac,
        "email": patient.email,
        "direccion": patient.direccion,
        "tel_contacto": patient.tel_contacto,
    }
    missing_fields: List[str] = []
    for field_name, value in required_fields.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            missing_fields.append(field_name)

    # Verificar tutor si aplica (menor de 18 años)
    if patient.edad_calc < 18:
        if not patient.tutor:
            missing_fields.append("tutor (obligatorio para menor de edad)")

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
    # Diccionarios básicos
    UNIDADES = ["", "UN ", "DOS ", "TRES ", "CUATRO ", "CINCO ", "SEIS ", "SIETE ", "OCHO ", "NUEVE ", "DIEZ ", "ONCE ", "DOCE ", "TRECE ", "CATORCE ", "QUINCE ", "DIECISEIS ", "DIECISIETE ", "DIECIOCHO ", "DIECINUEVE ", "VEINTE "]
    DECENAS = ["UNKNOWN", "DIEZ", "VEINTI", "TREINTA ", "CUARENTA ", "CINCUENTA ", "SESENTA ", "SETENTA ", "OCHENTA ", "NOVENTA "]
    CENTENAS = ["", "CIENTO ", "DOSCIENTOS ", "TRESCIENTOS ", "CUATROCIENTOS ", "QUINIENTOS ", "SEISCIENTOS ", "SETECIENTOS ", "OCHOCIENTOS ", "NOVECIENTOS "]

    entero = int(monto)
    decimal = int(round((monto - entero) * 100))
    texto = ""

    if entero == 0: texto = "CERO "
    elif entero == 100: texto = "CIEN "
    elif entero < 21: texto = UNIDADES[entero]
    elif entero < 30: texto = DECENAS[2] + UNIDADES[entero - 20]
    elif entero < 100: texto = DECENAS[int(entero / 10)] + ("Y " if entero % 10 > 0 else "") + UNIDADES[entero % 10]
    elif entero < 1000: texto = CENTENAS[int(entero / 100)] + numero_a_letras(entero % 100)
    elif entero < 2000: texto = "MIL " + numero_a_letras(entero % 1000)
    elif entero < 1000000:
        texto = numero_a_letras(int(entero / 1000)).replace("UN ", "UN MIL ") + numero_a_letras(entero % 1000)
        if texto.startswith("UN MIL"): texto = texto[3:] # Corregir 'UN MIL' a 'MIL'
    
    # Formato Boliviano estándar
    return f"({texto.strip()} {decimal:02d}/100 BOLIVIANOS)"

# --- Endpoints Principales ---

@router.post("/", response_model=schemas.PatientResponse, status_code=status.HTTP_201_CREATED)
async def create_patient(
    patient_in: schemas.PatientFullCreate,
    db: AsyncSession = Depends(get_db)
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
    structure_map = {
        "ci":         ("legal/identidad",   "ci_paciente",        "url_ci_paciente"),
        "medico":     ("legal/medico",      "cert_medico",        "url_certificado_medico"),
        "foto":       ("legal/fotos",       "foto_paciente",      "url_foto_paciente"),
        "compromiso": ("legal/compromisos", "declaracion_aporte", "url_declaracion_aporte"),
        "ci_tutor":   ("legal/identidad",   "ci_tutor",           "url_ci_tutor"),
        "foto_tutor": ("legal/fotos",       "foto_tutor",         "url_foto_tutor")
    }

    if doc_type not in structure_map:
        raise HTTPException(status_code=400, detail="Tipo de documento inválido.")

    subfolder, file_prefix, db_column = structure_map[doc_type]

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
    limit: int = 100,
    search: str = None,
    estado: str = None,
    db: AsyncSession = Depends(get_db),
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

@router.put("/{patient_id}/activate", response_model=schemas.UserResponse)
async def activate_patient_user(
    patient_id: int, 
    # Eliminamos activation_data porque ya no pediremos password manual
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user) 
):
    """
    Activa al paciente y genera su usuario automáticamente.
    Password inicial = Número de Carnet de Identidad (CI).
    """
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

    # 2. Validar integridad (Regla de Negocio 3.4)
    missing_fields = _get_missing_activation_fields(db_patient)
    if missing_fields:
        detail = "Faltan datos obligatorios para activar: " + ", ".join(missing_fields)
        raise HTTPException(status_code=400, detail=detail)

    # 3. Generar Password Automático (Su CI)
    hashed_password = hash_password(db_patient.ci)
    
    # 4. Crear Usuario
    # El email es obligatorio para activar y se usa como credencial.
    username_email = db_patient.email.strip()
    
    db_user = models.User(
        email=username_email,
        password_hash=hashed_password,
        role="PACIENTE", # Rol específico según Req 2.3
        estado="ACTIVO",
    )
    db.add(db_user)
    await db.flush() # Obtenemos el ID del nuevo usuario

    # 5. Vincular y Activar Paciente
    db_patient.user_id = db_user.id
    db_patient.estado = "PENDIENTE_DOC" # Actualizamos estado según Req 17
    
    try:
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback()
        if "users_email_key" in str(e):
            raise HTTPException(status_code=400, detail="El email del paciente ya está registrado como usuario.")
        raise HTTPException(status_code=500, detail=f"Error al generar credenciales: {e}")

@router.get("/{patient_id}", response_model=schemas.PatientDetailResponse)
async def get_patient(patient_id: int, db: AsyncSession = Depends(get_db)):
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
    patient_id: int, tutor: schemas.TutorCreate, db: AsyncSession = Depends(get_db)
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
    patient_id: int, tutor: schemas.TutorUpdate, db: AsyncSession = Depends(get_db)
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
async def get_tutor_by_patient_id(patient_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Tutor).where(models.Tutor.patient_id == patient_id))
    db_tutor = result.scalars().first()
    
    if db_tutor is None:
        raise HTTPException(status_code=404, detail="Tutor no encontrado para este paciente")
    return db_tutor

@router.post("/{patient_id}/medical", response_model=schemas.PatientMedicalResponse, status_code=status.HTTP_201_CREATED)
async def create_patient_medical(
    patient_id: int, medical: schemas.PatientMedicalCreate, db: AsyncSession = Depends(get_db)
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
    patient_id: int, medical: schemas.PatientMedicalUpdate, db: AsyncSession = Depends(get_db)
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
    patient_id: int, complication: schemas.PatientComplicationCreate, db: AsyncSession = Depends(get_db)
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
    patient_id: int, treatment: schemas.PatientTreatmentCreate, db: AsyncSession = Depends(get_db)
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
async def delete_patient(patient_id: int, db: AsyncSession = Depends(get_db)):
    """
    Elimina un paciente y toda su información asociada (Cascade).
    """
    query = select(models.Patient).where(models.Patient.id == patient_id)
    result = await db.execute(query)
    patient = result.scalars().first()

    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    try:
        await db.delete(patient)
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar el paciente: {str(e)}")
    
    return None

# --- ENDPOINTS DE BORRADO ESPECÍFICO (HIJOS) ---

@router.delete("/{patient_id}/medical", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient_medical(patient_id: int, db: AsyncSession = Depends(get_db)):
    query = select(models.PatientMedical).where(models.PatientMedical.patient_id == patient_id)
    result = await db.execute(query)
    medical = result.scalars().first()

    if not medical:
        raise HTTPException(status_code=404, detail="Ficha médica no encontrada")

    await db.delete(medical)
    await db.commit()
    return None

@router.delete("/{patient_id}/treatments/{treatment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient_treatment(patient_id: int, treatment_id: int, db: AsyncSession = Depends(get_db)):
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
async def delete_patient_complication(patient_id: int, complication_id: int, db: AsyncSession = Depends(get_db)):
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
async def delete_patient_tutor(patient_id: int, db: AsyncSession = Depends(get_db)):
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
    db: AsyncSession = Depends(get_db)
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
    db: AsyncSession = Depends(get_db)
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
    monto_compromiso: float = Query(..., ge=50, description="Monto voluntario (Mínimo 50 Bs)"),
    current_user: models.User = Depends(deps.get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Genera PDF con CÓDIGO DE SEGURIDAD.
    """
    query = select(models.Patient).where(models.Patient.user_id == current_user.id)
    result = await db.execute(query)
    patient = result.scalars().first()

    if not patient:
        raise HTTPException(status_code=400, detail="Sin datos de paciente.")

    committed_amount = float(patient.monto_aporte_comprometido) if patient.monto_aporte_comprometido is not None else None
    if committed_amount is not None:
        if round(committed_amount, 2) != round(monto_compromiso, 2):
            raise HTTPException(
                status_code=400,
                detail=f"Su aporte comprometido ya está fijado en Bs. {committed_amount:.2f}.",
            )
    else:
        patient.monto_aporte_comprometido = monto_compromiso
        db.add(patient)
        await db.commit()
        committed_amount = monto_compromiso

    # 1. Generar Código de Integridad
    random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    security_code = f"P{patient.id}-{int(committed_amount)}-{random_suffix}"

    # 2. Crear PDF
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # --- CABECERA ---
    p.setFont("Helvetica-Bold", 16)
    p.drawCentredString(width / 2, height - 100, "DECLARACIÓN JURADA DE APORTE VOLUNTARIO")
    
    # --- CÓDIGO DE SEGURIDAD ---
    p.setStrokeColor(colors.grey)
    p.rect(width - 220, height - 60, 200, 30, fill=0)
    p.setFont("Courier-Bold", 12)
    p.drawString(width - 210, height - 50, f"CÓDIGO: {security_code}")
    p.setFont("Helvetica-Oblique", 8)
    p.drawString(width - 210, height - 75, "No válido si este código es ilegible")

    # --- CUERPO ---
    text_y = height - 150
    p.setFont("Helvetica", 12)
    monto_str = f"{committed_amount:.2f}"
    monto_literal = numero_a_letras(committed_amount)

    lines = [
        f"Yo, {patient.nombres} {patient.ap_paterno} {patient.ap_materno or ''},",
        f"con Cédula de Identidad Nº {patient.ci},",
        "por medio de la presente declaro libre y voluntariamente que:",
        "",
        "1. Soy beneficiario activo de la Fundación Vida Plena.",
        f"2. Me comprometo a realizar un aporte mensual voluntario de Bs. {monto_str}",
        f"{monto_literal}.",
        "   para el sostenimiento de los programas de la fundación.",
        f"3. Entiendo que el incumplimiento reiterado de este aporte o la falta",
        "   de documentación resultará en la suspensión de los beneficios.",
        f"4. Entiendo que adulterar este documento es causal de bloqueo.",
        "",
        f"Fecha de emisión: {date.today().strftime('%d/%m/%Y')}",
        "",
        "",
        "__________________________",
        "Firma del Beneficiario",
        f"CI: {patient.ci}"
    ]
    
    for line in lines:
        p.drawString(80, text_y, line)
        text_y -= 25

    p.showPage()
    p.save()
    
    buffer.seek(0)
    return StreamingResponse(
        buffer, 
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Compromiso_{security_code}.pdf"'}
    )


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

