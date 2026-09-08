from datetime import datetime, timezone
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_

from app.db import get_db
from app import models, schemas
from app.core.security import hash_password
from app.core.departamentos import DEPARTAMENTOS_RESPONSABLE
from app.api import deps

router = APIRouter()

# Roles que corresponden al personal de la fundación. La tabla `users` mezcla
# ese personal (una decena de cuentas) con las cuentas de los beneficiarios
# (más de un centenar, y creciendo con cada autorregistro), y la pantalla de
# administración necesita verlos por separado: buscar a un responsable
# departamental entre las cuentas de beneficiarios obligaba a recorrer toda
# la lista. La definición vive acá y no en el frontend para que exista una
# sola fuente de verdad sobre qué es "personal".
ROLES_PERSONAL = [
    "SUPER_ADMIN",
    "REGISTRADOR",
    "EVALUADOR_SOCIAL",
    "RESPONSABLE_DEPARTAMENTAL",
    "COORDINADOR_NACIONAL",
]


def _validar_depto_asignado(role: str, depto_asignado: Optional[str]) -> Optional[str]:
    """
    RESPONSABLE_DEPARTAMENTAL exige un depto_asignado válido; cualquier otro
    rol lo ignora (siempre queda en None), para que nunca quede un valor
    obsoleto colgando si el usuario cambia de rol después.
    """
    if role != "RESPONSABLE_DEPARTAMENTAL":
        return None
    if not depto_asignado or depto_asignado not in DEPARTAMENTOS_RESPONSABLE:
        raise HTTPException(
            status_code=400,
            detail="Debe indicar un departamento válido para un usuario RESPONSABLE_DEPARTAMENTAL.",
        )
    return depto_asignado

