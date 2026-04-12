from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# 1. Creamos el motor ASÍNCRONO
# Usamos settings.DATABASE_URL directamente (ya configuramos asyncpg en config.py)
engine = create_async_engine(
    settings.DATABASE_URL,
    future=True,
    echo=True, # Recomendado en desarrollo para ver los queries
    pool_pre_ping=True
)

# 2. La fábrica de sesiones asíncronas
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()

# 3. Dependencia Asíncrona (Yield)
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()