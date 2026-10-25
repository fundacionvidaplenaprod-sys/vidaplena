"""
Registro Asistido por Situación Excepcional.

Reglamento especial: incorpora al programa, de forma gratuita y sin exigir documentos ni datos
personales a la persona asistida, a quienes están en centros de acogida, recintos penitenciarios,
situación de calle, etc.

- Los datos de la persona asistida son opcionales (Art. 9): se puede registrar a alguien sin llenar
  nada y el sistema le asigna su Código Interno de Registro (RA-00001).
- La persona referente, en cambio, es obligatoria: es quien recibe la insulina para entregarla. Se
  exigen su nombre completo, C.I., teléfono y una foto personal para identificarse, y el vínculo con el
  beneficiario (familiar, conocido, referido por terceros o amistad; nunca «no se sabe»). Una misma
  persona referente puede serlo de varios beneficiarios.
- No hay campos para documentos de la persona asistida ni para las causas del acogimiento o de la
  privación de libertad (Art. 8 y 9 III).
- Acceso restringido al Evaluador Social, la Coordinación y la Dirección Ejecutiva (Art. 19 I).
- Gratuidad absoluta (Art. 17): son tablas aparte de `patients`, sin usuario ni aporte, y no entran
  en los reportes de aportes ni de morosos.
"""
import re
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app import models, schemas
from app.api import deps
from app.api.deps import get_db
from app.core.firebase import upload_file_to_firebase
from app.core.text_normalize import fold_sql, normalize_name

router = APIRouter()

# Revisión periódica de vigencia: al menos semestral (Art. 20 c).
REVISION_DIAS = 183
FOTO_MAX_BYTES = 2 * 1024 * 1024
FOTO_TIPOS = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png"}


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


async def _codigos_por_referente(db: AsyncSession, referente_ids: set) -> dict:
    """Códigos de los registros ACTIVOS de cada persona referente."""
    ids = {i for i in referente_ids if i}
    if not ids:
        return {}
    R = models.AssistedRegistration
    rows = await db.execute(
        select(R.referente_id, R.codigo).where(R.referente_id.in_(ids), R.estado == "ACTIVO").order_by(R.id)
    )
    por_referente: dict = {}
    for referente_id, codigo in rows.all():
        por_referente.setdefault(referente_id, []).append(codigo)
    return por_referente


def _referente_out(ref: models.AssistedReferent, codigos: List[str], *, con_codigos: bool = False):
    base = schemas.AssistedReferentOut.model_validate(ref).model_dump()
    base["registros_activos"] = len(codigos)
    base["codigos"] = codigos if con_codigos else []
    return schemas.AssistedReferentOut(**base)


def _out(reg: models.AssistedRegistration, *, detail: bool = False, emails: Optional[dict] = None, codigos: Optional[dict] = None):
    base = schemas.AssistedRegistrationOut.model_validate(reg).model_dump(exclude={"referente"})
    base["referente"] = _referente_out(reg.referente, (codigos or {}).get(reg.referente_id, [])) if reg.referente else None
    base["referente_pendiente"] = reg.referente_id is None
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


def _audit(db: AsyncSession, actor: models.User, entidad_id: int, accion: str, payload: Optional[dict] = None, *, entidad: str = "assisted_registration") -> None:
    """Bitácora sin datos personales: solo el id y qué se hizo."""
    db.add(models.AuditLog(actor_id=actor.id, entidad=entidad, entidad_id=entidad_id, accion=accion, payload=payload or {}))


