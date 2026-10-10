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
- **Corrección del periodo (gestión) de un aporte** (`PUT /contributions/{id}/periodo`, botón *Corregir periodo* en Revisión de Aportes): el beneficiario elige el mes al subir su voucher y a menudo se equivoca (p. ej. sube en octubre un depósito de septiembre). **Solo `SUPER_ADMIN`** puede reasignarlo —el `REGISTRADOR` puede validar vouchers pero no cambiar su periodo, porque el periodo decide quién figura "al día" y quién entra al reparto de insulina—. Valida formato `AAAA-MM`, rechaza con 409 si el beneficiario ya tiene un aporte en el periodo destino (restricción `uq_contrib_patient_periodo`) y deja registro en `audit_logs` (`CAMBIO_PERIODO_APORTE`, con periodo anterior y nuevo). No altera el estado del aporte ni renombra el archivo del voucher en Storage (la ruta conserva el periodo original declarado).
- **Complicaciones médicas** (catálogo administrable) y **tratamientos** de insulina basal/rápida y material.
- **Tutor legal** para menores de edad y beneficiarios con capacidades diferentes (un tutor puede tener varios representados).
- **Activación manual por personal** (`PUT /patients/{id}/activate`, botón "Aprobar y Crear Usuario" en la ficha): con el autoregistro cerrado, `SUPER_ADMIN`/`REGISTRADOR` siguen pudiendo dar de alta a un beneficiario y generarle credenciales (email del paciente o del tutor si es menor; contraseña inicial = su C.I.), dejando `estado = PENDIENTE_DOC` para que pueda subir documentos al loguearse en `/mi-portal`.

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
El endpoint de beneficiarios activos entrega además el **tratamiento de insulina prescrito** de cada uno (tipo y dosis diaria, desde `patient_treatments`); en pantalla solo lo muestra el **Coordinador Nacional**, para planificar los envíos según lo que cada beneficiario realmente necesita en vez de un catálogo fijo — el Responsable Departamental recibe el mismo dato en el payload, pero la pantalla no se lo muestra hoy.

**Reparto automático desde almacén** (`POST /donations/calculate-distribution/{lot_id}`): calcula envases para un horizonte de 90 días (`math.ceil`), excluye morosos sin aporte `ACEPTADO` del periodo y, ante escasez, aplica la **regla de solidaridad** reduciendo a 1 envase por beneficiario. Este filtro conserva su comportamiento histórico y **no** honra las exoneraciones.

> **Estado: trabajo local, NO incluido en `main` ni desplegado.** Por decisión de la Fundación el reparto guardado del almacén (simular / borrador / consolidar sobre los lotes cargados) no se aplica por ahora para no tocar lo que ya funciona. El motor y las reglas son los mismos que usa el *reporte de distribución* de más abajo, que sí está en `main`.

