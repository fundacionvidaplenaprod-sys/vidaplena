import csv
import io
import uuid
import re
import unicodedata
from datetime import date, timedelta
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from fastapi.responses import StreamingResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func, delete, desc

from app import models, schemas
from app.db import get_db
from app.api import deps
from app.core.firebase import upload_file_to_firebase
import math

router = APIRouter()

CSV_ALLOWED_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
}
CSV_MAX_FILE_SIZE_MB = 5
CSV_MAX_FILE_SIZE_BYTES = CSV_MAX_FILE_SIZE_MB * 1024 * 1024
DISTRIBUTION_DAYS = 90

MAX_FILE_SIZE_MB = 2
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_RECEIPT_TYPES = {"application/pdf"}

CSV_REQUIRED_FIELDS = [
    "tipo",
    "nombre_generico",
    "marca",
    "nombre_comercial",
    "presentacion",
    "factor_conversion",
    "lote",
    "fecha_venc",
    "cantidad_total",
]

CANONICAL_INSULIN_ALIASES = {
    "Glargina": ["glargina", "glargin", "gliargina", "lantus", "toujeo", "basaglar", "semglee"],
    "Lispro": ["lispro", "humalog", "liprolog", "lyumjev"],
    "Protamina": ["protamina", "protaphane", "mix"],
    "Glulisina": ["glulisina", "apidra"],
    "NPH": ["nph", "insulatard", "huminsulin", "humulin", "berlinsulin"],
    "Aspart": ["aspart", "novorapid", "fiasp"],
    "Detemir": ["detemir", "levemir"],
    "Degludec": ["degludec", "tresiba"],
    "Regular": ["regular", "actrapid", "normal"],
}


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

def _normalize_header(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _get_treatment_daily_units(treatment: models.PatientTreatment) -> float:
    return float(getattr(treatment, "dosis_diaria", 0) or 0)


def _normalize_insulin_name(raw_name: Optional[str]) -> Optional[str]:
    normalized_name = (raw_name or "").strip().lower()
    normalized_name = unicodedata.normalize("NFD", normalized_name)
    normalized_name = "".join(ch for ch in normalized_name if unicodedata.category(ch) != "Mn")
    if not normalized_name:
        return None
    for canonical, aliases in CANONICAL_INSULIN_ALIASES.items():
        if any(alias in normalized_name for alias in aliases):
            return canonical
    return None


def _patient_daily_units_for_product(
    patient: models.Patient, canonical_name: str
) -> float:
    total_units = 0.0
    for tx in patient.treatments:
        treatment_type = getattr(tx, "tipo", "INSULINA")
        if treatment_type != "INSULINA":
            continue
        if _normalize_insulin_name(tx.nombre) != canonical_name:
            continue
        total_units += _get_treatment_daily_units(tx)
    return total_units

def _parse_float(value: str, field: str, row_number: int) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"Fila {row_number}: {field} inválido") from exc
    if parsed <= 0:
        raise ValueError(f"Fila {row_number}: {field} debe ser mayor a 0")
    return parsed

def _parse_int(value: str, field: str, row_number: int) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"Fila {row_number}: {field} inválido") from exc
    if parsed <= 0:
        raise ValueError(f"Fila {row_number}: {field} debe ser mayor a 0")
    return parsed


def _build_delivery_receipt_response(delivery: models.Delivery) -> StreamingResponse:
    patient = delivery.patient
    allocation = delivery.allocation
    lot = allocation.lot if allocation else None
    donation = lot.donation if lot else None

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawCentredString(width / 2, height - 80, "BOLETA DE RECEPCION DE INSULINA")

    pdf.setStrokeColor(colors.grey)
    pdf.rect(width - 220, height - 60, 200, 30, fill=0)
    pdf.setFont("Courier-Bold", 10)
    pdf.drawString(width - 210, height - 50, f"ENTREGA #{delivery.id}")

    pdf.setFont("Helvetica", 12)
    text_y = height - 130
    nombre_completo = f"{patient.nombres} {patient.ap_paterno} {patient.ap_materno or ''}".strip()
    fecha_emision = delivery.fecha_entrega.strftime("%d/%m/%Y")
    lines = [
        f"Beneficiario: {nombre_completo}",
        f"CI: {patient.ci}",
        f"Fecha de entrega: {fecha_emision}",
        "",
        "Insulina entregada:",
        f"- Nombre generico: {donation.nombre_generico if donation else 'N/A'}",
        f"- Marca: {donation.marca or 'N/A'}",
        f"- Presentacion: {donation.presentacion or 'N/A'}",
        f"- Lote: {lot.lote or 'N/A'}",
        f"- Vencimiento: {lot.fecha_venc.strftime('%d/%m/%Y') if lot and lot.fecha_venc else 'N/A'}",
        "",
        f"Cantidad entregada: {delivery.cantidad_entregada}",
        "",
        "",
        "______________________________",
        "Firma del beneficiario",
        f"CI: {patient.ci}",
    ]
    for line in lines:
        pdf.drawString(70, text_y, line)
        text_y -= 22

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    filename = f"Boleta_Entrega_{delivery.id}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

