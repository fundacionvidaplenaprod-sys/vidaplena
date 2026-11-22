"""Asignación exacta de envases para el motor equitativo (programación lineal entera con HiGHS, vía scipy).

El reparto envase por envase no puede garantizar que nadie quede bajo su piso: los envases enteros (un vial de
1.000 UI, un pen de 300) y la tabla de sustituciones hacen que un reparto «goloso» gaste insulina que otro
necesita para llegar a su mínimo. Este módulo resuelve el reparto completo como un problema de optimización:

  Etapa A  Menor faltante posible sobre los pisos (ponderado por grupo de prioridad). Si es 0, todos llegan a su
           piso; si no, el faltante es inevitable con este stock y se informa.
  Etapa B  (solo si hay faltante inevitable) reparte ese faltante lo más parejo posible entre los afectados:
           minimiza el mayor faltante relativo, de modo que nadie queda en 0 % mientras haya envases.
  Etapa C  Con esos resultados fijados, acerca a cada tratamiento al 100 % de su necesidad (priorizando los grupos
           de mayor prioridad y repartiendo parejo dentro de cada uno), prefiere la insulina propia a un sustituto,
           la marca preferida de los menores (Lantus) y el lote que vence antes, y solo usa la reserva para llegar
           a los pisos.

Si scipy no está instalado o el optimizador no encuentra solución a tiempo, `solve` devuelve None y el motor usa
su reparto aproximado, avisando que ya no garantiza los mínimos.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

try:  # scipy es opcional: sin él, el motor usa el reparto aproximado
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    HAS_SOLVER = True
except Exception:  # pragma: no cover - depende del entorno
    HAS_SOLVER = False

# Ponderación del faltante sobre el piso cuando es inevitable: se protege primero a los menores.
SHORTFALL_WEIGHT = {1: 1000.0, 2: 100.0, 3: 10.0, 4: 10.0}
# Ponderación de lo que falta para llegar al 100 %: los grupos de mayor prioridad se acercan primero.
DEFICIT_WEIGHT = {1: 5.0, 2: 4.0, 3: 2.0, 4: 1.0}
# Tramos de la penalización por quedar bajo el 100 % (ancho como fracción de la necesidad y costo creciente:
# la convexidad reparte el faltante en vez de concentrarlo en unos pocos).
DEFICIT_SEGMENTS = ((0.10, 1.0), (0.15, 2.0), (0.25, 4.0), (0.50, 8.0))
OVER_NEED_COST = 0.5  # pasar del 100 % hasta el techo
OVER_CEIL_COST = 20.0  # pasar del techo (solo por envase entero)
SUBSTITUTE_COST = 0.6  # por fracción de la necesidad cubierta con otra insulina
SUBSTITUTE_COST_MINOR = 3.0  # un sustituto en un menor requiere aval médico: solo si no hay otra salida
BRAND_COST = 0.02  # marca que no corresponde (Lantus a un adulto, otra marca a un menor), por fracción
RESERVE_COST = 50.0  # por envase de la reserva: solo se gasta si evita quedar bajo el piso
VIAL_BONUS = -5.0  # por vial: preferirlo a quien usa rápida con 14-20 UI/día (supera lo que cuesta pasar del techo)


@dataclass
class Pool:
    ing: str
    size: float
    preferred: bool  # marca preferida de los menores (Lantus)
    reserve: bool
    count: int


@dataclass
class Item:
    """Un tratamiento: lo que necesita y con qué pools se puede cubrir."""

    idx: int
    group: int
    ing: str
    need: float
    floor: float
    ceil: float
    upper: float  # máximo de UI que puede recibir
    is_minor: bool
    vial_pref: bool  # rápida con 14-20 UI/día
    pools: List[int]  # índices de pools compatibles (propia y sustitutos)


def _solve(c, rows, lbs, ubs, lb, ub, integrality, time_limit, gap):
    A = coo_matrix(rows[0], shape=rows[1]).tocsr()
    return milp(
        c=c,
        constraints=LinearConstraint(A, lbs, ubs),
        integrality=integrality,
        bounds=Bounds(lb, ub),
        options={"time_limit": time_limit, "mip_rel_gap": gap, "disp": False},
    )


def solve(
    items: Sequence[Item], pools: Sequence[Pool], *, time_limit: float = 60.0, stats: Optional[dict] = None
) -> Optional[Dict[Tuple[int, int], int]]:
    """{(tratamiento, pool): envases} o None si no hay optimizador o no se halló solución."""
    if not HAS_SOLVER or not items:
        return None
    nt, npool = len(items), len(pools)
    var: List[Tuple[int, int]] = [(it.idx, p) for it in items for p in it.pools]
    nx = len(var)
    K = len(DEFICIT_SEGMENTS)
    # índices de las variables: x | u | M | e (nt*K) | o1 | o2
    iu = nx
    iM = iu + nt
    ie = iM + 1
    io1 = ie + nt * K
    io2 = io1 + nt
    n = io2 + nt
    pos = {it.idx: k for k, it in enumerate(items)}

    lb = np.zeros(n)
    ub = np.full(n, np.inf)
    for k, (ti, p) in enumerate(var):
        it = items[pos[ti]]
        ub[k] = min(pools[p].count, int(it.upper // pools[p].size) + 1)
    for k, it in enumerate(items):
        ub[ie + k * K : ie + (k + 1) * K] = [w for w, _ in DEFICIT_SEGMENTS]
        ub[io1 + k] = max(0.0, it.ceil / it.need - 1.0)
    integrality = np.zeros(n)
    integrality[:nx] = 1

    r, cidx, v = [], [], []
    lo_b, up_b = [], []
    nrows = 0

    def add_row(entries, lo, up):
        nonlocal nrows
        for j, val in entries:
            r.append(nrows)
            cidx.append(j)
            v.append(val)
        lo_b.append(lo)
        up_b.append(up)
        nrows += 1

    by_item: Dict[int, List[int]] = {}
    by_pool: Dict[int, List[int]] = {}
    for k, (ti, p) in enumerate(var):
        by_item.setdefault(ti, []).append(k)
        by_pool.setdefault(p, []).append(k)
    for p, ks in by_pool.items():
        add_row([(k, 1.0) for k in ks], 0, pools[p].count)
    for k, it in enumerate(items):
        cov = [(j, pools[var[j][1]].size) for j in by_item.get(it.idx, [])]
        add_row(cov + [(iu + k, 1.0)], it.floor, np.inf)  # piso
        add_row(cov, 0, it.upper)  # tope
        add_row(cov + [(ie + k * K + s, it.need) for s in range(K)], it.need, np.inf)  # faltante al 100 %
        add_row(cov + [(io1 + k, -it.need), (io2 + k, -it.need)], -np.inf, it.need)  # sobrecobertura
        add_row([(iu + k, 1.0), (iM, -it.floor)], -np.inf, 0)  # faltante relativo al piso <= M

    def run(c, extra_rows, stage, gap=1e-6, limit=time_limit):
        nonlocal r, cidx, v, lo_b, up_b, nrows
        base = (len(r), nrows)
        for entries, lo, up in extra_rows:
            add_row(entries, lo, up)
        t0 = time.time()
        res = _solve(c, ((v, (r, cidx)), (nrows, n)), np.array(lo_b), np.array(up_b), lb, ub, integrality, limit, gap)
        if stats is not None:
            stats[stage] = {"segundos": round(time.time() - t0, 1), "estado": res.status, "brecha": getattr(res, "mip_gap", None)}
        del r[base[0]:], cidx[base[0]:], v[base[0]:], lo_b[base[1]:], up_b[base[1]:]
        nrows = base[1]
        return res

    short_row = [(iu + k, SHORTFALL_WEIGHT[it.group]) for k, it in enumerate(items)]

    # Etapa A: menor faltante ponderado sobre los pisos
    cA = np.zeros(n)
    for j, w in short_row:
        cA[j] = w
    resA = run(cA, [], "A")
    if resA.x is None:
        return None
    a_star = float(resA.x[iu : iu + nt] @ np.array([SHORTFALL_WEIGHT[it.group] for it in items]))
    cap_short = (short_row, 0, a_star + max(0.5, a_star * 1e-6))

    # Etapa B: si el faltante es inevitable, repartirlo parejo (minimizar el mayor faltante relativo al piso)
    m_star = 0.0
    if a_star > 0.5:
        cB = np.zeros(n)
        cB[iM] = 1.0
        resB = run(cB, [cap_short], "B")
        if resB.x is None:
            return None
        m_star = float(resB.x[iM])

    # Etapa C: acercar a 100 %, preferir lo propio, la marca y la reserva solo para los pisos
    cC = np.zeros(n)
    for k, it in enumerate(items):
        for s, (_w, cost) in enumerate(DEFICIT_SEGMENTS):
            cC[ie + k * K + s] = DEFICIT_WEIGHT[it.group] * cost
        cC[io1 + k] = OVER_NEED_COST
        cC[io2 + k] = OVER_CEIL_COST
    for j, (ti, p) in enumerate(var):
        it = items[pos[ti]]
        pool = pools[p]
        frac = pool.size / it.need
        cost = 0.0
        if pool.ing != it.ing:
            cost += (SUBSTITUTE_COST_MINOR if it.is_minor else SUBSTITUTE_COST) * frac
        if pool.preferred != it.is_minor:  # menores: marca preferida; adultos: las demás
            cost += BRAND_COST * frac
        if pool.reserve:
            cost += RESERVE_COST
        if it.vial_pref and pool.size >= 1000.0 - 1e-6 and pool.ing == it.ing:
            # primero a los grupos de mayor prioridad y a quien el vial le queda más cerca del 100 %
            cost += VIAL_BONUS - 0.5 * DEFICIT_WEIGHT[it.group] + 5.0 * abs(1.0 - frac)
        cC[j] = cost + 1e-6
    extra = [cap_short]
    if a_star > 0.5:
        extra.append(([(iM, 1.0)], 0, m_star + 1e-4))
    # La etapa C solo mejora detalles (cercanía al 100 %, marcas): una brecha del 2 % basta y acota el tiempo.
    resC = run(cC, extra, "C", gap=2e-2, limit=min(time_limit, 25.0))
    if resC.x is None:
        return None
    out: Dict[Tuple[int, int], int] = {}
    for j, (ti, p) in enumerate(var):
        q = int(round(resC.x[j]))
        if q > 0:
            out[(ti, p)] = q
    return out