**Reparto global de la donación** (`POST /donations/distribution/{simulate|calculate|consolidate}`, solo `SUPER_ADMIN`; panel «Reparto global de la donación» en `DonationsWarehousePage`): reparte **todos los lotes a la vez** en vez de uno por uno, para un horizonte de **60 días** (antes 90). El motor es una función pura, `app/core/insulin_distribution.py::plan_distribution`, sin base de datos —los endpoints solo traducen BD ↔ motor—, y sus reglas son:
- **Todo en UI**, convirtiendo a envases enteros al final. El factor de conversión del producto son las UI por envase (Toujeo U300 1,5 ml = 450 UI, Lantus 3 ml = 300 UI, Tresiba U200 3 ml = 600 UI).
- **Reserva del 10 % global** del total de UI. Se cubre primero con el sobrante de cada insulina (lo que nadie necesita) y, si no alcanza, el resto se descuenta proporcionalmente del stock necesario. Se aparta en envases enteros de los lotes que vencen más tarde y el reparto nunca los toca.
- **Orden de prioridad: menores de 18 → adultos con diabetes tipo 1 → resto.** Cada grupo se cubre completo antes de pasar al siguiente; si dentro de un grupo falta stock, se reparte en proporción a la necesidad. El tipo de diabetes es texto libre en `patient_medical.tipo_diabetes` («Tipo 1», «TIPO 1»…); `is_type1_diabetes()` lo normaliza (mayúsculas, acentos, «tipo I», «DM1»). En los datos cargados, 72 de los 88 activos con insulina son tipo 1, así que el grupo prioritario es la mayoría. Los adultos tipo 1 **no** heredan la preferencia de Lantus, que sigue siendo solo de menores.
- **Lantus reservado a menores** dentro de la glargina (`MINOR_PREFERRED_BRANDS`): los menores lo toman primero y los adultos lo dejan para el final. La preferencia se decide por la marca del lote porque el tratamiento del paciente solo guarda el principio activo, no la marca.
- **FEFO**: dentro de cada preferencia se usa primero el lote que vence antes. Lotes vencidos, ya consolidados o sin nombre válido en el catálogo se excluyen y se informan.
- **Redondeo a envases enteros sin quitarle stock a otros**: los **menores y adultos tipo 1** reciben su tratamiento completo de inmediato, con el último envase incluido. Para el **resto de adultos** (y sus sustituciones) primero se entregan los envases enteros que caben dentro de la necesidad (mínimo uno) y el envase extra que completa el resto se aplaza a una **fase 3** que corre al final, en orden de prioridad y solo con el stock libre; así el redondeo hacia arriba ya no deja sin stock a otros pacientes ni a las sustituciones. Además, el último envase se elige para que **sobre lo mínimo** (un pen de 300 UI en vez del vial de 10 ml de 1.000 UI que vencía antes); el vencimiento (FEFO) sigue mandando para los envases completos. Con stock de sobra el resultado es el mismo que antes. En la simulación con todos al día, la falta de glulisina bajó de 18.910 a 11.410 UI y la de regular de 14.520 a 7.020 UI.
- **Sustituciones** (`DEFAULT_SUBSTITUTIONS`, `Substitution` en el motor), siempre en la **fase 2**: después de que todos recibieron su propia insulina (quien usa la insulina sustituta va primero) y solo con stock libre, así que **la reserva no se toca**. Son tres: **glargina → detemir**, solo adultos y de **cambio completo** (un adulto recibe toda su glargina o todo su tratamiento en detemir, nunca una mezcla; se recorre por id y entra quien quepa entero, por lo que un adulto con poca necesidad aún puede usar la glargina que dejó uno que no cupo; si el detemir no alcanza, la glargina que sobre se reparte parcialmente entre los adultos sin cubrir y los menores nunca pasan a detemir); **glulisina → aspart**, para menores y adultos, completando solo lo que falta; y **regular → lispro**, para todos. Entre quienes sustituyen se respeta el orden de prioridad (menores, tipo 1, resto). Los factores son **1 UI por cada UI, provisionales** y pendientes de validación médica; se cambian en un solo lugar. La respuesta marca la línea con `sustituto` y el panel muestra «+ Detemir» y la columna «Sustitución».
- Mismos filtros de elegibilidad que el reparto por lote (ACTIVO + aporte al día o exonerado, vía `is_patient_current_on_contribution`). Horizonte 60 días.
- `simulate` no escribe nada; `calculate` reemplaza los borradores (`BORRADOR`) de los lotes considerados, y `consolidate` consolida de una vez todos los lotes con borrador (reutiliza `_apply_consolidation`, extraído de `consolidate_lot`).

