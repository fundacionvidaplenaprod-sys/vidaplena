// Formato de los datos clínicos de un beneficiario para el reporte de beneficiarios.

const COMPLICATION_LABELS = {
  RETINOPATIA: 'Retinopatía',
  NEFROPATIA: 'Nefropatía',
  NEUROPATIA: 'Neuropatía',
  PIE_DIABETICO: 'Pie diabético',
  CARDIOVASCULAR: 'Enf. cardiovasculares',
};

const capitalize = (text) => text.charAt(0).toUpperCase() + text.slice(1);

// 40 -> «40», 12.5 -> «12.5» (sin el «.0» que deja el decimal)
const formatUnits = (value) => String(Number(Number(value).toFixed(2)));

/**
 * Un tratamiento por línea: «Glargina: 40 UI al día».
 * Sin dosis diaria registrada, solo el nombre de la insulina.
 */
export const formatTreatments = (treatments) => {
  const lines = (treatments || [])
    .filter((tx) => tx?.nombre)
    .map((tx) => {
      const units = Number(tx.dosis_diaria || 0);
      return units > 0 ? `${tx.nombre.trim()}: ${formatUnits(units)} UI al día` : tx.nombre.trim();
    });
  return lines.length ? lines.join('\n') : '-';
};

/**
 * Una complicación por línea. «Otras» es texto libre («Hipotiroidismo, presión alta»):
 * se separa por comas, punto y coma o saltos de línea para que cada una quede en su línea.
 */
export const formatComplications = (complications) => {
  const seen = new Set();
  const lines = [];
  const add = (text) => {
    const clean = String(text || '').replace(/\s+/g, ' ').trim();
    if (!clean) return;
    const key = clean.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    lines.push(capitalize(clean));
  };

  (complications || []).forEach((c) => {
    if (c.complication_code === 'OTRAS') {
      String(c.detalle || '').split(/[,;\n]+/).forEach(add);
    } else {
      add(COMPLICATION_LABELS[c.complication_code] || c.complication_code);
    }
  });
  return lines.length ? lines.join('\n') : '-';
};

// Años con la diabetes, tal como se registraron («8 años»).
export const formatEvolutionTime = (medical) => (medical?.tiempo_enfermedad || '').trim() || '-';
