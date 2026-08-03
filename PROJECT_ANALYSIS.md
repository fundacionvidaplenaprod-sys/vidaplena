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
│   │   ├── endpoints/          # (auth.py, users.py, patients.py, appointments.py, director_deliveries.py, etc.)
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
│   │       ├── admin/          # Panel de Super Admin (Gestión de Usuarios, Agenda Médica - DoctorAgendaPage)
│   │       ├── auth/           # Login
│   │       ├── dashboard/      # Dashboard principal (Inicio, Reportes)
│   │       ├── director/       # Módulo especializado de entrega rápida (DirectorDeliveryPage)
│   │       ├── patients/       # Gestión completa de pacientes (Registro, Historial)
│   │       └── AppointmentBookingPage.jsx # Reserva pública de citas y validación OCR de vouchers
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
  - **Aportes Voluntarios con Lectura Inteligente (OCR)**: Al subir su comprobante mensual (`VoluntaryContributionModal.jsx`), el motor OCR (`/api/v1/contributions/ocr-preview`) detecta de forma automática y precarga el monto, fecha y hora del recibo. A diferencia del SAPAM, no impone un monto fijo, permitiendo al paciente confirmar o editar libremente su aporte.
  - **Complicaciones Médicas** (Tipos administrables por el Super Admin).

### Módulo Especializado de la Directora (`/directora`)
- Un sistema aislado y ágil diseñado para la Directora de la fundación, operado de forma rápida y sin ataduras al padrón general de expedientes.
- **Autenticación Silenciosa**: Utiliza un Keypad Numérico. El PIN de 4 dígitos actúa como contraseña de un usuario técnico (`directora@vidaplena.org`).
- **Bloqueo Inteligente**: Se bloquea manualmente o por inactividad (3 minutos sin interacciones).
- **Pestañas de Atención Clínica (Sin Administración)**:
  - **1. Entrega Rápida de Insulina**: Registro veloz en campo sobre la tabla independiente (`director_insulin_deliveries`) con alerta de duplicados en los últimos 25 días.
  - **2. Agenda de Citas del Día**: Vista clínica especializada de solo atención que permite a la doctora consultar las citas confirmadas para el día de hoy, revisar los datos básicos del paciente (CI y fecha de nacimiento) y registrar la **Nota Clínica de Evolución / Consulta (`nota_consulta`)**. No incluye funciones de administración para mantener la simplicidad y rapidez.

### Módulo de Reserva de Cita Médica (SAPAM) (`/agendar-cita` y `/dashboard/agenda-medica`)
- **Reserva Pública sin Sesión**: Cualquier paciente puede solicitar una cita de atención médica en los horarios disponibles indicando sus datos personales básicos (Nombres, Apellidos, CI y Fecha de Nacimiento).
- **Validación Automática de Comprobante (OCR)**: Para confirmar la cita, el sistema solicita cargar la foto de un comprobante de aporte/donación con valor a **70.00 Bs**. El motor OCR (`extract_receipt_data`) verifica de forma automatizada:
  - El monto exacto (Bs. 70.00).
  - La fecha del comprobante (debe ser la fecha actual).
  - La hora de transacción (dentro de una ventana temporal reciente).