**No hay más sustituciones que esas tres**: el resto de pacientes recibe solo la insulina que usa. El resumen «Por insulina» muestra cuánto falta de cada una, que es justo donde servirá la **tabla de equivalencias** (pendiente, decisión de la Fundación: los factores clínicos los valida el equipo médico); las reglas actuales son sus primeras entradas y el motor ya acepta una lista de `Substitution`. Simulación con la donación del Excel y los pacientes cargados a 60 días (base sin cambios, «como si todos estuvieran al día»): **todos los tratamientos quedan cubiertos**. A 14 pacientes con glulisina (10 adultos y 4 menores; 7.500 UI de stock frente a 20.250 de necesidad) se les dio aspart (15.500 UI) y a 6 adultos con insulina regular, lispro (7.800 UI). La glargina alcanza sola y no hace falta detemir. Con 90 días la glargina quedaba corta: 5 adultos pasaron enteros a detemir (ninguno mezclado), aunque el detemir libre solo cubrió una parte de su necesidad. Ojo con la reserva global: como se cubre primero con sobrantes, **las insulinas escasas pueden quedar con reserva cero** (con 90 días, en la simulación con el Excel de donación, la glargina agotó todo su stock y la reserva salió de degludec, detemir, NPH y premezclas; con 60 días la glargina sí conserva 7.800 UI, pero la glulisina y la regular siguen sin reserva). Si se prefiere un 10 % por cada insulina, es un cambio acotado en `_split_reserve`.

El **catálogo de nombres corregido** (premezclas aparte, Protaphane como NPH, Actraphane/NovoMix) vive en `app/core/insulin_catalog.py` y lo usa el reporte. `donations.py` (almacén) **conserva por ahora el catálogo anterior**, donde «Humalog Mix» o «Aspart bifásica» se clasifican como Lispro/Aspart y «Humana bifásica» no se reconoce al importar CSV; se corregirá al aplicar el reparto global.


**Reporte de distribución desde el Excel** (`POST /reports/insulin-distribution`, solo `SUPER_ADMIN`; pestaña «Distribución de insulina» en `/dashboard/reportes`): es la vía que se usa por ahora para planificar el reparto de una donación. Recibe el `.xlsx` con la insulina que llegó y calcula el reparto con **exactamente las mismas reglas** del motor (60 días, menores y tipo 1 primero, Lantus para menores, reserva global del 10 %, sustituciones y redondeo), pero:
- **No depende del almacén ni guarda nada**: los lotes salen del Excel, no de `donation_lots`; no crea asignaciones, no descuenta stock y no escribe auditoría. Se puede repetir con cualquier lista.
- **Considera a los beneficiarios `ACTIVO`, `PENDIENTE_DOC` y `HABILITADO`** con insulina cargada, **sin exigir aporte al día** (el reparto guardado sigue exigiéndolo, solo ACTIVO). Quedan fuera INACTIVO, NO_REGISTRADO, etc.
- **Excel**: columnas `CANTIDAD`, `PRODUCTO`, `TIPO DE INSULINA`, `PRESENTACIÓN`, `CONCENTRACIÓN` y, opcionales, `FECHA VENCIMIENTO` y `NRO LOTE` (sin importar mayúsculas ni acentos). UI por envase = ml × UI/ml (Toujeo 1,5 ml U300 = 450 UI). Una fila con problemas (cantidad no entera, insulina fuera del catálogo, presentación o fecha ilegible, lote vencido) se **lista y se omite sin detener a las demás**. Lectura en `app/core/donation_excel.py` con `openpyxl` (importado de forma diferida; máx. 5 MB y 5.000 filas).
- **Salida**: por beneficiario (CI, estado, depto, edad, tipo de diabetes, grupo de prioridad) qué insulina recibe, cuánto, **qué envases y de qué lote/vencimiento**, y si se le da un sustituto; resumen por insulina (stock, necesidad, reserva, falta, sobra), reserva apartada por lote, y filas omitidas. Se exporta a **PDF** y a **Excel** (4 hojas: Beneficiarios, Por insulina, Reserva, Donación).
- **Independiente del almacén**: `reports.py` no importa `donations.py`. Comparte el motor (`app/core/insulin_distribution.py`), el catálogo (`insulin_catalog.py`) y los armadores de respuesta (`distribution_service.py`) con el reparto global local, y hay una prueba que impide que el reporte vuelva a depender del módulo del almacén. Si falta `openpyxl` en el servidor, solo este reporte responde con un error claro; el resto de la API arranca normal.

