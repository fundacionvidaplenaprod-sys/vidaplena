# Análisis del Proyecto: Fundación V.I.D.A. Plena

Visión general de la arquitectura, tecnologías y módulos del sistema de información de la **Fundación V.I.D.A. Plena**.

> Última actualización: 8 de septiembre de 2026.

## 1. Arquitectura General

Arquitectura **Cliente-Servidor** en dos componentes:
- **Backend**: API RESTful en Python (FastAPI).
- **Frontend**: SPA en React.

Se comunican por HTTP (Axios) consumiendo endpoints JSON. La seguridad se gestiona con **Tokens JWT**, enviados en el header `Authorization: Bearer <token>` mediante un interceptor de Axios.

---

## 2. Tecnologías Utilizadas

### Backend (`/app`)
- **Framework**: FastAPI 0.115 sobre **Python 3.14** (estricto, para evitar corrupción de entornos virtuales).
- **Base de Datos**: PostgreSQL.
- **ORM**: SQLAlchemy 2.0 **asíncrono** (`asyncpg` / `AsyncSession`). Se eliminaron las dependencias síncronas (`psycopg2-binary`).
- **Migraciones**: Alembic 1.13.
- **Autenticación**: JWT (`python-jose`), hashing con `bcrypt`.
- **Documentos**: `reportlab` para la generación de PDF en servidor.
- **Integraciones**: Firebase Admin SDK (Storage de documentos).

### Frontend (`/vidaplena-web`)
- **Framework**: React 19 + Vite 7.
- **Estilos**: Tailwind CSS 3 (colores de marca en `tailwind.config.js`: `vida-primary`, `vida-main`, etc.).
- **Navegación**: `react-router-dom` 7.
- **Formularios**: `react-hook-form`.
- **API**: `axios` con interceptor de token.
- **UI**: `lucide-react` (iconos), `react-hot-toast` (alertas).
- **Exportación**: `jspdf` + `jspdf-autotable` (PDF) y `xlsx` (Excel).

---

## 3. Estructura de Directorios

```text
VIDAPLENA/
│
├── app/                        # BACKEND
│   ├── api/
│   │   ├── endpoints/          # auth, users, patients, donations, contributions,
│   │   │                       # reports, appointments, evaluations, departmental,
│   │   │                       # director_deliveries, gallery, site_assets,
│   │   │                       # site_settings, admin_complications
│   │   └── deps.py             # Inyección de BD y dependencias de rol
│   ├── core/                   # config, security, firebase, ocr, contributions,
│   │                           # departamentos, text_normalize
│   ├── db.py                   # Motor asíncrono
│   ├── main.py                 # Entrada FastAPI y registro de routers (CORS)
│   ├── models.py               # Modelos SQLAlchemy
│   └── schemas.py              # Modelos Pydantic
│
├── alembic/versions/           # Migraciones
├── tests/                      # pytest (ver sección 6)
├── scripts/                    # dump_prod_db.sh, restore_local_db.sh, anonymize_local.sql
│
├── vidaplena-web/              # FRONTEND
│   └── src/
│       ├── api/                # Axios e interceptores
│       ├── components/         # layout (Sidebar), ui, patients, appointments, landing
│       ├── constants/          # departamentos.js, insulins.js, features.js (interruptores)
│       ├── context/            # AuthContext.jsx
│       └── pages/
│           ├── admin/          # Usuarios, Revisión de Aportes, Agenda Médica,
│           │                   # Evaluaciones Sociales, Galería, QR, Contacto, Nombres
│           ├── appointments/   # Reserva pública de citas (SAPAM)
│           ├── auth/           # Login
│           ├── dashboard/      # Inicio
│           ├── departmental/   # Panel Departamental / Nacional
│           ├── director/       # Entrega rápida de la Directora
│           ├── patients/       # Registro, ficha, autorregistro, portal, eval. social
│           ├── reports/        # Reportes dinámicos
│           └── warehouse/      # Almacén y donaciones
│
├── docker-compose.yml
├── requirements.txt
└── firebase-adminsdk.json
```

---

