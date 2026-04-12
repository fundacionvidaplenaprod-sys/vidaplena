from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, model_validator

# ==========================================
#   1. SCHEMAS DE USUARIO Y AUTENTICACIÓN
# ==========================================

class UserBase(BaseModel):
    email: EmailStr
    role: Literal["SUPER_ADMIN", "REGISTRADOR", "PACIENTE"]

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = Field(None)
    password: Optional[str] = Field(None)
    role: Optional[Literal["SUPER_ADMIN", "REGISTRADOR", "PACIENTE"]] = Field(None)
    estado: Optional[str] = Field(None)

class UserResponse(UserBase):
    id: int
    estado: str
    last_login: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class PatientActivate(BaseModel):
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[EmailStr] = None
    sub: Optional[str] = None

# ==========================================
#   2. SCHEMAS DE UTILIDAD (ESTADOS/TIPOS)
# ==========================================

class PatientStateResponse(BaseModel):
    code: str
    model_config = ConfigDict(from_attributes=True)

class ComplicationTypeResponse(BaseModel):
    code: str
    name: Optional[str] = None
    description: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class ComplicationTypeCreate(BaseModel):
    code: str = Field(..., max_length=50)
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None

class ComplicationTypeUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None

# ==========================================
#   3. SCHEMAS DE PACIENTES (SUB-MODELOS)
# ==========================================

# --- Tutor ---
class TutorBase(BaseModel):
    nombres: str = Field(..., max_length=120)
    apellidos: str = Field(..., max_length=160)
    ci: str = Field(..., max_length=32)
    parentesco: Optional[str] = Field(None, max_length=50)
    direccion: Optional[str] = None
    telef_celular: Optional[str] = Field(None, max_length=40)
    telefonos: Optional[str] = Field(None, max_length=160)
    email: Optional[EmailStr] = Field(None, max_length=160)

class TutorCreate(TutorBase):
    pass

class TutorUpdate(TutorBase):
    nombres: Optional[str] = Field(None, max_length=120)
    apellidos: Optional[str] = Field(None, max_length=160)
    ci: Optional[str] = Field(None, max_length=32)
    parentesco: Optional[str] = Field(None, max_length=50)
    direccion: Optional[str] = None
    telef_celular: Optional[str] = Field(None, max_length=40)
    telefonos: Optional[str] = Field(None, max_length=160)
    email: Optional[EmailStr] = Field(None, max_length=160)

class TutorResponse(TutorBase):
    id: int
    patient_id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- Info Médica ---
class PatientMedicalBase(BaseModel):
    tipo_diabetes: str = Field(..., max_length=50)
    fecha_diagnostico: Optional[date] = None
    hospital_tratante: Optional[str] = Field(None, max_length=120)
    peso_kg: Optional[float] = Field(None, ge=0)
    talla_cm: Optional[float] = Field(None, ge=0)
    alergias: Optional[str] = None
    tiempo_enfermedad: Optional[str] = Field(None, max_length=50)
    notas: Optional[str] = None

class PatientMedicalCreate(PatientMedicalBase):
    pass

class PatientMedicalUpdate(PatientMedicalBase):
    tipo_diabetes: Optional[str] = Field(None, max_length=50)
    fecha_diagnostico: Optional[date] = None
    hospital_tratante: Optional[str] = Field(None, max_length=120)
    peso_kg: Optional[float] = Field(None, ge=0)
    talla_cm: Optional[float] = Field(None, ge=0)
    alergias: Optional[str] = None
    tiempo_enfermedad: Optional[str] = Field(None, max_length=50)
    notas: Optional[str] = None

class PatientMedicalResponse(PatientMedicalBase):
    patient_id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- Complicaciones ---
class PatientComplicationBase(BaseModel):
    complication_code: str
    detalle: Optional[str] = None

class PatientComplicationCreate(PatientComplicationBase):
    pass

class PatientComplicationResponse(PatientComplicationBase):
    id: int
    patient_id: int
    model_config = ConfigDict(from_attributes=True)

# --- Tratamientos ---
class PatientTreatmentBase(BaseModel):
    nombre: str = Field(..., max_length=120)
    dosis_diaria: Optional[float] = 0.0
    dosis: Optional[str] = Field(None, max_length=80)
    frecuencia: Optional[str] = Field(None, max_length=80)

    @model_validator(mode="before")
    @classmethod
    def normalize_daily_dose_payload(cls, data):
        if not isinstance(data, dict):
            return data

        daily = data.get("dosis_diaria")
        if daily is not None:
            try:
                daily_value = float(daily)
            except (TypeError, ValueError):
                daily_value = 0.0
            
            data["dosis_diaria"] = daily_value

            if not data.get("dosis") and daily_value > 0:
                data["dosis"] = f"{daily_value} UI/día"

        return data

class PatientTreatmentCreate(PatientTreatmentBase):
    pass

class PatientTreatmentResponse(PatientTreatmentBase):
    id: int
    patient_id: int
    model_config = ConfigDict(from_attributes=True)


# ==========================================
#   4. SCHEMA PRINCIPAL DE PACIENTE
# ==========================================