**Prioridad entre insulinas**: el motor recorre los grupos en orden (menores → adultos tipo 1 → resto) y **cada grupo completa todo su tratamiento —insulina propia y sustituciones— antes de que el siguiente toque el stock**. Antes la prioridad solo valía dentro de cada insulina: los usuarios de aspart de cualquier grupo agotaban el aspart antes de que un menor con glulisina pudiera usarlo como sustituto (11 menores quedaban entre 50 % y 86 %, faltándoles solo 2.640 UI). Con el Excel y los 199 beneficiarios reales, los menores pasaron de 11 tratamientos incompletos a 0; el costo lo asumen los de menor prioridad (adultos «otros»: 36 % → 18 % de cobertura).

**Una sola insulina de cada grupo**: los beneficiarios usan como máximo una insulina **rápida** (lispro, aspart, glulisina, regular) y una **basal / intermedia / premezcla** (glargina, protamina, NPH, detemir, degludec). Si la ficha trae dos insulinas *distintas* del mismo grupo es un error de carga y **el reparto usa una sola** (`resolve_group_choices`), elegida así: (1) la que **tiene stock** en la donación, con más holgura frente a la demanda de quienes no tienen duda; (2) si ninguna tiene stock propio, la que se **cubre con una sustitución conocida** (respetando que glargina → detemir es solo para adultos); (3) si ninguna, la de **mayor dosis registrada** (queda como faltante). La disponibilidad se mide sobre el 90 % del stock (sin la reserva) y se va descontando a medida que se decide, en orden de prioridad (menores → adultos tipo 1 → resto), de modo que dos fichas dudosas no se disputan la misma insulina. La dosis que se usa es la de la insulina elegida (con el tope de menores si corresponde). Después de elegir corren las sustituciones de siempre. La ficha **aparece igual en «Fichas por corregir»** del reporte (qué trae, cuál se usó y por qué; también en PDF y en la hoja «Por corregir» del Excel) para que se deje una sola en el padrón. La misma insulina cargada dos veces se suma y no es conflicto; las sustituciones nunca salen de su grupo. En los datos reales hay 11 fichas en conflicto (10 beneficiarios, 2 de menores) y las 10 reciben reparto: p. ej. aspart + lispro → lispro, degludec + NPH → degludec, glargina + protamina → protamina, glargina + NPH → glargina (cubierta con detemir si falta). **Una premezcla nunca sustituye a una basal** (`PREMIX_INSULINS` = protamina / Mix / bifásicas): si la ficha trae una premezcla junto a una basal o intermedia, compiten solo las basales aunque la premezcla tenga más stock (si la basal no tiene stock ni sustituto queda como faltante) y la ficha se avisa con «premezcla descartada». Además ninguna regla de sustitución puede tener una premezcla como destino (el motor rechaza esa configuración). Una premezcla registrada sola sí se reparte como insulina propia. En los datos reales las dos fichas «glargina + protamina» quedaron en glargina (cubierta con detemir) y ninguna premezcla se entregó a quien no la usa.

**Garantía 100 % sin pasar de 120 % (menores y adultos tipo 1)**: para estos grupos el motor busca, entre las combinaciones de envases disponibles (hasta 4 tamaños distintos: 300, 450, 900, 1.000 UI…), la que cubre **al menos el 100 %** con el **menor exceso** (`PRIORITY_MIN_COVERAGE` / `PRIORITY_MAX_COVERAGE`, `_best_pens`). Primero se prueba solo con la marca preferida del grupo (Lantus para menores); si ahí no hay una combinación dentro de 100-120 %, se amplía a todas las marcas. **Si ninguna combinación cabe en la ventana —un pen de 300 UI no se parte— gana la garantía del 100 %** y el reporte avisa («pasa de 120 % (envase entero)», contador `prioritarios_sobre_120`). Los demás adultos no tienen ventana, pero reciben igual la combinación de menor exceso.

