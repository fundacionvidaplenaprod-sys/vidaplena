from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app import models, schemas
from app.core import security
from app.core.config import settings
from app.db import get_db

router = APIRouter()

# La ruta exacta debe ser /login/access-token
@router.post("/login/access-token", response_model=schemas.Token)
async def login_access_token(
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    # 1. Buscar TODOS los usuarios con ese email (puede haber varios PACIENTE con tutor)
    query = select(models.User).where(models.User.email == form_data.username)
    result = await db.execute(query)
    candidates = result.scalars().all()

    # 2. Encontrar el que coincida con la contraseña
    user = next(
        (u for u in candidates if security.verify_password(form_data.password, u.password_hash)),
        None
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 3. Crear Token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        subject=user.id,
        expires_delta=access_token_expires
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }