from typing import Generator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app import models, schemas
from app.core import security
from app.core.config import settings
from app.db import get_db

# Definimos el esquema de autenticación (URL del endpoint de login)
reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)

async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(reusable_oauth2)
) -> models.User:
    """
    Valida el token y recupera al usuario asociado.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = schemas.TokenData(**payload)
    except (JWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No se pudieron validar las credenciales",
        )
    
    # El 'sub' del token es el ID del usuario (string)
    query = select(models.User).where(models.User.id == int(token_data.sub))
    result = await db.execute(query)
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    return user

def get_current_active_user(
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    """
    Verifica que el usuario no esté bloqueado/inactivo.
    """
    if current_user.estado != "ACTIVO":
        raise HTTPException(status_code=400, detail="Usuario inactivo")
    return current_user

# --- AQUÍ ESTÁ LA FUNCIÓN QUE FALTABA ---
def get_current_super_user(
    current_user: models.User = Depends(get_current_active_user),
) -> models.User:
    """
    Verifica que el usuario sea SUPER_ADMIN.
    """
    if current_user.role != "SUPER_ADMIN":
        raise HTTPException(
            status_code=403, detail="El usuario no tiene suficientes privilegios"
        )
    return current_user