**Tope de dosis para menores de 18**: en **glargina, lispro, glulisina, aspart, detemir y degludec** (solo esas) la dosis diaria usada en el cálculo no pasa de **30 UI/día por insulina**, sin importar la dosis registrada (`MINOR_DAILY_CAP_UI`, `MINOR_CAPPED_INGREDIENTS`). NPH, premezclas y regular no se limitan; adultos y adultos tipo 1 tampoco. El reporte muestra la dosis registrada y la usada («48 → 30 UI/día», «dosis limitada») y las exporta. En los datos reales el tope se aplicó a 7 tratamientos (incluido un menor de 1 año con 36 UI/día de glargina: es un registro válido, y el tope lo limita igual a 30). Se interpretó **por línea de tratamiento**: cada insulina registrada del menor tiene su propio tope de 30 UI/día; como ahora solo puede tener una de cada grupo, el máximo es 30 de rápida + 30 de basal (60 UI/día). La otra lectura posible es un **total de 30 UI/día entre todas sus insulinas**: afectaría a la mayoría de los menores con basal + rápida. **Confirmado por la Fundación: el tope se mantiene por insulina** (30 UI/día en cada una de las seis). Además, ninguna regla cambia degludec por NPH ni al revés: las únicas sustituciones son glargina → detemir (adultos), glulisina → aspart y regular → lispro, y hay pruebas que lo garantizan.

**Resultado de la ventana en los datos reales** (199 beneficiarios, Excel de la donación): 26 tratamientos prioritarios siguen sobre 120 %: 12 por el **vial de 10 ml** (1.000 UI, 7.140 UI de más; se asigna cuando los pens ya se agotaron) y 14 porque la necesidad no calza con envases de 300/450 UI (1.950 UI de más). El exceso total de menores y tipo 1 bajó de ~18.600 a ~15.900 UI.

**Cómo leer la cobertura** (el reporte lo explica en pantalla y agrega «días cubiertos»): es lo recibido ÷ lo necesario para 60 días. *Menos de 100 %* = no alcanzó el stock de esa insulina ni de su sustituto. *Más de 100 %* = solo el envase entero: un pen de 300 UI no se parte, así que a quien le faltan 360 UI se le dan 2 pens (600 UI, 166 % ≈ 100 días). En los datos reales el exceso de los grupos prioritarios suma ~18.600 UI (≈4,6 % del stock) y casi todo (17.600 UI) es de insulinas que ya tienen falta; es el costo de garantizar tratamiento completo. Un menor puede recibir un vial de 10 ml si es el único envase libre (4 casos en la simulación): el sistema no conoce el dispositivo (pen vs. jeringa) del paciente.

**Qué mirar en el resultado**: la reserva global se calcula *antes* de las sustituciones y se cubre primero con lo que parece sobrante; por eso puede quedar apartada insulina que luego haría falta como sustituto (p. ej. lispro reservada mientras pacientes con regular quedan sin cobertura). Es un ajuste acotado en `_split_reserve` si se decide anticipar las sustituciones.
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

