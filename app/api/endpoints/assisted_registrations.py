"""
Registro Asistido por Situación Excepcional.

Reglamento especial: incorpora al programa, de forma gratuita y sin exigir documentos ni datos
personales, a personas en centros de acogida, recintos penitenciarios, situación de calle, etc.

- Ningún dato es obligatorio (Art. 9): se puede registrar una persona sin llenar nada y el sistema
  le asigna su Código Interno de Registro (RA-00001).
- No se piden documentos ni se guardan causas del acogimiento o de la privación de libertad: no hay
  campos para eso (Art. 8 y 9 III).
- Acceso restringido al Evaluador Social, la Coordinación y la Dirección Ejecutiva (Art. 19 I).
- Gratuidad absoluta (Art. 17): son tablas aparte de `patients`, sin usuario ni aporte, y no entran
  en los reportes de aportes ni de morosos.
"""
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app import models, schemas
from app.api import deps
from app.api.deps import get_db
from app.core.text_normalize import fold_sql, normalize_name

router = APIRouter()

# Revisión periódica de vigencia: al menos semestral (Art. 20 c).
REVISION_DIAS = 183


def _revision_vencida(reg: models.AssistedRegistration, hoy: Optional[datetime] = None) -> bool:
    if reg.estado != "ACTIVO":
        return False
    ahora = hoy or datetime.now(timezone.utc)
    base = reg.ultima_revision_at or reg.created_at
    return bool(base) and (ahora - base) > timedelta(days=REVISION_DIAS)


async def _emails(db: AsyncSession, user_ids: set) -> dict:
    ids = {i for i in user_ids if i}
    if not ids:
        return {}
    rows = await db.execute(select(models.User.id, models.User.email).where(models.User.id.in_(ids)))
    return {uid: email for uid, email in rows.all()}


def _out(reg: models.AssistedRegistration, *, detail: bool = False, emails: Optional[dict] = None):
    base = schemas.AssistedRegistrationOut.model_validate(reg).model_dump()
    base["revision_vencida"] = _revision_vencida(reg)
    base["total_entregas"] = len(reg.deliveries)
    base["ultima_entrega"] = reg.deliveries[0].fecha if reg.deliveries else None
    if not detail:
        return schemas.AssistedRegistrationOut(**base)
    deliveries = [
        schemas.AssistedDeliveryOut(
            **{
                **schemas.AssistedDeliveryOut.model_validate(d).model_dump(exclude={"entregado_por"}),
                "entregado_por": (emails or {}).get(d.entregado_por_id),
            }
        )
        for d in reg.deliveries
    ]
    return schemas.AssistedRegistrationDetail(**base, deliveries=deliveries)


def _audit(db: AsyncSession, actor: models.User, reg_id: int, accion: str, payload: Optional[dict] = None) -> None:
    """Bitácora sin datos personales: solo el id del registro y qué se hizo."""
    db.add(
        models.AuditLog(
            actor_id=actor.id,
            entidad="assisted_registration",
            entidad_id=reg_id,
            accion=accion,
            payload=payload or {},
        )
    )


async def _load(db: AsyncSession, reg_id: int) -> models.AssistedRegistration:
    result = await db.execute(
        select(models.AssistedRegistration)
        .where(models.AssistedRegistration.id == reg_id)
        .options(selectinload(models.AssistedRegistration.treatments), selectinload(models.AssistedRegistration.deliveries))
        .execution_options(populate_existing=True)
    )
    reg = result.scalars().first()
    if not reg:
        raise HTTPException(status_code=404, detail="Registro asistido no encontrado.")
    return reg


def _require_active(reg: models.AssistedRegistration) -> None:
    if reg.estado != "ACTIVO":
        raise HTTPException(
            status_code=400,
            detail=f"El registro está {reg.estado.lower()}: ya no admite cambios ni entregas.",
        )


async def _detail(db: AsyncSession, reg_id: int):
    reg = await _load(db, reg_id)
    emails = await _emails(db, {d.entregado_por_id for d in reg.deliveries})
    return _out(reg, detail=True, emails=emails)


