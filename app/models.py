from datetime import date, datetime
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime,
    ForeignKey, Integer, Numeric, String, Text, Time, UniqueConstraint,
    func, Float
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship
from app.db import Base

class PatientState(Base):
    __tablename__ = "patient_states"
    code = Column(Text, primary_key=True)

class PreregisteredBeneficiary(Base):
    """
    Padrón de beneficiarios ya conocidos por la Fundación (importado de
    pacientes.csv), usado para validar el autoregistro público de pacientes.
    """
    __tablename__ = "preregistered_beneficiaries"

    id = Column(BigInteger, primary_key=True)
    nombres = Column(String(120), nullable=False)
    ap_paterno = Column(String(80), nullable=True)
    ap_materno = Column(String(80), nullable=True)
    depto = Column(String(80), nullable=True)
    matched_patient_id = Column(BigInteger, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    email = Column(postgresql.CITEXT(), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(String(20), nullable=False)
    estado = Column(String(20), nullable=False, default="ACTIVO")
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("role IN ('SUPER_ADMIN','REGISTRADOR','PACIENTE','EVALUADOR_SOCIAL')", name="ck_users_role"),
    )

    patient = relationship("Patient", back_populates="user", uselist=False)

class Patient(Base):
    __tablename__ = "patients"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), unique=True)
    ci = Column(String(32), unique=True, nullable=True)
    nombres = Column(String(120), nullable=False)
    ap_paterno = Column(String(80), nullable=False)
    ap_materno = Column(String(80))
    fecha_nac = Column(Date, nullable=False)
    
    # Datos Físicos
    peso = Column(Numeric(5, 2))
    altura = Column(Numeric(5, 2))
    imc = Column(Numeric(5, 2))
    tipo_sangre = Column(String(8))
    genero = Column(String(20), nullable=True) 
    seguro_medico = Column(String(100), nullable=True)

    # Ubicación
    depto = Column(String(80))
    municipio = Column(String(80))
    zona = Column(String(120))
    direccion = Column(Text)
    email = Column(String(160))
    tel_contacto = Column(String(40))
    tel_referencia = Column(String(40))

    # Estado del Sistema
    estado = Column(String(32), ForeignKey("patient_states.code"), nullable=False, default="PENDIENTE_DOC")
    
    # --- 📂 NUEVO: DOCUMENTACIÓN DIGITAL (LINKS FIREBASE) ---
    # Estos campos guardan la URL que nos devuelve Firebase
    url_ci_paciente = Column(String(500), nullable=True)        # Punto 5.2
    url_certificado_medico = Column(String(500), nullable=True) # Punto 5.2
    url_foto_paciente = Column(String(500), nullable=True)      # Punto 5.2
    url_declaracion_aporte = Column(String(500), nullable=True) # Punto 5.3
    monto_aporte_comprometido = Column(Numeric(12, 2), nullable=True)
    
    # Opcionales (Solo si tiene tutor)
    url_ci_tutor = Column(String(500), nullable=True)           # Punto 5.2
    url_foto_tutor = Column(String(500), nullable=True)         # Punto 5.2

    # Evaluación Socioeconómica
    exonerado_aporte = Column(Boolean, nullable=False, default=False)
    # ACTIVO | SUSPENDIDO. SUSPENDIDO = depurado por falsedad en su evaluación
    # (rechazo Nivel 2): bloquea permanentemente el envío de nuevas
    # evaluaciones hasta que un SUPER_ADMIN lo reactive explícitamente.
    estado_beneficio = Column(String(20), nullable=False, default="ACTIVO")
    # Cooldown temporal (rechazo Nivel 1, estándar): no puede volver a enviar
    # una evaluación socioeconómica hasta esta fecha.
    evaluacion_bloqueada_hasta = Column(Date, nullable=True)

    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    @property
    def edad_calc(self) -> int:
        today = date.today()
        return today.year - self.fecha_nac.year - ((today.month, today.day) < (self.fecha_nac.month, self.fecha_nac.day))

    # Relaciones
    user = relationship("User", back_populates="patient")
    tutor = relationship("Tutor", back_populates="patient", uselist=False, cascade="all, delete-orphan")
    medical = relationship("PatientMedical", back_populates="patient", uselist=False, cascade="all, delete-orphan")
    complications = relationship("PatientComplication", back_populates="patient", cascade="all, delete-orphan")
    treatments = relationship("PatientTreatment", back_populates="patient", cascade="all, delete-orphan")
    contributions = relationship("MonthlyContribution", back_populates="patient", cascade="all, delete-orphan")
    
    # NOTA: Si ya no vas a usar tablas separadas para documentos, puedes comentar o borrar estas:
    # documents = relationship("PatientDocument", back_populates="patient", cascade="all, delete-orphan")
    # pledges = relationship("VoluntaryPledge", back_populates="patient", cascade="all, delete-orphan")
    
    # passive_deletes=True: estas FK ya tienen ON DELETE CASCADE en la BD
    # (nullable=False del lado hijo), así que el ORM no debe intentar
    # desasociarlas poniendo su patient_id en NULL al borrar el paciente
    # (eso violaría la restricción NOT NULL) — se deja que la BD cascadee.
    allocations = relationship("DonationAllocation", back_populates="patient", passive_deletes=True)
    deliveries = relationship("Delivery", back_populates="patient", passive_deletes=True)
    social_evaluation = relationship("SocialEvaluation", back_populates="patient", uselist=False, passive_deletes=True)


