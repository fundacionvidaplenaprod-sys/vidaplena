from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_

from app.db import get_db
from app import models, schemas
from app.core.security import hash_password
from app.api import deps

router = APIRouter()

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
    limit: int = 100,
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
    
    new_user = models.User(
        email=user.email,
        password_hash=hashed_pwd,
        role=user.role,
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