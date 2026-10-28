// Las personas del Registro Asistido por Situación Excepcional también son beneficiarias. Este adaptador
// las presenta con la misma forma que una ficha ordinaria para que entren en el reporte de beneficiarios.

// Roles con acceso al Registro Asistido (Art. 19 del reglamento especial). Debe coincidir con
// ASSISTED_ROLES en app/api/deps.py.
export const ASSISTED_ROLES = ['SUPER_ADMIN', 'EVALUADOR_SOCIAL', 'COORDINADOR_NACIONAL'];

export const canSeeAssisted = (role) => ASSISTED_ROLES.includes(role);

export const assistedToBeneficiary = (reg) => ({
  id: `RA-${reg.id}`,
  _origen: 'Registro asistido',
  _codigo: reg.codigo,
  nombres: reg.nombre || reg.codigo,
  ap_paterno: '',
  ap_materno: '',
  ci: reg.ci,
  fecha_nac: reg.fecha_nacimiento,
  edad_aproximada: reg.edad_aproximada,
  // La persona asistida no tiene teléfono propio registrado: el contacto es el de su persona referente.
  tel_contacto: reg.referente?.telefono || null,
  depto: reg.depto,
  municipio: reg.municipio,
  estado: 'ASISTIDO',
  tutor: null,
  medical: {
    tipo_diabetes: reg.tipo_diabetes,
    tiempo_enfermedad: reg.anios_diabetes != null ? `${reg.anios_diabetes} años` : null,
  },
  treatments: (reg.treatments || []).map((t) => ({ id: t.id, nombre: t.insulina, dosis_diaria: t.dosis_diaria })),
  complications: reg.complicaciones_otras ? [{ complication_code: 'OTRAS', detalle: reg.complicaciones_otras }] : [],
  // No tienen aporte: están exonerados por definición (gratuidad absoluta, Art. 17).
  _aporteEstado: 'EXONERADO (REGISTRO ASISTIDO)',
});
