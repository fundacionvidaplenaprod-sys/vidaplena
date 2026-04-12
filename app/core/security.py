from datetime import datetime, timedelta, timezone
from typing import Any, Union
from jose import jwt
import bcrypt
from app.core.config import settings

# --- HASHING (Lo que ya tenías) ---
def hash_password(password: str) -> str:
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(pwd_bytes, salt)
    return hashed_bytes.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    plain_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(plain_bytes, hashed_bytes)

# --- JWT (Lo nuevo) ---
def create_access_token(subject: Union[str, Any], expires_delta: timedelta = None) -> str:
    """
    Genera un JWT firmado con nuestra SECRET_KEY.
    subject: Generalmente es el ID del usuario o el email (sub).
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # El payload es la información que viaja dentro del token
    to_encode = {"exp": expire, "sub": str(subject)}
    
    # Codificamos usando la clave secreta y el algoritmo definidos en config
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    
    return encoded_jwt