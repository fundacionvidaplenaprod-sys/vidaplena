from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # --- PROYECTO ---
    APP_NAME: str = "VIDAPLENA"
    
    API_V1_STR: str = ""
    # --- BASE DE DATOS ---
    # CAMBIO CRÍTICO: Usamos 'postgresql+asyncpg' en lugar de 'psycopg2'
    # Ajusta tu contraseña si no es 'postgres'
    DATABASE_URL: str = "postgresql+asyncpg://postgres:Bisa.2025@localhost:5432/vidaplena"
    DB_USER: str | None = None
    DB_PASSWORD: str | None = None
    DB_NAME: str | None = None

    # --- SEGURIDAD (JWT) ---
    # Esta clave firma los tokens. En producción, ¡nunca la compartas!
    # Puedes generar una buena ejecutando: openssl rand -hex 32
    SECRET_KEY: str = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    INVENTORY_LOW_STOCK_THRESHOLD: int = 10

    class Config:
        env_file = ".env"
        case_sensitive = True

# Instanciamos aquí para importar 'settings' directamente en otros archivos
settings = Settings()