class PatientBase(BaseModel):
    ci: str = Field(..., max_length=32)
    nombres: str = Field(..., max_length=120)
    ap_paterno: str = Field(..., max_length=80)
    ap_materno: Optional[str] = Field(None, max_length=80)
    fecha_nac: date
    genero: Optional[str] = Field(None, max_length=20)
    
    depto: Optional[str] = Field(None, max_length=80)
    municipio: Optional[str] = Field(None, max_length=80)
    zona: Optional[str] = Field(None, max_length=120)
    direccion: Optional[str] = None
    email: Optional[EmailStr] = Field(None, max_length=160)
    tel_contacto: Optional[str] = Field(None, max_length=40)
    tel_referencia: Optional[str] = Field(None, max_length=40)
    seguro_medico: Optional[str] = Field(None, max_length=100)
    peso: Optional[float] = Field(None, ge=0)
    altura: Optional[float] = Field(None, ge=0)
    tipo_sangre: Optional[str] = Field(None, max_length=10)

    url_ci_paciente: Optional[str] = None        
    url_certificado_medico: Optional[str] = None 
    url_foto_paciente: Optional[str] = None     
    url_declaracion_aporte: Optional[str] = None
    monto_aporte_comprometido: Optional[float] = None
    
    # Y los del tutor también:
    url_ci_tutor: Optional[str] = None          
    url_foto_tutor: Optional[str] = None

class PatientCreate(PatientBase):
    pass

class PatientUpdate(PatientBase):
    ci: Optional[str] = Field(None, max_length=32)
    nombres: Optional[str] = Field(None, max_length=120)
    ap_paterno: Optional[str] = Field(None, max_length=80)
    fecha_nac: Optional[date] = Field(None)
    url_declaracion_jurada: Optional[str] = None
    url_compromiso_firmado: Optional[str] = None
    peso: Optional[float] = Field(None, ge=0)
    altura: Optional[float] = Field(None, ge=0)
    tipo_sangre: Optional[str] = Field(None, max_length=10)
    tutor: Optional[TutorUpdate] = None
    medical: Optional[PatientMedicalUpdate] = None
    medical_info: Optional[PatientMedicalUpdate] = None
    treatments: Optional[List[PatientTreatmentCreate]] = None
    complications: Optional[List[PatientComplicationCreate]] = None

class PatientResponse(PatientBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int]
    edad_calc: Optional[int] = None
    estado: str

    created_at: datetime
    updated_at: datetime

    # Relaciones
    tutor: Optional[TutorResponse] = None
    medical: Optional[PatientMedicalResponse] = None
    complications: List[PatientComplicationResponse] = []
    treatments: List[PatientTreatmentResponse] = []

    # ---------------------------------------------------------
    # 1. CAMPOS OCULTOS (exclude=True)
    # ---------------------------------------------------------
    url_ci_paciente: Optional[str] = Field(default=None, exclude=True)
    url_certificado_medico: Optional[str] = Field(default=None, exclude=True)
    url_foto_paciente: Optional[str] = Field(default=None, exclude=True)
    url_declaracion_aporte: Optional[str] = Field(default=None, exclude=True)
    url_ci_tutor: Optional[str] = Field(default=None, exclude=True)
    url_foto_tutor: Optional[str] = Field(default=None, exclude=True)

    model_config = ConfigDict(from_attributes=True)
    # ---------------------------------------------------------
    # 2. CAMPOS CALCULADOS (Visible para el Frontend)
    # ---------------------------------------------------------
    @computed_field
    def tiene_ci(self) -> bool:
        return bool(self.url_ci_paciente)

    @computed_field
    def tiene_medico(self) -> bool:
        return bool(self.url_certificado_medico)

    @computed_field
    def tiene_foto(self) -> bool:
        return bool(self.url_foto_paciente)

    @computed_field
    def tiene_compromiso(self) -> bool:
        return bool(self.url_declaracion_aporte)

    @computed_field
    def tiene_tutor_docs(self) -> bool:
        # Devuelve True solo si tiene AMBOS documentos del tutor
        return bool(self.url_ci_tutor and self.url_foto_tutor)

class PatientStatusObservation(BaseModel):
    doc_key: str = Field(..., max_length=32)
    motivo: str = Field(..., min_length=1)

class PatientStatusUpdate(BaseModel):
    estado: str
    observacion_admin: Optional[str] = None
    observaciones: Optional[List[PatientStatusObservation]] = None

class PatientDetailResponse(PatientResponse):
    """
    Este esquema SÍ muestra las URLs. 
    Solo se usa en el endpoint 'get_patient' (detalle individual).
    """
    # Sobrescribimos los campos quitando el 'exclude=True'
    url_ci_paciente: Optional[str] = None
    url_certificado_medico: Optional[str] = None
    url_foto_paciente: Optional[str] = None
    url_declaracion_aporte: Optional[str] = None
    url_ci_tutor: Optional[str] = None
    url_foto_tutor: Optional[str] = None
    observaciones_doc: Optional[List[PatientStatusObservation]] = None