## 4. Módulos y Lógica de Negocio

### Roles y Autenticación
Seis roles, con la restricción declarada en `CheckConstraint` sobre `users.role`:

| Rol | Alcance |
|---|---|
| `SUPER_ADMIN` | Control total. |
| `REGISTRADOR` | Operativo: registro de beneficiarios, reportes, agenda del día. |
| `EVALUADOR_SOCIAL` | Evaluación socioeconómica y su revisión. |
| `RESPONSABLE_DEPARTAMENTAL` | Acotado a su `depto_asignado`: entrega insulina y registra casos en su departamento. |
| `COORDINADOR_NACIONAL` | Todos los departamentos, de solo lectura; origina los envíos a responsables. |
| `PACIENTE` | Portal del beneficiario. |

Las dependencias de `app/api/deps.py` (`get_current_super_user`, `get_current_departmental_viewer`, `get_current_staff_user`, etc.) aplican estos límites en cada endpoint.

### Gestión de Usuarios (`/dashboard/usuarios`)
Exclusiva de `SUPER_ADMIN`. La tabla `users` mezcla al personal de la fundación (una decena de cuentas) con las cuentas de beneficiarios (más de un centenar, creciendo con cada autorregistro), por lo que la pantalla los separa:

- **Tres pestañas**: *Personal*, *Responsables Departamentales* y *Beneficiarios*. La definición de qué roles son "personal" vive en el backend (`ROLES_PERSONAL` en `users.py`), no en el frontend.
- **Paginación de servidor** (`GET /users/` devuelve `{total, items}`, 20 por página) y **búsqueda en servidor con debounce**. La búsqueda debe resolverse en el backend: filtrar en cliente con paginación solo miraría la página cargada y devolvería resultados incompletos en silencio.
- Alta, edición, baja/reactivación y borrado de cuentas; configuración del PIN de la Directora.

### Gestión de Beneficiarios (`/patients`)
Expediente central del beneficiario. Incluye:
- **Padrón precargado** (`preregistered_beneficiaries`) contra el que se valida el autorregistro público.
- **Autoregistro público** (`/registro-beneficiario`, `POST /patients/self-register`): **cerrado temporalmente hasta nuevo aviso** por plazo de registro vencido. Lo gobierna un único interruptor, `AUTOREGISTRO_HABILITADO` en `vidaplena-web/src/constants/features.js`: con `false` el login oculta el enlace *"¿Eres beneficiario de la Fundación?"* y la URL directa muestra `RegistroCerradoPage` (aviso con salidas a inicio de sesión e inicio) en vez del formulario. Un mismo interruptor gobierna ambos accesos para que no queden desalineados. Es un cierre **a nivel de pantalla**: el endpoint del backend sigue abierto. Para reabrirlo, poner la constante en `true`.
- **Documentación digital** en Firebase Storage (CI, certificado médico, foto, declaración de aporte, documentos del tutor).
- **Aportes Solidarios con Lectura Inteligente (OCR)**: al subir el comprobante mensual, `POST /contributions/ocr-preview` detecta monto, fecha y hora. A diferencia del SAPAM no impone un monto fijo; el beneficiario confirma o edita. `SUPER_ADMIN` puede además registrar aportes en efectivo manualmente.
- **Complicaciones médicas** (catálogo administrable) y **tratamientos** de insulina basal/rápida y material.
- **Tutor legal** para menores de edad y beneficiarios con capacidades diferentes (un tutor puede tener varios representados).

### Evaluación Socioeconómica y Categorización
Operada por `EVALUADOR_SOCIAL` o `SUPER_ADMIN`.

- **Formulario multi-step** (React Hook Form): vivienda, integrantes del hogar, servicios, transporte, deudas, ingresos y salud, más evidencias fotográficas.
- **Motor de Categorización (CFNR)**: calcula la **Capacidad Financiera Neta Residual** = ingresos totales − (canasta básica + vivienda/servicios/salud + transporte + deudas). La canasta escala con el hogar (1 persona = 1000 Bs, 2 = 1800, +700 por persona adicional). Umbrales:
  - **ALTA**: CFNR ≤ 0 Bs (déficit) → **única categoría con exoneración total del aporte**.
  - **MEDIA**: 0 < CFNR ≤ 1500 Bs → aporte reducido, con monto fijado por el entrevistador.
  - **BAJA**: CFNR > 1500 Bs → aporte completo, elegido por el beneficiario (mínimo 100 Bs).