@router.post("/", response_model=schemas.AssistedRegistrationDetail, status_code=201)
async def create_assisted_registration(
    data: schemas.AssistedRegistrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_assisted_staff),
):
    """
    Registra a una persona. Todo es opcional: con el cuerpo vacío igual se crea y recibe su código,
    para poder entregar insumos desde el primer contacto y completar el registro después (Art. 11 IV).
    """
    values = data.model_dump(exclude={"treatments", "buen_uso_comunicado"}, exclude_none=True)
    reg = models.AssistedRegistration(**values, estado="ACTIVO", registrado_por_id=current_user.id)
    reg.urgente = bool(data.urgente)
    if data.buen_uso_comunicado:
        reg.buen_uso_comunicado_at = datetime.now(timezone.utc)
        reg.buen_uso_comunicado_por_id = current_user.id
    reg.treatments = [
        models.AssistedTreatment(insulina=t.insulina, dosis_diaria=t.dosis_diaria) for t in data.treatments
    ]
    db.add(reg)
    await db.flush()
    reg.codigo = f"RA-{reg.id:05d}"
    _audit(db, current_user, reg.id, "CREATE", {"urgente": reg.urgente})
    await db.commit()
    return await _detail(db, reg.id)


@router.get("/", response_model=List[schemas.AssistedRegistrationOut])
async def list_assisted_registrations(
    estado: Optional[str] = Query(None, pattern="^(ACTIVO|DENEGADO|CESADO)$"),
    depto: Optional[str] = Query(None, max_length=80),
    q: Optional[str] = Query(None, max_length=80, description="Código, nombre, entidad o persona referente"),
    revision_vencida: Optional[bool] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_assisted_staff),
):
    R = models.AssistedRegistration
    query = select(R).options(selectinload(R.treatments), selectinload(R.deliveries))
    if estado:
        query = query.where(R.estado == estado)
    if depto:
        query = query.where(func.lower(R.depto) == depto.strip().lower())
    texto = fold_sql(
        func.concat_ws(" ", R.codigo, R.nombre, R.entidad_nombre, R.referente_nombre, R.ciudad_localidad)
    )
    for token in normalize_name(q).split():
        query = query.where(texto.contains(token, autoescape=True))
    query = query.order_by(R.created_at.desc(), R.id.desc()).limit(limit)
    regs = (await db.execute(query)).scalars().unique().all()

    items = [_out(r) for r in regs]
    if revision_vencida is not None:
        items = [i for i in items if i.revision_vencida == revision_vencida]
    return items


@router.get("/{reg_id}", response_model=schemas.AssistedRegistrationDetail)
async def get_assisted_registration(
    reg_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_assisted_staff),
):
    return await _detail(db, reg_id)


@router.put("/{reg_id}", response_model=schemas.AssistedRegistrationDetail)
async def update_assisted_registration(
    reg_id: int,
    data: schemas.AssistedRegistrationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_assisted_staff),
):
    """Completa o corrige los datos. Un campo en blanco (cadena vacía) lo borra; omitirlo lo deja igual."""
    reg = await _load(db, reg_id)
    _require_active(reg)

    sent = data.model_fields_set
    for field in schemas.AssistedRegistrationFields.model_fields:
        if field in sent:
            value = getattr(data, field)
            if field == "urgente":
                value = bool(value)
            setattr(reg, field, value)
    if data.treatments is not None:
        reg.treatments = [
            models.AssistedTreatment(insulina=t.insulina, dosis_diaria=t.dosis_diaria) for t in data.treatments
        ]
    if data.buen_uso_comunicado is True and reg.buen_uso_comunicado_at is None:
        reg.buen_uso_comunicado_at = datetime.now(timezone.utc)
        reg.buen_uso_comunicado_por_id = current_user.id
    elif data.buen_uso_comunicado is False:
        reg.buen_uso_comunicado_at = None
        reg.buen_uso_comunicado_por_id = None

    _audit(db, current_user, reg.id, "UPDATE", {"campos": sorted(sent)})
    await db.commit()
    return await _detail(db, reg.id)


