"""Motor de reparto equitativo de insulinas (reglas vigentes del reporte de distribución).

Función pura (sin base de datos), con las mismas entradas y salidas que el motor anterior
(`app.core.insulin_distribution.plan_distribution`, que se conserva como `v1` para comparar):
recibe lotes y pacientes y devuelve un `DistributionPlan`.

Regla de cobertura (reglamento, art. 2): la Fundación procura cubrir entre el 75 % y el 100 % del requerimiento de
CADA beneficiario, sea menor, adulto mayor, tipo 1 o tipo 2. Cobertura = UI recibidas / UI necesarias en el periodo
(dosis diaria x 60 días). Por criterio de la Fundación nadie recibe más de 65 días de tratamiento (65/60 = 108,3 %).

Principios, en orden de precedencia:
  1. Nadie queda en 0 % ni bajo el 75 % (PROHIBIDO) siempre que el stock y el envase entero lo permitan. El reparto se resuelve de una sola vez con
     optimización entera (`equitable_milp`, scipy/HiGHS); si es imposible (la suma de los pisos de una insulina
     supera su stock) se informa cuánto falta (`DistributionPlan.minimum_gaps`) y el faltante se reparte parejo,
     protegiendo primero a menores y tipo 1. Sin scipy se usa un reparto aproximado que lo avisa y no puede
     garantizarlo (el reporte exige el reparto exacto: `require_optimizer`).
  2. Nadie pasa del tope de 65 días. Con envases enteros puede no existir ningún total entre el 75 % y los 65 días
     (8 UI/día = 480 UI con pens de 300: 1 pen = 62,5 %, 2 pens = 125 %): ahí no se pueden cumplir a la vez el piso y
     el tope. Decisión de la Fundación: el tope de 65 días manda y, solo en estos casos excepcionales, el tratamiento
     puede quedar bajo el 75 % con la menor diferencia posible (`envase_rule`). Se informan con la nota ENVASE_ENTERO
     y causa ENVASE: no son falta de insulina. Una dosis tan baja que ningún envase cabe en 65 días recibe un solo
     envase (ENVASE_MINIMO): nadie en 0 %.
  3. Prioridad cuando no alcanza: menores, tipo 1, adultos mayores con tipo 2 y el resto. Todos llegan primero a su
     piso, en ese orden, y solo después se completa hacia el 100 %.
  4. Sustitución protegida: una insulina solo se entrega como sustituto si eso no deja a otro bajo su piso.
  5. Reserva (3 % del total, definida por la Fundación): nunca se aparta de lo que necesitan los pisos de los grupos
     1 y 2 y se libera solo lo necesario para que nadie quede bajo su piso.
  6. Equidad: con escasez el faltante se reparte parejo entre los afectados, no por orden arbitrario.
  7. Auditoría: envases asignados + libres + reservados = stock de cada lote, en cada ejecución.

Tope de dosis en menores: 30 UI/día en glargina, lispro, glulisina, aspart, detemir y degludec (reglamento, art. 10: una
dosis superior al estándar médico exige respaldo médico). La dosis registrada queda en la nota `DOSIS_TOPADA`;
con `minor_dose_cap=None` no se topa y queda la nota `REVISION_CLINICA`.

Notas que puede llevar un tratamiento (`PatientIngredientResult.notes`): SUSTITUCION (en menores agrega «requiere aval
médico»), ENVASE_MINIMO, ENVASE_ENTERO, FICHA_POR_CORREGIR, REVISION_CLINICA, DOSIS_TOPADA, CEDIÓ_ENVASE_A_PRIORITARIO
y SIN_ASIGNACION.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from app.core import equitable_milp
from app.core.insulin_distribution import (
    DEFAULT_SUBSTITUTIONS,
    DISTRIBUTION_DAYS,
    GROUP_RAPID,
    INSULIN_GROUPS,
    MINOR_CAPPED_INGREDIENTS,
    MINOR_DAILY_CAP_UI,
    MINOR_KEEP_INSULINS,
    MINOR_PREFERRED_BRANDS,
    PREMIX_INSULINS,
    PREMIX_REPLACEABLE,
    RESERVE_PCT,
    Assignment,
    DistributionPlan,
    IngredientSummary,
    LotInput,
    MinimumGap,
    PatientIngredientResult,
    PatientInput,
    ReserveLot,
    Substitution,
    resolve_group_choices,
)

EPS = 1e-6

# Tabla de sustituciones del reporte: la de la Fundación (la misma que usa el reparto del almacén) más la Mixta,
# que puede reemplazarse por NPH, detemir o glargina (en ese orden). Se define aquí y no en `insulin_distribution`
# para no cambiar el reparto del almacén, que sigue con la tabla anterior. Factores 1:1 provisionales.
MIXTA_SUBSTITUTIONS: Tuple[Substitution, ...] = tuple(
    Substitution("Mixta", target, factor=1.0) for target in ("NPH", "Detemir", "Glargina")
)
EQUITABLE_SUBSTITUTIONS: Tuple[Substitution, ...] = tuple(DEFAULT_SUBSTITUTIONS) + MIXTA_SUBSTITUTIONS

# Pisos y techos por grupo de prioridad (fracción de la necesidad), también para mostrarlos.
# Reglamento (art. 2): la Fundación procura cubrir entre el 75 % y el 100 % del requerimiento de CADA beneficiario.
# Por criterio de la Fundación, además, nadie recibe más de 65 días de tratamiento (60 + 5), es decir 65/60 = 108,3 %.
PRIORITY_FLOOR: Dict[int, float] = {1: 0.75, 2: 0.75, 3: 0.75, 4: 0.75}
PRIORITY_CEILING: Dict[int, float] = {1: 1.00, 2: 1.00, 3: 1.00, 4: 1.00}
MAX_EXTRA_DAYS = 5  # días de más que se toleran sobre los 60 (tope de 65 días)
MAX_DAYS_FACTOR = (DISTRIBUTION_DAYS + MAX_EXTRA_DAYS) / DISTRIBUTION_DAYS
EQUITABLE_RESERVE_PCT = 0.03  # reserva definida por la Fundación (3 % del total)
# Margen que se muestra y se verifica: piso 75 % y tope de 65 días.
PRIORITY_BANDS: Dict[int, Tuple[float, float]] = {g: (PRIORITY_FLOOR[g], MAX_DAYS_FACTOR) for g in PRIORITY_FLOOR}


class OptimizerUnavailable(RuntimeError):
    """No hay optimizador (scipy) o no halló solución, y se exigió el reparto exacto."""


@dataclass
class DistributionConfig:
    days: int = DISTRIBUTION_DAYS
    reserve_pct: float = EQUITABLE_RESERVE_PCT
    floor: Dict[int, float] = field(default_factory=lambda: dict(PRIORITY_FLOOR))
    ceiling: Dict[int, float] = field(default_factory=lambda: dict(PRIORITY_CEILING))
    extra_days: int = MAX_EXTRA_DAYS  # tope duro: días + extra_days (65 días con el horizonte de 60)
    protected_groups: Tuple[int, ...] = (1, 2)  # su necesidad nunca se aparta como reserva
    # Grupos cuyo piso se garantiza aunque el envase pase del tope de 65 días. Ninguno: el tope manda y, si el envase
    # entero no permite llegar al piso sin pasarlo, el tratamiento queda bajo el piso por «envase» (se informa).
    floor_guarantee_groups: Tuple[int, ...] = ()
    minor_dose_cap: Optional[float] = MINOR_DAILY_CAP_UI  # 30 UI/día en menores; None = sin tope
    minor_dose_warning: float = 30.0  # sobre este valor, nota REVISION_CLINICA
    minor_max_coverage: Optional[float] = None  # None = sin límite a la sobrecobertura por envase
    capped_ingredients: frozenset = MINOR_CAPPED_INGREDIENTS
    preferred_brands: Optional[Dict[str, Tuple[str, ...]]] = None  # None = MINOR_PREFERRED_BRANDS
    max_sizes: int = 4  # tamaños de envase distintos por combinación
    vial_ui: float = 1000.0
    prefer_vial_rapid: bool = True
    vial_dose: Tuple[float, float] = (14.0, 20.0)  # UI/día de insulina rápida a las que se prefiere el vial
    expiry_warning_days: int = 60
    today: Optional[date] = None
    use_solver: bool = True  # asignación exacta (garantiza los pisos cuando es posible); False = reparto aproximado
    solver_time_limit: float = 90.0  # segundos en total para el optimizador
    # True: si no hay reparto exacto se lanza `OptimizerUnavailable` en vez de entregar un reparto aproximado que
    # puede romper las reglas (nadie en 0 % ni bajo su mínimo).
    require_optimizer: bool = False
    # Qué gana cuando los envases enteros no permiten caer entre el piso (75 %) y el tope (65 días), como 8 UI/día con
    # pens de 300 UI (1 pen = 62,5 %, 2 pens = 125 % = 75 días):
    #   "cap"     (por defecto, decisión de la Fundación) = el tope de 65 días manda y, en ese caso excepcional, el
    #             tratamiento puede quedar bajo el 75 % con la menor diferencia posible (el mayor total que cabe en 65
    #             días); se informa con la nota ENVASE_ENTERO;
    #   "floor"   = nadie bajo el 75 %: el menor total que lo alcanza aunque pase de 65 días;
    #   "closest" = la opción más cercana a la banda medida en días.
    # Una dosis tan baja que ningún envase cabe en 65 días recibe un envase que pasa del tope: nadie queda en 0 %.
    envase_rule: str = "cap"


@dataclass
class _Treatment:
    pid: int
    ing: str
    group: int
    dose_reg: float
    dose: float
    need: float
    floor: float
    ceil: float
    cap: float
    floor_nominal: float = 0.0  # 75 % de la necesidad (reglamento)
    structural: bool = False  # ningún conjunto de envases enteros cae entre el piso y el tope: `floor` es lo mejor posible
    upper_ext: float = 0.0  # si es > 0, el máximo que se le permite es este total (pasa del tope por el envase entero)
    cap_days: float = 0.0  # tope de 65 días (el de `cap` se amplía a `upper_ext` en los casos de envase entero)
    assigned: Dict[int, int] = field(default_factory=dict)  # lote -> envases
    ui: Dict[str, float] = field(default_factory=dict)  # insulina -> UI entregadas
    notes: List[str] = field(default_factory=list)
    min_pen: bool = False
    pend: float = 0.0  # UI que aún le faltan para el piso (ya contadas en `Engine.pend`)

    @property
    def cov_ui(self) -> float:
        return sum(self.ui.values())

    @property
    def cov(self) -> float:
        return self.cov_ui / self.need if self.need > 0 else 0.0


class _Engine:
    def __init__(
        self,
        lots: Sequence[LotInput],
        patients: Sequence[PatientInput],
        cfg: DistributionConfig,
        rules: Sequence[Substitution],
    ):
        self.cfg = cfg
        self.today = cfg.today or date.today()
        self.patients = patients
        self.preferred = MINOR_PREFERRED_BRANDS if cfg.preferred_brands is None else cfg.preferred_brands
        for rule in rules:
            if abs(rule.factor - 1.0) > EPS:
                raise ValueError("El motor equitativo usa factores de sustitución 1:1 (provisionales)")
            if (
                rule.target in PREMIX_INSULINS
                and rule.source not in PREMIX_INSULINS
                and rule.source not in PREMIX_REPLACEABLE
            ):
                raise ValueError(f"Una premezcla no puede sustituir a una basal ({rule.source} -> {rule.target})")
        self.rules = tuple(rules)
        self.targets_of: Dict[str, List[str]] = defaultdict(list)
        for r in rules:
            self.targets_of[r.source].append(r.target)
        self.rapid = INSULIN_GROUPS[GROUP_RAPID]

        self.lots: List[LotInput] = [l for l in lots if l.units > 0 and l.ui_per_unit > 0]
        self.lots_of: Dict[str, List[LotInput]] = defaultdict(list)
        for l in self.lots:
            self.lots_of[l.ingredient].append(l)
        self.avail: Dict[int, int] = {l.lot_id: l.units for l in self.lots}
        self.reserve: Dict[int, int] = {}
        self.reserve_initial_ui = 0.0
        self.reserve_released: Dict[str, float] = defaultdict(float)
        self.pend: Dict[Tuple[str, int], float] = defaultdict(float)  # (insulina, grupo) -> UI aún necesarias para el piso
        self.min_size: Dict[str, float] = {}
        for l in self.lots:
            self.min_size[l.ingredient] = min(self.min_size.get(l.ingredient, 1e18), l.ui_per_unit)
        self.treatments: List[_Treatment] = []
        self.group_choices: list = []
        self.warnings: List[str] = []
        self.optimizer_used = False

    # ------------------------------------------------------------------ utilidades
    def _pref(self, l: LotInput) -> bool:
        return any(fragment in l.label.lower() for fragment in self.preferred.get(l.ingredient, ()))

    def _lot_key(self, l: LotInput, group: int):
        p = self._pref(l)
        expiry = l.expiry.toordinal() if l.expiry else date.max.toordinal()
        # menores: la marca preferida primero; adultos: la preferida al final
        return ((0 if p else 1) if group == 1 else (1 if p else 0), expiry, l.lot_id)

    def _lots(self, ing: str, group: int, klass: Optional[str] = None) -> List[LotInput]:
        out = []
        for l in self.lots_of.get(ing, []):
            if self.avail[l.lot_id] <= 0:
                continue
            if klass == "pref":
                p = self._pref(l)
                if (group == 1 and not p) or (group != 1 and p):
                    continue
            out.append(l)
        out.sort(key=lambda l: self._lot_key(l, group))
        return out

    def _free_ui(self, ing: str) -> float:
        return sum(self.avail[l.lot_id] * l.ui_per_unit for l in self.lots_of.get(ing, []))

    def _slack(self, ing: str, exclude: Optional[_Treatment] = None, group: int = 4) -> float:
        """UI de `ing` que pueden darse como sustituto sin quitar lo que sus usuarios propios de
        igual o mayor prioridad (grupo <= `group`) todavía necesitan para llegar a su piso."""
        pend = sum(self.pend[(ing, g)] for g in range(1, group + 1))
        if exclude is not None and exclude.ing == ing and exclude.group <= group:
            pend -= exclude.pend
        return max(0.0, self._free_ui(ing) - pend)

    def _put(self, t: _Treatment, lot: LotInput, n: int) -> None:
        self.avail[lot.lot_id] -= n
        t.assigned[lot.lot_id] = t.assigned.get(lot.lot_id, 0) + n
        t.ui[lot.ingredient] = t.ui.get(lot.ingredient, 0.0) + n * lot.ui_per_unit
        self._update_pend(t)

    def _take_back(self, t: _Treatment, lot: LotInput, n: int) -> None:
        self.avail[lot.lot_id] += n
        t.assigned[lot.lot_id] -= n
        if t.assigned[lot.lot_id] <= 0:
            del t.assigned[lot.lot_id]
        t.ui[lot.ingredient] = t.ui.get(lot.ingredient, 0.0) - n * lot.ui_per_unit
        if t.ui[lot.ingredient] <= EPS:
            del t.ui[lot.ingredient]
        self._update_pend(t)

    def _clear(self, t: _Treatment) -> None:
        by_id = {l.lot_id: l for l in self.lots}
        for lot_id, n in list(t.assigned.items()):
            self._take_back(t, by_id[lot_id], n)
        t.min_pen = False

    def _update_pend(self, t: _Treatment) -> None:
        new = max(0.0, t.floor - t.cov_ui)
        self.pend[(t.ing, t.group)] += new - t.pend
        t.pend = new

    # ------------------------------------------------------------------ 1. preparación
    def prepare(self) -> None:
        cfg = self.cfg
        lots_by_ing = {ing: ls for ing, ls in self.lots_of.items() if ls}
        effective, self.group_choices = resolve_group_choices(
            self.patients,
            lots_by_ing,
            days=cfg.days,
            reserve_pct=cfg.reserve_pct,
            rules=self.rules,
            minor_daily_cap_ui=cfg.minor_dose_cap,
        )
        chosen = {(c.patient_id, c.chosen) for c in self.group_choices}
        for p in self.patients:
            g = p.group
            for ing, daily in sorted(effective[p.patient_id].items()):
                if not daily or daily <= 0:
                    continue
                dose = daily
                notes: List[str] = []
                if p.is_minor and ing in cfg.capped_ingredients:
                    if cfg.minor_dose_cap is not None and dose > cfg.minor_dose_cap:
                        dose = cfg.minor_dose_cap
                        notes.append(f"DOSIS_TOPADA ({daily:g}→{cfg.minor_dose_cap:g})")
                    elif dose > cfg.minor_dose_warning:
                        notes.append(f"REVISION_CLINICA (dosis > {cfg.minor_dose_warning:g} UI/día)")
                if (p.patient_id, ing) in chosen:
                    notes.append("FICHA_POR_CORREGIR")
                need = dose * cfg.days
                self.treatments.append(
                    _Treatment(
                        pid=p.patient_id, ing=ing, group=g, dose_reg=daily, dose=dose, need=need,
                        floor=need * cfg.floor[g], ceil=need * cfg.ceiling[g], cap=need + dose * cfg.extra_days,
                        floor_nominal=need * cfg.floor[g], cap_days=need + dose * cfg.extra_days, notes=notes,
                    )
                )
        for t in self.treatments:
            self._update_pend(t)
        no_stock: Dict[str, int] = defaultdict(int)
        for t in self.treatments:
            if t.ing not in self.lots_of:
                no_stock[t.ing] += 1
        for ing, n in sorted(no_stock.items()):
            self.warnings.append(f"Sin stock alguno de {ing}: {n} tratamiento(s) no tienen con qué cubrirse")
        for l in self.lots:
            if l.expiry and (l.expiry - self.today).days < cfg.expiry_warning_days:
                self.warnings.append(
                    f"El lote {l.lot_id} de {l.ingredient} ({l.label}) vence el {l.expiry} "
                    f"(menos de {cfg.expiry_warning_days} días): se entrega primero (FEFO)"
                )

    def _apply_envase_limits(self) -> None:
        """Con envases enteros puede no existir ningún total entre el piso (75 %) y el tope (65 días): 8 UI/día son
        480 UI y un pen de 300 UI es 62,5 % mientras dos pens son 125 %. Según `envase_rule`: "cap" (por defecto) manda el
        tope y el tratamiento queda con el mayor total que cabe en 65 días (la menor diferencia posible con el 75 %);
        "floor" nadie queda bajo el piso aunque pase del tope; "closest" elige la opción más cercana a la banda medida
        en días. El caso se informa con la nota ENVASE_ENTERO."""
        cfg = self.cfg
        for t in self.treatments:
            counts: Dict[float, int] = defaultdict(int)
            for ing in self._compatible(t):
                for l in self.lots_of.get(ing, []):
                    counts[l.ui_per_unit] += l.units
            if not counts:
                continue
            sizes = sorted(counts)[: cfg.max_sizes]
            upper = max(t.cap, min(sizes))
            limit = max(upper, t.floor_nominal) + max(sizes)
            usable = [(sz, min(counts[sz], int(limit // sz))) for sz in sizes if int(limit // sz) > 0]
            totals = self._totals(usable, limit)
            if any(x > EPS and t.floor_nominal - EPS <= x <= upper + EPS for x in totals):
                continue
            below = [x for x in totals if EPS < x < t.floor_nominal - EPS]
            above = [x for x in totals if x > upper + EPS]
            best_below = max(below) if below else None
            best_above = min(above) if above else None
            take_below = best_below is not None and (
                cfg.envase_rule == "cap"
                or best_above is None
                or (cfg.envase_rule == "closest" and (t.floor_nominal - best_below) <= (best_above - t.cap) + EPS)
            )
            if take_below:
                t.floor = best_below
                t.structural = True
            elif best_above is not None:
                t.upper_ext = best_above  # el piso no cambia: solo se le permite pasar del tope hasta este total
                t.cap = max(t.cap, best_above)
                t.structural = True
        self.pend.clear()
        for t in self.treatments:
            t.pend = 0.0
            self._update_pend(t)

    def _order(self, g: int) -> List[_Treatment]:
        return sorted((t for t in self.treatments if t.group == g), key=lambda t: (t.need, t.pid, t.ing))

    # ------------------------------------------------------------------ 2. reserva
    def reserve_stock(self) -> None:
        cfg = self.cfg
        stock: Dict[str, float] = defaultdict(float)
        for l in self.lots:
            stock[l.ingredient] += l.units * l.ui_per_unit
        total = sum(stock.values())
        target = cfg.reserve_pct * total
        need: Dict[str, float] = defaultdict(float)
        prot: Dict[str, float] = defaultdict(float)
        for t in self.treatments:
            need[t.ing] += t.need
            if t.group in cfg.protected_groups:
                prot[t.ing] += t.floor
        surplus = {i: max(0.0, stock[i] - need[i]) for i in stock}
        capmax = {i: max(0.0, stock[i] - prot[i]) for i in stock}
        total_surplus = sum(surplus.values())
        if total_surplus >= target and total_surplus > 0:
            part = {i: target * surplus[i] / total_surplus for i in stock}
        else:
            part = dict(surplus)
            rest = target - total_surplus
            room = {i: max(0.0, capmax[i] - surplus[i]) for i in stock}
            sr = sum(room.values())
            if sr > 0 and rest > 0:
                for i in stock:
                    part[i] += min(rest, sr) * room[i] / sr
        for ing in stock:
            kept = 0.0
            ordered = sorted(
                self.lots_of[ing],
                key=lambda l: (1 if self._pref(l) else 0, -(l.expiry.toordinal() if l.expiry else date.max.toordinal()), l.lot_id),
            )
            for l in ordered:
                while (
                    self.avail[l.lot_id] > 0
                    and kept < part.get(ing, 0) - EPS
                    and stock[ing] - kept - l.ui_per_unit >= prot[ing] - EPS
                ):
                    self.avail[l.lot_id] -= 1
                    self.reserve[l.lot_id] = self.reserve.get(l.lot_id, 0) + 1
                    kept += l.ui_per_unit
        by_id = {l.lot_id: l for l in self.lots}
        self.reserve_initial_ui = sum(by_id[i].ui_per_unit * n for i, n in self.reserve.items())
        self.stock = dict(stock)
        self.total_stock = total
        self.reserve_target = target

    # ------------------------------------------------------------------ 3. combinaciones de envases
    @staticmethod
    def _totals(counts: List[Tuple[float, int]], limit: float) -> dict:
        cur: dict = {0.0: (0, ())}
        for s, c in counts:
            nxt: dict = {}
            for tot, (np_, combo) in cur.items():
                for k in range(c + 1):
                    x = round(tot + k * s, 6)
                    if x > limit + EPS:
                        break
                    cand = (np_ + k, combo + ((s, k),))
                    if x not in nxt or cand[0] < nxt[x][0]:
                        nxt[x] = cand
            cur = nxt
        return cur

    def _options(self, t: _Treatment, ing: str, klass: Optional[str], max_ui: Optional[float] = None):
        """Totales alcanzables (UI -> (nº envases, combinación)) de `ing` para el tratamiento `t`."""
        if klass == "pref" and ing not in self.preferred:
            return None
        by_size: Dict[float, int] = defaultdict(int)
        for l in self._lots(ing, t.group, klass):
            by_size[l.ui_per_unit] += self.avail[l.lot_id]
        if not by_size:
            return {0.0: (0, ())}
        sizes = sorted(by_size)[: self.cfg.max_sizes]
        counts = []
        for s in sizes:
            c = by_size[s]
            if max_ui is not None:
                c = min(c, int(max_ui // s))
            if c > 0:
                counts.append((s, c))
        return self._totals(counts, t.cap + max(sizes))

    def _to_lots(self, t: _Treatment, ing: str, klass: Optional[str], combo) -> List[Tuple[LotInput, int]]:
        out = []
        ordered = self._lots(ing, t.group, klass)
        for size, k in combo:
            missing = k
            for l in ordered:
                if missing <= 0:
                    break
                if abs(l.ui_per_unit - size) > EPS:
                    continue
                n = min(missing, self.avail[l.lot_id])
                if n > 0:
                    out.append((l, n))
                    missing -= n
        return out

    def _candidates(self, t: _Treatment, with_subs: bool) -> List[Tuple[str, Optional[float]]]:
        """[(insulina, máx. UI utilizables)] empezando por la propia."""
        out: List[Tuple[str, Optional[float]]] = [(t.ing, None)]
        if with_subs and not (t.group == 1 and t.ing in MINOR_KEEP_INSULINS):
            for s in self.targets_of.get(t.ing, []):
                h = self._slack(s, exclude=t, group=t.group)
                if h > EPS:
                    out.append((s, h))
        return out

    @staticmethod
    def _in_band(x: float, lo: float, hi: float) -> bool:
        return x > EPS and lo - EPS <= x <= hi + EPS

    def _plan(self, t: _Treatment, mode: str, ideal: Optional[float] = None):
        """Líneas [(insulina, clase, combinación)] o None. `mode`: 'band' (solo dentro de la banda) | 'full'.

        `ideal` es el total al que se quiere acercar la combinación: la necesidad (por defecto) o el piso,
        cuando se reparte «piso primero» y solo se busca el menor total que lo alcance.
        """
        cfg = self.cfg
        lo, hi, cap = t.floor, t.ceil, t.cap
        ideal = t.need if ideal is None else ideal
        is_minor = t.group == 1
        guarantee = t.group in cfg.floor_guarantee_groups
        cands = self._candidates(t, with_subs=True)
        own = cands[0]
        # --- vial para insulina rápida de 14 a 20 UI/día
        if cfg.prefer_vial_rapid and t.ing in self.rapid and cfg.vial_dose[0] <= t.dose <= cfg.vial_dose[1]:
            for ing, mx in cands:
                if is_minor and ing != t.ing:
                    continue
                for l in self._lots(ing, t.group):
                    if (
                        l.ui_per_unit >= cfg.vial_ui - EPS
                        and lo - EPS <= l.ui_per_unit <= cap + EPS
                        and (mx is None or l.ui_per_unit <= mx + EPS)
                    ):
                        return [(ing, None, ((l.ui_per_unit, 1),))]
        # --- paso 1: una sola insulina dentro de la banda (menores: solo la propia)
        for ing, mx in [own] if is_minor else cands:
            for klass in ("pref", None):
                tot = self._options(t, ing, klass, mx)
                if tot is None:
                    continue
                band = [x for x in tot if self._in_band(x, lo, hi)]
                if band:
                    x = min(band, key=lambda x: (abs(x - ideal), tot[x][0]))
                    return [(ing, klass, tot[x][1])]
        # --- paso 2: propia + sustituto dentro de la banda
        own_tot = self._options(t, own[0], None, own[1])
        own_max = max(own_tot) if own_tot else 0.0
        best = None
        if own_max < lo - EPS or not is_minor:
            for ing, mx in cands[1:]:
                st = self._options(t, ing, None, mx)
                for a, (na, ca) in own_tot.items():
                    if a <= EPS:
                        continue
                    for b, (nb, cb) in st.items():
                        if b <= EPS:
                            continue
                        if self._in_band(a + b, lo, hi):
                            k = (abs(a + b - ideal), na + nb)
                            if best is None or k < best[0]:
                                best = (k, [(own[0], None, ca), (ing, None, cb)])
        if best and (own_max < lo - EPS or not is_minor):
            return best[1]
        if mode == "band":
            return None
        # --- paso 3: pasar del techo. Grupos con garantía: el menor total que alcance el piso
        if guarantee:
            limit = cfg.minor_max_coverage * t.need if cfg.minor_max_coverage else float("inf")
            over = [x for x in own_tot if x >= lo - EPS and x > EPS and x <= limit + EPS]
            if over:
                x = min(over, key=lambda x: (x, own_tot[x][0]))
                return [(own[0], None, own_tot[x][1])]
        else:
            best3 = None
            for rank, (ing, mx) in enumerate(cands):
                tot = self._options(t, ing, None, mx)
                for x in tot:
                    if hi + EPS < x <= cap + EPS:
                        k = (x, rank, tot[x][0])
                        if best3 is None or k < best3[0]:
                            best3 = (k, [(ing, None, tot[x][1])])
            if best3:
                return best3[1]
        # --- paso 3b (grupos con garantía): propia + sustituto cubriendo el piso con el menor exceso
        if guarantee and own_max < lo - EPS:
            best = None
            for ing, mx in cands[1:]:
                st = self._options(t, ing, None, mx)
                for a, (na, ca) in own_tot.items():
                    for b, (nb, cb) in st.items():
                        if a + b >= lo - EPS and a + b > EPS and (a > EPS or b > EPS):
                            k = (a + b, na + nb)
                            if best is None or k < best[0]:
                                best = (k, [(own[0], None, ca)] + ([(ing, None, cb)] if b > EPS else []))
            if best:
                return best[1]
        # --- paso 4: mejor esfuerzo con lo que haya, en el orden de la tabla
        lines, acc = [], 0.0
        for ing, mx in cands:
            tot = self._options(t, ing, None, mx)
            ok = [x for x in tot if x > EPS and acc + x <= hi + EPS]
            if ok:
                x = max(ok)
                lines.append((ing, None, tot[x][1]))
                acc += x
        if lines:
            return lines
        # --- excepción: ningún envase cabe; se da uno solo, el más chico
        for ing, mx in cands:
            for l in self._lots(ing, t.group):
                if abs(l.ui_per_unit - self.min_size.get(ing, 0)) < EPS and (mx is None or l.ui_per_unit <= mx + EPS):
                    t.min_pen = True
                    return [(ing, None, ((l.ui_per_unit, 1),))]
        return None

    def _apply(self, t: _Treatment, lines) -> None:
        for ing, klass, combo in lines:
            for lot, n in self._to_lots(t, ing, klass, combo):
                self._put(t, lot, n)

    def _serve(self, t: _Treatment, mode: str = "full", ideal: Optional[float] = None) -> bool:
        before = t.cov_ui
        old = dict(t.assigned)
        old_min = t.min_pen
        by_id = {l.lot_id: l for l in self.lots}
        if t.assigned:
            self._clear(t)
        t.min_pen = False
        lines = self._plan(t, mode, ideal)
        if lines:
            self._apply(t, lines)
        if (not lines or t.cov_ui <= EPS) or (old and t.cov_ui < before - EPS):
            self._clear(t)
            for lot_id, n in old.items():
                self._put(t, by_id[lot_id], n)
            t.min_pen = old_min
            return False
        return True

    def _one_pen(self, t: _Treatment) -> bool:
        """Un envase a quien sigue en 0 %: el que menos sobra sin pasar del tope."""
        missing = t.floor
        for ing, mx in self._candidates(t, with_subs=True):
            packs = [l for l in self._lots(ing, t.group) if mx is None or l.ui_per_unit <= mx + EPS]
            ok = [l for l in packs if l.ui_per_unit <= t.cap + EPS]
            if ok:
                cover = [l for l in ok if l.ui_per_unit >= missing - EPS]
                if cover:
                    l = min(cover, key=lambda l: (l.ui_per_unit, self._lot_key(l, t.group)))
                else:
                    l = max(ok, key=lambda l: (l.ui_per_unit, tuple(-x for x in self._lot_key(l, t.group))))
                self._put(t, l, 1)
                return True
        for ing, mx in self._candidates(t, with_subs=True):
            for l in self._lots(ing, t.group):
                if abs(l.ui_per_unit - self.min_size.get(ing, 0)) < EPS and (mx is None or l.ui_per_unit <= mx + EPS):
                    self._put(t, l, 1)
                    t.min_pen = True
                    return True
        return False

    def _add_toward_floor(self, t: _Treatment) -> bool:
        """Un envase más hacia el piso: el menor que lo alcanza, o el mayor que quepa bajo el tope."""
        missing = t.floor - t.cov_ui
        for ing, mx in self._candidates(t, with_subs=True):
            packs = [
                l for l in self._lots(ing, t.group)
                if (mx is None or l.ui_per_unit <= mx + EPS) and t.cov_ui + l.ui_per_unit <= t.cap + EPS
            ]
            if not packs:
                continue
            cover = [l for l in packs if l.ui_per_unit >= missing - EPS]
            if cover:
                l = min(cover, key=lambda l: (l.ui_per_unit, self._lot_key(l, t.group)))
            else:
                l = max(packs, key=lambda l: (l.ui_per_unit, tuple(-x for x in self._lot_key(l, t.group))))
            self._put(t, l, 1)
            return True
        return False

    def _progressive(self, treatments: List[_Treatment]) -> None:
        """Llenado progresivo: de a un envase por vuelta, empezando por el de menor cobertura."""
        changed = True
        while changed:
            changed = False
            pending = [t for t in treatments if t.cov_ui < t.floor - EPS]
            for t in sorted(pending, key=lambda t: (t.cov, t.group, t.need, t.pid, t.ing)):
                if self._add_toward_floor(t):
                    changed = True

    def _compatible(self, t: _Treatment) -> set:
        """Insulinas con las que se puede cubrir un tratamiento: la propia y sus sustitutos."""
        out = {t.ing}
        if not (t.group == 1 and t.ing in MINOR_KEEP_INSULINS):
            out |= set(self.targets_of.get(t.ing, []))
        return out

    def _reserved_ui(self, ing: str) -> float:
        return sum(n * l.ui_per_unit for l in self.lots_of.get(ing, []) for lot_id, n in self.reserve.items() if lot_id == l.lot_id)

    def _short_insulins(self) -> set:
        """Insulinas con las que es imposible que todos lleguen a su piso: el stock (libre y reservado, más lo que
        sus sustitutos tengan de sobra sobre sus propios pisos) no alcanza para la suma de los pisos."""
        floors: Dict[str, float] = defaultdict(float)
        for t in self.treatments:
            floors[t.ing] += t.floor
        have = {ing: self._free_ui(ing) + self._reserved_ui(ing) for ing in set(floors) | set(self.lots_of)}
        short = set()
        for ing, need in floors.items():
            slack = sum(max(0.0, have.get(s, 0.0) - floors.get(s, 0.0)) for s in self.targets_of.get(ing, []))
            if have.get(ing, 0.0) + slack < need - EPS:
                short.add(ing)
        return short

    def _equalize(self, ts: List[_Treatment]) -> None:
        """Con una insulina que no alcanza, pasa envases del que más cobertura tiene al que menos, mientras el
        receptor no quede por encima del donante: todos terminan con un porcentaje parecido."""
        by_id = {l.lot_id: l for l in self.lots}
        for _ in range(5000):
            ordered = sorted(ts, key=lambda t: (t.cov, t.group, t.need, t.pid))
            moved = False
            for r in ordered:
                for d in reversed(ordered):
                    if d is r or d.cov <= r.cov + EPS:
                        break
                    for lot_id in sorted(d.assigned, key=lambda i: by_id[i].ui_per_unit):
                        l = by_id[lot_id]
                        if l.ingredient != r.ing:
                            continue
                        d_after = (d.cov_ui - l.ui_per_unit) / d.need
                        r_after = (r.cov_ui + l.ui_per_unit) / r.need
                        if d_after > EPS and r_after <= d_after + EPS and r.cov_ui + l.ui_per_unit <= r.cap + EPS:
                            self._take_back(d, l, 1)
                            self._put(r, l, 1)
                            moved = True
                            break
                    if moved:
                        break
                if moved:
                    break
            if not moved:
                return

    def _share_equally(self, ing: str) -> None:
        """Insulina que no alcanza para todos: un envase a cada uno y luego se reparte parejo (menores y tipo 1 ya se sirvieron)."""
        ts = sorted((t for t in self.treatments if t.ing == ing and t.group > 2), key=lambda t: (t.group, t.need, t.pid))
        for t in ts:
            if t.cov_ui <= EPS:
                self._one_pen(t)
        self._progressive(ts)
        self._equalize(ts)

    # ------------------------------------------------------------------ completar hacia 100 %
    def _add_one(self, t: _Treatment) -> bool:
        used = list(t.ui) or [t.ing]
        if t.ing not in used:
            used.insert(0, t.ing)
        best = None
        for ing in used:
            slack = self._slack(ing, exclude=t)
            for l in self._lots(ing, t.group):
                if l.ui_per_unit > slack + EPS:
                    continue
                new = t.cov_ui + l.ui_per_unit
                if new <= t.ceil + EPS and abs(new - t.need) < abs(t.cov_ui - t.need) - EPS:
                    k = (abs(new - t.need), self._lot_key(l, t.group))
                    if best is None or k < best[0]:
                        best = (k, l)
        if best:
            self._put(t, best[1], 1)
            return True
        return False

    def complete(self) -> None:
        for g in (1, 2, 3, 4):
            tier = [t for t in self.treatments if t.group == g]
            changed = True
            while changed:
                changed = False
                for t in sorted(tier, key=lambda t: (t.cov, t.need, t.pid, t.ing)):
                    if t.cov_ui > EPS and self._add_one(t):
                        changed = True

    # ------------------------------------------------------------------ reserva liberada y rebalanceo
    def _below_floor(self, groups=(1, 2, 3, 4)) -> List[_Treatment]:
        return [t for g in groups for t in self._order(g) if t.cov_ui < t.floor - EPS]

    def settle(self) -> None:
        """Reserva liberada y reparto de las insulinas que no alcanzan.

        Los envases de la reserva vuelven al stock libre para que nadie quede bajo su piso ni en 0 %; lo que
        no se use se guarda de nuevo. Las insulinas que no alcanzan se reparten parejo con todo lo que hay."""
        pending = [t for t in self._below_floor() if t.ing not in self.short]
        if not (pending or self.short) or not (self.reserve or self.short):
            return
        by_id = {l.lot_id: l for l in self.lots}
        previous = dict(self.reserve)
        for lot_id, n in previous.items():
            self.avail[lot_id] += n
        self.reserve = {}
        for t in pending:
            self._serve(t, "full", ideal=t.floor)
        for ing in sorted(self.short):
            self._share_equally(ing)
        for lot_id, n in previous.items():  # lo que no se usó vuelve a guardarse (mismos lotes)
            back = min(n, self.avail[lot_id])
            if back > 0:
                self.avail[lot_id] -= back
                self.reserve[lot_id] = self.reserve.get(lot_id, 0) + back
        used: Dict[str, float] = defaultdict(float)
        for lot_id, n in previous.items():
            used[by_id[lot_id].ingredient] += (n - self.reserve.get(lot_id, 0)) * by_id[lot_id].ui_per_unit
        for ing, v in used.items():
            if v > EPS:
                self.reserve_released[ing] += v

    def repair_floors(self) -> None:
        """Quien sigue bajo su piso recibe envases de quienes tienen de más: el que cede nunca baja de su propio piso."""
        by_id = {l.lot_id: l for l in self.lots}
        for t in sorted(self._below_floor(), key=lambda t: (t.group, t.cov, t.pid, t.ing)):
            if t.ing in self.short:
                continue
            names = self._compatible(t)
            banned = set()
            guard = 0
            while t.cov_ui < t.floor - EPS and guard < 300:
                guard += 1
                donors = []
                for d in self.treatments:
                    if d is t:
                        continue
                    for lot_id in d.assigned:
                        l = by_id[lot_id]
                        if l.ingredient not in names or (d.pid, d.ing, lot_id) in banned:
                            continue
                        rest = d.cov_ui - l.ui_per_unit
                        if rest >= d.floor - EPS:
                            donors.append((-(rest - d.floor), -d.group, d.pid, lot_id, d))
                if not donors:
                    break
                donors.sort(key=lambda x: x[:4])
                _e, _g, _p, lot_id, d = donors[0]
                before = t.cov_ui
                self._take_back(d, by_id[lot_id], 1)
                self._serve(t, "full", ideal=t.floor)
                if t.cov_ui <= before + EPS:
                    self._put(d, by_id[lot_id], 1)  # no ayudó: se devuelve
                    banned.add((d.pid, d.ing, lot_id))
                elif d.group > t.group and "CEDIÓ_ENVASE_A_PRIORITARIO" not in d.notes:
                    d.notes.append("CEDIÓ_ENVASE_A_PRIORITARIO")

    def guard_zero(self) -> None:
        """Nadie se queda en 0 % mientras exista un envase con el que cubrirlo: si no hay libre, lo cede quien
        más cobertura tiene (que conserva al menos un envase y, si es de los grupos 1-2, su piso)."""
        by_id = {l.lot_id: l for l in self.lots}
        for t in sorted((t for t in self.treatments if t.cov_ui <= EPS), key=lambda t: (t.group, t.need, t.pid, t.ing)):
            if self._one_pen(t):
                continue
            names = self._compatible(t)
            best = None
            for d in self.treatments:
                if d is t or sum(d.assigned.values()) < 2:
                    continue
                for lot_id in d.assigned:
                    l = by_id[lot_id]
                    if l.ingredient not in names:
                        continue
                    d_after = (d.cov_ui - l.ui_per_unit) / d.need
                    if d.group <= 2 and d_after * d.need < d.floor - EPS:
                        continue
                    if d_after + EPS < l.ui_per_unit / t.need:
                        continue
                    if best is None or d_after > best[0]:
                        best = (d_after, d, l)
            if best is not None:
                _a, d, l = best
                self._take_back(d, l, 1)
                self._put(t, l, 1)
                if d.group > t.group and "CEDIÓ_ENVASE_A_PRIORITARIO" not in d.notes:
                    d.notes.append("CEDIÓ_ENVASE_A_PRIORITARIO")

    # ------------------------------------------------------------------ ejecución
    def run(self) -> DistributionPlan:
        self.prepare()
        self.reserve_stock()
        self._apply_envase_limits()
        self.short = self._short_insulins()
        if not (self.cfg.use_solver and self._run_optimal()):
            if self.cfg.require_optimizer:
                raise OptimizerUnavailable(
                    "No se pudo calcular el reparto exacto (falta el optimizador scipy o no halló solución)."
                )
            if self.cfg.use_solver:
                self.warnings.append(
                    "El optimizador no está disponible o no halló solución: se usó el reparto aproximado, "
                    "que no garantiza que todos lleguen a su mínimo."
                )
            self._run_greedy()
        self._verify()
        return self._result()

    def _run_greedy(self) -> None:
        # 1) Pisos primero: todos reciben el menor total que alcanza su piso, en orden de prioridad. Las
        #    insulinas que no alcanzan para todos se reparten parejo más abajo (salvo menores y tipo 1, que van primero).
        for g in (1, 2, 3, 4):
            for t in self._order(g):
                if g > 2 and t.ing in self.short:
                    continue
                self._serve(t, "full", ideal=t.floor)
        # 2) Reserva liberada y reparto parejo de lo que no alcanza.
        self.settle()
        # 3) Quien sigue bajo su piso recibe de quienes tienen de más; nadie queda en 0 % si hay un envase.
        self.repair_floors()
        self.guard_zero()
        # 4) Con lo que sobra, cada tratamiento se acerca a 100 % sin pasar del techo.
        self.complete()

    def _run_optimal(self) -> bool:
        """Asignación exacta de todos los envases (ver `equitable_milp`). False si no hay optimizador o solución."""
        cfg = self.cfg
        pools: List[equitable_milp.Pool] = []
        members: List[List[Tuple[LotInput, int]]] = []
        index: Dict[tuple, int] = {}
        for l in sorted(self.lots, key=lambda l: (l.expiry.toordinal() if l.expiry else date.max.toordinal(), l.lot_id)):
            for reserve, units in ((False, self.avail[l.lot_id]), (True, self.reserve.get(l.lot_id, 0))):
                if units <= 0:
                    continue
                key = (l.ingredient, l.ui_per_unit, self._pref(l), reserve)
                if key not in index:
                    index[key] = len(pools)
                    pools.append(equitable_milp.Pool(l.ingredient, l.ui_per_unit, self._pref(l), reserve, 0))
                    members.append([])
                pools[index[key]].count += units
                members[index[key]].append((l, units))
        items: List[equitable_milp.Item] = []
        lo_dose, hi_dose = cfg.vial_dose
        for i, t in enumerate(self.treatments):
            names = self._compatible(t)
            compat = [p for p, pool in enumerate(pools) if pool.ing in names]
            if not compat:
                continue
            sizes = [pools[p].size for p in compat]
            if t.group in cfg.floor_guarantee_groups:
                upper = max(t.cap, t.floor + max(sizes))
                if cfg.minor_max_coverage:
                    upper = max(t.cap, min(upper, cfg.minor_max_coverage * t.need))
            else:
                upper = max(t.cap, min(sizes), t.upper_ext)
            items.append(
                equitable_milp.Item(
                    idx=i, group=t.group, ing=t.ing, need=t.need, floor=t.floor, ceil=t.ceil, upper=upper,
                    is_minor=t.group == 1,
                    vial_pref=cfg.prefer_vial_rapid and t.ing in self.rapid and lo_dose <= t.dose <= hi_dose,
                    pools=compat,
                )
            )
        self.solver_stats = {}
        solution = equitable_milp.solve(items, pools, time_limit=cfg.solver_time_limit, stats=self.solver_stats)
        if solution is None:
            return False
        by_treatment: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
        for (ti, p), n in solution.items():
            by_treatment[ti].append((p, n))
        cursor = [[[l, u] for l, u in m] for m in members]  # envases que van quedando en cada pool, en orden FEFO
        order = sorted(by_treatment, key=lambda i: (self.treatments[i].group, self.treatments[i].need, self.treatments[i].pid, self.treatments[i].ing))
        for ti in order:
            t = self.treatments[ti]
            for p, n in sorted(by_treatment[ti]):
                missing = n
                for entry in cursor[p]:
                    lot, units = entry
                    if missing <= 0:
                        break
                    take = min(units, missing)
                    if take <= 0:
                        continue
                    if pools[p].reserve:  # la reserva se libera solo para esto
                        self.reserve[lot.lot_id] -= take
                        self.avail[lot.lot_id] += take
                        self.reserve_released[lot.ingredient] += take * lot.ui_per_unit
                    self._put(t, lot, take)
                    entry[1] -= take
                    missing -= take
        self.reserve = {k: v for k, v in self.reserve.items() if v > 0}
        self._trim()
        self.guard_zero()
        self.optimizer_used = True
        if not self.solver_stats.get("optimo_demostrado", True):
            self.warnings.append(
                "El optimizador agotó su tiempo: este es el mejor reparto que encontró, pero no está demostrado "
                "que sea el mejor posible."
            )
        return True

    def _trim(self) -> None:
        """El optimizador acepta una brecha pequeña: si a un tratamiento le quedó un envase de más sobre el techo,
        se lo quita siempre que siga en su piso y quede más cerca de su necesidad."""
        by_id = {l.lot_id: l for l in self.lots}
        for t in self.treatments:
            while t.cov_ui > t.ceil + EPS:
                best = None
                for lot_id in t.assigned:
                    l = by_id[lot_id]
                    new = t.cov_ui - l.ui_per_unit
                    if new >= t.floor - EPS and abs(new - t.need) < abs(t.cov_ui - t.need) - EPS:
                        if best is None or abs(new - t.need) < best[0]:
                            best = (abs(new - t.need), l)
                if best is None:
                    break
                self._take_back(t, best[1], 1)

    def _verify(self) -> None:
        for l in self.lots:
            assigned = sum(t.assigned.get(l.lot_id, 0) for t in self.treatments)
            total = assigned + self.avail[l.lot_id] + self.reserve.get(l.lot_id, 0)
            if total != l.units or self.avail[l.lot_id] < 0:
                raise AssertionError(f"Invariante de stock roto en el lote {l.lot_id}: {total} != {l.units}")

    # ------------------------------------------------------------------ resultado
    def _cause(self, t: _Treatment) -> str:
        ok = [t.ing] + ([] if (t.group == 1 and t.ing in MINOR_KEEP_INSULINS) else list(self.targets_of.get(t.ing, [])))
        free = [l for ing in ok for l in self.lots_of.get(ing, []) if self.avail[l.lot_id] > 0]
        if not free:
            return "STOCK"
        if min(l.ui_per_unit for l in free) > t.cap - t.cov_ui + EPS:
            return "ENVASE"
        return "OTRO"

    def _result(self) -> DistributionPlan:
        cfg = self.cfg
        by_id = {l.lot_id: l for l in self.lots}
        plan = DistributionPlan(
            days=cfg.days, reserve_pct=cfg.reserve_pct, total_stock_ui=self.total_stock,
            reserve_target_ui=self.reserve_target, reserve_ui=0.0, allocated_ui=0.0,
            group_choices=self.group_choices, warnings=list(self.warnings), optimizer_used=self.optimizer_used,
        )
        ordered = sorted(self.treatments, key=lambda t: (t.group, t.pid, t.ing))
        unmet: Dict[str, int] = defaultdict(int)
        for t in ordered:
            below = t.cov_ui < t.floor_nominal - EPS  # bajo el 75 % del reglamento
            short_stock = t.cov_ui < t.floor - EPS  # bajo lo que permitían los envases: falta de stock
            above = t.cov_ui > t.cap_days + EPS  # pasa de 65 días
            shortfall = max(0.0, t.floor_nominal - t.cov_ui)
            notes = list(t.notes)
            # un solo envase que pasa del tope porque ninguno cabía (dosis muy baja)
            min_pen = t.min_pen or (sum(t.assigned.values()) == 1 and t.cov_ui > t.cap_days + EPS)
            if min_pen:
                notes.append("ENVASE_MINIMO")
            if t.structural:
                notes.append("ENVASE_ENTERO")
            others = [i for i in t.ui if i != t.ing]
            if others:
                notes.append("SUSTITUCION" + (" (MENOR: requiere aval médico)" if t.group == 1 else ""))
            if t.cov_ui <= EPS:
                notes.append("SIN_ASIGNACION")
            plan.patients.setdefault(t.pid, []).append(
                PatientIngredientResult(
                    ingredient=t.ing,
                    need_ui=t.need,
                    given_ui=t.ui.get(t.ing, 0.0),
                    substitute=" + ".join(others) if others else None,
                    substitute_ui=sum(t.ui[i] for i in others),
                    substitute_equiv_ui=sum(t.ui[i] for i in others),
                    daily_registered=t.dose_reg,
                    daily_applied=t.dose,
                    group=t.group,
                    band_min=cfg.floor[t.group],
                    band_max=(t.cap_days / t.need) if t.need else 1.0,  # tope de 65 días
                    outside_band=below or above,
                    min_pen_exception=min_pen,
                    min_shortfall_ui=shortfall if below else 0.0,
                    min_shortfall_cause=(("ENVASE" if t.structural and not short_stock else self._cause(t)) if below else None),
                    notes=notes,
                )
            )
            for lot_id, n in sorted(t.assigned.items()):
                plan.assignments.append(Assignment(t.pid, lot_id, n, n * by_id[lot_id].ui_per_unit, t.ing))
            if below:
                unmet[t.ing] += 1

        kept: List[ReserveLot] = []
        for lot_id, n in sorted(self.reserve.items()):
            if n > 0:
                l = by_id[lot_id]
                kept.append(ReserveLot(lot_id, l.ingredient, l.label, n, n * l.ui_per_unit))
        plan.reserve_lots = kept
        plan.reserve_ui = sum(r.ui for r in kept)
        plan.reserve_released_ui = sum(self.reserve_released.values())

        stock = self.stock
        for ing in sorted(set(stock) | {t.ing for t in self.treatments}):
            own = [t for t in self.treatments if t.ing == ing]
            demand = sum(t.need for t in own)
            delivered = sum(t.ui.get(ing, 0.0) for t in self.treatments)
            plan.allocated_ui += delivered
            plan.ingredients.append(
                IngredientSummary(
                    ingredient=ing,
                    stock_ui=stock.get(ing, 0.0),
                    demand_ui=demand,
                    reserve_ui=sum(r.ui for r in kept if r.ingredient == ing),
                    allocated_ui=delivered,
                    unmet_ui=sum(max(0.0, t.need - t.cov_ui) for t in own),
                    leftover_ui=sum(self.avail[l.lot_id] * l.ui_per_unit for l in self.lots_of.get(ing, [])),
                    patients_with_need=len(own),
                    patients_unmet=unmet.get(ing, 0),
                    substituted_out_ui=sum(v for t in own for i, v in t.ui.items() if i != ing),
                    substituted_in_ui=sum(t.ui.get(ing, 0.0) for t in self.treatments if t.ing != ing),
                    reserve_released_ui=self.reserve_released.get(ing, 0.0),
                )
            )
        for ing in sorted({t.ing for t in self.treatments}):
            below = [t for t in self.treatments if t.ing == ing and t.cov_ui < t.floor - EPS]
            if not below:
                continue
            counts: Dict[float, int] = defaultdict(int)
            for l in self.lots_of.get(ing, []):
                counts[l.ui_per_unit] += l.units
            pen = max(counts, key=lambda size: (counts[size], size)) if counts else 0.0
            plan.minimum_gaps.append(
                MinimumGap(ing, sum(t.floor - t.cov_ui for t in below), len(below), pen)
            )
        plan.remaining_units = dict(self.avail)
        return plan


def plan_distribution(
    lots: Sequence[LotInput],
    patients: Sequence[PatientInput],
    *,
    days: Optional[int] = None,
    reserve_pct: Optional[float] = None,
    config: Optional[DistributionConfig] = None,
    substitutions: Optional[Sequence[Substitution]] = None,
) -> DistributionPlan:
    """Reparte la donación entre los pacientes. Ver el encabezado del módulo para las reglas."""
    cfg = config or DistributionConfig()
    if days is not None:
        cfg = DistributionConfig(**{**cfg.__dict__, "days": days})
    if reserve_pct is not None:
        cfg = DistributionConfig(**{**cfg.__dict__, "reserve_pct": reserve_pct})
    rules = EQUITABLE_SUBSTITUTIONS if substitutions is None else tuple(substitutions)
    return _Engine(lots, patients, cfg, rules).run()