class PatientStatusEvent(Base):
    __tablename__ = "patient_status_events"

    id = Column(BigInteger, primary_key=True)
    patient_id = Column(BigInteger, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    old_state = Column(String(32), nullable=False)
    new_state = Column(String(32), nullable=False)
    observacion = Column(Text)
    payload = Column(postgresql.JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("Patient")
    user = relationship("User")

class Tutor(Base):
    __tablename__ = "tutors"

    id = Column(BigInteger, primary_key=True)
    patient_id = Column(BigInteger, ForeignKey("patients.id", ondelete="CASCADE"), unique=True)
    nombres = Column(String(120), nullable=False)
    apellidos = Column(String(160), nullable=False)
    ci = Column(String(32), nullable=False)
    parentesco = Column(String(50), nullable=True)
    
    direccion = Column(Text)
    telefonos = Column(String(160))
    telef_celular = Column(String(40), nullable=True)
    email = Column(String(160))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    patient = relationship("Patient", back_populates="tutor")

class PatientMedical(Base):
    __tablename__ = "patient_medical"

    patient_id = Column(BigInteger, ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True)
    tipo_diabetes = Column(String(50), nullable=False)
    tiempo_enfermedad = Column(String(50))
    
    fecha_diagnostico = Column(Date, nullable=True)
    hospital_tratante = Column(String(120), nullable=True)
    peso_kg = Column(Float, nullable=True)
    talla_cm = Column(Float, nullable=True)
    alergias = Column(Text, nullable=True)

    notas = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    patient = relationship("Patient", back_populates="medical")

class ComplicationType(Base):
    __tablename__ = "complication_types"
    code = Column(Text, primary_key=True)
    name = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)

class PatientComplication(Base):
    __tablename__ = "patient_complications"

    id = Column(BigInteger, primary_key=True)
    patient_id = Column(BigInteger, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    complication_code = Column(Text, ForeignKey("complication_types.code"), nullable=False)
    detalle = Column(Text)

    patient = relationship("Patient", back_populates="complications")
    complication = relationship("ComplicationType")

class PatientTreatment(Base):
    __tablename__ = "patient_treatments"

    id = Column(BigInteger, primary_key=True)
    patient_id = Column(BigInteger, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    
    # 👋 ADIÓS a la columna 'tipo' y al CheckConstraint
    nombre = Column(String(120), nullable=False) # Aquí se guardará "Glargina", "Lispro", etc.
    
    # 👇 Reemplazamos mañana/tarde/noche por la dosis diaria total
    dosis_diaria = Column(Float, default=0.0)

    dosis = Column(String(80))
    frecuencia = Column(String(80))
    tiempo_uso_meses = Column(Integer, nullable=True)
    tiempo_uso_anios = Column(Integer, nullable=True)

    patient = relationship("Patient", back_populates="treatments")

class MonthlyContribution(Base):
    __tablename__ = "monthly_contributions"

    id = Column(BigInteger, primary_key=True)
    patient_id = Column(BigInteger, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    periodo = Column(String(7), nullable=False)
    fecha_pago = Column(Date, nullable=False)
    monto = Column(Numeric(12, 2), nullable=False)
    url_comprobante = Column(Text, nullable=False)
    estado = Column(String(20), nullable=False)
    observacion_admin = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("patient_id", "periodo", name="uq_contrib_patient_periodo"),
        CheckConstraint("estado IN ('DECLARADO','OBSERVADO','ACEPTADO')", name="ck_contrib_estado"),
    )

    patient = relationship("Patient", back_populates="contributions")

class Donation(Base):
    __tablename__ = "donations"

    id = Column(BigInteger, primary_key=True)
    tipo = Column(String(16), nullable=False)
    nombre_generico = Column(String(160))
    marca = Column(String(120))
    nombre_comercial = Column(String(160))
    presentacion = Column(String(120))
    factor_conversion = Column(Float, default=1.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("tipo IN ('MED','INSULINA','INSUMO')", name="ck_donations_tipo"),
    )

    lots = relationship("DonationLot", back_populates="donation", cascade="all, delete-orphan")

class DonationLot(Base):
    __tablename__ = "donation_lots"

    id = Column(BigInteger, primary_key=True)
    donation_id = Column(BigInteger, ForeignKey("donations.id", ondelete="CASCADE"), nullable=False)
    lote = Column(String(80))
    fecha_venc = Column(Date)
    cantidad_total = Column(Integer, nullable=False)
    cantidad_disponible = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    donation = relationship("Donation", back_populates="lots")
    allocations = relationship("DonationAllocation", back_populates="lot", cascade="all, delete-orphan")
    movements = relationship("StockMovement", back_populates="lot", cascade="all, delete-orphan")

class StockMovement(Base):
    __tablename__ = "stock_movements"

    id = Column(BigInteger, primary_key=True)
    lot_id = Column(BigInteger, ForeignKey("donation_lots.id", ondelete="CASCADE"), nullable=False)
    tipo = Column(String(10), nullable=False)
    cantidad = Column(Integer, nullable=False)
    referencia = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("tipo IN ('ENTRADA','SALIDA')", name="ck_stock_movement_tipo"),
    )

    lot = relationship("DonationLot", back_populates="movements")

class DonationAllocation(Base):
    __tablename__ = "donation_allocations"

    id = Column(BigInteger, primary_key=True)
    lot_id = Column(BigInteger, ForeignKey("donation_lots.id", ondelete="CASCADE"), nullable=False)
    patient_id = Column(BigInteger, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    cantidad_sugerida = Column(Integer, nullable=False)
    cantidad_ajustada = Column(Integer)
    estado = Column(String(20), nullable=False)
    autor_ajuste = Column(BigInteger, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("estado IN ('BORRADOR','CONSOLIDADO')", name="ck_alloc_estado"),
    )

    lot = relationship("DonationLot", back_populates="allocations")
    patient = relationship("Patient", back_populates="allocations")
    deliveries = relationship("Delivery", back_populates="allocation", cascade="all, delete-orphan")

class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(BigInteger, primary_key=True)
    allocation_id = Column(BigInteger, ForeignKey("donation_allocations.id", ondelete="CASCADE"), nullable=False)
    patient_id = Column(BigInteger, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    fecha_entrega = Column(Date, nullable=False)
    cantidad_entregada = Column(Integer, nullable=False)
    url_constancia_pdf = Column(Text)
    estado = Column(String(24), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("estado IN ('PENDIENTE_CARGA','CARGADA','VALIDADA')", name="ck_delivery_estado"),
    )

    allocation = relationship("DonationAllocation", back_populates="deliveries")
    patient = relationship("Patient", back_populates="deliveries")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True)
    actor_id = Column(BigInteger, ForeignKey("users.id"))
    entidad = Column(Text, nullable=False)
    entidad_id = Column(BigInteger, nullable=False)
    accion = Column(Text, nullable=False)
    payload = Column(postgresql.JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    actor = relationship("User")

class DirectorInsulinDelivery(Base):
    __tablename__ = "director_insulin_deliveries"

    id = Column(BigInteger, primary_key=True)
    patient_nombres = Column(String(120), nullable=False)
    patient_ap_paterno = Column(String(80), nullable=False)
    patient_ap_materno = Column(String(80), nullable=True)
    insulin_type = Column(Text, nullable=False)
    quantity = Column(Text, nullable=False)
    delivery_date = Column(Date, nullable=False, default=func.current_date())
    recorded_by_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    recorded_by = relationship("User")


class DoctorBlockedDay(Base):
    """Días en los que la doctora no puede atender (bloqueados manualmente)."""
    __tablename__ = "doctor_blocked_days"

    id = Column(BigInteger, primary_key=True)
    fecha = Column(Date, unique=True, nullable=False)
    motivo = Column(Text, nullable=True)
    created_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    creator = relationship("User")


class Appointment(Base):
    """
    Cita de atención médica agendada públicamente (SAPAM). No requiere
    cuenta de usuario: cualquier persona puede solicitar una cita indicando
    sus datos y validando una donación institucional (verificada por OCR).
    """
    __tablename__ = "appointments"

    id = Column(BigInteger, primary_key=True)
    nombres = Column(String(120), nullable=False)
    ap_paterno = Column(String(80), nullable=False)
    ap_materno = Column(String(80), nullable=True)
    ci = Column(String(32), nullable=False)
    fecha_nac = Column(Date, nullable=False)

    fecha_cita = Column(Date, nullable=False)
    hora_cita = Column(Time, nullable=False)

    estado = Column(String(20), nullable=False)  # CONFIRMADA | RECHAZADA

    url_comprobante = Column(String(500), nullable=True)
    ocr_monto_detectado = Column(Numeric(12, 2), nullable=True)
    ocr_fecha_detectada = Column(Date, nullable=True)
    ocr_hora_detectada = Column(Time, nullable=True)
    motivo_rechazo = Column(Text, nullable=True)

    security_code = Column(String(32), unique=True, nullable=True)

    # Aprobación manual (SUPER_ADMIN): cuando el OCR rechazó la cita pero el
    # paciente se comunicó por WhatsApp y se verificó que el comprobante sí
    # era válido, la doctora puede aprobar la cita manualmente.
    revisado_manualmente_por = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    revisado_manualmente_at = Column(DateTime(timezone=True), nullable=True)

    # Exención de pago ("Caso Social"): la doctora/SUPER_ADMIN puede confirmar
    # la cita sin voucher para pacientes en situación de vulnerabilidad.
    eximido_por = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    eximido_at = Column(DateTime(timezone=True), nullable=True)
    motivo_exencion = Column(Text, nullable=True)

    # Historia clínica simple: una nota de texto por cita, con fecha y autor.
    nota_consulta = Column(Text, nullable=True)
    nota_consulta_at = Column(DateTime(timezone=True), nullable=True)
    nota_consulta_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("estado IN ('CONFIRMADA','RECHAZADA')", name="ck_appointment_estado"),
    )

    nota_consulta_author = relationship("User", foreign_keys=[nota_consulta_by])
    revisado_por = relationship("User", foreign_keys=[revisado_manualmente_por])
    eximido_por_user = relationship("User", foreign_keys=[eximido_por])


class GalleryPhoto(Base):
    """Fotos de la sección Galería de la página pública."""
    __tablename__ = "gallery_photos"

    id = Column(BigInteger, primary_key=True)
    url = Column(String(500), nullable=False)
    storage_path = Column(String(500), nullable=False)
    caption = Column(String(200), nullable=True)
    orden = Column(Integer, nullable=False, default=0)
    created_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    creator = relationship("User")


class SiteAsset(Base):
    """
    Recursos únicos y reemplazables de la página pública, identificados por
    una clave fija (p.ej. los QR de pago: donaciones, compromisos, consultas).
    A diferencia de GalleryPhoto, aquí solo existe una fila activa por clave.
    """
    __tablename__ = "site_assets"

    id = Column(BigInteger, primary_key=True)
    key = Column(String(50), unique=True, nullable=False)
    url = Column(String(500), nullable=False)
    storage_path = Column(String(500), nullable=False)
    updated_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    updater = relationship("User")


class SiteContactInfo(Base):
    """
    Información de contacto de la página pública (sección Contacto).
    Fila única (singleton), gestionada desde el panel de SUPER_ADMIN.
    """
    __tablename__ = "site_contact_info"

    id = Column(BigInteger, primary_key=True)
    phone = Column(String(40), nullable=True)
    email = Column(String(160), nullable=True)
    facebook_url = Column(String(300), nullable=True)
    instagram_url = Column(String(300), nullable=True)
    whatsapp_number = Column(String(40), nullable=True)
    updated_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    updater = relationship("User")


class SocialEvaluation(Base):
    """
    Evaluación Socioeconómica y Categorización de Beneficiarios.
    Registrada por un EVALUADOR_SOCIAL o SUPER_ADMIN.
    Relación 1:1 con Patient.
    """
    __tablename__ = "social_evaluations"

    id = Column(BigInteger, primary_key=True)
    patient_id = Column(
        BigInteger, ForeignKey("patients.id", ondelete="CASCADE"),
        unique=True, nullable=False
    )
    evaluator_id = Column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    # --- Datos Demográficos ---
    departamento = Column(String(80), nullable=False)
    integrantes_hogar = Column(Integer, nullable=False)
    dependientes = Column(Integer, nullable=False, default=0)

    # --- Vivienda ---
    tipo_vivienda = Column(String(60), nullable=False)  # Propia, Alquilada, Familiar, etc.
    monto_alquiler = Column(Float, nullable=False, default=0.0)

    # --- Salud e Ingresos ---
    tiene_seguro = Column(Boolean, nullable=False, default=False)
    tipo_seguro = Column(String(80), nullable=True)
    condicion_laboral = Column(String(80), nullable=True)
    ingreso_titular = Column(Float, nullable=False, default=0.0)
    ingreso_conyuge = Column(Float, nullable=False, default=0.0)
    ingreso_otros_familiares = Column(Float, nullable=False, default=0.0)  # otros miembros del hogar

    # --- Ayuda externa y endeudamiento ---
    recibe_ayuda_otra_institucion = Column(Boolean, nullable=False, default=False)
    nombre_institucion_ayuda = Column(String(160), nullable=True)
    # Si es True, se pide el monto exacto de la cuota (monto_deuda_mensual) para el CFNR.
    tiene_deudas_comprometen_ingresos = Column(Boolean, nullable=False, default=False)
    monto_deuda_mensual = Column(Float, nullable=False, default=0.0)

    # --- Servicios del hogar (para el cálculo de CFNR) ---
    # Cada servicio se declara con su propio costo; el monto solo entra al CFNR
    # si el hogar marcó que cuenta con ese servicio.
    tiene_agua = Column(Boolean, nullable=False, default=False)
    monto_agua = Column(Float, nullable=False, default=0.0)
    tiene_luz = Column(Boolean, nullable=False, default=False)
    monto_luz = Column(Float, nullable=False, default=0.0)
    tiene_gas_domiciliario = Column(Boolean, nullable=False, default=False)
    monto_gas_domiciliario = Column(Float, nullable=False, default=0.0)
    tiene_internet = Column(Boolean, nullable=False, default=False)
    monto_internet = Column(Float, nullable=False, default=0.0)

    # --- Transporte (pasajes / movilidad, Bs/mes) ---
    monto_transporte = Column(Float, nullable=False, default=0.0)

    # --- Resultados del Motor de Categorización (CFNR) ---
    # CFNR = Ingresos Totales - (Canasta Básica + Vivienda/Servicios/Salud + Transporte + Deudas)
    ingreso_per_capita = Column(Float, nullable=False, default=0.0)  # dato de referencia
    costo_vida_estimado = Column(Float, nullable=False, default=0.0)  # total de egresos estimados
    cfnr = Column(Float, nullable=False, default=0.0)  # Capacidad Financiera Neta Residual
    categoria_asignada = Column(String(10), nullable=False)  # ALTA | MEDIA | BAJA (sugerida por el sistema)
    # Categoría que el entrevistador elige explícitamente al aprobar (puede confirmar o
    # corregir la sugerencia del sistema). Es la que realmente queda vigente para el beneficiario.
    categoria_final = Column(String(10), nullable=True)  # ALTA | MEDIA | BAJA
    estado_alerta = Column(String(50), nullable=False, default="NORMAL")  # NORMAL | REVISIÓN MANUAL URGENTE

    # --- Evidencias (URLs de Firebase Storage) ---
    foto_ci_url = Column(String(500), nullable=True)
    foto_fachada_url = Column(String(500), nullable=True)
    foto_sala_url = Column(String(500), nullable=True)
    foto_dormitorio_url = Column(String(500), nullable=True)

    # --- Auditoría y Cumplimiento Legal ---
    # Art. 130 CPE + Ley 164: Consentimiento Habeas Data
    habeas_data_accepted = Column(Boolean, nullable=False, default=False)
    # Consentimiento de uso de imágenes para auditoría interna
    imagen_consent_accepted = Column(Boolean, nullable=False, default=False)
    # Trazabilidad técnica: IP del evaluador y dispositivo al momento del envío
    ip_address = Column(String(45), nullable=True)   # IPv4 o IPv6
    user_agent = Column(String(300), nullable=True)

    # --- Revisión / Aval del Staff ---
    # PENDIENTE | APROBADO | RECHAZADO. Aprobar exonera al paciente del aporte.
    estado_revision = Column(String(20), nullable=False, default="PENDIENTE")
    reviewer_id = Column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revisado_at = Column(DateTime(timezone=True), nullable=True)
    motivo_rechazo = Column(Text, nullable=True)

    # --- Entrevista virtual (por medios externos al sistema) ---
    # Requisito previo obligatorio para poder avalar o rechazar (ver review_social_evaluation).
    entrevista_realizada = Column(Boolean, nullable=False, default=False)
    entrevista_fecha = Column(DateTime(timezone=True), nullable=True)
    entrevista_notas = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # --- Relaciones ---
    patient = relationship("Patient", back_populates="social_evaluation")
    evaluator = relationship("User", foreign_keys=[evaluator_id])
    reviewer = relationship("User", foreign_keys=[reviewer_id])