from fastapi import FastAPI
from app.core.config import settings
# Importamos todos los endpoints, INCLUYENDO auth
from app.api.endpoints import patients, admin_complications, users, auth, donations,contributions, reports
from app.core.firebase import init_firebase
from fastapi.middleware.cors import CORSMiddleware

def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME)
    # 1. Definir la lista blanca de dominios permitidos (Tus orígenes)
    origenes_permitidos = [
        "http://localhost:3000",                  # Para que puedas seguir programando localmente
        "http://localhost:5173",                  # Vite puerto local por defecto
        "http://127.0.0.1:5173",
        "https://www.vidaplenafundacion.org",     # Tu frontend oficial con 'www'
        "https://vidaplenafundacion.org",         # Tu frontend oficial sin 'www'
    ]

    # 2. Inyectar el middleware de seguridad
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origenes_permitidos,
        allow_credentials=True,
        allow_methods=["*"], # Permite GET, POST, PUT, DELETE, etc.
        allow_headers=["*"], # Permite todos los headers (incluyendo tokens de autenticación)
    )
    # --- REGISTRO DE RUTAS ---
    # 1. Login (Es vital que esté aquí para evitar el 404)
    app.include_router(auth.router, tags=["Login"])
    
    # 2. Usuarios
    app.include_router(users.router, prefix="/users", tags=["Users"])
    
    # 3. Pacientes y otros
    app.include_router(patients.router, prefix="/patients", tags=["patients"])
    app.include_router(admin_complications.router, prefix="/admin/complication-types", tags=["Admin - Complication Types"])
    app.include_router(donations.router, prefix="/donations", tags=["Donations"])
    app.include_router(contributions.router, prefix="/contributions", tags=["Aportes"]) 
    app.include_router(reports.router, prefix="/reports", tags=["Reportes Gerenciales"])

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok", "app": settings.APP_NAME}

    return app

app = create_app()
init_firebase()