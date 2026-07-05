# Análisis del Proyecto: Fundación V.I.D.A. Plena

Este documento proporciona una visión general de la arquitectura, tecnologías y módulos principales del sistema de información de la **Fundación V.I.D.A. Plena**.

## 1. Arquitectura General

El proyecto sigue una arquitectura clásica de **Cliente-Servidor**, dividida en dos componentes principales:
- **Backend**: API RESTful desarrollada en Python (FastAPI).
- **Frontend**: Aplicación de Página Única (SPA) desarrollada en React.

Ambas partes se comunican mediante HTTP (Axios en el cliente) consumiendo endpoints JSON. La seguridad del sistema está gestionada mediante autenticación con **Tokens JWT (JSON Web Tokens)**.

---

## 2. Tecnologías Utilizadas

### Backend (`/app`)
- **Framework Core**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.10+).
- **Base de Datos**: PostgreSQL.
- **ORM**: [SQLAlchemy](https://www.sqlalchemy.org/) configurado de manera **asíncrona** (`asyncpg` / `AsyncSession`).
- **Migraciones**: [Alembic](https://alembic.sqlalchemy.org/) para el control de versiones del esquema de la base de datos.
- **Autenticación**: JWT (`jose`), encriptación de contraseñas con `bcrypt`.
- **Integraciones Externas**: Firebase Admin SDK (para manejo opcional de archivos en Storage u otros servicios).

### Frontend (`/vidaplena-web`)
- **Framework/Librería**: [React 19](https://react.dev/) + [Vite](https://vitejs.dev/).
- **Estilos**: [Tailwind CSS](https://tailwindcss.com/) y componentes base (UI elements en `src/components/ui/`).
- **Navegación**: `react-router-dom` para el manejo de rutas protegidas y públicas.
- **Manejo de Estado de Formularios**: `react-hook-form`.
- **Llamadas a API**: `axios`.
- **Iconografía y Alertas**: `lucide-react` y `react-hot-toast`.
- **Exportación a PDF**: `jspdf` y `jspdf-autotable`.

---

## 3. Estructura de Directorios

```text
VIDAPLENA/
│
├── app/                        # CÓDIGO FUENTE DEL BACKEND
│   ├── api/                    # Endpoints de la API organizados por módulos
│   │   ├── endpoints/          # (auth.py, users.py, patients.py, director_deliveries.py, etc.)
│   │   └── deps.py             # Dependencias (Inyección de Base de Datos, Verificación de JWT)
│   ├── core/                   # Configuración global, Seguridad, Firebase init
│   ├── db.py                   # Configuración del Motor Asíncrono de BD
│   ├── main.py                 # Punto de entrada de FastAPI y registro de Routers (CORS)
│   ├── models.py               # Modelos SQLAlchemy (Esquemas de Base de Datos)
│   └── schemas.py              # Modelos Pydantic (Validación de entrada y salida de datos)
│
├── alembic/                    # Módulo de migraciones de SQLAlchemy
├── tests/                      # Pruebas automatizadas (pytest)
│
├── vidaplena-web/              # CÓDIGO FUENTE DEL FRONTEND
│   ├── src/
│   │   ├── api/                # Configuración de Axios e interceptores
│   │   ├── assets/             # Imágenes y recursos estáticos
│   │   ├── components/         # Componentes reutilizables (Botones, Inputs, Layouts)
│   │   ├── context/            # AuthContext.jsx (Manejo global de estado de sesión)
│   │   └── pages/              # Vistas organizadas por roles y características
│   │       ├── admin/          # Panel de Super Admin (Gestión de Usuarios, Complicaciones)
│   │       ├── auth/           # Login
│   │       ├── dashboard/      # Dashboard principal (Inicio, Reportes)
│   │       ├── director/       # Módulo especializado de entrega rápida (DirectorDeliveryPage)
│   │       └── patients/       # Gestión completa de pacientes (Registro, Historial)
│   ├── index.html              # Plantilla HTML principal
│   ├── package.json            # Dependencias de NPM
│   └── tailwind.config.js      # Configuración de colores de la marca (vida-primary, vida-main, etc.)
│
├── docker-compose.yml          # Opcional para orquestación de contenedores
├── requirements.txt            # Dependencias de Python
└── firebase-adminsdk.json      # Llave de servicio (Backend)
```

---

## 4. Módulos y Lógica de Negocio

### Gestión de Usuarios y Roles (Auth)
- El acceso está restringido por Roles (`SUPER_ADMIN`, `REGISTRADOR`).
- El inicio de sesión genera un **Token JWT** que se envía en los Headers (`Authorization: Bearer <token>`) a través de un interceptor de Axios en el frontend.
- Los Super Administradores pueden dar de alta a nuevos usuarios desde `/dashboard/usuarios`.

### Gestión de Pacientes (`/patients`)
- Módulo central donde se registran los pacientes y su expediente.
- Incluye el seguimiento de:
  - **Donaciones** (Donaciones recibidas por el paciente u otorgadas).
  - **Aportes** (Contribuciones económicas o en especie).
  - **Complicaciones Médicas** (Tipos administrables por el Super Admin).

### Módulo Especializado de la Directora (`/directora`)
- Un sistema aislado y ágil para el registro rápido de entrega de insulinas, diseñado para la Directora de la fundación.
- **Autenticación Silenciosa**: Utiliza un Keypad Numérico. El PIN de 4 dígitos actúa como contraseña de un usuario técnico (`directora@vidaplena.org`).
- **Bloqueo Inteligente**: Se bloquea manualmente o por inactividad (3 minutos sin interacciones).
- **Alerta de Duplicados**: Busca en tiempo real entregas de insulina previas a pacientes con el mismo nombre y apellido en los últimos 25 días.

### Reportes (`/reports`)
- Generación de reportes gerenciales con métricas sobre pacientes, entregas, donaciones y tipos de complicaciones.
- Exportación en pantalla y generación de documentos estructurados en PDF mediante el frontend.
