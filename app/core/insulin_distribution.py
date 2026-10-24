"""Motor de reparto de insulinas de una donación.

Función pura (sin base de datos): recibe lotes y pacientes ya cargados y
devuelve el plan. Así se puede probar con cualquier escenario y el endpoint
solo se ocupa de traducir BD <-> motor.

Reglas:
  * Todo se calcula en UI (un envase de Toujeo U300 1,5 ml tiene 450 UI; uno
    de Lantus 3 ml, 300 UI) y recién al final se convierte a envases enteros.
    La dosis diaria nunca depende de la concentración.
  * Horizonte de 60 días. Reserva: el 5 % del total de UI se aparta antes de repartir y se
    cubre primero con el sobrante de cada insulina. La reserva se libera solo en la medida
    necesaria: cuando todo está repartido, a los tratamientos que siguen bajo el mínimo de su
    banda (o en 0 %) se les completa con envases de la reserva, en orden de prioridad y con el
    menor número de envases posible. Lo que no hace falta queda guardado.
  * Prioridad y margen de cobertura (cobertura = UI recibidas / UI necesarias en el
    periodo). Cada grupo tiene una banda que NO se debe romper:
        1. Menores de 18 años ........ 80 % - 120 %   y su insulina específica
        2. Diabéticos tipo 1 ......... 75 % - 110 %
        3. Adultos mayores, tipo 2 ... 65 % - 100 %
        4. Diabéticos tipo 2 ......... 65 % - 100 %
    Los grupos se atienden en ese orden y con prioridad estricta: menores y tipo 1
    reciben primero el mínimo de su banda; en los grupos 3 y 4 entran primero los que
    caben en su banda, luego un envase a cada uno (nadie queda en 0 % mientras haya
    envases) y luego hasta el mínimo. Con lo que sobra se acerca a cada uno al 100 %
    sin pasar del máximo. Los envases enteros no siempre permiten caer en la banda:
    entonces gana la garantía del mínimo (el mínimo cubierto con el menor exceso) y el
    caso queda marcado, pero NUNCA por encima del 120 % (`MAX_COVERAGE`): si para llegar
    al mínimo hay que pasar del 120 %, se queda por debajo del mínimo. Para menores, cuando
    ningún envase cae entre su mínimo y el 120 %, se elige lo más cercano al 100 % (p. ej.
    8 UI/día = 480 UI: 2 pens = 125 % antes que 1 pen = 62,5 %). Otra excepción:
    si ningún envase de esa insulina (ni de sus sustitutos) cabe en el 120 % —una dosis de
    3 o 4 UI/día frente a un pen de 300 UI—, recibe un solo envase del tamaño más chico,
    porque un envase no se parte; el caso queda marcado (`min_pen_exception`).
  * Menores: reciben su insulina específica todo lo que haya y solo el faltante sale de la
    tabla de sustituciones (la NPH puede pasar a degludec o detemir, nunca al revés). Un adulto
    pasa entero al sustituto cuando este solo alcanza su banda.
  * Tope de dosis para menores de 18: en glargina, lispro, glulisina, aspart, detemir y
    degludec la dosis diaria no pasa de 30 UI sin importar lo registrado.
  * Un beneficiario usa como máximo UNA insulina de cada grupo: rápidas (lispro,
    aspart, glulisina, regular) y basales/intermedias (glargina, mixta, NPH,
    detemir, degludec). Si la ficha trae dos del mismo grupo es un error de carga y
    se usa UNA, la que mejor se puede atender (con stock, luego con sustitución,
    luego la de mayor dosis); el caso se informa (`resolve_group_choices`).
  * Una premezcla (`PREMIX_INSULINS`) nunca sustituye a una basal análoga (glargina,
    detemir, degludec). La única excepción definida por la Fundación es la NPH, que sí
    puede reemplazarse por la premezcla (`PREMIX_REPLACEABLE`).
  * Sustituciones (`SUBSTITUTION_TABLE`): si falta la insulina propia se completa con
    la tabla, en su orden de preferencia, y solo con stock libre. Se prefiere que todo
    el tratamiento salga de una sola insulina (el cambio es completo); si ninguna
    alcanza sola, se combinan.
  * Viales de 10 ml (1.000 UI): ya separada la reserva, se entregan primero a quienes usan
    una insulina rápida con 14 a 20 UI/día (`VIAL_DOSE_RANGE`), en orden de prioridad;
    nunca más del 120 %. Después corre el reparto normal con lo que queda.
  * Marca preferida para menores (Lantus en glargina): se trata de cubrir con Lantus la
    glargina de los menores. Los menores toman esa marca primero, los adultos la dejan para el
    final y la reserva se aparta de otras marcas antes que de Lantus, para que siga libre
    para los menores. Si Lantus no permite caer en la banda, se amplía a otras glargina.
    Dentro de cada preferencia se usa primero el lote que vence antes (FEFO).
  * Degludec de menores: un menor que usa degludec la mantiene siempre. Nunca se sustituye
    por otra insulina, si la ficha trae otra basal junto a la degludec se usa la degludec, y
    su degludec se completa hasta el 100 % antes de que otros grupos la reciban como
    sustituto (p. ej. de la NPH).
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

DISTRIBUTION_DAYS = 60
RESERVE_PCT = 0.05
MINOR_AGE = 18
OLDER_ADULT_AGE = 60
# insulina canónica -> fragmentos del nombre comercial que se reservan a menores
MINOR_PREFERRED_BRANDS: Dict[str, Tuple[str, ...]] = {"Glargina": ("lantus",)}

# Grupos de prioridad y su banda de cobertura (mínimo, máximo) sobre la necesidad.
PRIORITY_MINOR = 1
PRIORITY_TYPE1 = 2
PRIORITY_OLDER_TYPE2 = 3
PRIORITY_TYPE2 = 4
COVERAGE_BANDS: Dict[int, Tuple[float, float]] = {
    PRIORITY_MINOR: (0.80, 1.20),
    PRIORITY_TYPE1: (0.75, 1.10),
    PRIORITY_OLDER_TYPE2: (0.65, 1.00),
    PRIORITY_TYPE2: (0.65, 1.00),
}
# Tope absoluto de cobertura: nadie recibe más del 120 % de su necesidad del periodo.
MAX_COVERAGE = 1.20
# Viales (10 ml = 1.000 UI): se reparten primero, ya separada la reserva, a quienes usan una
# insulina rápida con una dosis entre estos dos valores (UI/día); a esa dosis un vial cubre
# del 83 % al 119 % de los 60 días. El resto del reparto sigue las bandas de cada grupo.
VIAL_MIN_UI = 1000.0
VIAL_DOSE_RANGE = (14.0, 20.0)
PRIORITY_NAMES: Dict[int, str] = {
    PRIORITY_MINOR: "Menores de 18 años",
    PRIORITY_TYPE1: "Diabéticos tipo 1",
    PRIORITY_OLDER_TYPE2: "Adultos mayores con diabetes tipo 2",
    PRIORITY_TYPE2: "Diabéticos tipo 2",
}

# Tope de dosis diaria (UI/día) para menores de 18, solo en estas insulinas.
MINOR_DAILY_CAP_UI = 30.0
MINOR_CAPPED_INGREDIENTS = frozenset({"Glargina", "Lispro", "Glulisina", "Aspart", "Detemir", "Degludec"})
# Grupos de insulina: un beneficiario usa una sola de cada grupo.
GROUP_RAPID = "RAPIDA"
GROUP_BASAL = "BASAL"
INSULIN_GROUPS: Dict[str, frozenset] = {
    GROUP_RAPID: frozenset({"Lispro", "Aspart", "Glulisina", "Regular"}),
    GROUP_BASAL: frozenset({"Glargina", "Mixta", "NPH", "Detemir", "Degludec"}),
}
# Insulinas que un menor conserva siempre: nunca se sustituyen y se prefieren sobre otra basal
# registrada en su ficha.
MINOR_KEEP_INSULINS = frozenset({"Degludec"})
# Premezclas: nunca reemplazan a una basal análoga (glargina, detemir, degludec).
PREMIX_INSULINS = frozenset({"Mixta"})
# Excepción: la NPH (intermedia) sí puede reemplazarse por una premezcla cuando falta.
PREMIX_REPLACEABLE = frozenset({"NPH"})
GROUP_LABELS = {GROUP_RAPID: "rápidas", GROUP_BASAL: "basales / intermedias / premezclas"}

_EPS = 1e-6
_MAX_SIZES = 4  # tamaños de envase distintos que se combinan por insulina


@dataclass(frozen=True)
class Substitution:
    """`target` reemplaza a `source` cuando falta `source`.

    `factor` son las UI de `target` por cada UI de `source` que no se pudo dar.
    """

    source: str
    target: str
    factor: float = 1.0


# Tabla de sustituciones de la Fundación (en el orden de preferencia en que se escribió).
# «X → Y → Z» = si falta X se le da Y y, si Y no alcanza, Z. Los factores 1:1 son
# provisionales y los debe validar el equipo médico; son el único dato clínico que hay
# que cambiar aquí. Una premezcla (Mixta) solo es destino de la NPH, nunca de una basal.
#
#   Glargina  → Detemir → Degludec        Glulisina → Aspart → Lispro
#   Detemir   → Glargina → Degludec       Lispro    → Aspart → Glulisina
#   Degludec  → Glargina                  Aspart    → Lispro → Glulisina
#   NPH       → Degludec → Detemir        Regular   → Aspart → Lispro
#               → Mixta (premezcla)
SUBSTITUTION_TABLE: Dict[str, Tuple[str, ...]] = {
    "Glargina": ("Detemir", "Degludec"),
    "Detemir": ("Glargina", "Degludec"),
    "Degludec": ("Glargina",),
    "Glulisina": ("Aspart", "Lispro"),
    "Lispro": ("Aspart", "Glulisina"),
    "Aspart": ("Lispro", "Glulisina"),
    "Regular": ("Aspart", "Lispro"),
    "NPH": ("Degludec", "Detemir", "Mixta"),
}

DEFAULT_SUBSTITUTIONS: Tuple[Substitution, ...] = tuple(
    Substitution(source, target, factor=1.0)
    for source, targets in SUBSTITUTION_TABLE.items()
    for target in targets
)


@dataclass
class LotInput:
    lot_id: int
    ingredient: str
    label: str  # nombre comercial / marca, solo para mostrar y para la preferencia
    ui_per_unit: float
    units: int
    expiry: Optional[date] = None


@dataclass
class PatientInput:
    patient_id: int
    is_minor: bool
    daily_ui: Dict[str, float]
    is_type1: bool = False
    # 1 menores, 2 tipo 1, 3 adulto mayor tipo 2, 4 tipo 2 / resto. Si no se indica se deduce.
    priority_group: Optional[int] = None

    @property
    def group(self) -> int:
        if self.priority_group is not None:
            return self.priority_group
        if self.is_minor:
            return PRIORITY_MINOR
        return PRIORITY_TYPE1 if self.is_type1 else PRIORITY_TYPE2


@dataclass
class Assignment:
    patient_id: int
    lot_id: int
    units: int
    ui: float
    # Insulina que el paciente usa y que este envase cubre. Es distinta de la del
    # lote cuando es una sustitución (detemir entregada en lugar de glargina).
    for_ingredient: str = ""


@dataclass
class IngredientSummary:
    ingredient: str
    stock_ui: float
    demand_ui: float
    reserve_ui: float
    allocated_ui: float
    unmet_ui: float
    leftover_ui: float
    patients_with_need: int
    patients_unmet: int
    # Parte de la necesidad (en UI de esta insulina) cubierta con otra insulina,
    # y UI de esta insulina entregadas como sustituto de otra.
    substituted_out_ui: float = 0.0
    substituted_in_ui: float = 0.0
    reserve_released_ui: float = 0.0  # UI de la reserva de esta insulina que se usaron para repartir


@dataclass
class ReserveLot:
    lot_id: int
    ingredient: str
    label: str
    units: int
    ui: float


@dataclass
class PatientIngredientResult:
    ingredient: str
    need_ui: float
    given_ui: float  # solo con su propia insulina
    substitute: Optional[str] = None
    substitute_ui: float = 0.0  # UI del sustituto efectivamente entregadas
    substitute_equiv_ui: float = 0.0  # lo que eso cubre, en UI de `ingredient`
    daily_registered: float = 0.0  # UI/día registradas en el tratamiento
    daily_applied: float = 0.0  # UI/día con las que se calculó (tras el tope de menores)
    group: int = PRIORITY_TYPE2
    band_min: float = 0.0  # fracciones de la necesidad
    band_max: float = 1.0
    outside_band: bool = False  # la cobertura quedó fuera de [band_min, band_max]
    # Ningún envase cabía en el 120 % y se entregó uno solo, el más chico (dosis muy baja).
    min_pen_exception: bool = False
    # Cuánto le falta (UI de su insulina) para el mínimo de su banda y por qué no se llegó:
    # "STOCK" = no queda envase de su insulina ni de sus sustitutos; "ENVASE" = el envase más
    # chico que queda lo llevaría por encima del 120 %; "OTRO" = había envase y no se asignó.
    min_shortfall_ui: float = 0.0
    min_shortfall_cause: Optional[str] = None


@dataclass
class GroupChoice:
    """Ficha con dos insulinas del mismo grupo: cuál se usó y por qué."""

    patient_id: int
    group: str
    options: Dict[str, float]  # insulina -> dosis diaria registrada
    chosen: str
    reason: str  # STOCK | SUSTITUTO | SIN_STOCK
    substitute: Optional[str] = None  # insulina que la cubriría si falta (reason == SUSTITUTO)
    premix_discarded: bool = False  # había una premezcla junto a una basal y se descartó


@dataclass
class DistributionPlan:
    days: int
    reserve_pct: float
    total_stock_ui: float
    reserve_target_ui: float
    reserve_ui: float
    allocated_ui: float
    assignments: List[Assignment] = field(default_factory=list)
    reserve_released_ui: float = 0.0  # UI de la reserva que se repartieron para llegar a los mínimos
    reserve_lots: List[ReserveLot] = field(default_factory=list)
    ingredients: List[IngredientSummary] = field(default_factory=list)
    patients: Dict[int, List[PatientIngredientResult]] = field(default_factory=dict)
    group_choices: List[GroupChoice] = field(default_factory=list)
    remaining_units: Dict[int, int] = field(default_factory=dict)  # envases libres por lote al terminar


# --------------------------------------------------------------------------- catálogo de grupos


def insulin_group(ingredient: str) -> Optional[str]:
    for group, members in INSULIN_GROUPS.items():
        if ingredient in members:
            return group
    return None


def split_group_conflicts(
    daily_ui: Dict[str, float],
) -> Tuple[Dict[str, float], Dict[str, Dict[str, float]]]:
    """Separa las insulinas que se pueden repartir de las que están en conflicto.

    Devuelve (dosis sin conflicto, {grupo: {insulina: dosis}} de los grupos con dos o más
    insulinas distintas). Una misma insulina cargada dos veces ya viene sumada y no es
    conflicto. Las insulinas fuera de los dos grupos pasan tal cual.
    """
    clean: Dict[str, float] = {}
    by_group: Dict[str, Dict[str, float]] = {}
    for ing, dose in daily_ui.items():
        group = insulin_group(ing)
        if group is None:
            clean[ing] = dose
        else:
            by_group.setdefault(group, {})[ing] = dose
    conflicts: Dict[str, Dict[str, float]] = {}
    for group, members in by_group.items():
        if len(members) > 1:
            conflicts[group] = members
        else:
            clean.update(members)
    return clean, conflicts


def _plain(raw: Optional[str]) -> str:
    text = unicodedata.normalize("NFD", (raw or "").strip().lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def is_type1_diabetes(raw: Optional[str]) -> bool:
    """Reconoce «Tipo 1», «TIPO 1», «tipo1», «Diabetes tipo I», «DM1»... (texto libre)."""
    return bool(re.fullmatch(r"(diabetes\s*(mellitus\s*)?)?(tipo|tp|dm|t)\s*[-.]?\s*(1|i)", _plain(raw)))


def is_type2_diabetes(raw: Optional[str]) -> bool:
    """Reconoce «Tipo 2», «TIPO 2», «tipo II», «DM2»... (texto libre)."""
    return bool(re.fullmatch(r"(diabetes\s*(mellitus\s*)?)?(tipo|tp|dm|t)\s*[-.]?\s*(2|ii)", _plain(raw)))


def priority_group_for(age: Optional[int], diabetes_type: Optional[str]) -> int:
    """Grupo de prioridad: menores; tipo 1; adulto mayor tipo 2; tipo 2 y todo lo demás."""
    if age is not None and age < MINOR_AGE:
        return PRIORITY_MINOR
    if is_type1_diabetes(diabetes_type):
        return PRIORITY_TYPE1
    if age is not None and age >= OLDER_ADULT_AGE and is_type2_diabetes(diabetes_type):
        return PRIORITY_OLDER_TYPE2
    return PRIORITY_TYPE2


# --------------------------------------------------------------------------- stock y combinaciones


def _fefo_key(lot: LotInput) -> Tuple[date, int]:
    return (lot.expiry or date.max, lot.lot_id)


def _is_preferred(lot: LotInput, preferred: Sequence[str]) -> bool:
    label = lot.label.lower()
    return any(fragment in label for fragment in preferred)


def _split_reserve(
    stock: Dict[str, float], demand: Dict[str, float], reserve_target: float
) -> Dict[str, float]:
    """Reparte la reserva global entre insulinas: primero sobrante, luego proporcional."""
    surplus = {k: max(0.0, stock[k] - demand.get(k, 0.0)) for k in stock}
    total_surplus = sum(surplus.values())
    if total_surplus >= reserve_target:
        if total_surplus <= 0:
            return {k: 0.0 for k in stock}
        return {k: reserve_target * surplus[k] / total_surplus for k in stock}
    covered = {k: stock[k] - surplus[k] for k in stock}
    total_covered = sum(covered.values())
    missing = reserve_target - total_surplus
    return {
        k: min(stock[k], surplus[k] + (missing * covered[k] / total_covered if total_covered else 0.0))
        for k in stock
    }


def _take_reserve(
    lots: List[LotInput], reserve_ui: float, avail: Dict[int, int], preferred: Sequence[str] = ()
) -> List[ReserveLot]:
    """Aparta envases enteros: primero de las marcas no preferidas (la preferida, Lantus, se
    deja libre para los menores) y, dentro de cada una, de los lotes que vencen más tarde."""
    reserved: List[ReserveLot] = []
    remaining = reserve_ui
    order = sorted(lots, key=lambda l: (0 if _is_preferred(l, preferred) else 1, _fefo_key(l)), reverse=True)
    for lot in order:
        if remaining <= _EPS:
            break
        n = min(avail[lot.lot_id], math.ceil((remaining - _EPS) / lot.ui_per_unit))
        if n <= 0:
            continue
        avail[lot.lot_id] -= n
        remaining -= n * lot.ui_per_unit
        reserved.append(ReserveLot(lot.lot_id, lot.ingredient, lot.label, n, n * lot.ui_per_unit))
    return reserved


class _Order(list):
    """Lista de lotes en orden de preferencia + FEFO, con la clase de preferencia de cada lote.

    `classes[lot_id]` es 0 para los lotes preferidos del grupo y 1 para el resto; sin
    clases, todos valen igual.
    """

    def __init__(self, items, classes: Optional[Dict[int, int]] = None):
        super().__init__(items)
        self.classes = classes or {}


def _totals(lots: Sequence[LotInput], avail: Dict[int, int], max_total: float) -> Dict[float, tuple]:
    """Totales de UI alcanzables combinando envases de hasta 4 tamaños, hasta `max_total`.

    Devuelve {total: (envases, tamaños usados, {tamaño: cantidad})} con la combinación de
    menos envases para cada total; los tamaños siguen el orden de preferencia de los lotes.
    """
    by_size: Dict[float, List[LotInput]] = {}
    for lot in lots:
        if avail[lot.lot_id] > 0:
            by_size.setdefault(lot.ui_per_unit, []).append(lot)
    sizes = list(by_size)[:_MAX_SIZES]
    if not sizes:
        return {}
    caps = [sum(avail[l.lot_id] for l in by_size[sz]) for sz in sizes]
    found: Dict[float, tuple] = {}

    def walk(idx: int, counts: List[int], total: float) -> None:
        if idx == len(sizes):
            if total > _EPS:
                key = round(total, 6)
                npens = sum(counts)
                kinds = sum(1 for c in counts if c)
                cur = found.get(key)
                if cur is None or (npens, kinds) < (cur[0], cur[1]):
                    found[key] = (npens, kinds, {sz: c for sz, c in zip(sizes, counts) if c})
            return
        size = sizes[idx]
        c = 0
        while c <= caps[idx] and total + c * size <= max_total + _EPS:
            walk(idx + 1, counts + [c], total + c * size)
            c += 1

    walk(0, [], 0.0)
    return found


def _select_total(
    totals: Dict[float, tuple], lo: float, hi: float, ideal: float
) -> Optional[Tuple[float, str]]:
    """Elige un total: dentro de [lo, hi] el más cercano a `ideal`; si no hay, el mínimo
    sobre `lo` (gana la garantía del mínimo); si tampoco, el mayor posible bajo `lo`.

    Devuelve (total, "in" | "above" | "below") o None si no hay ninguna combinación.
    """
    if not totals:
        return None
    within = [(abs(t - ideal), totals[t][0], t) for t in totals if lo - _EPS <= t <= hi + _EPS]
    if within:
        return min(within)[2], "in"
    above = [t for t in totals if t > hi + _EPS and t >= lo - _EPS]
    if above:
        return min(above), "above"
    below = [t for t in totals if t < lo - _EPS]
    if below:
        return max(below), "below"
    return None


def _counts_to_lots(
    lots: Sequence[LotInput], avail: Dict[int, int], counts: Dict[float, int]
) -> Dict[int, int]:
    """Pasa {tamaño: cantidad} a {lote: envases}, usando primero el lote que vence antes."""
    out: Dict[int, int] = {}
    for size, count in counts.items():
        remaining = count
        for lot in lots:
            if remaining <= 0:
                break
            if lot.ui_per_unit != size:
                continue
            n = min(avail[lot.lot_id], remaining)
            if n > 0:
                out[lot.lot_id] = out.get(lot.lot_id, 0) + n
                remaining -= n
    return out


def _band_pick(
    order: Sequence[LotInput], avail: Dict[int, int], lo: float, hi: float, ideal: float
) -> Optional[Tuple[Dict[int, int], float, str]]:
    """Mejor combinación de envases para cubrir entre `lo` y `hi` (UI), cerca de `ideal`.

    Prueba primero con los lotes preferidos del grupo (p. ej. Lantus para menores) y solo
    si ahí no hay una combinación dentro de la banda amplía a todos los lotes.
    Devuelve ({lote: envases}, total, "in"|"above"|"below") o None.
    """
    classes = getattr(order, "classes", None) or {}
    levels = sorted({classes.get(l.lot_id, 0) for l in order})
    best = None
    for level in levels:
        subset = [l for l in order if classes.get(l.lot_id, 0) <= level and avail[l.lot_id] > 0]
        if not subset:
            continue
        max_size = max(l.ui_per_unit for l in subset)
        totals = _totals(subset, avail, hi + max_size)
        chosen = _select_total(totals, lo, hi, ideal)
        if chosen is None:
            continue
        total, kind = chosen
        rank = {"in": 0, "above": 1, "below": 2}[kind]
        key = (rank, abs(total - ideal) if kind == "in" else (total - hi if kind == "above" else lo - total), level)
        if best is None or key < best[0]:
            best = (key, subset, totals[round(total, 6)][2], total, kind)
        if kind == "in":
            break  # ya cabe con los lotes preferidos: no se amplía
    if best is None:
        return None
    _key, subset, counts, total, kind = best
    return _counts_to_lots(subset, avail, counts), total, kind


def _pick_one(ordered: Sequence[LotInput], avail: Dict[int, int], rem: float, hi: float) -> Optional[LotInput]:
    """Envase que menos sobra para cubrir `rem` sin pasar de `hi`; si ninguno alcanza solo, el más grande.

    Nunca devuelve un envase más grande que `hi`.
    """
    cands = [(k, l) for k, l in enumerate(ordered) if avail[l.lot_id] > 0 and l.ui_per_unit <= hi + _EPS]
    if not cands:
        return None
    fits = [(k, l) for k, l in cands if l.ui_per_unit + _EPS >= rem]
    if fits:
        return min(fits, key=lambda kl: (kl[1].ui_per_unit, kl[0]))[1]
    return max(cands, key=lambda kl: (kl[1].ui_per_unit, -kl[0]))[1]


# --------------------------------------------------------------------------- una insulina por grupo


def resolve_group_choices(
    patients: Sequence[PatientInput],
    lots_by_ing: Dict[str, List[LotInput]],
    *,
    days: int,
    reserve_pct: float,
    rules: Sequence[Substitution],
    minor_daily_cap_ui: Optional[float],
) -> Tuple[Dict[int, Dict[str, float]], List[GroupChoice]]:
    """Deja una sola insulina por grupo en cada ficha.

    Devuelve ({paciente: {insulina: dosis diaria}}, elecciones hechas). Las fichas sin
    conflicto pasan igual. Para las que tienen dos insulinas del mismo grupo se elige la
    que se puede cubrir: primero con stock propio, luego con una sustitución conocida
    (no para menores), y si ninguna, la de mayor dosis. La disponibilidad se mide frente a
    la demanda de quienes no tienen duda y se va descontando a medida que se decide, en
    orden de prioridad.
    """
    usable_stock = {
        ing: sum(l.units * l.ui_per_unit for l in ls) * (1 - reserve_pct) for ing, ls in lots_by_ing.items()
    }

    def need_of(p: PatientInput, ing: str, dose: float) -> float:
        if (
            p.is_minor
            and minor_daily_cap_ui is not None
            and ing in MINOR_CAPPED_INGREDIENTS
            and dose > minor_daily_cap_ui
        ):
            dose = minor_daily_cap_ui
        return dose * days

    effective: Dict[int, Dict[str, float]] = {}
    pending: List[Tuple[PatientInput, str, Dict[str, float]]] = []
    committed: Dict[str, float] = {}
    for p in patients:
        clean, conflicts = split_group_conflicts({k: v for k, v in p.daily_ui.items() if v and v > 0})
        effective[p.patient_id] = dict(clean)
        for ing, dose in clean.items():
            committed[ing] = committed.get(ing, 0.0) + need_of(p, ing, dose)
        for group, options in conflicts.items():
            pending.append((p, group, options))

    surplus = {ing: usable_stock.get(ing, 0.0) - committed.get(ing, 0.0) for ing in set(usable_stock) | set(committed)}
    choices: List[GroupChoice] = []

    for p, group, options in sorted(pending, key=lambda x: (x[0].group, x[0].patient_id, x[1])):
        scored = []
        # Una premezcla nunca sustituye a una basal: si hay una basal registrada, compiten
        # solo las basales aunque la premezcla tenga más stock.
        premix_in = [ing for ing in options if ing in PREMIX_INSULINS]
        basal_in = [ing for ing in options if ing not in PREMIX_INSULINS]
        premix_discarded = bool(premix_in and basal_in)
        candidates = {ing: options[ing] for ing in basal_in} if premix_discarded else options
        for ing, dose in candidates.items():
            need = need_of(p, ing, dose)
            direct = surplus.get(ing, 0.0) >= need - _EPS
            via = None
            if not direct:
                for r in rules:
                    if r.source != ing:
                        continue
                    if surplus.get(r.target, 0.0) >= need * r.factor - _EPS:
                        via = r
                        break
            level = 0 if direct else 1 if via else 2
            # menor nivel = mejor; luego más holgura de stock y más dosis registrada
            scored.append(((level, -surplus.get(ing, 0.0), -dose, ing), ing, need, via, level))
        scored.sort(key=lambda x: x[0])
        keep = [x for x in scored if p.is_minor and x[1] in MINOR_KEEP_INSULINS]
        if keep:
            # Un menor con degludec la conserva siempre, tenga o no stock, aunque haya otra basal.
            chosen = keep[0][1]
            need = keep[0][2]
            surplus[chosen] = surplus.get(chosen, 0.0) - need
            effective[p.patient_id][chosen] = options[chosen]
            choices.append(
                GroupChoice(
                    patient_id=p.patient_id,
                    group=group,
                    options=dict(options),
                    chosen=chosen,
                    reason="MENOR_DEGLUDEC",
                    substitute=None,
                    premix_discarded=premix_discarded,
                )
            )
            continue
        _key, chosen, need, via, level = scored[0]
        if level == 0:
            surplus[chosen] = surplus.get(chosen, 0.0) - need
            reason = "STOCK"
        elif level == 1:
            surplus[via.target] = surplus.get(via.target, 0.0) - need * via.factor
            reason = "SUSTITUTO"
        else:
            reason = "SIN_STOCK"
        effective[p.patient_id][chosen] = options[chosen]
        choices.append(
            GroupChoice(
                patient_id=p.patient_id,
                group=group,
                options=dict(options),
                chosen=chosen,
                reason=reason,
                substitute=via.target if via else None,
                premix_discarded=premix_discarded,
            )
        )
    return effective, choices


# --------------------------------------------------------------------------- reparto


@dataclass
class _Entry:
    """Una insulina de un paciente: lo que necesita y lo que ya se le dio."""

    pid: int
    ing: str
    group: int
    is_minor: bool
    need: float
    lo: float
    hi: float
    cap: float  # tope absoluto (MAX_COVERAGE de la necesidad)
    daily: float = 0.0  # dosis diaria usada en el cálculo (UI/día)
    own: float = 0.0
    subs: Dict[str, List[float]] = field(default_factory=dict)  # destino -> [UI del destino, UI que cubre]
    min_pen: bool = False  # recibió un envase sobre el tope porque ninguno cabía

    @property
    def covered(self) -> float:
        return self.own + sum(v[1] for v in self.subs.values())


def plan_distribution(
    lots: Sequence[LotInput],
    patients: Sequence[PatientInput],
    *,
    days: int = DISTRIBUTION_DAYS,
    reserve_pct: float = RESERVE_PCT,
    minor_preferred_brands: Optional[Dict[str, Tuple[str, ...]]] = None,
    substitutions: Optional[Sequence[Substitution]] = None,
    minor_daily_cap_ui: Optional[float] = MINOR_DAILY_CAP_UI,
    bands: Optional[Dict[int, Tuple[float, float]]] = None,
    release_reserve: bool = True,
) -> DistributionPlan:
    """Reparte la donación entre los pacientes. Ver el encabezado del módulo para las reglas.

    La prioridad es estricta: un grupo no cede stock a otro de menor prioridad para llegar a
    su mínimo. Si una insulina no alcanza, quedan por debajo (incluso en 0 %) los últimos.

    `release_reserve`: con True, lo que haga falta de la reserva se reparte al final a los
    tratamientos que siguen bajo su mínimo; con False la reserva no se toca. Si aun así alguien
    queda bajo su mínimo por falta de una insulina que otros reciben como sustituto, esos
    otros pasan a otra alternativa disponible y le dejan los envases.
    """
    preferred_map = MINOR_PREFERRED_BRANDS if minor_preferred_brands is None else minor_preferred_brands
    rules = DEFAULT_SUBSTITUTIONS if substitutions is None else tuple(substitutions)
    band_of = COVERAGE_BANDS if bands is None else bands
    for rule in rules:
        if (
            rule.target in PREMIX_INSULINS
            and rule.source not in PREMIX_INSULINS
            and rule.source not in PREMIX_REPLACEABLE
        ):
            raise ValueError(f"Una premezcla no puede sustituir a una basal ({rule.source} -> {rule.target})")
    factor_of = {(r.source, r.target): r.factor for r in rules}
    targets_of: Dict[str, List[str]] = {}
    for r in rules:
        targets_of.setdefault(r.source, []).append(r.target)

    lots_by_ing: Dict[str, List[LotInput]] = {}
    for lot in lots:
        if lot.units > 0 and lot.ui_per_unit > 0:
            lots_by_ing.setdefault(lot.ingredient, []).append(lot)

    # Dos insulinas del mismo grupo es un error de la ficha: se usa una sola, la que se puede atender.
    effective, group_choices = resolve_group_choices(
        patients, lots_by_ing, days=days, reserve_pct=reserve_pct, rules=rules, minor_daily_cap_ui=minor_daily_cap_ui,
    )

    registered: Dict[Tuple[int, str], float] = {}
    applied: Dict[Tuple[int, str], float] = {}
    entries: List[_Entry] = []
    for p in patients:
        lo_f, hi_f = band_of[p.group]
        for ing, daily in effective[p.patient_id].items():
            if not daily or daily <= 0:
                continue
            registered[(p.patient_id, ing)] = daily
            # Tope para menores de 18, sin importar la dosis registrada.
            if (
                p.is_minor
                and minor_daily_cap_ui is not None
                and ing in MINOR_CAPPED_INGREDIENTS
                and daily > minor_daily_cap_ui
            ):
                daily = minor_daily_cap_ui
            applied[(p.patient_id, ing)] = daily
            need = daily * days
            entries.append(
                _Entry(
                    p.patient_id, ing, p.group, p.is_minor, need, need * lo_f, need * hi_f, need * MAX_COVERAGE,
                    daily=daily,
                )
            )

    needs_by_ing: Dict[str, float] = {}
    for e in entries:
        needs_by_ing[e.ing] = needs_by_ing.get(e.ing, 0.0) + e.need
    stock = {ing: sum(l.units * l.ui_per_unit for l in ls) for ing, ls in lots_by_ing.items()}
    total_stock = sum(stock.values())
    reserve_target = total_stock * reserve_pct
    reserve_by_ing = _split_reserve(stock, {k: needs_by_ing.get(k, 0.0) for k in stock}, reserve_target) if stock else {}

    avail: Dict[int, int] = {l.lot_id: l.units for ls in lots_by_ing.values() for l in ls}
    plan = DistributionPlan(
        days=days, reserve_pct=reserve_pct, total_stock_ui=total_stock, reserve_target_ui=reserve_target,
        reserve_ui=0.0, allocated_ui=0.0, group_choices=group_choices,
    )

    # Reserva y orden de lotes por insulina: se fijan antes de repartir nada.
    reserve_ui_by_ing: Dict[str, float] = {}
    minor_orders: Dict[str, _Order] = {}
    adult_orders: Dict[str, _Order] = {}
    for ing, ing_lots in lots_by_ing.items():
        reserved = _take_reserve(ing_lots, reserve_by_ing.get(ing, 0.0), avail, preferred_map.get(ing, ()))
        plan.reserve_lots.extend(reserved)
        reserve_ui_by_ing[ing] = sum(r.ui for r in reserved)
        plan.reserve_ui += reserve_ui_by_ing[ing]
        preferred = preferred_map.get(ing, ())
        base_order = sorted(ing_lots, key=_fefo_key)
        minor_class = {l.lot_id: (0 if _is_preferred(l, preferred) else 1) for l in base_order}
        adult_class = {l.lot_id: (1 if _is_preferred(l, preferred) else 0) for l in base_order}
        minor_orders[ing] = _Order(sorted(base_order, key=lambda l: minor_class[l.lot_id]), minor_class)
        adult_orders[ing] = _Order(sorted(base_order, key=lambda l: adult_class[l.lot_id]), adult_class)

    def order_for(entry: _Entry, ing: str) -> Sequence[LotInput]:
        orders = minor_orders if entry.is_minor else adult_orders
        return orders.get(ing, [])

    def candidates(entry: _Entry) -> List[Tuple[str, float]]:
        """Insulina propia primero y los sustitutos de la tabla en su orden."""
        out = [(entry.ing, 1.0)]
        if entry.is_minor and entry.ing in MINOR_KEEP_INSULINS:
            return out  # un menor mantiene su degludec: no se sustituye
        out += [(t, factor_of[(entry.ing, t)]) for t in targets_of.get(entry.ing, []) if t in lots_by_ing]
        return out

    def apply(entry: _Entry, ing: str, factor: float, combo: Dict[int, int]) -> float:
        """Entrega un combo y devuelve las UI de la insulina propia que cubre."""
        by_id = {l.lot_id: l for l in lots_by_ing.get(ing, [])}
        total = 0.0
        for lot_id, n in combo.items():
            lot = by_id[lot_id]
            avail[lot_id] -= n
            ui = n * lot.ui_per_unit
            total += ui
            plan.assignments.append(Assignment(entry.pid, lot_id, n, ui, entry.ing))
        equiv = total / factor
        if ing == entry.ing:
            entry.own += equiv
        else:
            slot = entry.subs.setdefault(ing, [0.0, 0.0])
            slot[0] += total
            slot[1] += equiv
        return equiv

    # Envase más chico de cada insulina en toda la donación (para la excepción del tope).
    min_size = {ing: min(l.ui_per_unit for l in ls) for ing, ls in lots_by_ing.items()}

    def smallest_pen_exception(entry: _Entry) -> None:
        """Dosis tan baja que ningún envase de la donación cabe en el 120 %: un solo envase, el más chico.

        Solo aplica si ningún tamaño de envase de su insulina ni de sus sustitutos cabe en el
        tope; si hay envases que caben pero se agotaron, no se entrega uno más grande.
        """
        if entry.covered > _EPS:
            return
        cands = [(ing, f) for ing, f in candidates(entry) if ing in min_size]
        if not cands or any(min_size[ing] / f <= entry.cap + _EPS for ing, f in cands):
            return
        for ing, factor in cands:
            size = min_size[ing]
            lot = next((l for l in order_for(entry, ing) if avail[l.lot_id] > 0 and l.ui_per_unit == size), None)
            if lot is not None:
                apply(entry, ing, factor, {lot.lot_id: 1})
                entry.min_pen = True
                return

    def one_pen(entry: _Entry) -> None:
        """Un envase para quien sigue en 0 %: de su insulina o del primer sustituto, sin pasar del 120 %."""
        if entry.covered > _EPS:
            return
        for ing, factor in candidates(entry):
            lot = _pick_one(order_for(entry, ing), avail, entry.lo * factor, entry.cap * factor)
            if lot is not None:
                apply(entry, ing, factor, {lot.lot_id: 1})
                return
        smallest_pen_exception(entry)

    def reach_min(entry: _Entry, in_band_only: bool = False) -> None:
        """Lleva la cobertura hasta el mínimo de la banda, sin pasar del máximo si se puede.

        Con `in_band_only` solo aplica las soluciones que caen dentro de la banda; las que
        pasan del máximo o se quedan cortas se dejan para una pasada posterior.
        """
        lo_x = entry.lo - entry.covered
        if lo_x <= _EPS:
            return
        hi_x = entry.hi - entry.covered
        cands = candidates(entry)
        # 1) una sola insulina que lo cubre dentro de la banda. Un menor conserva su insulina
        #    específica todo lo posible: solo ella en este paso y, si no alcanza, se completa abajo.
        for ing, factor in (cands[:1] if entry.is_minor else cands):
            res = _band_pick(order_for(entry, ing), avail, lo_x * factor, hi_x * factor, lo_x * factor)
            if res and res[2] == "in":
                apply(entry, ing, factor, res[0])
                return
        # 2) combinando insulinas (propia + sustituto) sin salirse de la banda: de cada una se
        #    toma lo que cabe y la última cierra dentro de la banda
        sim = dict(avail)
        steps: List[Tuple[str, float, Dict[int, int]]] = []
        rem_lo, rem_hi = lo_x, hi_x
        for ing, factor in cands:
            if rem_lo <= _EPS:
                break
            order = order_for(entry, ing)
            res = _band_pick(order, sim, rem_lo * factor, rem_hi * factor, rem_lo * factor)
            if res and res[2] != "in":
                res = None
            if res is None:
                # sola no alcanza la banda: se toma lo más grande que cabe bajo el máximo
                res = _band_pick(order, sim, 0.0, rem_hi * factor, rem_hi * factor)
                if res is None or res[2] != "in" or res[1] <= _EPS:
                    continue
            combo, total, _kind = res
            for lot_id, n in combo.items():
                sim[lot_id] -= n
            steps.append((ing, factor, combo))
            rem_lo -= total / factor
            rem_hi -= total / factor
        if rem_lo <= _EPS and steps:
            for ing, factor, combo in steps:
                apply(entry, ing, factor, combo)
            return
        if in_band_only:
            return
        # 3) una sola insulina que lo cubre aunque pase del máximo: gana la garantía del mínimo,
        #    pero nunca por encima del tope absoluto (120 %)
        cap_x = entry.cap - entry.covered
        above = []
        for ing, factor in cands:
            res = _band_pick(order_for(entry, ing), avail, lo_x * factor, hi_x * factor, lo_x * factor)
            if res and res[2] == "above" and res[1] / factor <= cap_x + _EPS:
                above.append((res[1] / factor, ing, factor, res[0]))
        if above:
            _t, ing, factor, combo = min(above, key=lambda x: x[0])
            apply(entry, ing, factor, combo)
            return
        # 3b) menores: si ninguna combinación cae entre su mínimo y el 120 %, se elige lo más
        #     cercano al 100 %: quedarse corto o el envase de más (aunque pase del 120 %).
        if entry.is_minor:
            over = None
            for ing, factor in cands:
                res = _band_pick(order_for(entry, ing), avail, lo_x * factor, hi_x * factor, lo_x * factor)
                if res and res[2] == "above" and (over is None or res[1] / factor < over[0]):
                    over = (res[1] / factor, ing, factor, res[0])
            if over is not None:
                sim = dict(avail)
                short, rem_hi = 0.0, hi_x
                for ing, factor in cands:
                    if short >= lo_x - _EPS:
                        break
                    res = _band_pick(order_for(entry, ing), sim, 0.0, rem_hi * factor, (lo_x - short) * factor)
                    if res and res[2] == "in":
                        for lot_id, n in res[0].items():
                            sim[lot_id] -= n
                        short += res[1] / factor
                        rem_hi -= res[1] / factor
                if abs(entry.covered + over[0] - entry.need) < abs(entry.covered + short - entry.need) - _EPS:
                    _t, ing, factor, combo = over
                    apply(entry, ing, factor, combo)
                    return
        # 4) mejor esfuerzo con lo que haya, en el orden de la tabla
        rem_lo, rem_hi = lo_x, hi_x
        for ing, factor in cands:
            if rem_lo <= _EPS:
                break
            res = _band_pick(order_for(entry, ing), avail, 0.0, rem_hi * factor, rem_lo * factor)
            if res and res[2] == "in":
                got = apply(entry, ing, factor, res[0])
                rem_lo -= got
                rem_hi -= got
        smallest_pen_exception(entry)

    def top_up(entry: _Entry) -> None:
        """Con lo que sobra, acerca la cobertura al 100 % sin pasar del máximo."""
        gap = entry.need - entry.covered
        if gap <= _EPS:
            return
        room = entry.hi - entry.covered
        cands = candidates(entry)
        # Un tratamiento ya iniciado se completa con las insulinas que ya usa: no se agrega otra
        # solo para acercarlo al 100 %.
        used = {ing for ing in entry.subs} | ({entry.ing} if entry.own > _EPS else set())
        if used:
            cands = [(ing, f) for ing, f in cands if ing in used]
        for ing, factor in cands:
            res = _band_pick(order_for(entry, ing), avail, 0.0, room * factor, gap * factor)
            if not res or res[2] != "in":  # lo que sobra no se usa para pasar del máximo
                continue
            combo, total, _kind = res
            added = total / factor
            if added > _EPS and abs(entry.covered + added - entry.need) < abs(entry.covered - entry.need) - _EPS:
                apply(entry, ing, factor, combo)
            return

    def vial_phase() -> None:
        """Antes que nada: un vial a cada tratamiento de insulina rápida con 14-20 UI/día.

        Va en orden de prioridad (menores, tipo 1, mayores, resto) y, dentro del grupo, primero
        a quien el vial le queda más cerca del 100 %. Se usa la insulina propia y, si no hay
        vial de ella, los sustitutos de la tabla (glulisina y regular no traen viales propios).
        Nunca se entrega un vial que lleve a alguien por encima del 120 %.
        """
        lo_dose, hi_dose = VIAL_DOSE_RANGE
        rapid = INSULIN_GROUPS[GROUP_RAPID]
        cands = [e for e in entries if e.ing in rapid and lo_dose - _EPS <= e.daily <= hi_dose + _EPS]
        cands.sort(key=lambda e: (e.group, abs(VIAL_MIN_UI / e.need - 1.0), e.pid, e.ing))
        for e in cands:
            for ing, factor in candidates(e):
                vials = [
                    l for l in order_for(e, ing) if avail[l.lot_id] > 0 and l.ui_per_unit >= VIAL_MIN_UI - _EPS
                ]
                for lot in vials:
                    if lot.ui_per_unit / factor <= e.cap + _EPS:
                        apply(e, ing, factor, {lot.lot_id: 1})
                        break
                else:
                    continue
                break

    vial_phase()

    def below_min_cause(entry: _Entry) -> Tuple[float, Optional[str]]:
        """UI que le faltan para su mínimo y la causa (con el stock que quedó al final)."""
        gap = entry.lo - entry.covered
        if gap <= 1e-6:
            return 0.0, None
        pens = [
            l.ui_per_unit / f
            for ing, f in candidates(entry)
            for l in lots_by_ing.get(ing, [])
            if avail[l.lot_id] + reserve_units.get(l.lot_id, 0) > 0  # libre o guardado en la reserva
        ]
        if not pens:
            return gap, "STOCK"
        if entry.covered + min(pens) > entry.cap + _EPS:
            return gap, "ENVASE"
        return gap, "OTRO"

    by_group: Dict[int, List[_Entry]] = {}
    for e in entries:
        by_group.setdefault(e.group, []).append(e)
    for members in by_group.values():
        members.sort(key=lambda e: (e.need, e.pid, e.ing))
    groups = sorted(by_group)

    reserve_units = {r.lot_id: r.units for r in plan.reserve_lots}
    lot_ingredient = {l.lot_id: ing for ing, ls in lots_by_ing.items() for l in ls}

    def resource_holder(holder: _Entry, given: str) -> bool:
        """Cambia a `holder` a otra insulina para liberar los envases de `given` que recibía como sustituto.

        Solo si queda dentro de su banda con lo que haya (libre o de la reserva) de una sola de
        sus otras alternativas. Devuelve True si el cambio se hizo.
        """
        factor_given = factor_of.get((holder.ing, given))
        if factor_given is None:
            return False
        taken = [
            a for a in plan.assignments
            if a.patient_id == holder.pid and a.for_ingredient == holder.ing and lot_ingredient.get(a.lot_id) == given
        ]
        if not taken:
            return False
        equiv = sum(a.ui for a in taken) / factor_given
        base = holder.covered - equiv
        lo_eq = max(0.0, holder.lo - base)
        hi_eq = max(holder.hi, holder.covered) - base
        if hi_eq <= _EPS:
            return False
        for ing2, f2 in candidates(holder):
            if ing2 == given:
                continue
            res = _band_pick(order_for(holder, ing2), avail, lo_eq * f2, hi_eq * f2, equiv * f2)
            if not res or res[2] != "in":
                continue
            for a in taken:
                avail[a.lot_id] += a.units
                plan.assignments.remove(a)
            holder.subs.pop(given, None)
            apply(holder, ing2, f2, res[0])
            return True
        return False

    def rescue_by_resourcing(entry: _Entry) -> None:
        """Quien sigue bajo su mínimo por falta de una insulina que otros reciben como sustituto.

        Los que la reciben como sustituto pasan a otra alternativa que sí hay (p. ej. detemir de la
        reserva) y sus envases quedan para este tratamiento. Nadie sale de su banda."""
        # Si ni el envase más chico cabe bajo el tope, mover envases de otros no sirve de nada.
        pens = [
            l.ui_per_unit / f
            for ing, f in candidates(entry)
            for l in lots_by_ing.get(ing, [])
        ]
        if not pens or entry.covered + min(pens) > entry.cap + _EPS:
            return
        saved = (
            dict(avail),
            list(plan.assignments),
            [(x, x.own, {k: list(v) for k, v in x.subs.items()}, x.min_pen) for x in entries],
        )
        for ing_x, _f in candidates(entry):
            holders = [h for h in entries if h is not entry and ing_x in h.subs and h.ing != ing_x]
            holders.sort(key=lambda h: (-h.group, -(h.covered - h.lo), h.pid))
            for h in holders:
                if entry.covered >= entry.lo - _EPS:
                    return
                if resource_holder(h, ing_x):
                    reach_min(entry)
        if entry.covered < entry.lo - _EPS:
            # No alcanzó: se deshace todo para no gastar reserva en cambios que no ayudan.
            avail.clear()
            avail.update(saved[0])
            plan.assignments[:] = saved[1]
            for x, own, subs, min_pen in saved[2]:
                x.own, x.subs, x.min_pen = own, subs, min_pen

    def release_reserve_phase() -> None:
        """Al final del reparto: la reserva cubre lo que falta para llegar al mínimo de cada banda.

        Solo reparte a quien sigue bajo su mínimo (en orden de prioridad) y con el menor número de
        envases; usa primero lo libre y recién después la reserva. Lo que no se usa vuelve a
        quedar guardado. Si falta una insulina que otros reciben como sustituto, ellos pasan a otra
        alternativa. No se completa hasta el 100 %: eso es `top_up`, que no toca la reserva.
        """
        if not release_reserve:
            return
        pending = [e for g in groups for e in by_group[g] if e.covered < e.lo - _EPS]
        if not pending:
            return
        for lot_id, n in reserve_units.items():
            avail[lot_id] += n
        for e in pending:
            reach_min(e)
        for e in pending:
            if e.covered < e.lo - _EPS:
                rescue_by_resourcing(e)
        for lot_id, n in reserve_units.items():
            keep = min(n, avail[lot_id])  # lo libre se gasta primero; la reserva es lo último
            avail[lot_id] -= keep
            reserve_units[lot_id] = keep

    # Menores y tipo 1: se les garantiza su banda completa, en ese orden, antes que a nadie más.
    top = [g for g in groups if g <= PRIORITY_TYPE1]
    rest = [g for g in groups if g > PRIORITY_TYPE1]
    for g in top:
        for e in by_group[g]:
            reach_min(e)
        if g == PRIORITY_MINOR:
            # La degludec de los menores se completa de una vez (hasta el 100 %, sin pasar del
            # máximo): así los demás grupos no la toman como sustituto antes de que la reciban entera.
            for e in by_group[g]:
                if e.ing in MINOR_KEEP_INSULINS:
                    top_up(e)
    # Resto de los grupos: primero a quien le cabe dentro de la banda, luego un envase a cada uno
    # (nadie queda en 0 % mientras haya envases) y solo después las garantías que obligan a pasar
    # del máximo o a repartir lo poco que queda.
    for g in rest:
        for e in by_group[g]:
            reach_min(e, in_band_only=True)
    for g in rest:
        for e in by_group[g]:
            one_pen(e)
    for g in rest:
        for e in by_group[g]:
            reach_min(e)
    release_reserve_phase()
    # Con lo que sobra, acercar a cada uno al 100 % (sin pasar del máximo), también en orden de prioridad.
    for g in groups:
        for e in by_group[g]:
            top_up(e)

    # ------------------------------------------------------------------ resultados
    subs_in: Dict[str, float] = {}
    subs_out: Dict[str, float] = {}
    needs_per_ing: Dict[str, Dict[int, float]] = {}
    unmet_count: Dict[str, int] = {}
    own_total: Dict[str, float] = {}
    for e in entries:
        lo_f, hi_f = band_of[e.group]
        cov = e.covered
        outside = cov < e.lo - 1e-6 or cov > e.hi + 1e-6
        names = list(e.subs)
        shortfall, cause = below_min_cause(e)
        plan.patients.setdefault(e.pid, []).append(
            PatientIngredientResult(
                ingredient=e.ing,
                need_ui=e.need,
                given_ui=e.own,
                substitute=" + ".join(names) if names else None,
                substitute_ui=sum(v[0] for v in e.subs.values()),
                substitute_equiv_ui=sum(v[1] for v in e.subs.values()),
                daily_registered=registered.get((e.pid, e.ing), 0.0),
                daily_applied=applied.get((e.pid, e.ing), 0.0),
                group=e.group,
                band_min=lo_f,
                band_max=hi_f,
                outside_band=outside,
                min_pen_exception=e.min_pen,
                min_shortfall_ui=shortfall,
                min_shortfall_cause=cause,
            )
        )
        needs_per_ing.setdefault(e.ing, {})[e.pid] = e.need
        own_total[e.ing] = own_total.get(e.ing, 0.0) + e.own
        for target, (ui, equiv) in e.subs.items():
            subs_in[target] = subs_in.get(target, 0.0) + ui
            subs_out[e.ing] = subs_out.get(e.ing, 0.0) + equiv
        if cov < e.lo - 1e-6:
            unmet_count[e.ing] = unmet_count.get(e.ing, 0) + 1

    for ing in sorted(set(lots_by_ing) | set(needs_per_ing)):
        demand = sum(needs_per_ing.get(ing, {}).values())
        own = own_total.get(ing, 0.0)
        delivered = own + subs_in.get(ing, 0.0)
        plan.allocated_ui += delivered
        plan.ingredients.append(
            IngredientSummary(
                ingredient=ing,
                stock_ui=stock.get(ing, 0.0),
                demand_ui=demand,
                reserve_ui=reserve_ui_by_ing.get(ing, 0.0),
                allocated_ui=delivered,
                unmet_ui=max(0.0, demand - own - subs_out.get(ing, 0.0)),
                leftover_ui=max(0.0, sum(avail[l.lot_id] * l.ui_per_unit for l in lots_by_ing.get(ing, []))),
                patients_with_need=len(needs_per_ing.get(ing, {})),
                patients_unmet=unmet_count.get(ing, 0),
                substituted_out_ui=subs_out.get(ing, 0.0),
                substituted_in_ui=subs_in.get(ing, 0.0),
            )
        )
    # Reserva que quedó guardada (la liberada ya se repartió a los tratamientos bajo su mínimo).
    released_by_ing: Dict[str, float] = {}
    kept_lots: List[ReserveLot] = []
    for r in plan.reserve_lots:
        keep = reserve_units.get(r.lot_id, r.units)
        per_unit = r.ui / r.units if r.units else 0.0
        released_by_ing[r.ingredient] = released_by_ing.get(r.ingredient, 0.0) + (r.units - keep) * per_unit
        if keep > 0:
            kept_lots.append(ReserveLot(r.lot_id, r.ingredient, r.label, keep, keep * per_unit))
    plan.reserve_lots = kept_lots
    plan.reserve_ui = sum(r.ui for r in kept_lots)
    plan.reserve_released_ui = sum(released_by_ing.values())
    for item in plan.ingredients:
        item.reserve_ui = sum(r.ui for r in kept_lots if r.ingredient == item.ingredient)
        item.reserve_released_ui = released_by_ing.get(item.ingredient, 0.0)
    plan.remaining_units = dict(avail)
    return plan