class PatientFullCreate(PatientCreate):
    tutor: Optional[TutorCreate] = None
    medical: Optional[PatientMedicalCreate] = None
    treatments: List[PatientTreatmentCreate] = []
    complications: List[PatientComplicationCreate] = []


# ==========================================
#   5. GESTIÓN DE DONACIONES Y APORTES 📦
# ==========================================

# --- APORTES MENSUALES (Anti-Morosos) ---
class ContributionBase(BaseModel):
    periodo: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="Formato YYYY-MM")
    fecha_pago: date
    monto: float
    url_comprobante: str

class ContributionCreate(ContributionBase):
    pass 

class ContributionUpdate(BaseModel):
    estado: Literal["ACEPTADO", "OBSERVADO", "DECLARADO"] 
    observacion_admin: Optional[str] = None


class ContributionResponse(ContributionBase):
    id: int
    patient_id: int
    periodo: str
    created_at: datetime
    estado: str
    observacion_admin: Optional[str] = None
    
    # 1. OCULTAMOS LA URL (Seguridad)
    # Aunque hereda de Base, aquí la sobrescribimos para excluirla del JSON
    url_comprobante: str = Field(exclude=True) 

    model_config = ConfigDict(from_attributes=True)

    # 2. AGREGAMOS LA BANDERA (Para la UI)
    @computed_field
    def tiene_comprobante(self) -> bool:
        return bool(self.url_comprobante)

class ContributionReviewResponse(BaseModel):
    id: int
    patient_id: int
    patient_nombre: str
    patient_ci: str
    periodo: str
    fecha_pago: date
    monto: float
    estado: Literal["DECLARADO", "OBSERVADO", "ACEPTADO"]
    observacion_admin: Optional[str] = None
    url_comprobante: str
    created_at: datetime
    updated_at: datetime

# --- PRODUCTOS (CATÁLOGO) ---
class DonationBase(BaseModel):
    tipo: Literal["MED", "INSULINA", "INSUMO"]
    nombre_generico: str = Field(..., max_length=160)
    marca: Optional[str] = Field(None, max_length=120)
    nombre_comercial: Optional[str] = Field(None, max_length=160)
    presentacion: Optional[str] = Field(None, max_length=120)
    factor_conversion: Optional[float] = Field(1.0, description="Dosis por envase") 

class DonationCreate(DonationBase):
    pass

class DonationResponse(DonationBase):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- LOTES (STOCK) ---
class DonationLotBase(BaseModel):
    lote: Optional[str] = Field(None, max_length=80)
    fecha_venc: Optional[date] = None
    cantidad_total: int = Field(..., gt=0)
    
class DonationLotCreate(DonationLotBase):
    donation_id: int 

class DonationLotResponse(DonationLotBase):
    id: int
    donation_id: int
    cantidad_disponible: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- MOVIMIENTOS DE STOCK ---
class StockMovementResponse(BaseModel):
    id: int
    lot_id: int
    tipo: Literal["ENTRADA", "SALIDA"]
    cantidad: int
    referencia: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- IMPORTACIÓN CSV ---
class DonationImportRowResult(BaseModel):
    row_number: int
    status: Literal["IMPORTED", "ERROR"]
    message: str
    donation_id: Optional[int] = None
    lot_id: Optional[int] = None

class DonationImportResponse(BaseModel):
    total_rows: int
    imported_rows: int
    error_rows: int
    results: List[DonationImportRowResult] = []

# --- ASIGNACIÓN (VALES) ---
class DonationAllocationBase(BaseModel):
    patient_id: int
    lot_id: int
    cantidad_sugerida: int 
    cantidad_ajustada: Optional[int] = None
    autor_ajuste: Optional[int] = None
    estado: Literal["BORRADOR", "CONSOLIDADO"]

class DonationAllocationCreate(BaseModel):
    lot_id: int

class DonationAllocationUpdate(BaseModel):
    cantidad_ajustada: int = Field(..., ge=0)
    estado: Optional[Literal["CONSOLIDADO"]] = None 

class DonationAllocationResponse(DonationAllocationBase):
    id: int
    patient: Optional[PatientResponse] = None
    model_config = ConfigDict(from_attributes=True)

class DonationLotDetailResponse(DonationLotResponse):
    donation: Optional[DonationResponse] = None
    allocations: List[DonationAllocationResponse] = []
    model_config = ConfigDict(from_attributes=True)

# --- ENTREGAS (CONSTANCIAS) ---
class DeliveryBase(BaseModel):
    fecha_entrega: date
    cantidad_entregada: int
    url_constancia_pdf: Optional[str] = None

class DeliveryCreate(DeliveryBase):
    allocation_id: int
    
class DeliveryResponse(DeliveryBase):
    id: int
    estado: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- DETALLES DE CÁLCULO (NO BD) ---
class ExclusionDetail(BaseModel):
    patient_id: int
    nombre_completo: str
    motivo: str

class CalculationResult(BaseModel):
    lot_id: int
    total_pacientes_compatibles: int
    total_stock_disponible: int
    total_requerido_teorico: int
    sobrante_stock: int
    
    allocations: List[DonationAllocationResponse]
    excluded_patients: List[ExclusionDetail] = []