- **Módulo Anti-Fraude**: reglas que marcan `REVISIÓN MANUAL URGENTE` ante inconsistencias (ingresos cero con seguro médico activo, pobreza extrema con vivienda propia sin alquiler, etc.).
- **Evaluación extraordinaria**: cuando el beneficiario no puede llenar el formulario digital, el evaluador registra el informe de una entrevista telefónica con su justificación; esa creación es ya la decisión final, sin aval posterior separado.
- **Cooldowns**: rechazo estándar bloquea nuevas evaluaciones por un plazo; `RECHAZADO_FRAUDE` deja `estado_beneficio = SUSPENDIDO` hasta que un `SUPER_ADMIN` reactive; una aprobación abre cooldown de 6 meses antes de reevaluar.
- **Cumplimiento legal (marco boliviano)**: Declaración Jurada (Art. 169 C.P.), Consentimiento Informado de Datos (Habeas Data, Art. 130 C.P.E. y Ley 164), consentimiento de uso de imágenes y trazabilidad de auditoría (IP, User-Agent y timestamp del evaluador).

> La firma electrónica en pantalla se **retiró del flujo** en agosto de 2026 (migración `20260814_000003`), reemplazada por el aviso de entrevista virtual.

### Exoneración del Aporte Mensual
Existen **dos exoneraciones distintas y simultáneas**, deliberadamente en columnas separadas de `patients`. Los reportes las distinguen como `EXONERADO (VULNERABILIDAD)` y `EXONERADO (CARGO)`, porque la fundación necesita justificar ambas poblaciones por separado.

| | `exonerado_aporte` | `exonerado_por_cargo` |
|---|---|---|
| **Causa** | Vulnerabilidad acreditada (categoría ALTA) | Incentivo al Responsable Departamental |
| **Quién la fija** | La evaluación socioeconómica | Un `SUPER_ADMIN`, manualmente |
| **Dónde se opera** | Revisión de Evaluación Social | Gestión de Usuarios → pestaña Responsables |

**Por qué están separadas:** la evaluación reescribe `exonerado_aporte` en *cada* revisión, incluido ponerla en `False`. Compartir el campo haría que la siguiente reevaluación borrara la exoneración del responsable en silencio.

**Exoneración por cargo** (`POST` / `DELETE /users/{id}/exoneracion-cargo`):
- Los responsables departamentales no reciben sueldo y algunos son además beneficiarios; la normativa interna permite eximirlos del aporte.
- La cuenta de personal y la ficha de beneficiario son **registros separados**, así que al otorgarla se vincula explícitamente por C.I. y se guarda en `exonerado_cargo_user_id`.
- **Revocación automática**: se retira sola al cambiar de rol o al dar de baja la cuenta, en la misma transacción que el cambio que la provoca. Reactivar la cuenta no la devuelve: hay que otorgarla de nuevo, para que siempre conste quién la autorizó.
- **Alcance acotado al aporte mensual**: no exime del voucher de 70 Bs de la cita médica ni altera el filtro anti-morosos del reparto automático de insulina.
- Queda auditoría de la concesión (`GRANT_EXONERACION_CARGO`) y de cada revocación, manual o automática.

El punto único de lectura es `esta_exonerado()` en `app/core/contributions.py`.

### Distribución Nacional de Insulina
Cadena logística en dos niveles, sobre tablas propias de control y auditoría:

1. **Coordinador Nacional → Responsable Departamental** (`insulin_shipments`): registra envíos con tipo de insulina, **presentación** (Frasco 10ml / Pen 3ml / Cartucho) y cantidad. Un envío puede llevar más de un tipo de insulina. Origina el envío únicamente `COORDINADOR_NACIONAL` o `SUPER_ADMIN`.
2. **Responsable Departamental → Beneficiario** (`departmental_insulin_deliveries`): registra la entrega en campo, también con presentación, varios tipos por entrega y **observaciones**. El responsable puede corregir sus propias entregas y consultar el historial.