# =============================================================================
# 1. 🥇 OBTENER MI PERFIL (El endpoint que te falta)
# ESTE ES EL QUE NECESITA EL AUTHCONTEXT PARA NO PATEARTE
# =============================================================================
@router.get("/me", response_model=schemas.UserResponse)
async def read_user_me(
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    Obtiene el perfil del usuario logueado (Admin, Registrador o Paciente).
    """
    return current_user


# =============================================================================
# 2. LISTAR USUARIOS (Para el Admin)
# OJO: La ruta es "/" (raíz de users), NO "/me"
# =============================================================================
@router.get("/", response_model=schemas.PaginatedUserResponse)
async def read_users(
    skip: int = 0,
    limit: int = 20,
    role: Optional[str] = None,
    grupo: Optional[Literal["PERSONAL", "BENEFICIARIOS"]] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user) # 🔒 Solo Super Admin
):
    """
    Lista paginada de usuarios, con el total para que el frontend pueda
    dibujar el paginador.

    `grupo` separa las dos poblaciones que conviven en la tabla: `PERSONAL`
    (ver `ROLES_PERSONAL`) y `BENEFICIARIOS` (rol `PACIENTE`). `role` filtra
    por un rol exacto y tiene precedencia sobre `grupo` si se envían ambos.
    """
    filters = []

    if role:
        filters.append(models.User.role == role)
    elif grupo == "PERSONAL":
        filters.append(models.User.role.in_(ROLES_PERSONAL))
    elif grupo == "BENEFICIARIOS":
        filters.append(models.User.role == "PACIENTE")

    if search:
        filters.append(models.User.email.ilike(f"%{search}%"))

    total = await db.scalar(
        select(func.count()).select_from(models.User).where(*filters)
    )

    query = (
        select(models.User)
        .where(*filters)
        .order_by(models.User.id)
        .offset(skip)
        .limit(limit)
    )

    result = await db.execute(query)
    users = result.scalars().all()

    return {"total": total or 0, "items": await _con_exoneraciones(db, users)}


async def _con_exoneraciones(db: AsyncSession, users) -> List[schemas.UserResponse]:
    """
    Adjunta a cada usuario su exoneración por cargo, si la tiene.

    Se resuelve con una sola consulta extra por página (y ninguna fila cuando
    no hay exoneraciones), en vez de un JOIN en el listado: la exoneración es
    excepcional —un puñado de responsables— y no debe encarecer la consulta
    principal, que casi siempre lista beneficiarios.
    """
    items = [schemas.UserResponse.model_validate(u) for u in users]
    if not items:
        return items

    ids = [u.id for u in users]
    res = await db.execute(
        select(models.Patient, models.User.email)
        .outerjoin(models.User, models.User.id == models.Patient.exonerado_cargo_por)
        .where(
            models.Patient.exonerado_cargo_user_id.in_(ids),
            models.Patient.exonerado_por_cargo.is_(True),
        )
    )

    por_user = {}
    for patient, autor_email in res.all():
        por_user[patient.exonerado_cargo_user_id] = schemas.ExoneracionCargoInfo(
            patient_id=patient.id,
            beneficiario_nombre=f"{patient.nombres} {patient.ap_paterno or ''}".strip(),
            beneficiario_ci=patient.ci,
            motivo=patient.exonerado_cargo_motivo,
            exonerado_at=patient.exonerado_cargo_at,
            autorizado_por=autor_email,
        )

    for item in items:
        item.exoneracion_cargo = por_user.get(item.id)
    return items


# =============================================================================
# 3. CREAR USUARIO
# =============================================================================
@router.post("/", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user: schemas.UserCreate, 
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user)
):
    query = select(models.User).where(models.User.email == user.email)
    result = await db.execute(query)
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="El email ya está registrado")

    hashed_pwd = hash_password(user.password)
    depto_asignado = _validar_depto_asignado(user.role, user.depto_asignado)

    new_user = models.User(
        email=user.email,
        password_hash=hashed_pwd,
        role=user.role,
        depto_asignado=depto_asignado,
        estado="ACTIVO"
    )
    
    db.add(new_user)
    try:
        await db.commit()
        await db.refresh(new_user)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al crear usuario: {str(e)}")
        
    return new_user


# =============================================================================
# 4. ACTUALIZAR USUARIO
# =============================================================================
@router.put("/{user_id}", response_model=schemas.UserResponse)
async def update_user(
    user_id: int,
    user_in: schemas.UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user)
):
    query = select(models.User).where(models.User.id == user_id)
    result = await db.execute(query)
    db_user = result.scalars().first()

    if not db_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    update_data = user_in.model_dump(exclude_unset=True)

    effective_role = update_data.get("role", db_user.role)
    effective_depto = update_data.get("depto_asignado", db_user.depto_asignado)
    update_data["depto_asignado"] = _validar_depto_asignado(effective_role, effective_depto)

    if 'password' in update_data and update_data['password']:
        hashed_pwd = hash_password(update_data['password'])
        db_user.password_hash = hashed_pwd
        del update_data['password']

    rol_anterior = db_user.role

    for field, value in update_data.items():
        setattr(db_user, field, value)

    # Si deja de ser responsable departamental, su exoneración por cargo se
    # cae con el cargo: se otorgó como incentivo al puesto, no a la persona.
    # Va en la misma transacción que el cambio de rol para que no puedan
    # quedar desincronizados.
    if rol_anterior == "RESPONSABLE_DEPARTAMENTAL" and db_user.role != "RESPONSABLE_DEPARTAMENTAL":
        await _revocar_exoneracion_por_cargo(
            db, db_user.id, current_user.id, f"cambio de rol a {db_user.role}"
        )

    try:
        await db.commit()
        await db.refresh(db_user)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error actualizando: {str(e)}")

    return db_user


# =============================================================================
# 5. DAR DE BAJA / REACTIVAR
# =============================================================================
@router.put("/{user_id}/toggle-status", response_model=schemas.UserResponse)
async def toggle_user_status(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user)
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="No puedes desactivarte a ti mismo.")

    query = select(models.User).where(models.User.id == user_id)
    result = await db.execute(query)
    db_user = result.scalars().first()

    if not db_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    new_status = "INACTIVO" if db_user.estado == "ACTIVO" else "ACTIVO"
    db_user.estado = new_status

    # Una cuenta dada de baja ya no ejerce el cargo: la exoneración se retira
    # con ella. Reactivarla no la devuelve —hay que otorgarla de nuevo— para
    # que siempre quede constancia de quién la autorizó y cuándo.
    if new_status == "INACTIVO":
        await _revocar_exoneracion_por_cargo(
            db, db_user.id, current_user.id, "baja de la cuenta"
        )

    await db.commit()
    await db.refresh(db_user)
    return db_user


# =============================================================================
# 6. ELIMINAR USUARIO
# =============================================================================
@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user)
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="No puedes auto-eliminarte.")

    query = select(models.User).where(models.User.id == user_id)
    result = await db.execute(query)
    db_user = result.scalars().first()

    if not db_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    try:
        await db.delete(db_user)
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=400, 
            detail="No se puede eliminar porque tiene registros asociados."
        )
    
    return None

# =============================================================================
# 7. EXONERACIÓN DEL APORTE MENSUAL POR CARGO
# =============================================================================
# Los responsables departamentales no reciben sueldo y algunos son además
# beneficiarios; por normativa interna un SUPER_ADMIN puede exonerarlos del
# aporte mensual. La exoneración vive en la ficha del beneficiario pero se
# otorga desde acá, junto al cargo, porque nace y muere con él.

def _log_audit_event(
    *,
    db: AsyncSession,
    actor_id: Optional[int],
    entidad: str,
    entidad_id: int,
    accion: str,
    payload: Optional[dict] = None,
) -> None:
    """Mismo helper que usa donations.py; se repite para no acoplar routers."""
    db.add(
        models.AuditLog(
            actor_id=actor_id,
            entidad=entidad,
            entidad_id=entidad_id,
            accion=accion,
            payload=payload,
        )
    )


async def _get_exoneracion_de(db: AsyncSession, user_id: int) -> Optional[models.Patient]:
    """Beneficiario exonerado atado a esta cuenta de responsable, si lo hay."""
    result = await db.execute(
        select(models.Patient).where(
            models.Patient.exonerado_cargo_user_id == user_id,
            models.Patient.exonerado_por_cargo.is_(True),
        )
    )
    return result.scalars().first()


def _limpiar_exoneracion(patient: models.Patient) -> None:
    patient.exonerado_por_cargo = False
    patient.exonerado_cargo_user_id = None
    patient.exonerado_cargo_motivo = None
    patient.exonerado_cargo_por = None
    patient.exonerado_cargo_at = None


async def _revocar_exoneracion_por_cargo(
    db: AsyncSession, user_id: int, actor_id: Optional[int], causa: str
) -> Optional[int]:
    """
    Revocación automática: se dispara cuando la persona deja de ser
    responsable departamental (cambio de rol o baja de la cuenta). Devuelve el
    patient_id afectado, o None si no había exoneración vigente.

    No hace commit: lo deja en manos de quien lo llama, para que la revocación
    viaje en la misma transacción que el cambio que la provocó y no puedan
    quedar desincronizados.
    """
    patient = await _get_exoneracion_de(db, user_id)
    if patient is None:
        return None

    _limpiar_exoneracion(patient)
    db.add(patient)
    _log_audit_event(
        db=db,
        actor_id=actor_id,
        entidad="patient",
        entidad_id=patient.id,
        accion="REVOKE_EXONERACION_CARGO_AUTO",
        payload={"responsable_user_id": user_id, "causa": causa},
    )
    return patient.id


@router.post("/{user_id}/exoneracion-cargo", response_model=schemas.ExoneracionCargoInfo)
async def exonerar_por_cargo(
    user_id: int,
    datos: schemas.ExoneracionCargoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    Vincula al responsable con su ficha de beneficiario (por C.I.) y lo exonera
    del aporte mensual. Solo alcanza al aporte mensual: no exime del voucher de
    la cita médica ni altera el reparto automático de insulina.
    """
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    responsable = result.scalars().first()
    if not responsable:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if responsable.role != "RESPONSABLE_DEPARTAMENTAL":
        raise HTTPException(
            status_code=400,
            detail="La exoneración por cargo solo aplica a un RESPONSABLE_DEPARTAMENTAL.",
        )

    ci = datos.ci.strip()
    res_p = await db.execute(select(models.Patient).where(models.Patient.ci.ilike(ci)))
    patient = res_p.scalars().first()
    if not patient:
        raise HTTPException(
            status_code=404,
            detail=f"No existe un beneficiario con C.I. {ci}.",
        )

    # Un responsable exonera una sola ficha, y una ficha no puede estar
    # exonerada por dos cargos a la vez.
    vigente = await _get_exoneracion_de(db, user_id)
    if vigente is not None and vigente.id != patient.id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Este responsable ya tiene una exoneración vigente sobre el "
                f"beneficiario {vigente.nombres} {vigente.ap_paterno} (C.I. {vigente.ci}). "
                "Retírela antes de asignar otra."
            ),
        )
    if patient.exonerado_por_cargo and patient.exonerado_cargo_user_id not in (None, user_id):
        raise HTTPException(
            status_code=400,
            detail="Ese beneficiario ya está exonerado por cargo desde otra cuenta.",
        )

    patient.exonerado_por_cargo = True
    patient.exonerado_cargo_user_id = user_id
    patient.exonerado_cargo_motivo = datos.motivo.strip()
    patient.exonerado_cargo_por = current_user.id
    patient.exonerado_cargo_at = datetime.now(timezone.utc)
    db.add(patient)

    _log_audit_event(
        db=db,
        actor_id=current_user.id,
        entidad="patient",
        entidad_id=patient.id,
        accion="GRANT_EXONERACION_CARGO",
        payload={
            "responsable_user_id": user_id,
            "responsable_email": responsable.email,
            "motivo": patient.exonerado_cargo_motivo,
        },
    )

    try:
        await db.commit()
        await db.refresh(patient)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al exonerar: {str(e)}")

    return schemas.ExoneracionCargoInfo(
        patient_id=patient.id,
        beneficiario_nombre=f"{patient.nombres} {patient.ap_paterno or ''}".strip(),
        beneficiario_ci=patient.ci,
        motivo=patient.exonerado_cargo_motivo,
        exonerado_at=patient.exonerado_cargo_at,
        autorizado_por=current_user.email,
    )


@router.delete("/{user_id}/exoneracion-cargo", status_code=status.HTTP_204_NO_CONTENT)
async def retirar_exoneracion_por_cargo(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """Retiro manual de la exoneración, sin tocar el rol del responsable."""
    patient = await _get_exoneracion_de(db, user_id)
    if patient is None:
        raise HTTPException(
            status_code=404,
            detail="Este responsable no tiene una exoneración vigente.",
        )

    _limpiar_exoneracion(patient)
    db.add(patient)
    _log_audit_event(
        db=db,
        actor_id=current_user.id,
        entidad="patient",
        entidad_id=patient.id,
        accion="REVOKE_EXONERACION_CARGO_MANUAL",
        payload={"responsable_user_id": user_id},
    )

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al retirar: {str(e)}")

    return None
