export const INSULIN_OPTIONS = [
  { value: 'Glargina', label: 'Glargina (Lantus, Toujeo, Basaglar, Semglee)' },
  { value: 'Lispro', label: 'Lispro (Humalog, Liprolog, Lyumjev)' },
  { value: 'Protamina', label: 'Protamina (Protaphane, mezclas Mix)' },
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
  Protamina: ['protamina', 'protaphane', 'mix'],
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
