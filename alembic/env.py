import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


from alembic import context

# 1. Importaciones de TU proyecto
# Ajusta los imports según donde estén tus archivos realmente
from app.core.config import Settings
from app.db import Base
from app import models  # <--- CRÍTICO: Importar modelos para que se registren en metadata

# 2. Configuración inicial de Alembic
config = context.config

# Configurar Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 3. Inyección de la URL de Base de Datos (Sobrescribe alembic.ini)
settings = Settings()
# Forzamos el driver asyncpg por si settings viene con el driver normal
sqlalchemy_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
config.set_main_option("sqlalchemy.url", sqlalchemy_url)

# 4. Definir la metadata para el 'autogenerate'
target_metadata = Base.metadata

def include_object(object, name, type_, reflected, compare_to):
    """
    Función para filtrar qué cosas ve Alembic.
    Devuelve False para ignorar objetos.
    """
    # Si es un índice y su nombre empieza con 'idx_', lo ignoramos
    if type_ == "index" and name and name.startswith("idx_"):
        return False
    
    # También puedes ignorar tablas específicas si quisieras
    # if type_ == "table" and name == "tabla_rara":
    #     return False
    
    return True

def run_migrations_offline() -> None:
    """
    Correr migraciones en modo 'offline'.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object
    )

    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection: Connection) -> None:
    """
    Función síncrona que ejecuta las migraciones
    dentro del contexto async.
    """
    context.configure(
        connection=connection, 
        target_metadata=target_metadata,
        include_object=include_object
        )

    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online() -> None:
    """
    Correr migraciones en modo 'online' (ASÍNCRONO).
    """
    # Crear el Engine Asíncrono
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        # Ejecutar la función síncrona dentro del loop async
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    # Punto de entrada Async
    asyncio.run(run_migrations_online())