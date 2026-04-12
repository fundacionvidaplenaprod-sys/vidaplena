import uuid
from datetime import date
from typing import List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc
from app import models, schemas
from app.api import deps
from app.db import get_db
from app.core.firebase import upload_file_to_firebase

router = APIRouter()

# Constantes
MAX_FILE_SIZE_MB = 2
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/jpg"]

# --- FUNCIÓN AUXILIAR (Aquí está la magia que faltaba) ---
async def get_patient_from_user(user_id: int, db: AsyncSession) -> models.Patient:
    """Busca el paciente asociado al usuario de forma explícita."""
    query = select(models.Patient).where(models.Patient.user_id == user_id)
    result = await db.execute(query)
    patient = result.scalars().first()
    return patient

# 1. PACIENTE: Subir aporte (Estado: DECLARADO)
@router.post("/me", response_model=schemas.ContributionResponse, status_code=status.HTTP_201_CREATED)
async def create_my_contribution(
    monto: float = Form(..., gt=0),
    periodo: str = Form(..., regex=r"^\d{4}-\d{2}$"),
    fecha_pago: date = Form(...),
    # NOTA: Se eliminó 'observacion' porque no existe en la BD
    comprobante: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    # Usamos la función auxiliar definida arriba
    patient = await get_patient_from_user(current_user.id, db)
    
    if not patient:
        raise HTTPException(status_code=400, detail="Usuario sin ficha de paciente asociada.")
    
    patient_id = patient.id
    if patient.monto_aporte_comprometido is not None:
        committed_amount = float(patient.monto_aporte_comprometido)
        if round(monto, 2) != round(committed_amount, 2):
            raise HTTPException(
                status_code=400,
                detail=f"El voucher debe coincidir con su aporte comprometido de Bs. {committed_amount:.2f}.",
            )

    existing_query = select(models.MonthlyContribution).where(
        models.MonthlyContribution.patient_id == patient_id,
        models.MonthlyContribution.periodo == periodo,
    )
    existing_contribution = (await db.execute(existing_query)).scalars().first()
    if existing_contribution and existing_contribution.estado == "ACEPTADO":
        raise HTTPException(status_code=400, detail=f"El aporte del periodo {periodo} ya fue validado y no se puede reemplazar.")

    # --- Lógica de Archivos ---
    if comprobante.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de archivo inválido.")
    
    content = await comprobante.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="El archivo excede los 2MB.")
    
    await comprobante.seek(0)
    
    ext = comprobante.filename.split(".")[-1]
    unique_name = f"pacientes/{patient_id}/aportes/{periodo}/voucher_{uuid.uuid4().hex[:8]}.{ext}"
    
    try:
        public_url = upload_file_to_firebase(content, unique_name, comprobante.content_type)
    except Exception as e:
        print(f"Error Firebase: {e}") 
        raise HTTPException(status_code=500, detail="Error al subir el voucher.")

    # Si ya existe para el periodo (DECLARADO/OBSERVADO), se reemplaza voucher y vuelve a DECLARADO.
    if existing_contribution:
        existing_contribution.fecha_pago = fecha_pago
        existing_contribution.monto = monto
        existing_contribution.url_comprobante = public_url
        existing_contribution.estado = "DECLARADO"
        existing_contribution.observacion_admin = None
        db.add(existing_contribution)
        await db.commit()
        await db.refresh(existing_contribution)
        return existing_contribution

    new_contribution = models.MonthlyContribution(
        patient_id=patient_id,
        periodo=periodo,
        fecha_pago=fecha_pago,
        monto=monto,
        url_comprobante=public_url,
        estado="DECLARADO"
    )
    db.add(new_contribution)
    await db.commit()
    await db.refresh(new_contribution)
    return new_contribution

# 2. VER HISTORIAL
@router.get("/me", response_model=List[schemas.ContributionResponse])
async def read_my_contributions(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    patient = await get_patient_from_user(current_user.id, db)

    if not patient: 
        raise HTTPException(status_code=400, detail="Sin ficha de paciente.")
    
    query = select(models.MonthlyContribution).where(
        models.MonthlyContribution.patient_id == patient.id
    ).order_by(desc(models.MonthlyContribution.periodo))
    
    result = await db.execute(query)
    return result.scalars().all()

@router.get("/review", response_model=List[schemas.ContributionReviewResponse])
async def read_contributions_for_review(
    estado: Optional[Literal["DECLARADO", "OBSERVADO", "ACEPTADO"]] = None,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    if current_user.role not in ["SUPER_ADMIN", "REGISTRADOR"]:
        raise HTTPException(status_code=403, detail="No tiene permisos para revisar aportes.")

    query = (
        select(models.MonthlyContribution, models.Patient)
        .join(models.Patient, models.Patient.id == models.MonthlyContribution.patient_id)
        .order_by(
            desc(models.MonthlyContribution.created_at),
            desc(models.MonthlyContribution.periodo),
        )
    )
    if estado:
        query = query.where(models.MonthlyContribution.estado == estado)

    result = await db.execute(query)
    rows = result.all()
    return [
        schemas.ContributionReviewResponse(
            id=contrib.id,
            patient_id=patient.id,
            patient_nombre=f"{patient.nombres} {patient.ap_paterno} {patient.ap_materno or ''}".strip(),
            patient_ci=patient.ci,
            periodo=contrib.periodo,
            fecha_pago=contrib.fecha_pago,
            monto=float(contrib.monto),
            estado=contrib.estado,
            observacion_admin=contrib.observacion_admin,
            url_comprobante=contrib.url_comprobante,
            created_at=contrib.created_at,
            updated_at=contrib.updated_at,
        )
        for contrib, patient in rows
    ]

# 3. ADMIN VALIDAR
class ContributionValidationSchema(schemas.BaseModel):
    estado: Literal["ACEPTADO", "OBSERVADO"] 
    observacion_admin: Optional[str] = None

@router.put("/{contribution_id}/validate", response_model=schemas.ContributionResponse)
async def validate_contribution(
    contribution_id: int,
    validation_in: ContributionValidationSchema,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    if current_user.role not in ["SUPER_ADMIN", "REGISTRADOR"]:
        raise HTTPException(status_code=403, detail="No tiene permisos para validar aportes.")

    contribution = await db.get(models.MonthlyContribution, contribution_id)
    if not contribution: 
        raise HTTPException(status_code=404, detail="Aporte no encontrado")

    if validation_in.estado == "OBSERVADO":
        if not (validation_in.observacion_admin or "").strip():
            raise HTTPException(status_code=400, detail="Debe registrar un motivo al observar el aporte.")
        contribution.observacion_admin = validation_in.observacion_admin.strip()
    else:
        contribution.observacion_admin = None

    contribution.estado = validation_in.estado
            
    await db.commit()
    await db.refresh(contribution)
    return contribution