**Panel Departamental** (`/dashboard/panel-departamental`): el responsable ve solo su departamento (Pando queda excluido de la asignación); el coordinador nacional ve todos en solo lectura. Muestra beneficiarios activos y con documentos pendientes, con badges de aporte del **mes actual y del anterior** y de exoneración, para decidir si corresponde entregar insulina.

**Reparto automático desde almacén** (`POST /donations/calculate-distribution/{lot_id}`): calcula envases para un horizonte de 90 días (`math.ceil`), excluye morosos sin aporte `ACEPTADO` del periodo y, ante escasez, aplica la **regla de solidaridad** reduciendo a 1 envase por beneficiario. Este filtro conserva su comportamiento histórico y **no** honra las exoneraciones.

### Módulo de la Directora (`/directora`)
Sistema aislado y ágil, sin ataduras al padrón estructurado:
- **Autenticación por keypad**: PIN de 4 dígitos que actúa como contraseña de un usuario técnico. Bloqueo manual o por 3 minutos de inactividad.
- **Entrega Rápida de Insulina** (`director_insulin_deliveries`): registro en campo con alerta anti-duplicados de 25 días; no afecta el stock de almacén.
- **Agenda de Citas del Día**: consulta de citas confirmadas y registro de la **Nota Clínica de Evolución** (`nota_consulta`). Sin funciones administrativas, a propósito.

### Reserva de Cita Médica — SAPAM (`/agendar-cita`, `/dashboard/agenda-medica`)
- **Reserva pública sin sesión**: nombres, apellidos, CI y fecha de nacimiento.
- **Validación automática del comprobante (OCR)**: exige un aporte de **70.00 Bs**, verificando monto exacto, fecha del día y hora dentro de una ventana reciente. Si valida, la cita queda `CONFIRMADA`, se emite un `security_code` y se genera la **Ficha de Atención Médica en PDF**.
- **Rechazo y rescate por WhatsApp**: si el OCR rechaza el voucher (imagen borrosa, corte de texto, fallo técnico), la cita queda `RECHAZADA` con su `motivo_rechazo` y se instruye contactar al WhatsApp oficial. El `SUPER_ADMIN` verifica el comprobante y aprueba desde **Historial por C.I.** (`POST /appointments/{id}/approve`), quedando registrado `revisado_manualmente_por`; luego descarga la ficha para enviarla.
- **Exención por vulnerabilidad ("Caso Social")**: `POST /appointments/{id}/approve-social-case` confirma sin voucher, registrando `motivo_exencion` y `eximido_por`.
- **Separación de roles**: aprobación manual, historial por C.I. y bloqueo de fechas (`doctor_blocked_days`) son exclusivos de `SUPER_ADMIN`; la agenda del día y la nota clínica están abiertas al personal médico.

### Reportes (`/dashboard/reportes`)
Reportes gerenciales sobre beneficiarios, entregas, donaciones y complicaciones, con paginación, filtros por estado de registro y de aporte, **historial de aportes solidarios por mes** y exportación a **PDF y Excel**.

---

## 5. Esquema de Base de Datos

26 modelos en `app/models.py`. Los principales:

