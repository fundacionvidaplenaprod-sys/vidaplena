import asyncio
import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db import Base, get_db
from app.core.config import settings
from app import models

# Configuración de la base de datos de prueba (usamos la misma por ahora, 
# pero idealmente se configuraría una separada en el .env de pruebas)
TEST_DATABASE_URL = settings.DATABASE_URL

engine = create_async_engine(TEST_DATABASE_URL, future=True)
TestingSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with TestingSessionLocal() as session:
        yield session
        await session.rollback()

@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    async def _get_test_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_test_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

@pytest_asyncio.fixture(scope="function")
async def superuser_token(client, db_session):
    # Crear un superusuario temporal para las pruebas o usar uno existente
    from app.core.security import hash_password
    
    # Limpiar si existe (opcional, depende de si se usa una DB limpia)
    # email = "testadmin@mail.com"
    # ...
    
    # Mocking get_current_super_user to avoid real token validation
    from app.api import deps
    
    admin_user = models.User(
        email=f"admin_{uuid.uuid4().hex[:8]}@test.com",
        password_hash="fakehash",
        role="SUPER_ADMIN",
        estado="ACTIVO"
    )
    db_session.add(admin_user)
    await db_session.commit()
    await db_session.refresh(admin_user)
    
    async def override_get_current_super_user():
        return admin_user
        
    app.dependency_overrides[deps.get_current_super_user] = override_get_current_super_user
    app.dependency_overrides[deps.get_current_active_user] = override_get_current_super_user
    
    yield "fake-token"
    
    app.dependency_overrides.pop(deps.get_current_super_user, None)
    app.dependency_overrides.pop(deps.get_current_active_user, None)
