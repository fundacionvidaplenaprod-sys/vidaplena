export const INSULIN_OPTIONS = [
  { value: 'Glargina', label: 'Glargina (Lantus, Toujeo, Basaglar, Semglee)' },
  { value: 'Lispro', label: 'Lispro (Humalog, Liprolog, Lyumjev)' },
  { value: 'Mixta', label: 'Mixta (Protaphane, mezclas Mix)' },
  { value: 'Glulisina', label: 'Glulisina (Apidra)' },
  { value: 'NPH', label: 'NPH (Insulatard, Huminsulin, Humulin, Berlinsulin)' },
  { value: 'Aspart', label: 'Aspart (NovoRapid, Fiasp)' },
  { value: 'Detemir', label: 'Detemir (Levemir)' },
  { value: 'Degludec', label: 'Degludec (Tresiba)' },
  { value: 'Regular', label: 'Regular (Actrapid, Huminsulin Normal, Berlinsulin Normal)' },
];

const INSULIN_ALIAS_MAP = {
  Glargina: ['glargina', 'lantus', 'toujeo', 'basaglar', 'semglee'],
  Lispro: ['lispro', 'humalog', 'liprolog', 'lyumjev'],
  Mixta: ['mixta', 'protamina', 'protaphane', 'mix'],
  Glulisina: ['glulisina', 'apidra'],
  NPH: ['nph', 'insulatard', 'huminsulin', 'humulin', 'berlinsulin'],
  Aspart: ['aspart', 'novorapid', 'fiasp'],
  Detemir: ['detemir', 'levemir'],
  Degludec: ['degludec', 'tresiba'],
  Regular: ['regular', 'actrapid', 'normal'],
};

export const normalizeInsulinName = (rawName) => {
  const value = String(rawName || '').toLowerCase();
  for (const [canonical, aliases] of Object.entries(INSULIN_ALIAS_MAP)) {
    if (aliases.some((alias) => value.includes(alias))) return canonical;
  }
  return 'Glargina';
};

// Presentaciones físicas en las que se entrega la insulina en campo (panel
// departamental). Lista fija — debe reflejar exactamente el Literal
// `PresentacionInsulina` en app/schemas.py.
export const PRESENTACION_OPTIONS = [
  { value: 'Frasco 10ml', label: 'Frasco 10ml' },
  { value: 'Cartucho 3ml', label: 'Cartucho 3ml' },
  { value: 'Pen 3ml', label: 'Pen 3ml' },
];

// Marcas comerciales seleccionables por insulina (cuaderno de la Directora). Salen de las marcas
// que llegan en las donaciones y de las que ella anota. «Otra» cubre lo que no esté en la lista.
export const INSULIN_BRANDS = {
  Glargina: ['Lantus', 'Toujeo', 'Abasaglar', 'Semglee'],
  Lispro: ['Humalog', 'Liprolog', 'Lyumjev'],
  Aspart: ['NovoRapid', 'Fiasp'],
  Glulisina: ['Apidra'],
  NPH: ['Insulatard', 'Protaphane', 'Huminsulin Basal', 'Humulin Basal'],
  Mixta: ['Humalog Mix 25', 'Humalog Mix 50', 'NovoMix 30', 'Actraphane 30'],
  Detemir: ['Levemir'],
  Degludec: ['Tresiba'],
  Regular: ['Actrapid', 'Huminsulin Normal', 'Humulin R'],
};

export const MARCA_OTRA = 'Otra';

// Marcas de una insulina (canónica) más «Otra».
export const brandOptions = (insulin) => [...(INSULIN_BRANDS[insulin] || []), MARCA_OTRA];

// Si el nombre anotado en la ficha ya es una marca («Lantus», «Toujeo 300»), la sugiere.
export const guessBrand = (insulin, fichaNombre) => {
  const texto = String(fichaNombre || '').toLowerCase();
  return (INSULIN_BRANDS[insulin] || []).find((brand) => texto.includes(brand.toLowerCase().split(' ')[0])) || '';
};
