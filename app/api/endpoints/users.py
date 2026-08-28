from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_

from app.db import get_db
from app import models, schemas
from app.core.security import hash_password
from app.core.departamentos import DEPARTAMENTOS
from app.api import deps

router = APIRouter()


def _validar_depto_asignado(role: str, depto_asignado: Optional[str]) -> Optional[str]:
    """
    RESPONSABLE_DEPARTAMENTAL exige un depto_asignado válido; cualquier otro
    rol lo ignora (siempre queda en None), para que nunca quede un valor
    obsoleto colgando si el usuario cambia de rol después.
    """
    if role != "RESPONSABLE_DEPARTAMENTAL":
        return None
    if not depto_asignado or depto_asignado not in DEPARTAMENTOS:
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
@router.get("/", response_model=List[schemas.UserResponse])
async def read_users(
    skip: int = 0,
    limit: int = 10000,
    role: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user) # 🔒 Solo Super Admin
):
    """
    Lista todos los usuarios del sistema.
    """
    query = select(models.User).order_by(models.User.id)

    if role:
        query = query.where(models.User.role == role)
    
    if search:
        query = query.where(models.User.email.ilike(f"%{search}%"))

    query = query.offset(skip).limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()


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

    for field, value in update_data.items():
        setattr(db_user, field, value)

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