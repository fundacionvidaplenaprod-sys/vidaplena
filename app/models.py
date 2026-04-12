from datetime import date, datetime
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, 
    ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, 
    func, Float
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship
from app.db import Base

class PatientState(Base):
    __tablename__ = "patient_states"
    code = Column(Text, primary_key=True)

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
        CheckConstraint("role IN ('SUPER_ADMIN','REGISTRADOR','PACIENTE')", name="ck_users_role"),
    )

    patient = relationship("Patient", back_populates="user", uselist=False)

class Patient(Base):
    __tablename__ = "patients"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), unique=True)
    ci = Column(String(32), unique=True, nullable=False)
    nombres = Column(String(120), nullable=False)
    ap_paterno = Column(String(80), nullable=False)
    ap_materno = Column(String(80))
    fecha_nac = Column(Date, nullable=False)
    
    # Datos Físicos
    peso = Column(Numeric(5, 2))
    altura = Column(Numeric(5, 2))
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
    
    allocations = relationship("DonationAllocation", back_populates="patient")
    deliveries = relationship("Delivery", back_populates="patient")


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
    ci = Column(String(32), unique=True, nullable=False)
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