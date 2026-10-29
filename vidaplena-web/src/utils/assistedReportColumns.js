// Columnas del reporte del Registro Asistido por Situación Excepcional.
import {
  CESE_CAUSAS, ENTIDAD_TIPOS, ESTADO_LABELS, RANGOS_EDAD, REFERENTE_VINCULOS, labelOf,
} from '../constants/assisted';
import { formatTreatments } from './beneficiaryFormat';

const fmtDate = (value) => (value ? new Date(value.length === 10 ? `${value}T12:00:00` : value).toLocaleDateString('es-BO') : '-');

const edadDe = (r) => {
  if (r.fecha_nacimiento) {
    const hoy = new Date();
    const nac = new Date(`${r.fecha_nacimiento}T12:00:00`);
    let edad = hoy.getFullYear() - nac.getFullYear();
    if (hoy < new Date(hoy.getFullYear(), nac.getMonth(), nac.getDate())) edad -= 1;
    return String(edad);
  }
  if (r.edad_aproximada != null) return `~${r.edad_aproximada}`;
  return r.rango_edad ? labelOf(RANGOS_EDAD, r.rango_edad) : '-';
};

/**
 * `identifica`: la columna permite individualizar a la persona (o a quien la atiende). En los informes a
 * donantes las personas se identifican solo por su Código Interno (Art. 19 IV del reglamento), así que
 * esas columnas se quitan cuando se elige «solo con código».
 * `multiline`: una línea por elemento (tratamiento).
 */
export const ASSISTED_COLUMNS = [
  { id: 'codigo', label: 'Código interno', getValue: (r) => r.codigo },
  { id: 'estado', label: 'Estado', getValue: (r) => ESTADO_LABELS[r.estado] || r.estado },
  { id: 'nombre', label: 'Nombre / apodo', identifica: true, getValue: (r) => r.nombre || '-' },
  { id: 'ci', label: 'C.I.', identifica: true, getValue: (r) => r.ci || '-' },
  { id: 'fecha_nacimiento', label: 'Fecha de nacimiento', identifica: true, getValue: (r) => fmtDate(r.fecha_nacimiento) },
  { id: 'edad', label: 'Edad', getValue: edadDe },
  { id: 'depto', label: 'Departamento', getValue: (r) => r.depto || '-' },
  { id: 'municipio', label: 'Municipio', identifica: true, getValue: (r) => r.municipio || '-' },
  { id: 'ciudad_localidad', label: 'Ciudad / localidad', identifica: true, getValue: (r) => r.ciudad_localidad || '-' },
  { id: 'tipo_diabetes', label: 'Tipo de diabetes', getValue: (r) => r.tipo_diabetes || '-' },
  { id: 'anios_diabetes', label: 'Años con diabetes', getValue: (r) => (r.anios_diabetes != null ? `${r.anios_diabetes} años` : '-') },
  { id: 'complicaciones', label: 'Complicaciones / otras enfermedades', getValue: (r) => r.complicaciones_otras || '-' },
  { id: 'tratamiento', label: 'Tratamiento', multiline: true, getValue: (r) => formatTreatments((r.treatments || []).map((t) => ({ nombre: t.insulina, dosis_diaria: t.dosis_diaria }))) },
  { id: 'insumos', label: 'Otros insumos', getValue: (r) => r.insumos_requeridos || '-' },
  { id: 'entidad_nombre', label: 'Entidad referente', identifica: true, getValue: (r) => r.entidad_nombre || '-' },
  { id: 'entidad_tipo', label: 'Tipo de entidad', getValue: (r) => (r.entidad_tipo ? labelOf(ENTIDAD_TIPOS, r.entidad_tipo) : '-') },
  { id: 'referente_nombre', label: 'Persona referente', identifica: true, getValue: (r) => r.referente?.nombre_completo || '-' },
  { id: 'referente_ci', label: 'C.I. persona referente', identifica: true, getValue: (r) => r.referente?.ci || '-' },
  { id: 'referente_telefono', label: 'Contacto persona referente', identifica: true, getValue: (r) => r.referente?.telefono || '-' },
  { id: 'referente_vinculo', label: 'Vínculo con el beneficiario', getValue: (r) => (r.referente_vinculo ? labelOf(REFERENTE_VINCULOS, r.referente_vinculo) : '-') },
  { id: 'entregas', label: 'Entregas', getValue: (r) => String(r.total_entregas ?? 0) },
  { id: 'ultima_entrega', label: 'Última entrega', getValue: (r) => (r.ultima_entrega ? fmtDate(r.ultima_entrega) : 'Sin entregas') },
  { id: 'registrado', label: 'Fecha de registro', getValue: (r) => fmtDate(r.created_at) },
  { id: 'ultima_revision', label: 'Última revisión', getValue: (r) => (r.ultima_revision_at ? fmtDate(r.ultima_revision_at) : 'Sin revisar') },
  { id: 'revision_vencida', label: 'Revisión semestral vencida', getValue: (r) => (r.revision_vencida ? 'Sí' : 'No') },
  { id: 'urgente', label: 'Necesidad médica inmediata', getValue: (r) => (r.urgente ? 'Sí' : 'No') },
  { id: 'cese', label: 'Causa de cese', getValue: (r) => (r.cese_causa ? labelOf(CESE_CAUSAS, r.cese_causa) : '-') },
];

export const DEFAULT_ASSISTED_COLUMNS = [
  'codigo', 'estado', 'nombre', 'ci', 'edad', 'depto', 'tipo_diabetes', 'tratamiento', 'referente_nombre',
  'referente_vinculo', 'ultima_entrega',
];

/** Columnas que se pueden usar en un informe «solo con código». */
export const ANONYMOUS_COLUMNS = ASSISTED_COLUMNS.filter((c) => !c.identifica);
