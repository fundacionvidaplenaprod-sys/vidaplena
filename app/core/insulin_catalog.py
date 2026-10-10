"""Catálogo de nombres de insulina: de cualquier nombre comercial o genérico al nombre canónico.

Se usa para leer el Excel de una donación y los tratamientos de los pacientes con el mismo
criterio. El orden de `CANONICAL_INSULIN_ALIASES` importa: se devuelve la primera coincidencia.
"""
from __future__ import annotations

import unicodedata
from typing import Optional

# «Protamina» agrupa las premezclas (Mix, bifásicas, Actraphane, NovoMix) y va primero para que
# «Humalog Mix» o «Aspart bifásica» no caigan en Lispro/Aspart. Protaphane es NPH.
CANONICAL_INSULIN_ALIASES = {
    "Protamina": ["protamina", "bifasic", "premezcla", "mix", "actraphane"],
    "Glargina": ["glargina", "glargin", "gliargina", "lantus", "toujeo", "basaglar", "semglee"],
    "Lispro": ["lispro", "humalog", "liprolog", "lyumjev"],
    "Glulisina": ["glulisina", "apidra"],
    "NPH": ["nph", "isofana", "protaphane", "insulatard", "huminsulin", "humulin", "berlinsulin"],
    "Aspart": ["aspart", "novorapid", "fiasp"],
    "Detemir": ["detemir", "levemir"],
    "Degludec": ["degludec", "tresiba"],
    "Regular": ["regular", "actrapid", "normal"],
}


def normalize_insulin_name(raw_name: Optional[str]) -> Optional[str]:
    """Nombre canónico de la insulina, o None si no está en el catálogo."""
    name = unicodedata.normalize("NFD", (raw_name or "").strip().lower())
    name = "".join(ch for ch in name if unicodedata.category(ch) != "Mn")
    if not name:
        return None
    for canonical, aliases in CANONICAL_INSULIN_ALIASES.items():
        if any(alias in name for alias in aliases):
            return canonical
    return None
