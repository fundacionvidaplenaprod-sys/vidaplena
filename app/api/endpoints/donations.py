"""Boletas de las entregas de insulina registradas con el almacén anterior.

El almacén anterior (productos y lotes cargados a mano, carga CSV, reparto por lote, asignaciones, entregas,
boletas y constancias) se reemplazó el 24/11/2026 por el almacén de `warehouse.py`: ingreso por el Excel de la
donación y reparto con el motor del reporte. Aquí queda solo lo que el beneficiario sigue viendo en su portal:
la lista de sus entregas anteriores (`deliveries` / `donation_allocations`, que se conservan) y su boleta en PDF.
"""
import io
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app import models, schemas
from app.api import deps
from app.db import get_db

router = APIRouter()


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
