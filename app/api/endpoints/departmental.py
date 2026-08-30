"""
Módulo departamental: endpoints para RESPONSABLE_DEPARTAMENTAL y
COORDINADOR_NACIONAL.

- RESPONSABLE_DEPARTAMENTAL: visibilidad y acciones acotadas estrictamente a
  su propio departamento (users.depto_asignado). Cualquier `depto` que mande
  por query string es ignorado — el departamento efectivo siempre sale del
  usuario autenticado, nunca del cliente.
- COORDINADOR_NACIONAL: misma visibilidad pero sin restricción de
  departamento (puede filtrar opcionalmente), estrictamente de solo lectura
  sobre beneficiarios/entregas — nunca puede pasar el gate de escritura de
  entregas a beneficiarios.
- SUPER_ADMIN: acceso total, igual que en el resto del sistema.

Flujo de insulina en dos etapas, cada una con su propio log de control (NO
descuentan stock de almacén/donaciones — eso lo maneja el módulo separado
en donations.py, exclusivo de SUPER_ADMIN):
  1. Coordinador Nacional -> Responsable Departamental (insulin_shipments):
     el coordinador registra qué envió a cada responsable. Solo
     COORDINADOR_NACIONAL/SUPER_ADMIN pueden originar un envío; el
     responsable destinatario solo lo ve en su historial.
  2. Responsable Departamental -> Beneficiario (departmental_insulin_deliveries):
     el responsable registra la entrega final en campo.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import or_

from app import models, schemas
from app.api import deps
from app.db import get_db
from app.core.text_normalize import normalize_name
from app.core.departamentos import DEPARTAMENTOS
from app.core.contributions import current_periodo, is_patient_current_on_contribution

router = APIRouter()


def _resolve_target_depto(current_user: models.User, depto_param: Optional[str]) -> Optional[str]:
    """
    Departamento efectivo a usar para filtrar. None = sin filtro (solo
    permitido para COORDINADOR_NACIONAL/SUPER_ADMIN sin depto indicado).
    Un RESPONSABLE_DEPARTAMENTAL SIEMPRE queda acotado al suyo, sin importar
    lo que mande el cliente.
    """
    if current_user.role == "RESPONSABLE_DEPARTAMENTAL":
        return current_user.depto_asignado

    if depto_param:
        if depto_param not in DEPARTAMENTOS:
            raise HTTPException(status_code=400, detail="Departamento inválido")
        return depto_param

    return None


def _matches_depto(patient_depto: Optional[str], target: Optional[str]) -> bool:
    if not target:
        return True
    return normalize_name(patient_depto) == normalize_name(target)


def _apply_search(query, search: Optional[str]):
    if search:
        term = f"%{search}%"
        query = query.where(or_(
            models.Patient.nombres.ilike(term),
            models.Patient.ap_paterno.ilike(term),
            models.Patient.ap_materno.ilike(term),
            models.Patient.ci.ilike(term),
        ))
    return query


def _shipment_to_response(s: "models.InsulinShipment") -> schemas.InsulinShipmentResponse:
    return schemas.InsulinShipmentResponse(
        id=s.id,
        recipient_user_id=s.recipient_user_id,
        recipient_email=s.recipient.email if s.recipient else "(usuario eliminado)",
        depto=s.depto,
        insulin_type=s.insulin_type,
        quantity=s.quantity,
        shipment_date=s.shipment_date,
        recorded_by_id=s.recorded_by_id,
        recorded_by_email=s.recorded_by.email if s.recorded_by else None,
        created_at=s.created_at,
    )


def _delivery_to_response(d: "models.DepartmentalInsulinDelivery") -> schemas.DepartmentalInsulinDeliveryResponse:
    nombre = "(beneficiario eliminado)"
    if d.patient:
        nombre = " ".join(filter(None, [d.patient.nombres, d.patient.ap_paterno, d.patient.ap_materno]))
    return schemas.DepartmentalInsulinDeliveryResponse(
        id=d.id,
        patient_id=d.patient_id,
        patient_nombre=nombre,
        depto=d.depto,
        insulin_type=d.insulin_type,
        quantity=d.quantity,
        delivery_date=d.delivery_date,
        recorded_by_id=d.recorded_by_id,
        recorded_by_email=d.recorded_by.email if d.recorded_by else None,
        created_at=d.created_at,
    )


@router.get("/beneficiarios/activos", response_model=schemas.PaginatedDepartmentalBeneficiaryResponse)
async def list_active_beneficiaries(
    skip: int = 0,
    limit: int = 20,
    search: Optional[str] = None,
    depto: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_departmental_viewer),
):
    """
    Beneficiarios ACTIVOS del departamento (o todos, para Coordinador
    Nacional sin filtro), con bandera de si están al día con el aporte del
    mes actual — para decidir si corresponde entregar insulina.
    """
    target_depto = _resolve_target_depto(current_user, depto)

    query = (
        select(models.Patient)
        .where(models.Patient.estado == "ACTIVO")
        .options(selectinload(models.Patient.contributions))
        .order_by(models.Patient.nombres)
    )
    query = _apply_search(query, search)

    result = await db.execute(query)
    candidates = [p for p in result.scalars().unique().all() if _matches_depto(p.depto, target_depto)]

    periodo_actual = current_periodo()
    total = len(candidates)
    page = candidates[skip: skip + limit]
    items = [
        schemas.DepartmentalBeneficiaryItem(
            id=p.id,
            nombres=p.nombres,
            ap_paterno=p.ap_paterno,
            ap_materno=p.ap_materno,
            ci=p.ci,
            depto=p.depto,
            tel_contacto=p.tel_contacto,
            estado=p.estado,
            al_dia_aporte=is_patient_current_on_contribution(p, periodo_actual, include_exonerados=True),
            periodo_actual=periodo_actual,
        )
        for p in page
    ]
    return {"total": total, "items": items}


@router.get("/beneficiarios/pendientes-docs", response_model=schemas.PaginatedDepartmentalPendingDocResponse)
async def list_pending_doc_beneficiaries(
    skip: int = 0,
    limit: int = 20,
    search: Optional[str] = None,
    depto: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_departmental_viewer),
):
    """
    Beneficiarios con documentación pendiente (nunca la subieron, o fue
    observada/rechazada y deben corregirla) — ambos casos quedan en
    estado PENDIENTE_DOC.
    """
    target_depto = _resolve_target_depto(current_user, depto)

    query = (
        select(models.Patient)
        .where(models.Patient.estado == "PENDIENTE_DOC")
        .order_by(models.Patient.updated_at.desc())
    )
    query = _apply_search(query, search)

    result = await db.execute(query)
    candidates = [p for p in result.scalars().unique().all() if _matches_depto(p.depto, target_depto)]

    total = len(candidates)
    page = candidates[skip: skip + limit]
    items = [schemas.DepartmentalPendingDocItem.model_validate(p) for p in page]
    return {"total": total, "items": items}


@router.post(
    "/entregas-insulina",
    response_model=schemas.DepartmentalInsulinDeliveryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_delivery(
    delivery_in: schemas.DepartmentalInsulinDeliveryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_departmental_delivery_writer),
):
    """
    Registra que se entregó insulina a un beneficiario. Es solo un log de
    control (fecha/cantidad/tipo) — NO descuenta stock de almacén.
    """
    patient = await db.get(models.Patient, delivery_in.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Beneficiario no encontrado.")
    if patient.estado != "ACTIVO":
        raise HTTPException(status_code=400, detail="Solo se pueden registrar entregas a beneficiarios ACTIVOS.")

    if current_user.role == "RESPONSABLE_DEPARTAMENTAL" and not _matches_depto(patient.depto, current_user.depto_asignado):
        raise HTTPException(status_code=403, detail="El beneficiario no pertenece a su departamento asignado.")

    delivery = models.DepartmentalInsulinDelivery(
        patient_id=patient.id,
        depto=patient.depto or current_user.depto_asignado or "",
        insulin_type=delivery_in.insulin_type,
        quantity=delivery_in.quantity,
        delivery_date=delivery_in.delivery_date or date.today(),
        recorded_by_id=current_user.id,
    )
    db.add(delivery)
    await db.commit()
    await db.refresh(delivery, attribute_names=["id", "created_at"])

    nombre = " ".join(filter(None, [patient.nombres, patient.ap_paterno, patient.ap_materno]))
    return schemas.DepartmentalInsulinDeliveryResponse(
        id=delivery.id,
        patient_id=patient.id,
        patient_nombre=nombre,
        depto=delivery.depto,
        insulin_type=delivery.insulin_type,
        quantity=delivery.quantity,
        delivery_date=delivery.delivery_date,
        recorded_by_id=current_user.id,
        recorded_by_email=current_user.email,
        created_at=delivery.created_at,
    )


@router.get("/entregas-insulina", response_model=schemas.PaginatedDepartmentalDeliveryResponse)
async def list_deliveries(
    skip: int = 0,
    limit: int = 20,
    patient_id: Optional[int] = None,
    depto: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_departmental_viewer),
):
    """Historial de entregas registradas, acotado por departamento (lectura para ambos roles)."""
    target_depto = _resolve_target_depto(current_user, depto)

    query = (
        select(models.DepartmentalInsulinDelivery)
        .options(
            selectinload(models.DepartmentalInsulinDelivery.patient),
            selectinload(models.DepartmentalInsulinDelivery.recorded_by),
        )
        .order_by(
            models.DepartmentalInsulinDelivery.delivery_date.desc(),
            models.DepartmentalInsulinDelivery.id.desc(),
        )
    )
    if patient_id:
        query = query.where(models.DepartmentalInsulinDelivery.patient_id == patient_id)

    result = await db.execute(query)
    # Matching tolerante a acentos/mayúsculas, igual que en el resto del
    # módulo (depto es texto libre históricamente).
    candidates = [d for d in result.scalars().unique().all() if _matches_depto(d.depto, target_depto)]

    total = len(candidates)
    page = candidates[skip: skip + limit]
    return {"total": total, "items": [_delivery_to_response(d) for d in page]}


@router.get("/responsables", response_model=list[schemas.DepartmentalResponsableItem])
async def list_responsables(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_shipment_writer),
):
    """Lista de RESPONSABLE_DEPARTAMENTAL para elegir destinatario de un envío."""
    query = (
        select(models.User)
        .where(models.User.role == "RESPONSABLE_DEPARTAMENTAL")
        .order_by(models.User.email)
    )
    result = await db.execute(query)
    return result.scalars().all()


@router.post(
    "/envios-insulina",
    response_model=schemas.InsulinShipmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_shipment(
    shipment_in: schemas.InsulinShipmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_shipment_writer),
):
    """
    Registra que el coordinador nacional envió insulina a un responsable de
    departamento. Es solo un log de control (fecha/cantidad/tipo) — NO
    descuenta stock de almacén.
    """
    recipient = await db.get(models.User, shipment_in.recipient_user_id)
    if not recipient or recipient.role != "RESPONSABLE_DEPARTAMENTAL":
        raise HTTPException(status_code=400, detail="El destinatario debe ser un responsable de departamento válido.")

    shipment = models.InsulinShipment(
        recipient_user_id=recipient.id,
        depto=recipient.depto_asignado or "",
        insulin_type=shipment_in.insulin_type,
        quantity=shipment_in.quantity,
        shipment_date=shipment_in.shipment_date or date.today(),
        recorded_by_id=current_user.id,
    )
    db.add(shipment)
    await db.commit()
    await db.refresh(shipment, attribute_names=["id", "created_at"])

    return schemas.InsulinShipmentResponse(
        id=shipment.id,
        recipient_user_id=recipient.id,
        recipient_email=recipient.email,
        depto=shipment.depto,
        insulin_type=shipment.insulin_type,
        quantity=shipment.quantity,
        shipment_date=shipment.shipment_date,
        recorded_by_id=current_user.id,
        recorded_by_email=current_user.email,
        created_at=shipment.created_at,
    )


@router.get("/envios-insulina", response_model=schemas.PaginatedInsulinShipmentResponse)
async def list_shipments(
    skip: int = 0,
    limit: int = 20,
    depto: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_departmental_viewer),
):
    """
    Historial de envíos del coordinador nacional a responsables de
    departamento. Un RESPONSABLE_DEPARTAMENTAL solo ve los envíos dirigidos
    a él mismo (no los de otros responsables); COORDINADOR_NACIONAL/
    SUPER_ADMIN ven todos, con filtro opcional por depto.
    """
    query = (
        select(models.InsulinShipment)
        .options(
            selectinload(models.InsulinShipment.recipient),
            selectinload(models.InsulinShipment.recorded_by),
        )
        .order_by(
            models.InsulinShipment.shipment_date.desc(),
            models.InsulinShipment.id.desc(),
        )
    )
    if current_user.role == "RESPONSABLE_DEPARTAMENTAL":
        query = query.where(models.InsulinShipment.recipient_user_id == current_user.id)
    else:
        target_depto = _resolve_target_depto(current_user, depto)
        if target_depto:
            query = query.where(models.InsulinShipment.depto == target_depto)

    result = await db.execute(query)
    shipments = result.scalars().unique().all()

    total = len(shipments)
    page = shipments[skip: skip + limit]
    return {"total": total, "items": [_shipment_to_response(s) for s in page]}
