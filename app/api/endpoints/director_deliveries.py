from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from app import models, schemas
from app.api.deps import get_db, get_current_user
from app.core.insulin_catalog import normalize_insulin_name
from app.core.security import hash_password
from app.core.text_normalize import fold_sql, normalize_name

router = APIRouter()

# El cuaderno lo llena la Directora (cuenta técnica con rol REGISTRADOR) y lo ve el SUPER_ADMIN.
CUADERNO_ROLES = ("SUPER_ADMIN", "REGISTRADOR")


def _require_cuaderno_role(user: models.User) -> None:
    if user.role not in CUADERNO_ROLES:
        raise HTTPException(status_code=403, detail="Not enough permissions")


def _upper(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip().upper()
    return value or None


async def _patient_names(db: AsyncSession, patient_id: int):
    patient = await db.get(models.Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Beneficiario no encontrado")
    return patient


@router.post("/", response_model=schemas.DirectorDeliveryResponse)
async def create_director_delivery(
    *,
    db: AsyncSession = Depends(get_db),
    delivery_in: schemas.DirectorDeliveryCreate,
    current_user: models.User = Depends(get_current_user)
):
    _require_cuaderno_role(current_user)

    nombres = delivery_in.patient_nombres
    ap_paterno = delivery_in.patient_ap_paterno
    ap_materno = delivery_in.patient_ap_materno
    if delivery_in.patient_id:
        patient = await _patient_names(db, delivery_in.patient_id)
        nombres, ap_paterno, ap_materno = patient.nombres, patient.ap_paterno, patient.ap_materno

    delivery = models.DirectorInsulinDelivery(
        patient_nombres=nombres.strip().upper(),
        patient_ap_paterno=ap_paterno.strip().upper(),
        patient_ap_materno=_upper(ap_materno),
        insulin_type=delivery_in.insulin_type,
        quantity=delivery_in.quantity,
        delivery_date=delivery_in.delivery_date or date.today(),
        recorded_by_id=current_user.id,
        patient_id=delivery_in.patient_id,
        presentacion=delivery_in.presentacion,
        marca=_upper_brand(delivery_in.marca),
    )
    db.add(delivery)
    await db.commit()
    await db.refresh(delivery)
    return delivery


def _upper_brand(marca: Optional[str]) -> Optional[str]:
    """La marca se guarda tal como se eligió en la lista (Lantus, Toujeo, ...), sin espacios sobrantes."""
    marca = (marca or "").strip()
    return marca or None


@router.post("/batch", response_model=List[schemas.DirectorDeliveryResponse])
async def create_director_deliveries_batch(
    *,
    db: AsyncSession = Depends(get_db),
    batch_in: schemas.DirectorDeliveryBatchCreate,
    current_user: models.User = Depends(get_current_user)
):
    """Registra la visita de una persona con una o varias insulinas, todo o nada.

    Con `patient_id` toma los nombres de la ficha del beneficiario; sin él pide los nombres
    (personas que todavía no están en el padrón).
    """
    _require_cuaderno_role(current_user)

    if batch_in.patient_id:
        patient = await _patient_names(db, batch_in.patient_id)
        nombres, ap_paterno, ap_materno = patient.nombres, patient.ap_paterno, patient.ap_materno
    else:
        nombres, ap_paterno, ap_materno = batch_in.patient_nombres, batch_in.patient_ap_paterno, batch_in.patient_ap_materno
        if not (nombres or "").strip() or not (ap_paterno or "").strip():
            raise HTTPException(status_code=422, detail="Indique el beneficiario o sus nombres y apellido paterno.")

    fecha = batch_in.delivery_date or date.today()
    rows = []
    for item in batch_in.items:
        row = models.DirectorInsulinDelivery(
            patient_nombres=nombres.strip().upper(),
            patient_ap_paterno=ap_paterno.strip().upper(),
            patient_ap_materno=_upper(ap_materno),
            insulin_type=item.insulin_type.strip(),
            quantity=item.quantity.strip(),
            delivery_date=fecha,
            recorded_by_id=current_user.id,
            patient_id=batch_in.patient_id,
            presentacion=item.presentacion,
            marca=_upper_brand(item.marca),
        )
        db.add(row)
        rows.append(row)
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return rows


async def _last_delivery(
    db: AsyncSession, nombres: str, ap_paterno: str, ap_materno: Optional[str], patient_id: Optional[int] = None
) -> Optional[models.DirectorInsulinDelivery]:
    """Última entrega de una persona: por su ficha, o por nombre para los registros anteriores."""
    by_name = [
        func.upper(models.DirectorInsulinDelivery.patient_nombres) == nombres.strip().upper(),
        func.upper(models.DirectorInsulinDelivery.patient_ap_paterno) == ap_paterno.strip().upper(),
    ]
    if ap_materno:
        by_name.append(func.upper(models.DirectorInsulinDelivery.patient_ap_materno) == ap_materno.strip().upper())
    cond = by_name[0]
    for extra in by_name[1:]:
        cond = cond & extra
    if patient_id:
        cond = or_(models.DirectorInsulinDelivery.patient_id == patient_id, cond)
    query = (
        select(models.DirectorInsulinDelivery)
        .filter(cond)
        .order_by(models.DirectorInsulinDelivery.delivery_date.desc(), models.DirectorInsulinDelivery.id.desc())
    )
    return (await db.execute(query)).scalars().first()


@router.get("/search", response_model=Optional[schemas.DirectorDeliveryResponse])
async def search_last_delivery(
    nombres: str = Query(...),
    ap_paterno: str = Query(...),
    ap_materno: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    _require_cuaderno_role(current_user)
    # Search for the most recent delivery by patient name
    return await _last_delivery(db, nombres, ap_paterno, ap_materno)


@router.get("/beneficiaries", response_model=List[schemas.DirectorBeneficiaryItem])
async def search_beneficiaries(
    q: str = Query(..., min_length=2, max_length=80, description="Nombre, apellido o C.I."),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Busca beneficiarios por nombre, apellido o C.I. y devuelve sus insulinas anotadas
    y su última entrega en el cuaderno (para avisar de una posible entrega duplicada)."""
    _require_cuaderno_role(current_user)

    # La búsqueda no distingue mayúsculas ni tildes («Jose» encuentra «José») y cada
    # palabra se busca por separado en el nombre completo, en cualquier orden.
    nombre_completo = fold_sql(
        func.concat_ws(
            " ",
            models.Patient.nombres,
            models.Patient.ap_paterno,
            models.Patient.ap_materno,
        )
    )
    tokens = normalize_name(q).split()
    if not tokens:
        return []
    query = select(models.Patient).options(selectinload(models.Patient.treatments))
    for token in tokens:
        query = query.where(
            or_(
                nombre_completo.contains(token, autoescape=True),
                models.Patient.ci.icontains(token, autoescape=True),
            )
        )
    # Primero quien empieza por lo escrito («José Diego…»), luego los activos; los
    # inactivos solo si no hay más coincidencias.
    query = query.order_by(
        nombre_completo.startswith(" ".join(tokens), autoescape=True).desc(),
        (models.Patient.estado == "INACTIVO"),
        models.Patient.ap_paterno,
        models.Patient.nombres,
    ).limit(15)
    patients = (await db.execute(query)).scalars().unique().all()

    items = []
    for patient in patients:
        tratamientos = [
            schemas.DirectorBeneficiaryTreatment(
                nombre=tx.nombre,
                insulina=normalize_insulin_name(tx.nombre),
                dosis_diaria=float(tx.dosis_diaria or 0),
            )
            for tx in sorted(patient.treatments, key=lambda t: t.id)
        ]
        ultima = await _last_delivery(db, patient.nombres, patient.ap_paterno, patient.ap_materno, patient.id)
        items.append(
            schemas.DirectorBeneficiaryItem(
                id=patient.id,
                nombres=patient.nombres,
                ap_paterno=patient.ap_paterno,
                ap_materno=patient.ap_materno,
                ci=patient.ci,
                depto=patient.depto,
                estado=patient.estado,
                edad=patient.edad_calc,
                tratamientos=tratamientos,
                ultima_entrega=schemas.DirectorDeliveryResponse.model_validate(ultima) if ultima else None,
            )
        )
    return items


@router.get("/", response_model=schemas.DirectorDeliveryReport)
async def list_director_deliveries(
    desde: Optional[date] = Query(None, description="Primera fecha de entrega (incluida)"),
    hasta: Optional[date] = Query(None, description="Última fecha de entrega (incluida)"),
    q: Optional[str] = Query(None, max_length=80, description="Nombre, apellido o C.I. del beneficiario"),
    limit: int = Query(1000, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Reporte del cuaderno de la Directora: lo que se registró, más reciente primero."""
    _require_cuaderno_role(current_user)
    if desde and hasta and desde > hasta:
        raise HTTPException(status_code=400, detail="La fecha «desde» no puede ser posterior a «hasta».")

    D = models.DirectorInsulinDelivery

    def filtered(query):
        query = query.outerjoin(models.Patient, models.Patient.id == D.patient_id)
        if desde:
            query = query.where(D.delivery_date >= desde)
        if hasta:
            query = query.where(D.delivery_date <= hasta)
        nombre_completo = fold_sql(
            func.concat_ws(" ", D.patient_nombres, D.patient_ap_paterno, D.patient_ap_materno)
        )
        for token in normalize_name(q).split():
            query = query.where(
                or_(
                    nombre_completo.contains(token, autoescape=True),
                    fold_sql(D.insulin_type).contains(token, autoescape=True),
                    fold_sql(D.marca).contains(token, autoescape=True),
                    models.Patient.ci.icontains(token, autoescape=True),
                )
            )
        return query

    total = (await db.execute(filtered(select(func.count(D.id)).select_from(D)))).scalar() or 0
    rows = (
        await db.execute(
            filtered(
                select(D, models.Patient, models.User.email).select_from(D)
            )
            .outerjoin(models.User, models.User.id == D.recorded_by_id)
            .order_by(D.delivery_date.desc(), D.id.desc())
            .limit(limit)
        )
    ).all()

    items = []
    for delivery, patient, email in rows:
        base = schemas.DirectorDeliveryResponse.model_validate(delivery).model_dump()
        items.append(
            schemas.DirectorDeliveryReportItem(
                **base,
                patient_ci=patient.ci if patient else None,
                patient_depto=patient.depto if patient else None,
                registrado_por=email,
            )
        )
    return schemas.DirectorDeliveryReport(total=total, items=items)


@router.put("/pin")
async def update_director_pin(
    *,
    db: AsyncSession = Depends(get_db),
    pin_update: schemas.DirectorPinUpdate,
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Only SUPER_ADMIN can update the director PIN")

    if len(pin_update.pin) != 4 or not pin_update.pin.isdigit():
        raise HTTPException(status_code=400, detail="PIN must be exactly 4 digits")

    directora_email = "directora@vidaplena.org"
    query = select(models.User).filter(func.lower(models.User.email) == directora_email.lower())
    result = await db.execute(query)
    user = result.scalars().first()

    if not user:
        user = models.User(
            email=directora_email,
            password_hash=hash_password(pin_update.pin),
            role="REGISTRADOR",
            estado="ACTIVO"
        )
        db.add(user)
    else:
        user.password_hash = hash_password(pin_update.pin)

    await db.commit()
    return {"msg": "PIN updated successfully"}