async def _load(db: AsyncSession, reg_id: int) -> models.AssistedRegistration:
    result = await db.execute(
        select(models.AssistedRegistration)
        .where(models.AssistedRegistration.id == reg_id)
        .options(
            selectinload(models.AssistedRegistration.treatments),
            selectinload(models.AssistedRegistration.deliveries),
            selectinload(models.AssistedRegistration.referente),
        )
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


async def _require_referente(db: AsyncSession, referente_id: int) -> models.AssistedReferent:
    ref = await db.get(models.AssistedReferent, referente_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="No existe esa persona referente.")
    return ref


async def _detail(db: AsyncSession, reg_id: int):
    reg = await _load(db, reg_id)
    emails = await _emails(db, {d.entregado_por_id for d in reg.deliveries})
    codigos = await _codigos_por_referente(db, {reg.referente_id})
    return _out(reg, detail=True, emails=emails, codigos=codigos)


# --- Personas referentes -----------------------------------------------------------------------
# Van antes de las rutas «/{reg_id}» para que «referentes» no se interprete como un id.

def _clean_referente_fields(nombre_completo: str, ci: str, telefono: str) -> tuple:
    nombre, ci, telefono = nombre_completo.strip(), ci.strip(), telefono.strip()
    if len(nombre) < 3:
        raise HTTPException(status_code=422, detail="Indique el nombre completo de la persona referente.")
    if len(ci) < 4:
        raise HTTPException(status_code=422, detail="Indique el C.I. de la persona referente.")
    if len(re.sub(r"\D", "", telefono)) < 6:
        raise HTTPException(status_code=422, detail="Indique un número de contacto válido de la persona referente.")
    return nombre, ci, telefono


async def _upload_foto(ref_id: int, foto: UploadFile) -> str:
    extension = FOTO_TIPOS.get(foto.content_type or "")
    if extension is None:
        raise HTTPException(status_code=400, detail="La foto debe ser una imagen JPG o PNG.")
    content = await foto.read()
    if not content:
        raise HTTPException(status_code=400, detail="La foto está vacía.")
    if len(content) > FOTO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="La foto supera el máximo de 2 MB.")
    path = f"registro_asistido/referentes/{ref_id}/foto.{extension}"
    try:
        return await run_in_threadpool(upload_file_to_firebase, content, path, foto.content_type)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo subir la foto: {exc}")


async def _ci_en_uso(db: AsyncSession, ci: str, excepto_id: Optional[int] = None) -> Optional[models.AssistedReferent]:
    query = select(models.AssistedReferent).where(func.lower(models.AssistedReferent.ci) == ci.lower())
    if excepto_id:
        query = query.where(models.AssistedReferent.id != excepto_id)
    return (await db.execute(query)).scalars().first()


@router.post("/referentes", response_model=schemas.AssistedReferentOut, status_code=201)
async def create_referent(
    nombre_completo: str = Form(...),
    ci: str = Form(...),
    telefono: str = Form(...),
    foto: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_assisted_staff),
):
    """Registra una persona referente: nombre completo, C.I., teléfono y foto personal son obligatorios."""
    nombre, ci, telefono = _clean_referente_fields(nombre_completo, ci, telefono)
    existente = await _ci_en_uso(db, ci)
    if existente:
        raise HTTPException(
            status_code=409,
            detail=f"Ya hay una persona referente con ese C.I. ({existente.nombre_completo}): selecciónela de la lista.",
        )
    ref = models.AssistedReferent(nombre_completo=nombre, ci=ci, telefono=telefono, created_by_id=current_user.id)
    db.add(ref)
    await db.flush()
    ref.foto_url = await _upload_foto(ref.id, foto)
    _audit(db, current_user, ref.id, "CREATE", entidad="assisted_referent")
    await db.commit()
    await db.refresh(ref)
    return _referente_out(ref, [])


@router.get("/referentes", response_model=List[schemas.AssistedReferentOut])
async def search_referents(
    q: Optional[str] = Query(None, max_length=80, description="Nombre o C.I."),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_assisted_staff),
):
    ref = models.AssistedReferent
    query = select(ref)
    for token in normalize_name(q).split():
        query = query.where(
            fold_sql(ref.nombre_completo).contains(token, autoescape=True) | ref.ci.icontains(token, autoescape=True)
        )
    refs = (await db.execute(query.order_by(ref.nombre_completo).limit(30))).scalars().all()
    codigos = await _codigos_por_referente(db, {r.id for r in refs})
    return [_referente_out(r, codigos.get(r.id, [])) for r in refs]


@router.get("/referentes/{referente_id}", response_model=schemas.AssistedReferentOut)
async def get_referent(
    referente_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_assisted_staff),
):
    ref = await _require_referente(db, referente_id)
    codigos = await _codigos_por_referente(db, {ref.id})
    return _referente_out(ref, codigos.get(ref.id, []), con_codigos=True)