# 0. Listar Productos Donados
@router.get("/products/", response_model=List[schemas.DonationResponse])
async def list_donation_products(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    result = await db.execute(
        select(models.Donation)
        .where(models.Donation.tipo == "INSULINA")
        .order_by(models.Donation.id.desc())
    )
    return result.scalars().all()

# 1. Listar Lotes
@router.get("/lots/", response_model=List[schemas.DonationLotResponse])
async def list_donation_lots(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    result = await db.execute(
        select(models.DonationLot)
        .join(models.Donation, models.Donation.id == models.DonationLot.donation_id)
        .where(models.Donation.tipo == "INSULINA")
        .order_by(models.DonationLot.id.desc())
    )
    return result.scalars().all()

# 2. Detalle de Lote con Asignaciones
@router.get("/lots/{lot_id}", response_model=schemas.DonationLotDetailResponse)
async def get_donation_lot_detail(
    lot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    query = (
        select(models.DonationLot)
        .options(
            selectinload(models.DonationLot.donation),
            selectinload(models.DonationLot.allocations)
            .selectinload(models.DonationAllocation.patient)
            .selectinload(models.Patient.tutor),
            selectinload(models.DonationLot.allocations)
            .selectinload(models.DonationAllocation.patient)
            .selectinload(models.Patient.medical),
            selectinload(models.DonationLot.allocations)
            .selectinload(models.DonationAllocation.patient)
            .selectinload(models.Patient.complications),
            selectinload(models.DonationLot.allocations)
            .selectinload(models.DonationAllocation.patient)
            .selectinload(models.Patient.treatments),
        )
        .where(models.DonationLot.id == lot_id)
    )
    result = await db.execute(query.with_for_update())
    lot = result.scalars().first()
    if not lot:
        raise HTTPException(status_code=404, detail="Lote no encontrado")
    return lot

# 2.2 Movimientos de Stock por Lote
@router.get("/lots/{lot_id}/movements", response_model=List[schemas.StockMovementResponse])
async def list_lot_movements(
    lot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    lot_exists = await db.execute(
        select(models.DonationLot.id).where(models.DonationLot.id == lot_id)
    )
    if not lot_exists.scalar():
        raise HTTPException(status_code=404, detail="Lote no encontrado")

    result = await db.execute(
        select(models.StockMovement)
        .where(models.StockMovement.lot_id == lot_id)
        .order_by(models.StockMovement.created_at.asc(), models.StockMovement.id.asc())
    )
    return result.scalars().all()

# 2.5 Editar Asignación (Ajuste Manual)
@router.put("/allocations/{allocation_id}", response_model=schemas.DonationAllocationResponse)
async def update_allocation(
    allocation_id: int,
    payload: schemas.DonationAllocationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    query = (
        select(models.DonationAllocation)
        .options(
            selectinload(models.DonationAllocation.patient).selectinload(models.Patient.tutor),
            selectinload(models.DonationAllocation.patient).selectinload(models.Patient.medical),
            selectinload(models.DonationAllocation.patient).selectinload(models.Patient.complications),
            selectinload(models.DonationAllocation.patient).selectinload(models.Patient.treatments),
            selectinload(models.DonationAllocation.lot),
        )
        .where(models.DonationAllocation.id == allocation_id)
    )
    result = await db.execute(query)
    allocation = result.scalars().first()
    if not allocation:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")
    if allocation.estado == "CONSOLIDADO":
        raise HTTPException(status_code=400, detail="La asignación ya está consolidada")

    sibling_query = (
        select(models.DonationAllocation)
        .where(
            models.DonationAllocation.lot_id == allocation.lot_id,
            models.DonationAllocation.id != allocation.id,
            models.DonationAllocation.estado != "CONSOLIDADO",
        )
    )
    sibling_result = await db.execute(sibling_query)
    sibling_allocations = sibling_result.scalars().all()
    sibling_total = sum(
        (item.cantidad_ajustada if item.cantidad_ajustada is not None else item.cantidad_sugerida or 0)
        for item in sibling_allocations
    )
    projected_total = sibling_total + payload.cantidad_ajustada
    if projected_total > allocation.lot.cantidad_disponible:
        raise HTTPException(
            status_code=400,
            detail="La suma de asignaciones ajustadas excede el stock disponible del lote",
        )

    allocation.cantidad_ajustada = payload.cantidad_ajustada
    allocation.autor_ajuste = current_user.id
    _log_audit_event(
        db=db,
        actor_id=current_user.id,
        entidad="donation_allocation",
        entidad_id=allocation.id,
        accion="UPDATE_ALLOCATION",
        payload={
            "lot_id": allocation.lot_id,
            "cantidad_ajustada": payload.cantidad_ajustada,
        },
    )

    await db.commit()
    await db.refresh(allocation)
    return allocation

# 3. Crear Producto Donado
@router.post("/products/", response_model=schemas.DonationResponse)
async def create_donation_product(
    donation: schemas.DonationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    if donation.tipo != "INSULINA":
        raise HTTPException(
            status_code=400,
            detail="Solo se permiten productos de tipo INSULINA.",
        )
    canonical_name = _normalize_insulin_name(donation.nombre_generico)
    if not canonical_name:
        raise HTTPException(
            status_code=400,
            detail="nombre_generico no coincide con el catálogo de insulinas permitido.",
        )

    payload = donation.model_dump()
    payload["nombre_generico"] = canonical_name
    db_donation = models.Donation(**payload)
    db.add(db_donation)
    await db.flush()
    _log_audit_event(
        db=db,
        actor_id=current_user.id,
        entidad="donation_product",
        entidad_id=db_donation.id,
        accion="CREATE_DONATION_PRODUCT",
        payload=payload,
    )
    await db.commit()
    await db.refresh(db_donation)
    return db_donation

# 4. Registrar Lote (Entrada de Almacén)
@router.post("/lots/", response_model=schemas.DonationLotResponse)
async def create_donation_lot(
    lot: schemas.DonationLotCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    donation_result = await db.execute(
        select(models.Donation).where(models.Donation.id == lot.donation_id)
    )
    donation = donation_result.scalars().first()
    if not donation:
        raise HTTPException(status_code=404, detail="Producto de donación no encontrado")
    if donation.tipo != "INSULINA":
        raise HTTPException(status_code=400, detail="Solo se pueden registrar lotes de INSULINA")

    # Calculamos disponible inicial igual al total
    # Mapeamos los nombres del schema (lote, fecha_venc) a los del modelo
    db_lot = models.DonationLot(
        donation_id=lot.donation_id,
        lote=lot.lote,
        fecha_venc=lot.fecha_venc,
        cantidad_total=lot.cantidad_total,
        cantidad_disponible=lot.cantidad_total
    )
    db.add(db_lot)
    await db.flush()

    movement = models.StockMovement(
        lot_id=db_lot.id,
        tipo="ENTRADA",
        cantidad=lot.cantidad_total,
        referencia=f"CREACION_LOTE:{db_lot.id}",
    )
    db.add(movement)
    _log_audit_event(
        db=db,
        actor_id=current_user.id,
        entidad="donation_lot",
        entidad_id=db_lot.id,
        accion="CREATE_DONATION_LOT",
        payload={
            "donation_id": lot.donation_id,
            "cantidad_total": lot.cantidad_total,
            "lote": lot.lote,
            "fecha_venc": str(lot.fecha_venc) if lot.fecha_venc else None,
        },
    )

    await db.commit()
    await db.refresh(db_lot)
    return db_lot

# 4.2 Consolidar Lote (Salida de Stock)
@router.post("/lots/{lot_id}/consolidate", response_model=schemas.DonationLotDetailResponse)
async def consolidate_lot(
    lot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    query = (
        select(models.DonationLot)
        .options(
            selectinload(models.DonationLot.donation),
            selectinload(models.DonationLot.allocations)
            .selectinload(models.DonationAllocation.patient)
            .selectinload(models.Patient.tutor),
            selectinload(models.DonationLot.allocations)
            .selectinload(models.DonationAllocation.patient)
            .selectinload(models.Patient.medical),
            selectinload(models.DonationLot.allocations)
            .selectinload(models.DonationAllocation.patient)
            .selectinload(models.Patient.complications),
            selectinload(models.DonationLot.allocations)
            .selectinload(models.DonationAllocation.patient)
            .selectinload(models.Patient.treatments),
        )
        .where(models.DonationLot.id == lot_id)
    )
    result = await db.execute(query)
    lot = result.scalars().first()
    if not lot:
        raise HTTPException(status_code=404, detail="Lote no encontrado")
    if not lot.allocations:
        raise HTTPException(status_code=400, detail="El lote no tiene asignaciones")

    total_salida = 0
    for allocation in lot.allocations:
        if allocation.estado == "CONSOLIDADO":
            raise HTTPException(status_code=400, detail="El lote ya fue consolidado")
        cantidad = allocation.cantidad_ajustada
        if cantidad is None:
            cantidad = allocation.cantidad_sugerida
        if cantidad is None or cantidad < 0:
            raise HTTPException(status_code=400, detail="Cantidad ajustada inválida")
        total_salida += cantidad

    if total_salida > lot.cantidad_disponible:
        raise HTTPException(
            status_code=400,
            detail="Stock insuficiente para consolidar las asignaciones",
        )

    for allocation in lot.allocations:
        if allocation.cantidad_ajustada is None:
            allocation.cantidad_ajustada = allocation.cantidad_sugerida
        allocation.estado = "CONSOLIDADO"

    lot.cantidad_disponible -= total_salida

    if total_salida > 0:
        movement = models.StockMovement(
            lot_id=lot.id,
            tipo="SALIDA",
            cantidad=total_salida,
            referencia=f"CONSOLIDACION_LOTE:{lot.id}",
        )
        db.add(movement)
    _log_audit_event(
        db=db,
        actor_id=current_user.id,
        entidad="donation_lot",
        entidad_id=lot.id,
        accion="CONSOLIDATE_DONATION_LOT",
        payload={
            "total_salida": total_salida,
            "allocations_count": len(lot.allocations),
            "stock_restante": lot.cantidad_disponible,
        },
    )

    await db.commit()

    refreshed = await db.execute(query)
    return refreshed.scalars().first()

# 4.5 Importar Lotes desde CSV
@router.post("/lots/import-csv", response_model=schemas.DonationImportResponse)
async def import_donation_lots_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    if file.content_type not in CSV_ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de archivo inválido. Usa CSV.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(content) > CSV_MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"El CSV excede el tamaño máximo ({CSV_MAX_FILE_SIZE_MB}MB).",
        )

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="El CSV no tiene encabezados.")

    normalized_headers = [_normalize_header(name) for name in reader.fieldnames]
    header_map = {original: normalized for original, normalized in zip(reader.fieldnames, normalized_headers)}

    if any(field not in normalized_headers for field in CSV_REQUIRED_FIELDS):
        raise HTTPException(
            status_code=400,
            detail="El CSV debe incluir los campos: " + ", ".join(CSV_REQUIRED_FIELDS),
        )

    results: List[schemas.DonationImportRowResult] = []
    imported_rows = 0
    total_rows = 0

    for idx, row in enumerate(reader, start=2):
        total_rows += 1
        normalized_row = {header_map[key]: (value or "").strip() for key, value in row.items()}

        try:
            tipo = normalized_row.get("tipo", "").upper()
            if tipo != "INSULINA":
                raise ValueError(f"Fila {idx}: solo se admite tipo INSULINA")

            nombre_generico_raw = normalized_row.get("nombre_generico", "")
            if not nombre_generico_raw:
                raise ValueError(f"Fila {idx}: nombre_generico es obligatorio")
            nombre_generico = _normalize_insulin_name(nombre_generico_raw)
            if not nombre_generico:
                raise ValueError(f"Fila {idx}: nombre_generico no corresponde al catálogo de insulinas")

            marca = normalized_row.get("marca") or None
            nombre_comercial = normalized_row.get("nombre_comercial") or None
            presentacion = normalized_row.get("presentacion") or None

            factor_raw = normalized_row.get("factor_conversion") or "1"
            factor_conversion = _parse_float(factor_raw, "factor_conversion", idx)

            lote = normalized_row.get("lote") or None
            fecha_venc_raw = normalized_row.get("fecha_venc") or None
            if fecha_venc_raw:
                try:
                    fecha_venc = date.fromisoformat(fecha_venc_raw)
                except ValueError as exc:
                    raise ValueError(f"Fila {idx}: fecha_venc inválida (YYYY-MM-DD)") from exc
            else:
                fecha_venc = None

            cantidad_total_raw = normalized_row.get("cantidad_total") or ""
            cantidad_total = _parse_int(cantidad_total_raw, "cantidad_total", idx)

            conditions = [
                models.Donation.tipo == tipo,
                models.Donation.nombre_generico == nombre_generico,
                models.Donation.factor_conversion == factor_conversion,
            ]
            conditions.append(models.Donation.marca.is_(None) if marca is None else models.Donation.marca == marca)
            conditions.append(
                models.Donation.nombre_comercial.is_(None)
                if nombre_comercial is None
                else models.Donation.nombre_comercial == nombre_comercial
            )
            conditions.append(
                models.Donation.presentacion.is_(None)
                if presentacion is None
                else models.Donation.presentacion == presentacion
            )

            existing = await db.execute(select(models.Donation).where(*conditions))
            donation = existing.scalars().first()

            if not donation:
                donation = models.Donation(
                    tipo=tipo,
                    nombre_generico=nombre_generico,
                    marca=marca,
                    nombre_comercial=nombre_comercial,
                    presentacion=presentacion,
                    factor_conversion=factor_conversion,
                )
                db.add(donation)
                await db.flush()

            new_lot = models.DonationLot(
                donation_id=donation.id,
                lote=lote,
                fecha_venc=fecha_venc,
                cantidad_total=cantidad_total,
                cantidad_disponible=cantidad_total,
            )
            db.add(new_lot)
            await db.flush()

            movement = models.StockMovement(
                lot_id=new_lot.id,
                tipo="ENTRADA",
                cantidad=cantidad_total,
                referencia=f"IMPORT_CSV_LOTE:{new_lot.id}",
            )
            db.add(movement)

            imported_rows += 1
            results.append(
                schemas.DonationImportRowResult(
                    row_number=idx,
                    status="IMPORTED",
                    message="Importado",
                    donation_id=donation.id,
                    lot_id=new_lot.id,
                )
            )
        except ValueError as exc:
            results.append(
                schemas.DonationImportRowResult(
                    row_number=idx,
                    status="ERROR",
                    message=str(exc),
                )
            )

    await db.commit()
    _log_audit_event(
        db=db,
        actor_id=current_user.id,
        entidad="donation_import",
        entidad_id=0,
        accion="IMPORT_DONATION_CSV",
        payload={
            "total_rows": total_rows,
            "imported_rows": imported_rows,
            "error_rows": total_rows - imported_rows,
        },
    )
    await db.commit()

    return schemas.DonationImportResponse(
        total_rows=total_rows,
        imported_rows=imported_rows,
        error_rows=total_rows - imported_rows,
        results=results,
    )

# 3. EL ALGORITMO FINAL: Cálculo con Filtro de Aportes por Periodo
@router.post("/calculate-distribution/{lot_id}", response_model=schemas.CalculationResult)
async def calculate_distribution(
    lot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    Algoritmo Maestro (horizonte máximo: 3 meses):
    1. Busca el lote y el factor de conversión del producto.
    2. Solo permite distribución para productos tipo INSULINA.
    3. Busca pacientes ACTIVOS y filtra los que tengan aporte ACEPTADO en el periodo actual.
    4. Calcula necesidad total en UI para 90 días usando tratamiento registrado.
    5. Convierte UI a unidades de stock con factor_conversion y distribuye según stock disponible.
    """
    # A. Obtener Lote y Producto
    result = await db.execute(select(models.DonationLot).where(models.DonationLot.id == lot_id))
    lot = result.scalars().first()
    if not lot:
        raise HTTPException(status_code=404, detail="Lote no encontrado")
    
    res_don = await db.execute(select(models.Donation).where(models.Donation.id == lot.donation_id))
    product = res_don.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto de donación no encontrado")
    if product.tipo != "INSULINA":
        raise HTTPException(
            status_code=400,
            detail="La distribución automática solo aplica a productos tipo INSULINA.",
        )

    existing_allocations_result = await db.execute(
        select(models.DonationAllocation).where(models.DonationAllocation.lot_id == lot.id)
    )
    existing_allocations = existing_allocations_result.scalars().all()
    if any(item.estado == "CONSOLIDADO" for item in existing_allocations):
        raise HTTPException(
            status_code=400,
            detail="El lote ya fue consolidado y no permite recálculo de distribución",
        )
    if existing_allocations:
        await db.execute(
            delete(models.DonationAllocation).where(
                models.DonationAllocation.lot_id == lot.id,
                models.DonationAllocation.estado == "BORRADOR",
            )
        )
        await db.flush()
    
    # Factor de conversión (Ej: 1000 unidades por vial)
    factor_stock = getattr(product, "factor_conversion", 1000.0) or 1000.0

    # B. Buscar Pacientes Candidatos
    query = (
        select(models.Patient)
        .options(
            selectinload(models.Patient.tutor),
            selectinload(models.Patient.medical),
            selectinload(models.Patient.treatments),
            selectinload(models.Patient.complications),
            selectinload(models.Patient.contributions),  # Cargamos aportes para filtrar
        )
        .where(
            models.Patient.estado == "ACTIVO",
        )
    )
    result_patients = await db.execute(query)
    candidates = result_patients.scalars().unique().all()

    allocations_preview = []
    excluded_list = []
    
    stock_disponible = lot.cantidad_disponible
    total_requerido_global = 0
    requerimientos_validos = []
    
    # Definir Periodo Actual (YYYY-MM)
    today = date.today()
    periodo_actual = f"{today.year}-{today.month:02d}" # Ej: "2026-01"

    canonical_product_name = _normalize_insulin_name(product.nombre_generico)
    if not canonical_product_name:
        raise HTTPException(
            status_code=400,
            detail="El producto de insulina no tiene un nombre canónico válido en catálogo.",
        )

    # C. Filtrado y Cálculo
    for patient in candidates:
        
        # --- 🛡️ FILTRO ANTI-MOROSOS ---
        es_aportante = False
        if patient.contributions:
            for aporte in patient.contributions:
                # Usamos TU campo 'periodo' y verificamos que esté aceptado
                if aporte.periodo == periodo_actual and aporte.estado == 'ACEPTADO':
                    es_aportante = True
                    break
        
        if not es_aportante:
            excluded_list.append({
                "patient_id": patient.id,
                "nombre_completo": f"{patient.nombres} {patient.ap_paterno}",
                "motivo": f"Falta aporte periodo {periodo_actual}"
            })
            continue # Al siguiente

        # --- 🧮 CÁLCULO DE DOSIS ---
        dosis_diaria_total = 0
        for tx in patient.treatments:
            treatment_type = getattr(tx, "tipo", "INSULINA")
            if treatment_type != "INSULINA":
                continue
            if _normalize_insulin_name(tx.nombre) != canonical_product_name:
                continue
            dosis_diaria_total += _get_treatment_daily_units(tx)
        
        if dosis_diaria_total <= 0:
            treatment_names = ", ".join(
                f"{(tx.nombre or 'N/A')} ({float(getattr(tx, 'dosis_diaria', 0) or 0)} UI/d)"
                for tx in (patient.treatments or [])
            ) or "sin tratamientos registrados"
            excluded_list.append({
                "patient_id": patient.id,
                "nombre_completo": f"{patient.nombres} {patient.ap_paterno}",
                "motivo": (
                    f"Sin tratamiento compatible con {canonical_product_name} o dosis diaria en cero. "
                    f"Tratamientos detectados: {treatment_names}"
                ),
            })
            continue

        necesidad_periodo = dosis_diaria_total * DISTRIBUTION_DAYS
        # Redondeo hacia arriba para unidades completas de stock (ej. frascos)
        frascos_necesarios = math.ceil(necesidad_periodo / factor_stock)
        
        requerimientos_validos.append({
            "patient": patient,
            "frascos_necesarios": frascos_necesarios
        })
        total_requerido_global += frascos_necesarios

    # D. Distribución (Lógica de Escasez)
    escasez = total_requerido_global > stock_disponible
    
    for req in requerimientos_validos:
        cantidad_a_entregar = 0
        necesita = req["frascos_necesarios"]
        
        if stock_disponible > 0:
            if not escasez:
                cantidad_a_entregar = necesita
            else:
                # Solidaridad: Asegurar 1 para todos antes de dar más
                cantidad_a_entregar = 1 if stock_disponible >= 1 else 0
            
            # Ajuste final por si queda menos de 1 (casos extremos)
            if cantidad_a_entregar > stock_disponible:
                cantidad_a_entregar = stock_disponible
            
            stock_disponible -= cantidad_a_entregar
        
        # Crear objeto Allocation (Borrador)
        alloc = models.DonationAllocation(
            lot_id=lot.id,
            patient_id=req["patient"].id,
            cantidad_sugerida=cantidad_a_entregar,
            cantidad_ajustada=cantidad_a_entregar,
            estado="BORRADOR"
        )
        # Inyectamos el paciente para que el schema lo serialice
        alloc.patient = req["patient"] 
        allocations_preview.append(alloc)
        
        # Guardamos el borrador en BD
        db.add(alloc)

    _log_audit_event(
        db=db,
        actor_id=current_user.id,
        entidad="donation_lot",
        entidad_id=lot.id,
        accion="CALCULATE_DONATION_DISTRIBUTION",
        payload={
            "allocations_generated": len(allocations_preview),
            "excluded_patients": len(excluded_list),
            "stock_disponible_inicial": lot.cantidad_disponible,
            "stock_sobrante": stock_disponible,
        },
    )
    await db.commit()

    return {
        "lot_id": lot.id,
        "total_pacientes_compatibles": len(candidates),
        "total_stock_disponible": lot.cantidad_disponible,
        "total_requerido_teorico": total_requerido_global,
        "sobrante_stock": stock_disponible,
        "allocations": allocations_preview,
        "excluded_patients": excluded_list
    }

# 5. Crear Entrega (por Asignación Consolidada)
@router.get("/deliveries/by-allocation/{allocation_id}", response_model=schemas.DeliveryResponse)
async def get_delivery_by_allocation(
    allocation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    query = select(models.Delivery).where(models.Delivery.allocation_id == allocation_id)
    result = await db.execute(query)
    delivery = result.scalars().first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Entrega no encontrada para esta asignación")
    return delivery


# 5. Crear Entrega (por Asignación Consolidada)
@router.post("/deliveries/", response_model=schemas.DeliveryResponse)
async def create_delivery(
    payload: schemas.DeliveryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    query = (
        select(models.DonationAllocation)
        .options(
            selectinload(models.DonationAllocation.lot).selectinload(models.DonationLot.donation),
            selectinload(models.DonationAllocation.patient).selectinload(models.Patient.treatments),
        )
        .where(models.DonationAllocation.id == payload.allocation_id)
    )
    result = await db.execute(query)
    allocation = result.scalars().first()
    if not allocation:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")
    if allocation.estado != "CONSOLIDADO":
        raise HTTPException(status_code=400, detail="La asignación debe estar consolidada")

    cantidad_maxima = allocation.cantidad_ajustada or allocation.cantidad_sugerida
    if cantidad_maxima is None or cantidad_maxima <= 0:
        raise HTTPException(status_code=400, detail="Cantidad inválida en asignación")
    if payload.cantidad_entregada <= 0 or payload.cantidad_entregada > cantidad_maxima:
        raise HTTPException(status_code=400, detail="Cantidad entregada fuera de rango")

    existing_delivery = await db.execute(
        select(models.Delivery).where(models.Delivery.allocation_id == allocation.id)
    )
    if existing_delivery.scalars().first():
        raise HTTPException(status_code=400, detail="La asignación ya tiene una entrega registrada")

    donation = allocation.lot.donation if allocation.lot else None
    if donation and donation.tipo == "INSULINA":
        canonical_product_name = _normalize_insulin_name(donation.nombre_generico)
        if canonical_product_name:
            daily_units = _patient_daily_units_for_product(allocation.patient, canonical_product_name)
            if daily_units > 0:
                last_signed_delivery_query = (
                    select(models.Delivery)
                    .join(models.DonationAllocation, models.DonationAllocation.id == models.Delivery.allocation_id)
                    .join(models.DonationLot, models.DonationLot.id == models.DonationAllocation.lot_id)
                    .where(
                        models.Delivery.patient_id == allocation.patient_id,
                        models.DonationLot.donation_id == donation.id,
                    )
                    .order_by(desc(models.Delivery.fecha_entrega), desc(models.Delivery.id))
                    .limit(1)
                )
                last_delivery_result = await db.execute(last_signed_delivery_query)
                last_delivery = last_delivery_result.scalars().first()
                if last_delivery:
                    factor_stock = float(getattr(donation, "factor_conversion", 0) or 0)
                    if factor_stock > 0:
                        delivered_units = float(last_delivery.cantidad_entregada) * factor_stock
                        covered_days = int(delivered_units // daily_units)
                        if covered_days > 0:
                            coverage_end = last_delivery.fecha_entrega + timedelta(days=covered_days)
                            if payload.fecha_entrega < coverage_end:
                                remaining_days = (coverage_end - payload.fecha_entrega).days
                                raise HTTPException(
                                    status_code=400,
                                    detail=(
                                        f"El paciente aún tiene cobertura de esta insulina por {remaining_days} días "
                                        f"(según última entrega del {last_delivery.fecha_entrega})."
                                    ),
                                )

    delivery = models.Delivery(
        allocation_id=allocation.id,
        patient_id=allocation.patient_id,
        fecha_entrega=payload.fecha_entrega,
        cantidad_entregada=payload.cantidad_entregada,
        estado="PENDIENTE_CARGA",
    )
    db.add(delivery)
    await db.flush()
    _log_audit_event(
        db=db,
        actor_id=current_user.id,
        entidad="delivery",
        entidad_id=delivery.id,
        accion="CREATE_DELIVERY",
        payload={
            "allocation_id": allocation.id,
            "patient_id": allocation.patient_id,
            "cantidad_entregada": payload.cantidad_entregada,
            "fecha_entrega": str(payload.fecha_entrega),
        },
    )
    await db.commit()
    await db.refresh(delivery)
    return delivery

# 6. Generar Boleta PDF de Recepción
@router.get("/deliveries/{delivery_id}/receipt")
async def get_delivery_receipt(
    delivery_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    query = (
        select(models.Delivery)
        .options(
            selectinload(models.Delivery.patient),
            selectinload(models.Delivery.allocation)
            .selectinload(models.DonationAllocation.lot)
            .selectinload(models.DonationLot.donation),
        )
        .where(models.Delivery.id == delivery_id)
    )
    result = await db.execute(query)
    delivery = result.scalars().first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Entrega no encontrada")
    return _build_delivery_receipt_response(delivery)


@router.get("/deliveries/me", response_model=List[schemas.DeliveryResponse])
async def list_my_deliveries(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    if current_user.role != "PACIENTE":
        raise HTTPException(status_code=403, detail="Solo los pacientes pueden acceder a este recurso.")

    patient_result = await db.execute(
        select(models.Patient.id).where(models.Patient.user_id == current_user.id)
    )
    patient_id = patient_result.scalar()
    if not patient_id:
        raise HTTPException(status_code=404, detail="No se encontró paciente asociado al usuario.")

    deliveries_result = await db.execute(
        select(models.Delivery)
        .join(models.DonationAllocation, models.DonationAllocation.id == models.Delivery.allocation_id)
        .join(models.DonationLot, models.DonationLot.id == models.DonationAllocation.lot_id)
        .join(models.Donation, models.Donation.id == models.DonationLot.donation_id)
        .where(
            models.Delivery.patient_id == patient_id,
            models.Donation.tipo == "INSULINA",
        )
        .order_by(desc(models.Delivery.fecha_entrega), desc(models.Delivery.id))
    )
    return deliveries_result.scalars().all()


@router.get("/deliveries/me/{delivery_id}/receipt")
async def get_my_delivery_receipt(
    delivery_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    if current_user.role != "PACIENTE":
        raise HTTPException(status_code=403, detail="Solo los pacientes pueden acceder a este recurso.")

    query = (
        select(models.Delivery)
        .options(
            selectinload(models.Delivery.patient),
            selectinload(models.Delivery.allocation)
            .selectinload(models.DonationAllocation.lot)
            .selectinload(models.DonationLot.donation),
        )
        .join(models.Patient, models.Patient.id == models.Delivery.patient_id)
        .where(
            models.Delivery.id == delivery_id,
            models.Patient.user_id == current_user.id,
        )
    )
    result = await db.execute(query)
    delivery = result.scalars().first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Boleta no encontrada para este paciente.")

    return _build_delivery_receipt_response(delivery)

# 7. Subir Boleta Firmada
@router.put("/deliveries/{delivery_id}/upload-receipt", response_model=schemas.DeliveryResponse)
async def upload_delivery_receipt(
    delivery_id: int,
    receipt: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    result = await db.execute(select(models.Delivery).where(models.Delivery.id == delivery_id))
    delivery = result.scalars().first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Entrega no encontrada")
    if delivery.estado == "VALIDADA":
        raise HTTPException(status_code=400, detail="La constancia ya fue validada")

    if receipt.content_type not in ALLOWED_RECEIPT_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de archivo inválido. Usa PDF.")

    content = await receipt.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="El archivo excede los 2MB.")

    await receipt.seek(0)
    ext = receipt.filename.split(".")[-1] if receipt.filename else "pdf"
    firebase_path = f"donaciones/entregas/{delivery_id}/constancia_{uuid.uuid4().hex[:8]}.{ext}"

    try:
        public_url = upload_file_to_firebase(content, firebase_path, receipt.content_type)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Error al subir la constancia") from exc

    delivery.url_constancia_pdf = public_url
    delivery.estado = "CARGADA"
    db.add(delivery)
    _log_audit_event(
        db=db,
        actor_id=current_user.id,
        entidad="delivery",
        entidad_id=delivery.id,
        accion="UPLOAD_DELIVERY_RECEIPT",
        payload={"estado": delivery.estado},
    )
    await db.commit()
    await db.refresh(delivery)
    return delivery