**Morosos** (pestaña *Morosos* y tarjeta del Resumen Operativo; `GET /reports/morosos`): beneficiarios **ACTIVOS** sin aporte **ACEPTADO** en el periodo evaluado, que por defecto es el **mes anterior** (evaluar el mes en curso marcaría como deudor a casi todos en sus primeros días). Excluye a los exonerados, tanto por vulnerabilidad como por cargo, y **nadie debe un periodo anterior a su activación**: quien queda activo en octubre paga desde octubre y no es moroso de septiembre. El ingreso es el **primer momento en que el beneficiario estuvo `ACTIVO`** (cuando se aprueban sus documentos), tomado de `patient_status_events` —el primer evento que lo muestra ya activo, sea por entrar a `ACTIVO` o por salir de él—, de modo que reabrirlo y volver a activarlo no reinicia lo que debe. Para los antiguos sin ese evento se usa, en orden, la creación de su usuario y la de su ficha; ninguna de las dos sirve como regla principal (la ficha de un precargado del padrón existe meses antes de registrarse —251 fichas `NO_REGISTRADO` de julio en la réplica— y el usuario se genera antes de aprobar los documentos). El mes se toma en hora de Bolivia. Un aporte `DECLARADO` u `OBSERVADO` sigue contando como no pagado, pero el listado distingue *no registró aporte* / *pendiente de revisión* / *observado* para separar a quien no pagó de quien pagó y falta validar. Permite elegir el mes y filtrar por departamento (comparación tolerante a mayúsculas y tildes), e incluye el celular para la cobranza; exporta a PDF y Excel. La tarjeta del resumen y el listado usan **la misma función** (`calcular_morosos` en `reports.py`), así que no pueden discrepar. Antes, la tarjeta "Inactivos / morosos" mostraba `total − activos − pendientes`, un resto aritmético que no miraba aportes: no detectaba a ningún deudor real entre los activos. Esa tarjeta se separó en *Morosos*, *Inactivos* y *Otros estados* (habilitados, pendientes de aporte, no registrados).

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

**459 pruebas (458 pasan)** en lo que está en `main` (el trabajo local del almacén agrega `test_global_distribution.py` y modifica `test_donations_deliveries.py`). Un fallo es constante (test desactualizado) y el otro es intermitente —depende del volumen acumulado en la base compartida—, así que el conteo exacto de "pasan/fallan" varía entre corridas; ver el detalle de ambos más abajo. Ejecutar con `.venv/Scripts/python.exe -m pytest -q`.

### Cómo corre la suite (importante)

`tests/conftest.py` usa **`settings.DATABASE_URL` directamente**, es decir la misma base PostgreSQL de desarrollo — *no* es SQLite en memoria. No crea ni destruye el esquema, y los helpers hacen `commit()`, por lo que **los datos de prueba se acumulan de forma permanente**. Consecuencias reales:

- La base local llegó a tener ~4.900 usuarios `@test.com` frente a 178 reales.
- Endpoints que consultan toda la tabla (como el reparto automático) ven esos datos y pueden comportarse distinto según lo acumulado.
- `tests/test_exoneracion_cargo.py` limpia lo que crea, a propósito: dejar fichas con `exonerado_por_cargo` las mostraría como "al día" en el panel departamental, con el que el personal decide entregas de insulina.

**Base de pruebas aparte (recomendado)**: la suite lee `DATABASE_URL` del entorno, así que se puede correr contra una copia sin tocar tus datos: `CREATE DATABASE vidaplena_test TEMPLATE vidaplena;` y luego `DATABASE_URL=postgresql+asyncpg://…/vidaplena_test pytest -q`. Los tests nuevos de distribución además corren dentro de una transacción que se revierte. Crear la base de pruebas con `alembic upgrade head` **no sirve hoy**: faltan migraciones (ver «Otros pendientes»).

### Cobertura por archivo