@router.put("/referentes/{referente_id}", response_model=schemas.AssistedReferentOut)
async def update_referent(
    referente_id: int,
    nombre_completo: Optional[str] = Form(None),
    ci: Optional[str] = Form(None),
    telefono: Optional[str] = Form(None),
    foto: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_assisted_staff),
):
    """Corrige o completa los datos de la persona referente. Lo que se omite queda igual; no se puede dejar en blanco."""
    ref = await _require_referente(db, referente_id)
    nombre, ci_nuevo, tel = _clean_referente_fields(
        nombre_completo if nombre_completo is not None else ref.nombre_completo,
        ci if ci is not None else (ref.ci or ""),
        telefono if telefono is not None else (ref.telefono or ""),
    )
    if ci_nuevo != (ref.ci or "") and await _ci_en_uso(db, ci_nuevo, excepto_id=ref.id):
        raise HTTPException(status_code=409, detail="Ya hay otra persona referente con ese C.I.")
    tiene_foto_nueva = foto is not None and bool(foto.filename)
    if not ref.foto_url and not tiene_foto_nueva:
        raise HTTPException(status_code=422, detail="Falta la foto personal de la persona referente.")
    ref.nombre_completo, ref.ci, ref.telefono = nombre, ci_nuevo, tel
    if tiene_foto_nueva:
        ref.foto_url = await _upload_foto(ref.id, foto)
    _audit(db, current_user, ref.id, "UPDATE", entidad="assisted_referent")
    await db.commit()
    await db.refresh(ref)
    codigos = await _codigos_por_referente(db, {ref.id})
    return _referente_out(ref, codigos.get(ref.id, []), con_codigos=True)


# --- Registros ---------------------------------------------------------------------------------
@router.post("/", response_model=schemas.AssistedRegistrationDetail, status_code=201)
async def create_assisted_registration(
    data: schemas.AssistedRegistrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_assisted_staff),
):
    """
    Registra a una persona. Los datos de la persona son opcionales, pero hay que indicar su persona
    referente (ya registrada) y el vínculo con ella. Recibe su Código Interno de Registro.
    """
    await _require_referente(db, data.referente_id)
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
    q: Optional[str] = Query(None, max_length=80, description="Código, nombre, C.I., entidad o persona referente"),
    revision_vencida: Optional[bool] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_assisted_staff),
):
    R = models.AssistedRegistration
    F = models.AssistedReferent
    query = (
        select(R)
        .outerjoin(F, F.id == R.referente_id)
        .options(selectinload(R.treatments), selectinload(R.deliveries), selectinload(R.referente))
    )
    if estado:
        query = query.where(R.estado == estado)
    if depto:
        query = query.where(func.lower(R.depto) == depto.strip().lower())
    texto = fold_sql(
        func.concat_ws(" ", R.codigo, R.nombre, R.ci, R.entidad_nombre, R.ciudad_localidad, F.nombre_completo, F.ci)
    )
    for token in normalize_name(q).split():
        query = query.where(texto.contains(token, autoescape=True))
    query = query.order_by(R.created_at.desc(), R.id.desc()).limit(limit)
    regs = (await db.execute(query)).scalars().unique().all()

    codigos = await _codigos_por_referente(db, {r.referente_id for r in regs})
    items = [_out(r, codigos=codigos) for r in regs]
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
    """
    Completa o corrige los datos. Un dato de la persona en blanco (cadena vacía) se borra; omitirlo lo
    deja igual. La persona referente y el vínculo se pueden cambiar, pero no dejar en blanco.
    """
    reg = await _load(db, reg_id)
    _require_active(reg)

    sent = data.model_fields_set
    for field in schemas.AssistedRegistrationFields.model_fields:
        if field in sent:
            value = getattr(data, field)
            if field == "urgente":
                value = bool(value)
            setattr(reg, field, value)
    if data.referente_id is not None:
        await _require_referente(db, data.referente_id)
        reg.referente_id = data.referente_id
    if data.referente_vinculo is not None:
        reg.referente_vinculo = data.referente_vinculo
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