- **`users`**: credenciales, rol y `depto_asignado` (obligatorio solo para `RESPONSABLE_DEPARTAMENTAL`).
- **`patients`**: núcleo del expediente. Datos personales y físicos (peso, altura, IMC), ubicación, URLs de documentos, estado del registro, `estado_beneficio`, cooldown de evaluación y **las dos banderas de exoneración** con su auditoría.
- **`preregistered_beneficiaries`**: padrón precargado para validar el autorregistro.
- **`patient_states`, `patient_status_events`**: catálogo de estados e historial de transiciones.
- **`tutors`, `patient_medical`, `complication_types`, `patient_complications`, `patient_treatments`**: sub-expediente del beneficiario.
- **`monthly_contributions`**: aportes mensuales por periodo (`YYYY-MM`) con su comprobante y estado.
- **`social_evaluations`**: evaluación socioeconómica (1:1 con `patients`), con CFNR, categoría sugerida y final, alerta de fraude, evidencias y auditoría legal.
- **`donations`, `donation_lots`, `stock_movements`, `donation_allocations`, `deliveries`**: catálogo, inventario, reservas y entregas de almacén.
- **`insulin_shipments`**: envíos del coordinador nacional a los responsables departamentales.
- **`departmental_insulin_deliveries`**: entregas del responsable departamental a los beneficiarios.
- **`director_insulin_deliveries`**: entregas rápidas de la Directora, independientes del almacén.
- **`appointments`, `doctor_blocked_days`**: módulo SAPAM.
- **`audit_logs`**: bitácora genérica (`entidad`, `entidad_id`, `accion`, `payload`).
- **`gallery_photos`, `site_assets`, `site_contact_info`**: contenido del sitio público.

---

## 6. Estado de las Pruebas Automatizadas

**297 pruebas: 295 pasan, 2 fallan.** Ejecutar con `.venv/Scripts/python.exe -m pytest -q`.

### Cómo corre la suite (importante)

`tests/conftest.py` usa **`settings.DATABASE_URL` directamente**, es decir la misma base PostgreSQL de desarrollo — *no* es SQLite en memoria. No crea ni destruye el esquema, y los helpers hacen `commit()`, por lo que **los datos de prueba se acumulan de forma permanente**. Consecuencias reales:

- La base local llegó a tener ~4.900 usuarios `@test.com` frente a 178 reales.
- Endpoints que consultan toda la tabla (como el reparto automático) ven esos datos y pueden comportarse distinto según lo acumulado.
- `tests/test_exoneracion_cargo.py` limpia lo que crea, a propósito: dejar fichas con `exonerado_por_cargo` las mostraría como "al día" en el panel departamental, con el que el personal decide entregas de insulina.

Aislar la suite (base dedicada, `create_all`/`drop_all` o transacción por test con rollback) es la deuda técnica pendiente más relevante.

### Cobertura por archivo

| Archivo | Tests | Qué cubre |
|---|---:|---|
| `test_social_evaluation.py` | 104 | Motor CFNR, ramas de categorización, anti-fraude, cumplimiento legal |
| `test_departmental_roles.py` | 43 | Permisos por departamento, entregas y correcciones |
| `test_appointments.py` | 23 | SAPAM: reserva, OCR de 70 Bs, aprobación manual, caso social |
| `test_social_evaluation_extraordinaria.py` | 14 | Evaluación por imposibilidad de llenado digital |
| `test_contributions_admin.py` | 14 | Revisión y registro manual de aportes |
| `test_exoneracion_cargo.py` | 13 | Exoneración por cargo, revocación automática y auditoría |
| `test_patients_list.py` | 12 | Listado, filtros y paginación de beneficiarios |
| `test_insulin_shipments.py` | 11 | Envíos del coordinador nacional |
| `test_beneficiary_admin.py` | 11 | Herramientas administrativas sobre el padrón |
| `test_users_pagination.py` | 8 | Paginación, grupos y búsqueda en `GET /users/` |
| `test_firebase_storage.py` | 7 | Subida y borrado en Storage |
| `test_donations_deliveries.py` | 7 | Inventario, reparto trimestral y solidaridad |
| `test_self_registration.py` | 6 | Autorregistro público contra el padrón |
| `test_reports_contributions.py` | 5 | Reportes de aportes |
| `test_patient_document_upload.py` | 5 | Carga de documentos del expediente |
| `test_director_deliveries.py` | 4 | Módulo de la Directora y anti-duplicados |
| `test_contributions_ocr.py` | 4 | Lectura OCR de comprobantes |
| `test_commitment_template.py` | 4 | Plantilla de compromiso de aporte |
| `test_minor_registration.py` | 1 | Registro de menores con tutor |
| `test_tutor_multiple_children.py` | 1 | Tutor con varios representados |

