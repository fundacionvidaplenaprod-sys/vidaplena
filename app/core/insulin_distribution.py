"""Motor de reparto de insulinas de una donación.

Función pura (sin base de datos): recibe lotes y pacientes ya cargados y
devuelve el plan. Así se puede probar con cualquier escenario y el endpoint
solo se ocupa de traducir BD <-> motor.

Reglas:
  * Todo se calcula en UI (un envase de Toujeo U300 1,5 ml tiene 450 UI; uno
    de Lantus 3 ml, 300 UI) y recién al final se convierte a envases enteros.
  * Reserva: el 10 % del total de UI de la donación queda sin asignar. Se
    cubre primero con el sobrante de cada insulina (lo que nadie necesita) y
    el resto se descuenta proporcionalmente del stock que sí hace falta.
  * Prioridad: primero los menores de 18 años, luego los adultos con diabetes
    tipo 1 y al final el resto; cada grupo se sirve completo antes de pasar al
    siguiente. Si dentro de un grupo falta stock, se reparte en proporción a
    la necesidad de cada uno.
  * Marca preferida para menores (Lantus en glargina): los menores toman esa
    marca primero y los adultos la dejan para el final.
  * Dentro de cada preferencia se usa primero el lote que vence antes (FEFO).
  * Un beneficiario usa como máximo UNA insulina de cada grupo: rápidas (lispro, aspart,
    glulisina, regular) y basales/intermedias (glargina, protamina, NPH, detemir,
    degludec). Si la ficha trae dos del mismo grupo es un error de carga y se usa UNA,
    la que mejor se puede atender: la que tiene stock en la donación (con más holgura
    frente a la demanda), o la que se cubre con una sustitución conocida; sin stock de
    ninguna, la de mayor dosis registrada. El caso se informa para corregir la ficha
    (`resolve_group_choices`). Las sustituciones nunca salen de su grupo.
  * Una premezcla (`PREMIX_INSULINS`: protamina, Mix, bifásicas) nunca sustituye a una
    basal o intermedia: si la ficha trae una premezcla junto a una basal, se usa la
    basal aunque la premezcla tenga más stock, y ninguna regla de sustitución puede
    tener una premezcla como destino.
  * Menores y adultos tipo 1: se les garantiza el 100 % del tratamiento y se busca la
    combinación de envases que no pase del 120 % (`PRIORITY_MAX_COVERAGE`), probando
    envases de distinto tamaño. Si ninguna combinación cabe en 100-120 % —un pen de
    300 UI no se parte— gana la garantía: se entrega la de menor exceso sobre el 100 %.
  * Tope de dosis para menores de 18: en glargina, lispro, glulisina, aspart, detemir y
    degludec la dosis diaria no pasa de 30 UI sin importar lo registrado
    (`MINOR_DAILY_CAP_UI`); las demás insulinas no se limitan.
  * Redondeo: primero todos reciben los envases enteros que caben dentro de su
    necesidad (como mínimo uno); el envase extra que completa lo que falta se
    entrega al final, en orden de prioridad y solo con el stock que sobró. Así
    redondear hacia arriba nunca le quita stock a quien todavía no recibió lo
    suyo ni a las sustituciones; con stock de sobra el resultado es el mismo.
  * Sustitución (`DEFAULT_SUBSTITUTIONS`), siempre con el stock que quedó libre
    después de que todos recibieran su propia insulina y fuera de la reserva:
      - glargina -> detemir, solo adultos y **cambio completo**: un adulto recibe
        toda su glargina o todo su tratamiento en detemir, no una mezcla. Si el
        detemir no alcanza, lo que sobre de glargina se reparte parcialmente
        entre los adultos que quedaron sin cubrir;
      - glulisina -> aspart (menores y adultos) y regular -> lispro (todos),
        completando solo lo que falta.
    Lo que siga sin cubrirse queda reportado por insulina, que es la entrada de
    la futura tabla de equivalencias.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, Optional, Sequence, Tuple

DISTRIBUTION_DAYS = 60
RESERVE_PCT = 0.10
MINOR_AGE = 18
# insulina canónica -> fragmentos del nombre comercial que se reservan a menores
MINOR_PREFERRED_BRANDS: Dict[str, Tuple[str, ...]] = {"Glargina": ("lantus",)}
# Menores y adultos tipo 1: cobertura mínima garantizada y máxima permitida.
PRIORITY_MIN_COVERAGE = 1.0
PRIORITY_MAX_COVERAGE = 1.2
# Tope de dosis diaria (UI/día) para menores de 18, solo en estas insulinas.
MINOR_DAILY_CAP_UI = 30.0
# Grupos de insulina: un beneficiario usa una sola de cada grupo.
GROUP_RAPID = "RAPIDA"
GROUP_BASAL = "BASAL"
INSULIN_GROUPS: Dict[str, frozenset] = {
    GROUP_RAPID: frozenset({"Lispro", "Aspart", "Glulisina", "Regular"}),
    GROUP_BASAL: frozenset({"Glargina", "Protamina", "NPH", "Detemir", "Degludec"}),
}
# Premezclas: nunca reemplazan a una basal ni a una intermedia.
PREMIX_INSULINS = frozenset({"Protamina"})
GROUP_LABELS = {GROUP_RAPID: "rápidas", GROUP_BASAL: "basales / intermedias / premezclas"}
MINOR_CAPPED_INGREDIENTS = frozenset({"Glargina", "Lispro", "Glulisina", "Aspart", "Detemir", "Degludec"})

_EPS = 1e-6


@dataclass(frozen=True)
class Substitution:
    """`target` reemplaza a `source` cuando falta `source`.

    `factor` son las UI de `target` por cada UI de `source` que no se pudo dar.
    """

    source: str
    target: str
    factor: float = 1.0
    adults_only: bool = True
    # Cambio completo: un adulto recibe toda su `source` o todo en `target`.
    whole_switch: bool = False


# Reglas de la Fundación: adultos sin glargina pasan enteros a detemir, quien no
# tenga glulisina (menores incluidos) recibe aspart y quien no tenga insulina
# regular recibe lispro. Los factores 1:1 son provisionales y los debe validar el
# equipo médico; son el único dato clínico que hay que cambiar aquí cuando se
# defina la tabla de equivalencias.
DEFAULT_SUBSTITUTIONS: Tuple[Substitution, ...] = (
    Substitution("Glargina", "Detemir", factor=1.0, adults_only=True, whole_switch=True),
    Substitution("Glulisina", "Aspart", factor=1.0, adults_only=False),
    Substitution("Regular", "Lispro", factor=1.0, adults_only=False),
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
    reserve_lots: List[ReserveLot] = field(default_factory=list)
    ingredients: List[IngredientSummary] = field(default_factory=list)
    patients: Dict[int, List[PatientIngredientResult]] = field(default_factory=dict)
    group_choices: List[GroupChoice] = field(default_factory=list)


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


def is_type1_diabetes(raw: Optional[str]) -> bool:
    """Reconoce «Tipo 1», «TIPO 1», «tipo1», «Diabetes tipo I», «DM1»... (texto libre)."""
    text = unicodedata.normalize("NFD", (raw or "").strip().lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return bool(re.fullmatch(r"(diabetes\s*(mellitus\s*)?)?(tipo|tp|dm|t)\s*[-.]?\s*(1|i)", text))


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


def _take_reserve(lots: List[LotInput], reserve_ui: float, avail: Dict[int, int]) -> List[ReserveLot]:
    """Aparta envases enteros, empezando por los lotes que vencen más tarde."""
    reserved: List[ReserveLot] = []
    remaining = reserve_ui
    for lot in sorted(lots, key=_fefo_key, reverse=True):
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


def _best_pens(
    lots: Sequence[LotInput], avail: Dict[int, int], target_ui: float
) -> Optional[Dict[int, int]]:
    """Combinación de envases (de distinto tamaño) que cubre `target_ui` con el menor exceso.

    Devuelve {lot_id: envases} o None si el stock no alcanza. Desempata por menos envases,
    menos tamaños distintos y lotes que van antes en el orden dado.
    """
    by_size: Dict[float, List[LotInput]] = {}
    for lot in lots:
        if avail[lot.lot_id] > 0:
            by_size.setdefault(lot.ui_per_unit, []).append(lot)
    sizes = list(by_size)[:4]  # los 4 primeros en orden de preferencia bastan en la práctica
    if not sizes:
        return None
    caps = [sum(avail[l.lot_id] for l in by_size[sz]) for sz in sizes]
    if sum(c * sz for c, sz in zip(caps, sizes)) + _EPS < target_ui:
        return None
    limits = [min(c, math.ceil(target_ui / sz - 1e-9) + 1) for c, sz in zip(caps, sizes)]

    best_key = None
    best_counts = None

    def walk(idx: int, counts: List[int], total: float) -> None:
        nonlocal best_key, best_counts
        if idx == len(sizes):
            if total + _EPS < target_ui or total <= 0:
                return
            key = (round(total - target_ui, 6), sum(counts), sum(1 for c in counts if c), tuple(-c for c in counts))
            if best_key is None or key < best_key:
                best_key, best_counts = key, list(counts)
            return
        for c in range(limits[idx] + 1):
            walk(idx + 1, counts + [c], total + c * sizes[idx])

    walk(0, [], 0.0)
    if best_counts is None:
        return None
    result: Dict[int, int] = {}
    for sz, count in zip(sizes, best_counts):
        remaining = count
        for lot in by_size[sz]:  # dentro de un mismo tamaño, primero el que vence antes
            if remaining <= 0:
                break
            n = min(avail[lot.lot_id], remaining)
            if n > 0:
                result[lot.lot_id] = n
                remaining -= n
    return result


def _pick_one(ordered: List[LotInput], avail: Dict[int, int], rem: float) -> Optional[LotInput]:
    """Envase que menos sobra para cubrir `rem`; si ninguno alcanza solo, el más grande."""
    cands = [(k, l) for k, l in enumerate(ordered) if avail[l.lot_id] > 0]
    if not cands:
        return None
    fits = [(k, l) for k, l in cands if l.ui_per_unit + _EPS >= rem]
    if fits:
        return min(fits, key=lambda kl: (kl[1].ui_per_unit, kl[0]))[1]
    return max(cands, key=lambda kl: (kl[1].ui_per_unit, -kl[0]))[1]


def _choose_combo(
    ordered: Sequence[LotInput], avail: Dict[int, int], target_ui: float
) -> Optional[Dict[int, int]]:
    """Mejor combinación respetando la preferencia de marca.

    Se prueba primero solo con los lotes preferidos del grupo (p. ej. Lantus para menores);
    si ahí no hay una combinación dentro del 100-120 %, se amplía a todos los lotes y gana
    la de menor exceso. Con stock insuficiente devuelve None.
    """
    classes = getattr(ordered, "classes", None) or {}
    levels = sorted({classes.get(l.lot_id, 0) for l in ordered})
    best = None  # (dentro_de_ventana, exceso, nivel)
    best_combo = None
    for level in levels:
        subset = [l for l in ordered if classes.get(l.lot_id, 0) <= level and avail[l.lot_id] > 0]
        combo = _best_pens(subset, avail, target_ui)
        if combo is None:
            continue
        total = sum(avail_lot.ui_per_unit * combo.get(avail_lot.lot_id, 0) for avail_lot in subset)
        coverage = total / target_ui
        dentro = PRIORITY_MIN_COVERAGE - 1e-9 <= coverage <= PRIORITY_MAX_COVERAGE + 1e-9
        key = (0 if dentro else 1, 0 if dentro else coverage, level)
        if best is None or key < best:
            best, best_combo = key, combo
        if dentro:
            break  # ya cabe con los lotes preferidos: no se amplía
    return best_combo


def _draw(
    ordered: List[LotInput],
    avail: Dict[int, int],
    target_ui: float,
    round_up: bool,
) -> List[Tuple[LotInput, int]]:
    """Saca envases para llegar a `target_ui`.

    Primero los envases enteros que caben, en el orden dado (FEFO). Con `round_up`,
    lo que falte se completa con el envase que menos sobre en vez del primero de
    la lista, para no entregar de más (p. ej. un vial de 1.000 UI a quien le faltan 300).
    """
    taken: Dict[int, List] = {}

    def take(lot: LotInput, n: int) -> None:
        avail[lot.lot_id] -= n
        taken.setdefault(lot.lot_id, [lot, 0])[1] += n

    if round_up and target_ui > _EPS:
        combo = _choose_combo(ordered, avail, target_ui)
        if combo is not None:
            by_id = {lot.lot_id: lot for lot in ordered}
            for lot_id, n in combo.items():
                take(by_id[lot_id], n)
            return [(lot, n) for lot, n in taken.values()]

    remaining = target_ui
    for lot in ordered:
        if remaining <= _EPS:
            break
        have = avail[lot.lot_id]
        if have <= 0:
            continue
        n = min(math.floor(remaining / lot.ui_per_unit + 1e-9), have)
        if n > 0:
            take(lot, n)
            remaining -= n * lot.ui_per_unit
    while round_up and remaining > _EPS:
        lot = _pick_one(ordered, avail, remaining)
        if lot is None:
            break
        take(lot, 1)
        remaining -= lot.ui_per_unit
    return [(lot, n) for lot, n in taken.values()]


@dataclass
class _Deferral:
    """Resto de una necesidad que no llenó un envase entero y queda para el final."""

    pid: int
    source: str  # insulina que el paciente usa
    kind: str  # "own": se cubre con su propia insulina; "sub": con el sustituto
    rem_ui: float  # en UI de la insulina que se entrega
    order: List[LotInput]
    rank: int  # 0 menores, 1 adultos tipo 1, 2 resto
    rule: Optional[Substitution] = None


DeferFn = Optional[Callable[[int, float], None]]


def _base_draw(order: List[LotInput], avail: Dict[int, int], need: float) -> List[Tuple[LotInput, int]]:
    """Envases enteros que caben dentro de la necesidad (sin pasarse); al menos uno."""
    taken = _draw(order, avail, need, round_up=False)
    if taken:
        return taken
    lot = _pick_one(order, avail, need)
    if lot is None:
        return []
    avail[lot.lot_id] -= 1
    return [(lot, 1)]


def _allocate(
    order: List[LotInput],
    avail: Dict[int, int],
    needs: Dict[int, float],
    assignments: List[Assignment],
    for_ingredient: str,
    defer: DeferFn,
) -> Dict[int, float]:
    """Reparte un grupo de pacientes (todos con la misma prioridad) y devuelve UI por paciente.

    Si el stock libre alcanza hay dos modos. Con `defer=None` (grupos prioritarios)
    cada paciente recibe su tratamiento completo, con el último envase incluido.
    Con `defer` cada uno recibe primero los envases enteros que caben en su
    necesidad y el resto (menos de un envase) se aplaza: el envase extra solo se
    entrega al final, con lo que sobre, para que redondear hacia arriba no le quite
    stock a quien todavía no recibió lo suyo. Si no alcanza, se reparte en
    proporción a la necesidad y los envases que sobran del redondeo hacia abajo van
    a quien más le falta.
    """
    pids = sorted(needs)
    if not pids or not order:
        return {}
    total = sum(needs.values())
    free_ui = sum(avail[l.lot_id] * l.ui_per_unit for l in order)
    full = total <= free_ui + _EPS
    ratio = 1.0 if full else (free_ui / total if total else 0.0)
    got: Dict[int, float] = {}
    for pid in pids:
        got[pid] = 0.0
        if not full:
            taken = _draw(order, avail, needs[pid] * ratio, round_up=False)
        elif defer is None:
            taken = _draw(order, avail, needs[pid], round_up=True)
        else:
            taken = _base_draw(order, avail, needs[pid])
        for lot, n in taken:
            ui = n * lot.ui_per_unit
            got[pid] += ui
            assignments.append(Assignment(pid, lot.lot_id, n, ui, for_ingredient))
        if full and defer is not None and needs[pid] - got[pid] > _EPS:
            defer(pid, needs[pid] - got[pid])
    if not full:
        for pid in sorted(pids, key=lambda x: needs[x] - got[x], reverse=True):
            if needs[pid] - got[pid] <= _EPS:
                break
            for lot in order:
                if avail[lot.lot_id] > 0:
                    avail[lot.lot_id] -= 1
                    got[pid] += lot.ui_per_unit
                    assignments.append(Assignment(pid, lot.lot_id, 1, lot.ui_per_unit, for_ingredient))
                    break
            else:
                break
    return got


def _allocate_whole(
    order: List[LotInput],
    avail: Dict[int, int],
    needs: Dict[int, float],
    assignments: List[Assignment],
    for_ingredient: str,
    defer: DeferFn,
) -> Dict[int, float]:
    """Todo o nada: cada paciente recibe su necesidad completa o no recibe nada.

    Se recorre por id y se entrega a quien quepa entero en lo que queda, de modo
    que un paciente chico todavía puede entrar después de uno que no cupo. Igual
    que en `_allocate`, `defer=None` redondea de inmediato y con `defer` el envase
    extra se aplaza al final.
    """
    got: Dict[int, float] = {}
    for pid in sorted(needs):
        free_ui = sum(avail[lot.lot_id] * lot.ui_per_unit for lot in order)
        if free_ui + _EPS < needs[pid]:
            continue
        if defer is None:
            trial = {lot.lot_id: avail[lot.lot_id] for lot in order}
            taken = _draw(order, trial, needs[pid], round_up=True)
            if sum(n * lot.ui_per_unit for lot, n in taken) + _EPS < needs[pid]:
                continue  # no cabe entero con envases enteros
            avail.update(trial)
        else:
            taken = _base_draw(order, avail, needs[pid])
        ui = sum(n * lot.ui_per_unit for lot, n in taken)
        if not taken:
            continue
        for lot, n in taken:
            assignments.append(Assignment(pid, lot.lot_id, n, n * lot.ui_per_unit, for_ingredient))
        got[pid] = ui
        if defer is not None and needs[pid] - ui > _EPS:
            defer(pid, needs[pid] - ui)
    return got


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
    que se puede cubrir: primero con stock propio, luego con una sustitución conocida,
    y si ninguna, la de mayor dosis. La disponibilidad se mide frente a la demanda de
    quienes no tienen duda y se va descontando a medida que se decide, en orden de
    prioridad (menores, adultos tipo 1, resto).
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

    def rank(p: PatientInput) -> int:
        return 0 if p.is_minor else 1 if p.is_type1 else 2

    for p, group, options in sorted(pending, key=lambda x: (rank(x[0]), x[0].patient_id, x[1])):
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
                    if r.source != ing or (r.adults_only and p.is_minor):
                        continue
                    if surplus.get(r.target, 0.0) >= need * r.factor - _EPS:
                        via = r
                        break
            level = 0 if direct else 1 if via else 2
            # menor nivel = mejor; luego más holgura de stock y más dosis registrada
            scored.append(((level, -surplus.get(ing, 0.0), -dose, ing), ing, need, via, level))
        scored.sort(key=lambda x: x[0])
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


def plan_distribution(
    lots: Sequence[LotInput],
    patients: Sequence[PatientInput],
    *,
    days: int = DISTRIBUTION_DAYS,
    reserve_pct: float = RESERVE_PCT,
    minor_preferred_brands: Optional[Dict[str, Tuple[str, ...]]] = None,
    substitutions: Optional[Sequence[Substitution]] = None,
    minor_daily_cap_ui: Optional[float] = MINOR_DAILY_CAP_UI,
) -> DistributionPlan:
    preferred_map = MINOR_PREFERRED_BRANDS if minor_preferred_brands is None else minor_preferred_brands
    rules = DEFAULT_SUBSTITUTIONS if substitutions is None else tuple(substitutions)
    for rule in rules:
        if rule.target in PREMIX_INSULINS and rule.source not in PREMIX_INSULINS:
            raise ValueError(f"Una premezcla no puede sustituir a una basal ({rule.source} -> {rule.target})")

    lots_by_ing: Dict[str, List[LotInput]] = {}
    for lot in lots:
        if lot.units > 0 and lot.ui_per_unit > 0:
            lots_by_ing.setdefault(lot.ingredient, []).append(lot)

    needs: Dict[str, Dict[int, float]] = {}
    minors = {p.patient_id for p in patients if p.is_minor}
    # Adultos con diabetes tipo 1: segundo grupo de prioridad, después de los menores.
    type1_adults = {p.patient_id for p in patients if p.is_type1 and not p.is_minor}
    registered: Dict[Tuple[int, str], float] = {}
    applied: Dict[Tuple[int, str], float] = {}
    # Dos insulinas del mismo grupo es un error de la ficha: se usa una sola, la que se puede atender.
    effective, group_choices = resolve_group_choices(
        patients,
        lots_by_ing,
        days=days,
        reserve_pct=reserve_pct,
        rules=rules,
        minor_daily_cap_ui=minor_daily_cap_ui,
    )
    for p in patients:
        for ing, daily in effective[p.patient_id].items():
            if daily and daily > 0:
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
                needs.setdefault(ing, {})[p.patient_id] = daily * days

    stock = {ing: sum(l.units * l.ui_per_unit for l in ls) for ing, ls in lots_by_ing.items()}
    demand = {ing: sum(needs.get(ing, {}).values()) for ing in stock}
    total_stock = sum(stock.values())
    reserve_target = total_stock * reserve_pct
    reserve_by_ing = _split_reserve(stock, demand, reserve_target) if stock else {}

    avail: Dict[int, int] = {l.lot_id: l.units for ls in lots_by_ing.values() for l in ls}
    plan = DistributionPlan(
        group_choices=group_choices,
        days=days,
        reserve_pct=reserve_pct,
        total_stock_ui=total_stock,
        reserve_target_ui=reserve_target,
        reserve_ui=0.0,
        allocated_ui=0.0,
    )
    given: Dict[Tuple[int, str], float] = {}
    reserve_ui_by_ing: Dict[str, float] = {}
    all_ingredients = sorted(set(lots_by_ing) | set(needs))
    # Insulinas cuyos adultos pasan enteros al sustituto, si el sustituto existe en stock.
    whole_switch = {r.source for r in rules if r.whole_switch and lots_by_ing.get(r.target)}
    adult_orders: Dict[str, List[LotInput]] = {}
    deferrals: List[_Deferral] = []

    def rank_of(pid: int) -> int:
        return 0 if pid in minors else 1 if pid in type1_adults else 2

    # Reserva y orden de lotes por insulina: se fijan antes de repartir nada.
    minor_orders: Dict[str, List[LotInput]] = {}
    for ing in all_ingredients:
        ing_lots = lots_by_ing.get(ing, [])
        reserved = _take_reserve(ing_lots, reserve_by_ing.get(ing, 0.0), avail) if ing_lots else []
        plan.reserve_lots.extend(reserved)
        reserve_ui_by_ing[ing] = sum(r.ui for r in reserved)
        plan.reserve_ui += reserve_ui_by_ing[ing]

        preferred = preferred_map.get(ing, ())
        base_order = sorted(ing_lots, key=_fefo_key)
        minor_class = {l.lot_id: (0 if _is_preferred(l, preferred) else 1) for l in base_order}
        adult_class = {l.lot_id: (1 if _is_preferred(l, preferred) else 0) for l in base_order}
        minor_orders[ing] = _Order(sorted(base_order, key=lambda l: minor_class[l.lot_id]), minor_class)
        adult_orders[ing] = _Order(sorted(base_order, key=lambda l: adult_class[l.lot_id]), adult_class)

    def own_rounding(pid: int, ing: str) -> float:
        return sum(d.rem_ui for d in deferrals if d.pid == pid and d.source == ing and d.kind == "own")

    def sub_rounding(pid: int, ing: str) -> float:
        return sum(
            d.rem_ui / d.rule.factor for d in deferrals if d.pid == pid and d.source == ing and d.kind == "sub"
        )

    substituted: Dict[Tuple[int, str], Tuple[str, float, float]] = {}  # (pid, fuente) -> (destino, UI destino, UI fuente)
    substituted_out: Dict[str, float] = {}
    substituted_in: Dict[str, float] = {}

    # La prioridad vale entre insulinas, no solo dentro de cada una: un grupo completa
    # TODO su tratamiento (insulina propia y sustituciones) antes de que el siguiente
    # grupo toque el stock. Si no, los usuarios de aspart de menor prioridad dejaban sin
    # aspart sustituto a un menor con glulisina.
    for rank in (0, 1, 2):
        # A) Cada paciente del grupo recibe su propia insulina.
        for ing in all_ingredients:
            ing_needs = needs.get(ing, {})
            tier_needs = {pid: n for pid, n in ing_needs.items() if rank_of(pid) == rank}
            if not tier_needs:
                continue
            order = minor_orders[ing] if rank == 0 else adult_orders[ing]
            allocate = _allocate_whole if (rank != 0 and ing in whole_switch) else _allocate

            def defer_own(pid, rem, ing=ing, order=order, rank=rank):
                deferrals.append(_Deferral(pid, ing, "own", rem, order, rank))

            # Menores y adultos tipo 1 reciben su tratamiento completo de inmediato;
            # el redondeo del resto de adultos se aplaza.
            defer = defer_own if rank == 2 else None
            for pid, ui in allocate(order, avail, tier_needs, plan.assignments, ing, defer).items():
                given[(pid, ing)] = ui

        # B) Lo que les falta se completa con el sustituto, solo con stock libre (la
        #    reserva no se toca).
        for rule in rules:
            target_lots = sorted(lots_by_ing.get(rule.target, []), key=_fefo_key)
            pending = {}
            for pid, need in needs.get(rule.source, {}).items():
                if rank_of(pid) != rank or (rule.adults_only and pid in minors):
                    continue
                missing = need - given.get((pid, rule.source), 0.0) - own_rounding(pid, rule.source)
                if missing > _EPS:
                    pending[pid] = missing * rule.factor
            if not pending or not target_lots:
                continue

            def defer_sub(pid, rem, rule=rule, order=target_lots, rank=rank):
                deferrals.append(_Deferral(pid, rule.source, "sub", rem, order, rank, rule))

            defer = defer_sub if rank == 2 else None
            for pid, ui in _allocate(target_lots, avail, pending, plan.assignments, rule.source, defer).items():
                if ui <= 0:
                    continue
                equiv = ui / rule.factor
                substituted[(pid, rule.source)] = (rule.target, ui, equiv)
                substituted_out[rule.source] = substituted_out.get(rule.source, 0.0) + equiv
                substituted_in[rule.target] = substituted_in.get(rule.target, 0.0) + ui

        # C) Si el sustituto de un cambio completo no alcanzó, la glargina que sobró se
        #    reparte entre los adultos del grupo que quedaron sin cubrir (mejor parcial
        #    que nada).
        if rank == 0:
            continue
        for rule in rules:
            if rule.source not in whole_switch or not rule.whole_switch:
                continue
            unmet = {}
            for pid, need in needs.get(rule.source, {}).items():
                if rank_of(pid) != rank:
                    continue
                missing = (
                    need
                    - given.get((pid, rule.source), 0.0)
                    - substituted.get((pid, rule.source), ("", 0.0, 0.0))[2]
                    - own_rounding(pid, rule.source)
                    - sub_rounding(pid, rule.source)
                )
                if missing > _EPS:
                    unmet[pid] = missing
            if not unmet:
                continue

            def defer_rescue(pid, rem, rule=rule, rank=rank):
                deferrals.append(_Deferral(pid, rule.source, "own", rem, adult_orders[rule.source], rank))

            defer = defer_rescue if rank == 2 else None
            for pid, ui in _allocate(
                adult_orders[rule.source], avail, unmet, plan.assignments, rule.source, defer
            ).items():
                if ui > 0:
                    given[(pid, rule.source)] = given.get((pid, rule.source), 0.0) + ui

    # Último paso: el envase extra del redondeo, solo con el stock que sobró y en orden de prioridad.
    for d in sorted(deferrals, key=lambda x: (x.rank, x.pid, x.source, x.kind)):
        taken = _draw(d.order, avail, d.rem_ui, round_up=True)
        ui = sum(n * lot.ui_per_unit for lot, n in taken)
        if ui <= 0:
            continue
        for lot, n in taken:
            plan.assignments.append(Assignment(d.pid, lot.lot_id, n, n * lot.ui_per_unit, d.source))
        if d.kind == "own":
            given[(d.pid, d.source)] = given.get((d.pid, d.source), 0.0) + ui
        else:
            target, prev_ui, prev_equiv = substituted[(d.pid, d.source)]
            extra_equiv = ui / d.rule.factor
            substituted[(d.pid, d.source)] = (target, prev_ui + ui, prev_equiv + extra_equiv)
            substituted_out[d.source] = substituted_out.get(d.source, 0.0) + extra_equiv
            substituted_in[target] = substituted_in.get(target, 0.0) + ui

    # Un mismo paciente puede recibir del mismo lote en varias pasadas: se junta en una fila.
    merged: Dict[Tuple[int, int, str], Assignment] = {}
    for a in plan.assignments:
        key = (a.patient_id, a.lot_id, a.for_ingredient)
        if key in merged:
            merged[key].units += a.units
            merged[key].ui += a.ui
        else:
            merged[key] = Assignment(a.patient_id, a.lot_id, a.units, a.ui, a.for_ingredient)
    plan.assignments = list(merged.values())

    # Resúmenes por insulina con el stock ya definitivo.
    for ing in all_ingredients:
        ing_lots = lots_by_ing.get(ing, [])
        ing_needs = needs.get(ing, {})
        own_ui = sum(ui for (pid, i), ui in given.items() if i == ing)
        covered_by_other = substituted_out.get(ing, 0.0)
        unmet_patients = sum(
            1
            for pid, need in ing_needs.items()
            if need - given.get((pid, ing), 0.0) - substituted.get((pid, ing), ("", 0.0, 0.0))[2] > _EPS
        )
        delivered = own_ui + substituted_in.get(ing, 0.0)
        plan.allocated_ui += delivered
        plan.ingredients.append(
            IngredientSummary(
                ingredient=ing,
                stock_ui=stock.get(ing, 0.0),
                demand_ui=sum(ing_needs.values()),
                reserve_ui=reserve_ui_by_ing.get(ing, 0.0),
                allocated_ui=delivered,
                unmet_ui=max(0.0, sum(ing_needs.values()) - own_ui - covered_by_other),
                leftover_ui=max(0.0, sum(avail[l.lot_id] * l.ui_per_unit for l in ing_lots)),
                patients_with_need=len(ing_needs),
                patients_unmet=unmet_patients,
                substituted_out_ui=covered_by_other,
                substituted_in_ui=substituted_in.get(ing, 0.0),
            )
        )

    for ing, per_patient in needs.items():
        for pid, need in per_patient.items():
            target, ui, equiv = substituted.get((pid, ing), (None, 0.0, 0.0))
            plan.patients.setdefault(pid, []).append(
                PatientIngredientResult(
                    ing,
                    need,
                    given.get((pid, ing), 0.0),
                    target,
                    ui,
                    equiv,
                    registered.get((pid, ing), 0.0),
                    applied.get((pid, ing), 0.0),
                )
            )
    return plan