| Archivo | Tests | Qué cubre |
|---|---:|---|
| `test_social_evaluation.py` | 104 | Motor CFNR, ramas de categorización, anti-fraude, cumplimiento legal |
| `test_departmental_roles.py` | 46 | Permisos por departamento, entregas, correcciones y visibilidad de tratamientos |
| `test_appointments.py` | 23 | SAPAM: reserva, OCR de 70 Bs, aprobación manual, caso social |
| `test_social_evaluation_extraordinaria.py` | 14 | Evaluación por imposibilidad de llenado digital |
| `test_contributions_admin.py` | 14 | Revisión y registro manual de aportes |
| `test_contribution_periodo.py` | 12 | Corrección de periodo: solo SUPER_ADMIN, 409 por choque, formato, auditoría |
| `test_morosos.py` | 30 | Definición de moroso, exonerados, motivos, filtro por depto, tarjeta == listado |
| `test_patient_status_endpoints.py` | 4 | `validate` y `change-status`: responden con la ficha y dejan evento de estado |
| `test_insulin_distribution_engine.py` | 83 | Motor de reparto (puro): reserva 10 %, menores primero, Lantus para menores, FEFO, UI vs envases, escasez proporcional, faltantes, sustituciones (glargina → detemir solo adultos y con cambio completo, con primer ajuste y rescate si el detemir no alcanza; glulisina → aspart para menores y adultos; regular → lispro; siempre después de quienes usan la insulina sustituta, sin gastar la reserva, con factor y desactivables), prioridad de diabetes tipo 1 (después de menores, antes del resto, sin la preferencia de Lantus), una sola insulina por grupo (elige la que tiene stock, luego la cubierta por sustitución, luego la de mayor dosis; decide en orden de prioridad y descuenta lo comprometido), lectura del texto libre «Tipo 1» horizonte de 60 días y redondeo (último envase con la menor sobra, envase extra aplazado para el resto de adultos, prioritarios completos). Se verificó con mutaciones (romper cada regla hace fallar su test) |
| `test_global_distribution.py` *(local, no incluido en main)* | 8 | Endpoints del reparto global: simular no escribe, guardar es idempotente, consolidación masiva, lotes vencidos/consolidados, morosos excluidos, solo SUPER_ADMIN, el adulto que recibe detemir mientras el menor no, y el adulto tipo 1 servido completo antes que otro adulto. **Corre dentro de una transacción que se revierte** (no ensucia la base compartida) |
| `test_donation_excel.py` | 7 | Lectura del Excel de la donación (pura): UI por envase, encabezados con otro formato, columnas opcionales, filas con error sin detener las demás, archivo inválido |
| `test_insulin_distribution_report.py` | 9 | Reporte desde el Excel: considera ACTIVO/PENDIENTE_DOC/HABILITADO sin exigir aporte, aplica las reglas y muestra lote/vencimiento, lista filas vencidas o con error, no escribe nada, rechaza archivos inválidos, solo SUPER_ADMIN. Corre en transacción revertida; se verificó con 5 mutaciones |
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

`npx vitest run` desde `vidaplena-web/`. **14 pruebas: 13 pasan, 1 falla** en `main` (+ 7 del panel del almacén, local).