### Pruebas del frontend (vitest + jsdom)

`npx vitest run` desde `vidaplena-web/`. **9 pruebas: 8 pasan, 1 falla.**

| Archivo | Tests | Qué cubre |
|---|---:|---|
| `src/__tests__/autoregistro.test.jsx` | 8 | Cierre del registro: enlace oculto en el login, URL directa muestra el aviso y no el formulario, y reversibilidad al reabrirlo. Monta `<App />` con `MemoryRouter` para probar el enrutado real; el interruptor se mockea con un objeto mutable. Se verificó con una mutación (romper el bloqueo hace fallar exactamente los 3 tests de la URL directa). |
| `src/pages/patients/__tests__/RegisterPatientPage.test.jsx` | 1 | Registro de un menor con tutor. **Falla desde antes** (`getAllByLabelText` no encuentra la etiqueta); se comprobó que falla también sobre el código original, sin relación con el autoregistro. |

### Fallos conocidos (2 en el backend)

1. **`test_beneficiary_admin.py::test_reset_registration_deletes_storage_documents`** — *test desactualizado*. Construye `SocialEvaluation(firma_digital_url=...)`, columna eliminada en la migración `20260814_000003`. El endpoint es correcto: `_collect_storage_urls` ya recolecta las cuatro evidencias vigentes. Se arregla quitando esa línea y la URL de la aserción.
2. **`test_donations_deliveries.py::test_calculate_distribution_applies_solidarity_when_shortage`** — *contaminación de datos*, no un bug de la regla. El test fija stock en 10 y espera que su beneficiario reciba 1 envase, pero `calculate_distribution` recorre **todos** los pacientes `ACTIVO` de la base; con más de 10 candidatos válidos el stock se agota antes de llegar al recién sembrado, que recibe 0. Se resuelve al aislar la suite, o haciendo el test robusto a candidatos preexistentes.

---

## 7. Deuda Técnica y Herramientas Temporales

### Endpoints temporales de QA
Rutas con privilegios destructivos creadas para el ciclo de desarrollo. Están protegidas bajo `SUPER_ADMIN`, pero deben **deprecarse o eliminarse antes de producción**:

- `DELETE /social-evaluations/debug-delete/{patient_id}` — borrado físico de una evaluación, para poder reprobar el formulario sin saturar la base.
- `PUT /patients/admin/beneficiaries/{beneficiary_id}` — corrección de errores tipográficos del padrón precargado, que de otro modo bloquean el autorregistro (exige coincidencia exacta).
- `POST /patients/admin/beneficiaries` — alta manual de una entrada del padrón.
- `DELETE /patients/admin/beneficiaries/{beneficiary_id}` — borrado de una entrada errónea del padrón.
- `POST /patients/admin/beneficiaries/{beneficiary_id}/reset-registration` — devuelve a un beneficiario al estado "No Registrado", purgando su usuario y sus documentos en Storage.

### Otros pendientes
- **Reabrir el autoregistro de beneficiarios** cuando la Fundación lo indique: `AUTOREGISTRO_HABILITADO = true` en `vidaplena-web/src/constants/features.js`. Mientras tanto, `POST /patients/self-register` sigue aceptando peticiones directas; si se quiere un cierre real y no solo de pantalla, debe responder `503` desde el backend.
- **Test del frontend roto**: `RegisterPatientPage.test.jsx` falla desde antes (ver sección 6).
- **Aislamiento de la suite de pruebas** (ver sección 6). Es la deuda de mayor impacto.
- `scripts/anonymize_local.sql` genera correos `paciente<id>@example.test`; `.test` es un TLD reservado que `email-validator` rechaza. Ya no rompe las respuestas —`UserResponse.email` es `str` y no revalida a la salida—, pero conviene usar `@example.com` para que la trampa no reaparezca.
- Warnings de deprecación pendientes: `regex=` → `pattern=` en `contributions.py`, y `class Config` → `ConfigDict` en `core/config.py` y `schemas.py`.
