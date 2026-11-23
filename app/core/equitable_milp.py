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
# Tiempo máximo (s) de cada etapa: A (faltante sobre los pisos), B (repartir el faltante), C (acercar al 100 %).
STAGE_LIMIT = (45.0, 20.0, 25.0)
# Solo se reparte el faltante entre afectados (etapa B) si alguien queda a más de esta fracción de su piso.
MIN_SPREAD_SHORTFALL = 0.05
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


def _solve_block(
    items: Sequence[Item], pools: Sequence[Pool], *, deadline: float, stats: Optional[dict], label: str
) -> Optional[Tuple[Dict[Tuple[int, int], int], bool]]:
    """Resuelve un bloque de tratamientos y pools que no comparte nada con los demás."""
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

    # Tratamientos idénticos (mismo grupo, insulina, necesidad y pools) son intercambiables: se exige que reciban UI en
    # orden no creciente. No cambia el óptimo y evita que el optimizador pruebe las mismas soluciones permutadas.
    identical: Dict[tuple, List[Item]] = {}
    for it in items:
        key = (it.group, it.ing, it.need, it.floor, it.ceil, it.upper, it.is_minor, it.vial_pref, tuple(it.pools))
        identical.setdefault(key, []).append(it)
    for members in identical.values():
        for a, b in zip(members, members[1:]):
            ra = [(j, pools[var[j][1]].size) for j in by_item.get(a.idx, [])]
            rb = [(j, -pools[var[j][1]].size) for j in by_item.get(b.idx, [])]
            add_row(ra + rb, 0, np.inf)

    def run(c, extra_rows, stage, gap=1e-6, cap=45.0):
        nonlocal r, cidx, v, lo_b, up_b, nrows
        base = (len(r), nrows)
        for entries, lo, up in extra_rows:
            add_row(entries, lo, up)
        t0 = time.time()
        limit = max(1.0, min(cap, deadline - t0))  # nunca pasa del presupuesto total
        res = _solve(c, ((v, (r, cidx)), (nrows, n)), np.array(lo_b), np.array(up_b), lb, ub, integrality, limit, gap)
        if stats is not None:
            stats[f"{label}{stage}"] = {"segundos": round(time.time() - t0, 1), "estado": res.status, "brecha": getattr(res, "mip_gap", None)}
        del r[base[0]:], cidx[base[0]:], v[base[0]:], lo_b[base[1]:], up_b[base[1]:]
        nrows = base[1]
        return res

    short_row = [(iu + k, SHORTFALL_WEIGHT[it.group]) for k, it in enumerate(items)]

    def pick(res):
        return None if res.x is None else res.x

    def extract(x) -> Dict[Tuple[int, int], int]:
        out: Dict[Tuple[int, int], int] = {}
        for j, (ti, p) in enumerate(var):
            q = int(round(x[j]))
            if q > 0:
                out[(ti, p)] = q
        return out

    weights = np.array([SHORTFALL_WEIGHT[it.group] for it in items])
    floors = np.array([it.floor for it in items])

    # Etapa A: menor faltante ponderado sobre los pisos. Si agota su tiempo se usa la mejor solución hallada.
    cA = np.zeros(n)
    for j, w in short_row:
        cA[j] = w
    resA = run(cA, [], "A", cap=STAGE_LIMIT[0])
    xA = pick(resA)
    if xA is None:
        return None
    proved = resA.status == 0
    best = xA
    a_star = float(xA[iu : iu + nt] @ weights)
    cap_short = (short_row, 0, a_star + max(0.5, a_star * 1e-6))

    # Etapa B: si hay faltante inevitable y alguien queda lejos de su piso, repartirlo parejo (minimizar el mayor
    # faltante relativo al piso). Si el faltante es mínimo (p. ej. 5 UI en un tratamiento) no hace falta.
    m_star = 0.0
    spread = a_star > 0.5 and float((xA[iu : iu + nt] / floors).max()) > MIN_SPREAD_SHORTFALL
    if spread:
        cB = np.zeros(n)
        cB[iM] = 1.0
        resB = run(cB, [cap_short], "B", cap=STAGE_LIMIT[1])
        xB = pick(resB)
        if xB is not None:
            best = xB
            m_star = float(xB[iM])
        else:
            spread = False  # sin solución a tiempo: se queda con la de la etapa A

    # Etapa C: acercar a 100 %, preferir lo propio, la marca y la reserva solo para los pisos
    cC = np.zeros(n)
    for k, it in enumerate(items):
        for s_, (_w, cost) in enumerate(DEFICIT_SEGMENTS):
            cC[ie + k * K + s_] = DEFICIT_WEIGHT[it.group] * cost
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
    if spread:
        extra.append(([(iM, 1.0)], 0, m_star + 1e-4))
    # La etapa C solo mejora detalles (cercanía al 100 %, marcas): una brecha del 2 % basta y acota el tiempo.
    resC = run(cC, extra, "C", gap=2e-2, cap=STAGE_LIMIT[2])
    xC = pick(resC)
    if xC is not None:
        best = xC
    return extract(best), proved


def solve(
    items: Sequence[Item], pools: Sequence[Pool], *, time_limit: float = 90.0, stats: Optional[dict] = None
) -> Optional[Dict[Tuple[int, int], int]]:
    """{(tratamiento, pool): envases} o None si no hay optimizador o no se halló ninguna solución.

    El problema se parte en bloques independientes (p. ej. insulinas rápidas por un lado y basales por otro): cada uno
    se resuelve por separado, lo que lo hace mucho más rápido que resolverlo todo junto. `time_limit` es el presupuesto
    total en segundos: si una etapa lo agota se usa la mejor solución hallada y `stats["optimo_demostrado"]` queda en
    False.
    """
    if not HAS_SOLVER or not items:
        return None
    deadline = time.time() + time_limit
    # componentes conexos entre tratamientos y pools (union-find sobre los pools)
    parent = list(range(len(pools)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for it in items:
        for p in it.pools[1:]:
            parent[find(p)] = find(it.pools[0])
    blocks: Dict[int, List[Item]] = {}
    for it in items:
        blocks.setdefault(find(it.pools[0]), []).append(it)
    out: Dict[Tuple[int, int], int] = {}
    all_proved = True
    # los bloques chicos primero: así el grande dispone de lo que quede del presupuesto
    for n, root in enumerate(sorted(blocks, key=lambda r: len(blocks[r]))):
        block = blocks[root]
        used = sorted({p for it in block for p in it.pools})
        remap = {g: l for l, g in enumerate(used)}
        local_items = [
            Item(it.idx, it.group, it.ing, it.need, it.floor, it.ceil, it.upper, it.is_minor, it.vial_pref, [remap[p] for p in it.pools])
            for it in block
        ]
        res = _solve_block(local_items, [pools[g] for g in used], deadline=deadline, stats=stats, label=f"b{n}")
        if res is None:
            return None
        sol, proved = res
        all_proved = all_proved and proved
        for (ti, lp), q in sol.items():
            out[(ti, used[lp])] = q
    if stats is not None:
        stats["optimo_demostrado"] = all_proved
    return out