- **Emisión Automática de Ficha PDF**: Si la validación OCR es exitosa, la cita queda `CONFIRMADA`, se genera un código de seguridad único (`security_code`, ej. `CITA-...`) y se emite la **Ficha de Atención Médica en PDF** para el paciente.
- **Mecanismo Administrativo de Solución a Rechazos OCR (Atención por WhatsApp)**:
  - Cuando el OCR rechaza el voucher (por imagen borrosa, iluminación, corte de texto o fallo técnico), la cita se guarda con estado `RECHAZADA` junto con el `motivo_rechazo` y se instruye al paciente a comunicarse al número oficial de **WhatsApp** de la fundación.
  - **Dispensación manual de la ficha por el personal administrativo (`SUPER_ADMIN`)**:
    1. El personal autorizado (`SUPER_ADMIN`) accede a la sección **Agenda Médica** (`/dashboard/agenda-medica`) y entra a la pestaña **"Historial por C.I."**.
    2. Busca por el carnet de identidad del paciente, listándose todas sus citas (incluyendo las rechazadas con su motivo).
    3. Al verificar por WhatsApp que el voucher enviado por el paciente es auténtico y correcto, el administrador presiona el botón **`Aprobar (verificado por WhatsApp)`**.
    4. El sistema ejecuta el endpoint `POST /api/v1/appointments/{id}/approve`, cambiando el estado a `CONFIRMADA`, registrando la auditoría del usuario que aprobó (`revisado_manualmente_por`, `revisado_manualmente_at`) y generando el `security_code`.
    5. Inmediatamente se habilita el botón **`Descargar ficha`** en la misma interfaz para que el administrador descargue el PDF y se lo envíe al paciente por WhatsApp (o para que el paciente lo descargue desde el portal).
- **Exención por Vulnerabilidad ("Caso Social")**: Para pacientes en situación de vulnerabilidad o de escasos recursos que no pueden realizar el aporte de 70.00 Bs, el `SUPER_ADMIN` puede exonerar el pago y confirmar la cita directamente sin requerir voucher (`POST /api/v1/appointments/{id}/approve-social-case`), registrando el motivo de exención (`motivo_exencion`) y auditoría del usuario que autoriza (`eximido_por`, `eximido_at`).
- **Separación de Roles (Administración vs. Atención)**: 
  - Todas las tareas administrativas (aprobación manual por WhatsApp, historial por C.I. y bloqueo/desbloqueo de fechas no laborables en `doctor_blocked_days`) están restringidas estrictamente al rol **`SUPER_ADMIN`** (`get_current_super_user`).
  - La consulta de la agenda del día y el registro de notas clínicas de evolución (`nota_consulta`) están habilitadas tanto para `SUPER_ADMIN` como para el personal médico/directora (`REGISTRADOR`) mediante la dependencia `get_current_staff_user`.

### Reportes (`/reports`)
- Generación de reportes gerenciales con métricas sobre pacientes, entregas, donaciones y tipos de complicaciones.
- Exportación en pantalla y generación de documentos estructurados en PDF mediante el frontend.

---

## 5. Esquema de Base de Datos (Modelos)

El sistema utiliza **PostgreSQL** administrado por **SQLAlchemy**. A continuación se presentan las entidades principales y sus relaciones:

- **Users (`users`)**: Entidad de autenticación y autorización. Almacena credenciales, roles (`SUPER_ADMIN`, `REGISTRADOR`, `PACIENTE`) y estado de la cuenta.
- **Patients (`patients`)**: El núcleo del expediente médico. 
  - Relacionado 1:1 con un `User` si es un paciente que puede iniciar sesión.
  - Almacena datos personales, datos físicos (peso, altura, IMC), dirección y enlaces a la **documentación digital** subida (fotos de CI, certificado médico, etc.) que se almacenan en Firebase Storage u otros proveedores en la nube.