| Archivo | Tests | Qué cubre |
|---|---:|---|
| `src/__tests__/autoregistro.test.jsx` | 8 | Cierre del registro: enlace oculto en el login, URL directa muestra el aviso y no el formulario, y reversibilidad al reabrirlo. Monta `<App />` con `MemoryRouter` para probar el enrutado real; el interruptor se mockea con un objeto mutable. Se verificó con una mutación (romper el bloqueo hace fallar exactamente los 3 tests de la URL directa). |
| `src/__tests__/globalDistributionPanel.test.jsx` *(local, no incluido en main)* | 7 | Panel de reparto global: estado inicial, simulación (no guarda), filtro de menores, que «Guardar borrador» y «Consolidar todo» exijan confirmación antes de llamar a la API, que se vea la sustitución por detemir y la etiqueta/filtro de tipo 1. |
| `src/__tests__/insulinDistributionReport.test.jsx` | 5 | Reporte de distribución desde el Excel: exige archivo, muestra beneficiarios por estado con lote, filtros (menores, tipo 1, sin cubrir, con sustituto, estado, búsqueda por nombre/CI), filas omitidas y errores del servidor |
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
- **Las migraciones de Alembic no reproducen el esquema**: 9 columnas existen en los modelos y en producción pero no en ninguna migración (`patients.genero`, `patients.seguro_medico`, `patient_medical.fecha_diagnostico`, `.hospital_tratante`, `.peso_kg`, `.talla_cm`, `.alergias`, `tutors.parentesco`, `tutors.telef_celular`). Una base nueva creada con `alembic upgrade head` queda rota (los inserts de pacientes fallan). Hay que escribir una migración idempotente (`ADD COLUMN IF NOT EXISTS`) antes de montar un entorno desde cero.
- **`openpyxl==3.1.5` es dependencia nueva** (`requirements.txt`): el servidor debe reconstruir la imagen para que el reporte de distribución lea el Excel; si falta, solo ese reporte responde con error claro y el resto de la API arranca normal.
- **Tabla de equivalencias entre insulinas** (sustitución cuando una se agota, dentro de la misma clase: basales, NPH, rápidas, premezclas). Aplazada a pedido de la Fundación; los factores de dosis los debe validar el equipo médico. Las tres reglas actuales (glargina → detemir, glulisina → aspart, regular → lispro) son su primera versión y el motor ya reporta el faltante por insulina. Cuestiones por decidir: ¿la reserva global puede dejar a una insulina escasa sin respaldo? y si Toujeo (U300) es apto para menores.
- **Reparto global sin datos reales todavía**: se probó con el Excel de la donación contra una población sintética y con los datos de la base de desarrollo, no con los pacientes definitivos. Antes de usarlo hay que importar el Excel como CSV (`factor_conversion` = ml × UI/ml de cada producto) y revisar la simulación.
- **Reabrir el autoregistro de beneficiarios** cuando la Fundación lo indique: `AUTOREGISTRO_HABILITADO = true` en `vidaplena-web/src/constants/features.js`. Mientras tanto, `POST /patients/self-register` sigue aceptando peticiones directas; si se quiere un cierre real y no solo de pantalla, debe responder `503` desde el backend.
- ~~`window.confirm()` nativo en acciones críticas~~ — **resuelto.** `window.confirm()`/`window.prompt()` pueden devolver `false` sin mostrarse nunca (Chrome los suprime tras varios diálogos seguidos si se marca "evitar más cuadros", navegadores embebidos/webviews, iframes sin `allow="modals"`, herramientas de automatización), y cuando eso pasa el botón que los dispara parece no hacer nada: sin red, sin error, sin aviso. Se reemplazaron los 13 usos en los 9 archivos que los tenían (`PatientDetailsPage.jsx` —2—, `Sidebar.jsx`, `BeneficiaryNamesPage.jsx`, `DoctorAgendaPage.jsx` —2, una con texto libre—, `GalleryManagementPage.jsx`, `SocialEvaluationsReviewPage.jsx` —2—, `UsersManagementPage.jsx` —3—, `RegisterPatientPage.jsx`, `DonationsWarehousePage.jsx`) por `components/ui/ConfirmModal.jsx`, un modal propio cuya visibilidad depende solo del estado de React y nunca de si el navegador quiere mostrar un diálogo; admite opcionalmente un campo de texto para reemplazar también a `window.prompt()`. Verificado con build limpio, la suite de vitest sin regresiones, y dos recorridos end-to-end en navegador (logout desde `Sidebar`; recálculo de distribución con asignaciones `BORRADOR` existentes en `DonationsWarehousePage`, que exigió partir `handleCalculate` en dos pasos para intercalar la confirmación). El incidente que motivó esta auditoría terminó explicándose por otra causa (correos duplicados por reintentos), pero la fragilidad de `window.confirm()` era real e independiente de eso.
- **Test del frontend roto**: `RegisterPatientPage.test.jsx` falla desde antes (ver sección 6).
- **Aislamiento de la suite de pruebas** (ver sección 6). Es la deuda de mayor impacto.
- `scripts/anonymize_local.sql` genera correos `paciente<id>@example.test`; `.test` es un TLD reservado que `email-validator` rechaza. Ya no rompe las respuestas —`UserResponse.email` es `str` y no revalida a la salida—, pero conviene usar `@example.com` para que la trampa no reaparezca.
- Warnings de deprecación pendientes: `regex=` → `pattern=` en `contributions.py`, y `class Config` → `ConfigDict` en `core/config.py` y `schemas.py`.