@router.post("/{reg_id}/entregas", response_model=schemas.AssistedRegistrationDetail, status_code=201)
async def add_assisted_delivery(
    reg_id: int,
    data: schemas.AssistedDeliveryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_assisted_staff),
):
    """
    Anota una entrega de insumos por Código Interno (fecha, insumo y cantidad). La constancia de
    recepción es opcional: nunca se condiciona la entrega a obtenerla (Art. 14 II).
    """
    reg = await _load(db, reg_id)
    _require_active(reg)
    hoy = date.today()
    if data.fecha and data.fecha > hoy:
        raise HTTPException(status_code=400, detail="La fecha de la entrega no puede ser futura.")
    db.add(
        models.AssistedDelivery(
            registration_id=reg.id,
            fecha=data.fecha or hoy,
            insumo=data.insumo,
            cantidad=data.cantidad,
            receptor_tipo=data.receptor_tipo,
            receptor_nombre=data.receptor_nombre,
            constancia_tipo=data.constancia_tipo,
            entregado_por_id=current_user.id,
        )
    )
    _audit(db, current_user, reg.id, "ENTREGA", {"insumo": data.insumo, "cantidad": data.cantidad})
    await db.commit()
    return await _detail(db, reg.id)


@router.post("/{reg_id}/revision", response_model=schemas.AssistedRegistrationDetail)
async def register_assisted_review(
    reg_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_assisted_staff),
):
    """Deja constancia de la revisión de vigencia hecha con la Persona Referente (Art. 20 c)."""
    reg = await _load(db, reg_id)
    _require_active(reg)
    reg.ultima_revision_at = datetime.now(timezone.utc)
    reg.ultima_revision_por_id = current_user.id
    _audit(db, current_user, reg.id, "REVISION")
    await db.commit()
    return await _detail(db, reg.id)


@router.post("/{reg_id}/denegar", response_model=schemas.AssistedRegistrationDetail)
async def deny_assisted_registration(
    reg_id: int,
    data: schemas.AssistedDenyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_assisted_staff),
):
    """
    Deniega la admisión mediante resolución motivada. Solo procede por manifiesta ausencia de
    necesidad de insulina o de los insumos solicitados (Art. 11 III), y la decide el Evaluador Social
    (o la Dirección Ejecutiva). La persona puede volver a solicitar: se crea un registro nuevo.
    """
    if current_user.role not in ("SUPER_ADMIN", "EVALUADOR_SOCIAL"):
        raise HTTPException(status_code=403, detail="La admisión la resuelve el Evaluador Social.")
    reg = await _load(db, reg_id)
    _require_active(reg)
    if reg.deliveries:
        raise HTTPException(
            status_code=400,
            detail="Ya se entregaron insumos a esta persona: corresponde el cese del registro, no la denegación.",
        )
    reg.estado = "DENEGADO"
    reg.motivo_denegacion = data.motivo.strip()
    _audit(db, current_user, reg.id, "DENEGAR")
    await db.commit()
    return await _detail(db, reg.id)


@router.post("/{reg_id}/cese", response_model=schemas.AssistedRegistrationDetail)
async def end_assisted_registration(
    reg_id: int,
    data: schemas.AssistedCeseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_assisted_staff),
):
    """
    Cesa el registro por una de las causas del Art. 23. La pérdida de contacto con la Persona
    Referente o el cambio de institución NO son causales de cese, por eso no existen como opción.
    """
    reg = await _load(db, reg_id)
    _require_active(reg)
    if data.causa == "FALTA_GRAVE" and not data.detalle:
        raise HTTPException(
            status_code=422,
            detail="La falta grave exige indicar el detalle y que se cumplió el debido proceso.",
        )
    if data.patient_id is not None:
        if data.causa != "TRASLADO_REGIMEN_ORDINARIO":
            raise HTTPException(status_code=422, detail="La ficha ordinaria solo se vincula en un traslado al régimen ordinario.")
        exists = await db.execute(select(models.Patient.id).where(models.Patient.id == data.patient_id))
        if exists.first() is None:
            raise HTTPException(status_code=404, detail="No existe esa ficha de beneficiario.")
        reg.patient_id = data.patient_id
    reg.estado = "CESADO"
    reg.cese_causa = data.causa
    reg.cese_detalle = data.detalle
    reg.cese_at = datetime.now(timezone.utc)
    _audit(db, current_user, reg.id, "CESE", {"causa": data.causa})
    await db.commit()
    return await _detail(db, reg.id)