- **Tutors (`tutors`)**: Información del tutor legal o familiar de contacto (Relación 1:1 con `patients`).
- **Patient Medical (`patient_medical`)**: Diagnóstico principal, hospital base y médico tratante (Relación 1:1 con `patients`).
- **Complication Types & Patient Complications**: Un catálogo administrable de tipos de complicaciones diabéticas (`complication_types`) y una tabla intermedia (`patient_complications`) que asocia múltiples complicaciones a un paciente.
- **Patient Treatments (`patient_treatments`)**: Registro de los requerimientos de insulina basal, insulina rápida y material (jeringas) de cada paciente (Relación 1:N).
- **Contributions (`monthly_contributions`)**: Seguimiento de los pagos o aportes mensuales realizados por el paciente. Se complementa con el servicio OCR (`/contributions/ocr-preview`) para detectar de manera inteligente monto, fecha y hora al cargar recibos.
- **Donations & Lots (`donation_lots`)**: Registro de lotes de insulinas ingresadas al inventario de la fundación, con tipo, cantidad y fecha de vencimiento.
- **Allocations & Deliveries (`donation_allocations`, `deliveries`)**: `donation_allocations` reserva insulinas de un lote para un paciente específico, y `deliveries` registra la entrega física o consumo de esas insulinas, generando constancias en PDF.
- **Director Deliveries (`director_insulin_deliveries`)**: Tabla independiente que alimenta el "Módulo de Directora". Registra entregas de forma rápida, libre de ataduras al expediente estructurado del paciente, para agilizar operaciones en campo.
- **Appointments (`appointments`) & Blocked Days (`doctor_blocked_days`)**: Entidades del Módulo SAPAM para la reserva de citas médicas y control de agenda. `appointments` registra datos del solicitante, horario, resultados de validación OCR del voucher de 70 Bs, auditoría de aprobación manual (`revisado_manualmente_por`), exención por vulnerabilidad social (`eximido_por`, `motivo_exencion`) y notas clínicas; `doctor_blocked_days` almacena las fechas no disponibles en la agenda médica.

---

## 6. Estado de Verificación y Pruebas Automatizadas (54/54 Pruebas en Verde)

El sistema cuenta con una suite de pruebas automatizadas en **pytest** e **In-Memory SQLite AsyncSession** para garantizar la ausencia de regresiones y auditar cada regla de negocio crítica:

1. **`tests/test_donations_deliveries.py` (7 tests aprobados - Registro y Distribución de Insulinas)**:
   - **Registro de Catálogo e Inventario**: Validación del alta de productos de insulina (`/donations/products/`), creación de lotes con stock y vencimiento (`/donations/lots/`) y registro de tratamientos prescritos por paciente (`PatientTreatment`).
   - **Algoritmo de Distribución Trimestral (`/donations/calculate-distribution/{lot_id}`)**:
     - Cálculo automático de envases requeridos para el periodo de 90 días (`DISTRIBUTION_DAYS = 90`, redondeo hacia arriba con `math.ceil`).
     - **Filtro Anti-Morosos**: Exclusión automática de la repartición (`excluded_patients`) para aquellos pacientes que no cuenten con su aporte mensual del periodo actual en estado `ACEPTADO`.
     - **Regla de Solidaridad en Escasez**: Cuando la demanda teórica supera el stock disponible en almacén (`escasez = True`), el algoritmo reduce de forma equitativa la asignación a **1 envase por paciente** para evitar que ningún beneficiario se quede sin cobertura.
   - **Consolidación y Entregas**: Descuento oficial de `DonationLot.cantidad_disponible` al registrar una entrega en `/donations/deliveries/`.
2. **`tests/test_director_deliveries.py` (4 tests aprobados - Módulo Aislado de Entrega Rápida)**:
   - Prueba de registro de entregas en campo por la Directora sin afectar el stock de almacén.
   - Búsqueda por nombres y apellidos normalizados (mayúsculas/minúsculas).
   - Alerta anti-duplicados y candado temporal preventivo de 25 días.
3. **`tests/test_appointments.py` (23 tests aprobados - Módulo SAPAM de Citas Médicas)**:
   - Reserva pública de citas y validación automática del voucher de **70.00 Bs** mediante OCR.
   - Aprobación manual por WhatsApp y exención por vulnerabilidad ("Caso Social") restringidas a `SUPER_ADMIN`.
   - Limpieza automática e isolación transaccional (`cleanup_test_appointments` y `DoctorBlockedDay`).
4. **Otras Suites de Pruebas Aprobadas**:
   - `tests/test_beneficiary_admin.py` (8 tests aprobados)
   - `tests/test_contributions_ocr.py` (4 tests aprobados)
   - `tests/test_minor_registration.py` (1 test aprobado)
   - `tests/test_self_registration.py` (6 tests aprobados)
   - `tests/test_tutor_multiple_children.py` (1 test aprobado)

**Estado General**: `54 passed, 3 warnings` (100% en verde). Todos los flujos clínicos, logísticos y administrativos están completamente respaldados por pruebas automatizadas.
