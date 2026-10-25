// Registro Asistido por Situación Excepcional: listas y etiquetas. Deben coincidir con los
// Literal de app/schemas.py (AssistedEntidadTipo, AssistedReferenteVinculo, ...).

export const ENTIDAD_TIPOS = [
  { value: 'CENTRO_ACOGIDA', label: 'Centro de acogida' },
  { value: 'RECINTO_PENITENCIARIO', label: 'Recinto penitenciario' },
  { value: 'CENTRO_REINTEGRACION', label: 'Centro de reintegración social' },
  { value: 'HOGAR_ALBERGUE', label: 'Hogar / albergue' },
  { value: 'ASILO_LARGA_ESTANCIA', label: 'Asilo / centro de larga estancia' },
  { value: 'CENTRO_ESPECIALIZADO', label: 'Centro especializado' },
  { value: 'CASA_REFUGIO', label: 'Casa de acogida / refugio' },
  { value: 'COMUNIDAD', label: 'Comunidad de difícil acceso' },
  { value: 'SITUACION_CALLE', label: 'Situación de calle' },
  { value: 'OTRO', label: 'Otro' },
];

// Vínculo de la persona referente con el beneficiario. Es obligatorio y no admite «no se sabe».
export const REFERENTE_VINCULOS = [
  { value: 'FAMILIAR', label: 'Familiar' },
  { value: 'CONOCIDO', label: 'Conocido/a' },
  { value: 'REFERIDO_POR_TERCEROS', label: 'Referido/a por terceros' },
  { value: 'AMISTAD', label: 'Amistad' },
];

export const TIPOS_DIABETES = ['Tipo 1', 'Tipo 2', 'Gestacional', 'Otra'];

export const RANGOS_EDAD = [
  { value: '0-11', label: 'Niño/a (0 a 11 años)' },
  { value: '12-17', label: 'Adolescente (12 a 17 años)' },
  { value: '18-59', label: 'Adulto (18 a 59 años)' },
  { value: '60+', label: 'Adulto mayor (60 años o más)' },
];

// Art. 23 del reglamento. La pérdida de contacto o el cambio de institución NO son causales de cese.
export const CESE_CAUSAS = [
  { value: 'FALLECIMIENTO', label: 'Fallecimiento' },
  { value: 'RENUNCIA', label: 'Renuncia expresa de la persona' },
  { value: 'SIN_NECESIDAD', label: 'Ausencia de necesidad de insulina' },
  { value: 'TRASLADO_REGIMEN_ORDINARIO', label: 'Traslado al registro ordinario' },
  { value: 'FALTA_GRAVE', label: 'Falta grave comprobada (con debido proceso)' },
];

export const RECEPTOR_TIPOS = [
  { value: 'PERSONA', label: 'La propia persona' },
  { value: 'PERSONA_REFERENTE', label: 'Persona referente' },
  { value: 'PERSONAL_SALUD', label: 'Personal de salud de la entidad' },
  { value: 'OTRO_MEDIO', label: 'Otro medio logístico seguro' },
];

export const CONSTANCIA_TIPOS = [
  { value: 'FIRMA', label: 'Firma' },
  { value: 'HUELLA', label: 'Huella' },
  { value: 'CONFIRMACION', label: 'Confirmación del receptor' },
  { value: 'TESTIMONIO_PERSONAL', label: 'Testimonio del personal de la Fundación' },
  { value: 'NINGUNA', label: 'Sin constancia' },
];

export const ESTADO_LABELS = { ACTIVO: 'Activo', DENEGADO: 'Denegado', CESADO: 'Cesado' };
export const ESTADO_STYLES = {
  ACTIVO: 'bg-green-100 text-green-700 border-green-200',
  DENEGADO: 'bg-red-100 text-red-700 border-red-200',
  CESADO: 'bg-gray-100 text-gray-600 border-gray-200',
};

export const labelOf = (list, value) => list.find((o) => o.value === value)?.label || value || '-';
