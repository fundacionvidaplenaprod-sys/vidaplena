"""Pruebas del motor de reparto equitativo (reglas vigentes del reporte de distribución)."""
import random
import sys
from datetime import date, timedelta

import pytest

from app.core import equitable_milp
from app.core.equitable_distribution import (
    DistributionConfig,
    PRIORITY_BANDS,
    plan_distribution,
)
from app.core.insulin_distribution import LotInput, PatientInput, is_type1_diabetes, priority_group_for

USE_SOLVER = False  # lo fija el fixture `modo`


@pytest.fixture(params=["aproximado", "exacto"], autouse=True)
def modo(request, monkeypatch):
    """Cada prueba corre con el reparto aproximado y con el optimizador (si scipy está instalado)."""
    if request.param == "exacto" and not equitable_milp.HAS_SOLVER:
        pytest.skip("scipy no está instalado: no hay optimizador")
    monkeypatch.setattr(sys.modules[__name__], "USE_SOLVER", request.param == "exacto")


HOY = date(2026, 11, 19)
VENCE = date(2028, 6, 30)


def lote(lot_id, ing, ui, cantidad, label=None, vence=VENCE):
    return LotInput(lot_id, ing, label or ing, ui, cantidad, vence)


def benef(pid, edad, tipo, ing, dosis=None):
    daily = dict(ing) if isinstance(ing, list) else {ing: dosis}
    tipo = {"1": "Tipo 1", "2": "Tipo 2"}.get(tipo, tipo)
    return PatientInput(
        pid,
        edad is not None and edad < 18,
        daily,
        is_type1=is_type1_diabetes(tipo),
        priority_group=priority_group_for(edad, tipo),
    )


def correr(lotes, bens, **kw):
    kw.setdefault("config", DistributionConfig(today=HOY, use_solver=USE_SOLVER))
    return plan_distribution(lotes, bens, **kw)


def res(plan, pid, ing=None):
    for r in plan.patients[pid]:
        if ing is None or r.ingredient == ing:
            return r
    raise KeyError(pid)


def cov(plan, pid, ing=None):
    r = res(plan, pid, ing)
    return (r.given_ui + r.substitute_equiv_ui) / r.need_ui


def entregado(plan, pid, ing=None):
    r = res(plan, pid, ing)
    return r.given_ui + r.substitute_equiv_ui


def test_bands_are_the_new_ones():
    # Reglamento art. 2: 75-100 % para todos. Criterio de la Fundación: nadie pasa de 65 días (65/60 = 108,3 %).
    assert PRIORITY_BANDS == {g: (0.75, pytest.approx(65 / 60)) for g in (1, 2, 3, 4)}


# ---------------------------------------------------------------- prioridad de menores
def test_8_ui_a_day_cannot_fit_the_band_so_the_cap_wins_with_the_smallest_difference():
    # 480 UI: un pen de 300 es 62,5 % (bajo el 75 %) y dos son 125 % (75 días, sobre el tope de 65). Decisión de la
    # Fundación: manda el tope y, en este caso excepcional, queda bajo el 75 % con la menor diferencia posible (1 pen).
    for kind in ("1", "2"):
        plan = correr([lote(1, "Glargina", 300, 50)], [benef(1, 10, kind, "Glargina", 8)])
        r = res(plan, 1)
        assert entregado(plan, 1) == 300 and "ENVASE_ENTERO" in r.notes
        assert r.min_shortfall_cause == "ENVASE" and round(r.min_shortfall_ui) == 60  # 360 - 300 UI
        assert not plan.minimum_gaps  # no es falta de stock


def test_the_65_day_cap_wins_by_default_when_the_envase_does_not_fit_the_band():
    # 540 UI (9 UI/día): 1 pen = 55,6 % y 2 pens = 111 % (66,7 días). Por defecto manda el tope: 1 pen, con la menor
    # diferencia posible con el 75 % (el mayor total que cabe en 65 días).
    lotes = [lote(1, "Glargina", 300, 50)]
    b = [benef(1, 45, "2", "Glargina", 9)]
    plan = correr(lotes, b, reserve_pct=0.0)
    assert entregado(plan, 1) == 300 and res(plan, 1).min_shortfall_cause == "ENVASE" and not plan.minimum_gaps
    # Otras reglas, solo si la Fundación las pide: nadie bajo el 75 % (2 pens) o la opción más cercana a la banda.
    for rule, expected in (("floor", 600), ("closest", 600)):
        cfg = DistributionConfig(today=HOY, use_solver=USE_SOLVER, envase_rule=rule)
        assert entregado(correr(lotes, b, reserve_pct=0.0, config=cfg), 1) == expected, rule


def test_minors_are_covered_first_even_with_scarcity_and_adult_pressure():
    lotes = [lote(1, "Glargina", 300, 40, label="Lantus"), lote(2, "Detemir", 300, 40)]
    bens = [benef(i, 10, "1", "Glargina", 20) for i in range(1, 6)]  # 5 x 1.200 = 6.000 UI
    bens += [benef(100 + i, 40, "2", "Glargina", 30) for i in range(40)]  # 72.000 UI de necesidad
    plan = correr(lotes, bens)
    for i in range(1, 6):
        assert cov(plan, i) >= 0.75 - 1e-9
        assert res(plan, i).substitute is None


def test_reserve_does_not_reduce_minors_below_their_floor():
    lotes = [lote(1, "Glargina", 300, 6)]  # 1.800 UI: alcanza justo para el 75 % de dos menores (900 cada uno)
    bens = [benef(1, 8, "1", "Glargina", 20), benef(2, 9, "1", "Glargina", 20)]
    plan = correr(lotes, bens)
    assert cov(plan, 1) >= 0.75 and cov(plan, 2) >= 0.75
    assert plan.reserve_ui == 0


def test_the_default_reserve_is_3_percent():
    plan = correr([lote(1, "NPH", 300, 100)], [benef(1, 45, "2", "NPH", 10)], config=DistributionConfig(today=HOY, use_solver=USE_SOLVER))
    assert plan.reserve_pct == 0.03 and plan.reserve_target_ui == pytest.approx(0.03 * 30000)


def test_lantus_is_left_to_minors_and_adults_use_other_brands():
    lotes = [lote(1, "Glargina", 300, 10, label="Lantus"), lote(2, "Glargina", 300, 10, label="Abasaglar")]
    bens = [benef(1, 12, "1", "Glargina", 10), benef(2, 45, "2", "Glargina", 10)]
    plan = correr(lotes, bens)
    by_patient = {}
    for a in plan.assignments:
        by_patient.setdefault(a.patient_id, set()).add(a.lot_id)
    assert by_patient[1] == {1} and by_patient[2] == {2}


# ---------------------------------------------------------------- sustitución protegida
def test_a_substitute_never_leaves_own_users_below_their_floor():
    # Detemir (6 pens): dos usuarios propios necesitan 2 pens cada uno para su piso; el usuario de glargina (sin
    # stock de glargina) solo puede recibir lo que sobra: los 2 pens restantes.
    lotes = [lote(1, "Detemir", 300, 6)]
    bens = [benef(1, 50, "2", "Detemir", 10), benef(2, 50, "2", "Detemir", 10), benef(3, 50, "2", "Glargina", 10)]
    plan = correr(lotes, bens, reserve_pct=0.0)
    for i in (1, 2, 3):
        assert cov(plan, i) >= 0.65 - 1e-9
    assert res(plan, 3).substitute == "Detemir"


def test_the_premix_can_be_replaced_by_nph_detemir_or_glargina():
    # Solo en el reporte: la mixta se reemplaza por NPH (primera de la tabla) y, si no hay, por detemir o glargina.
    plan = correr([lote(1, "NPH", 300, 100)], [benef(1, 45, "2", "Mixta", 20)], reserve_pct=0.0)
    r = res(plan, 1)
    assert r.substitute == "NPH" and r.substitute_equiv_ui == 1200
    for basal in ("Detemir", "Glargina"):
        plan = correr([lote(1, basal, 300, 100)], [benef(1, 45, "2", "Mixta", 20)], reserve_pct=0.0)
        assert res(plan, 1).substitute == basal


def test_the_shared_substitution_table_of_the_warehouse_is_not_changed():
    from app.core.insulin_distribution import DEFAULT_SUBSTITUTIONS, SUBSTITUTION_TABLE

    assert "Mixta" not in SUBSTITUTION_TABLE
    assert not any(r.source == "Mixta" for r in DEFAULT_SUBSTITUTIONS)


def test_minor_can_use_substitute_even_if_adults_have_pending_floor_in_that_insulin():
    lotes = [lote(1, "Lispro", 300, 10)]
    bens = [benef(1, 10, "1", "Glulisina", 10)] + [benef(10 + i, 45, "2", "Lispro", 10) for i in range(10)]
    plan = correr(lotes, bens, reserve_pct=0.0)
    r = res(plan, 1)
    assert cov(plan, 1) >= 1.0 - 1e-9 and r.substitute == "Lispro"
    assert any("requiere aval" in n for n in r.notes)


def test_minor_with_degludec_is_never_substituted():
    plan = correr([lote(1, "Glargina", 300, 50)], [benef(1, 10, "1", "Degludec", 10)])
    r = res(plan, 1)
    assert entregado(plan, 1) == 0 and r.min_shortfall_cause == "STOCK" and "SIN_ASIGNACION" in r.notes


# ---------------------------------------------------------------- equidad entre adultos
def test_progressive_fill_gives_adults_a_similar_coverage():
    lotes = [lote(1, "NPH", 300, 60)]  # 18.000 UI
    bens = [benef(i, 45, "2", "NPH", 10) for i in range(1, 51)]  # 50 x 600 = 30.000 UI
    plan = correr(lotes, bens, reserve_pct=0.0)
    covs = [cov(plan, i) for i in range(1, 51)]
    assert max(covs) - min(covs) <= 0.55
    assert sum(1 for c in covs if c == 0) == 0


def test_nobody_is_left_at_zero_while_there_are_pens():
    plan = correr([lote(1, "NPH", 300, 10)], [benef(i, 45, "2", "NPH", 10) for i in range(1, 11)], reserve_pct=0.0)
    assert all(entregado(plan, i) > 0 for i in range(1, 11))


# ---------------------------------------------------------------- reserva
def test_reserve_is_released_when_needed_and_reported():
    lotes = [lote(1, "NPH", 300, 20, vence=date(2029, 1, 1))]  # 6.000 UI, reserva 5 % = 300
    bens = [benef(i, 45, "2", "NPH", 10) for i in range(1, 11)]  # necesidad 6.000; piso 65 % = 3.900
    plan = correr(lotes, bens)
    assert all(cov(plan, i) >= 0.65 - 1e-9 for i in range(1, 11))
    s = next(x for x in plan.ingredients if x.ingredient == "NPH")
    assert s.reserve_ui + s.allocated_ui + s.leftover_ui == pytest.approx(6000)
    assert s.reserve_released_ui == plan.reserve_released_ui


def test_reserve_is_kept_when_stock_is_plentiful():
    plan = correr([lote(1, "NPH", 300, 100)], [benef(i, 45, "2", "NPH", 10) for i in range(1, 11)])
    assert plan.reserve_ui >= 0.03 * 30000 - 1e-6
    assert all(0.75 <= cov(plan, i) <= 65 / 60 + 1e-9 for i in range(1, 11))


def test_reserve_is_never_taken_from_what_groups_1_and_2_need():
    # El stock justo cubre el 75 % de un menor y un tipo 1; la reserva no puede salir de ahí.
    lotes = [lote(1, "Glargina", 300, 10, label="Abasaglar")]
    bens = [benef(1, 10, "1", "Glargina", 10), benef(2, 40, "1", "Glargina", 10)]  # 2 x 600 = 1.200 UI
    plan = correr(lotes, bens)
    assert plan.reserve_ui <= 3000 - 2 * 450 + 1e-6
    assert cov(plan, 1) >= 0.75 and cov(plan, 2) >= 0.75


def test_a_minor_is_covered_even_if_adults_have_the_insulin_first():
    lotes = [lote(1, "Glargina", 300, 6, label="Abasaglar")]
    bens = [benef(1, 10, "1", "Glargina", 20), benef(2, 50, "2", "Glargina", 20), benef(3, 55, "2", "Glargina", 20)]
    plan = correr(lotes, bens, reserve_pct=0.0)
    assert cov(plan, 1) >= 0.75 - 1e-9


def test_smallest_pen_exception_for_a_very_low_adult_dose():
    plan = correr([lote(1, "NPH", 300, 5)], [benef(1, 45, "2", "NPH", 3)], reserve_pct=0.0)
    r = res(plan, 1)
    assert entregado(plan, 1) == 300 and r.min_pen_exception and "ENVASE_MINIMO" in r.notes


def test_vial_for_rapid_insulin_between_14_and_20_ui_a_day():
    lotes = [lote(1, "Lispro", 300, 20), lote(2, "Lispro", 1000, 2)]
    plan = correr(lotes, [benef(1, 45, "2", "Lispro", 16)], reserve_pct=0.0)
    assert entregado(plan, 1) == 1000


def test_one_insulin_per_group_and_premix_discarded():
    lotes = [lote(1, "Glargina", 300, 50), lote(2, "NPH", 300, 50), lote(3, "Mixta", 300, 50)]
    plan = correr(lotes, [benef(1, 45, "2", [("Glargina", 20), ("NPH", 10), ("Mixta", 10)])], reserve_pct=0.0)
    assert len(plan.patients[1]) == 1
    assert any(c.premix_discarded for c in plan.group_choices)
    assert "FICHA_POR_CORREGIR" in plan.patients[1][0].notes


def test_minor_dose_is_capped_at_30_by_default_and_the_cap_is_configurable():
    lotes = [lote(1, "Glargina", 300, 100)]
    b = [benef(1, 10, "1", "Glargina", 40)]
    r = res(correr(lotes, b), 1)
    assert r.daily_applied == 30 and r.daily_registered == 40 and any("DOSIS_TOPADA" in n for n in r.notes)
    plan = correr(lotes, b, config=DistributionConfig(today=HOY, use_solver=USE_SOLVER, minor_dose_cap=None))
    r = res(plan, 1)
    assert r.daily_applied == 40 and any("REVISION_CLINICA" in n for n in r.notes)


def test_nobody_gets_more_than_65_days_when_the_pens_allow_it():
    # 6 UI/día = 360 UI: 1 pen (300) = 83 % entra en la banda; 2 pens serían 100 días y no se dan.
    plan = correr([lote(1, "Lispro", 300, 10)], [benef(1, 10, "1", "Lispro", 6)])
    assert entregado(plan, 1) == 300 and cov(plan, 1) == pytest.approx(300 / 360)
    assert not res(plan, 1).outside_band


def test_a_very_low_dose_gets_one_envase_even_if_it_passes_65_days():
    # 3 UI/día = 180 UI: el pen más chico (300 UI) son 100 días, pero nadie queda en 0 %.
    plan = correr([lote(1, "Glargina", 300, 10)], [benef(1, 45, "2", "Glargina", 3)], reserve_pct=0.0)
    r = res(plan, 1)
    assert entregado(plan, 1) == 300 and r.min_pen_exception and r.outside_band


def test_the_same_band_applies_to_every_group():
    # Mismo requerimiento, distinto grupo: todos terminan dentro de 75 %-65 días cuando el stock alcanza.
    lotes = [lote(1, "Glargina", 300, 200, label="Abasaglar")]
    bens = [benef(1, 10, "2", "Glargina", 20), benef(2, 30, "1", "Glargina", 20), benef(3, 65, "2", "Glargina", 20), benef(4, 40, "2", "Glargina", 20)]
    plan = correr(lotes, bens)
    for i in (1, 2, 3, 4):
        assert 0.75 <= cov(plan, i) <= 65 / 60 + 1e-9


def test_warnings_for_lots_close_to_expiry_and_insulin_without_stock():
    lotes = [lote(1, "NPH", 300, 10, vence=HOY + timedelta(days=30))]
    bens = [benef(1, 45, "2", "NPH", 10), benef(2, 45, "2", "Lispro", 10)]
    plan = correr(lotes, bens, reserve_pct=0.0)
    assert any("vence el" in w for w in plan.warnings)
    assert any("Sin stock alguno de Lispro" in w for w in plan.warnings)


def test_assignments_match_the_given_ui():
    lotes = [lote(1, "NPH", 300, 30), lote(2, "Glargina", 300, 30, label="Lantus")]
    bens = [benef(i, 10 + i, "2", "NPH" if i % 2 else "Glargina", 10 + i) for i in range(1, 30)]
    plan = correr(lotes, bens)
    for pid, rows in plan.patients.items():
        got = sum(a.ui for a in plan.assignments if a.patient_id == pid)
        assert got == pytest.approx(sum(r.given_ui + r.substitute_ui for r in rows))


def test_determinism():
    lotes = [lote(1, "NPH", 300, 30), lote(2, "Glargina", 300, 30, label="Lantus")]
    bens = [benef(i, 10 + i, "2", "NPH" if i % 2 else "Glargina", 10 + i) for i in range(1, 30)]
    a = correr(lotes, bens)
    b = correr(lotes, bens)
    assert [(x.patient_id, x.lot_id, x.units) for x in a.assignments] == [(x.patient_id, x.lot_id, x.units) for x in b.assignments]


def test_require_optimizer_raises_instead_of_delivering_an_approximate_split(monkeypatch):
    from app.core.equitable_distribution import OptimizerUnavailable

    monkeypatch.setattr(equitable_milp, "HAS_SOLVER", False)
    with pytest.raises(OptimizerUnavailable):
        plan_distribution(
            [lote(1, "NPH", 300, 10)], [benef(1, 45, "2", "NPH", 10)],
            config=DistributionConfig(today=HOY, use_solver=True, require_optimizer=True),
        )


def test_substitution_with_a_factor_different_from_one_is_rejected():
    from app.core.insulin_distribution import Substitution

    with pytest.raises(ValueError):
        plan_distribution([lote(1, "NPH", 300, 5)], [benef(1, 45, "2", "NPH", 5)], substitutions=[Substitution("NPH", "Detemir", 1.5)])


@pytest.mark.parametrize("seed", range(25))
def test_random_invariants(seed):
    rnd = random.Random(seed)
    ings = ["Glargina", "Detemir", "Degludec", "NPH", "Lispro", "Aspart", "Regular"]
    lotes = []
    lot_id = 0
    for ing in ings:
        for size in rnd.sample([150, 300, 450, 1000], k=rnd.randint(1, 3)):
            lot_id += 1
            lotes.append(
                lote(
                    lot_id, ing, size, rnd.randint(0, 40),
                    label="Lantus" if (ing == "Glargina" and rnd.random() < 0.5) else ing,
                    vence=date(2027, 1, 1) + timedelta(days=rnd.randint(0, 600)),
                )
            )
    bens = []
    for i in range(1, rnd.randint(30, 120)):
        bens.append(
            benef(
                i, rnd.choice([5, 9, 14, 17, 25, 40, 62, 75]), rnd.choice(["1", "2", "2", "2", ""]),
                rnd.choice(ings), rnd.choice([3, 8, 12, 16, 20, 30, 45]),
            )
        )
    plan = correr(lotes, bens, reserve_pct=rnd.choice([0.0, 0.05]))
    # 1) el stock se conserva por lote
    for l in lotes:
        if l.units <= 0:
            continue
        assigned = sum(a.units for a in plan.assignments if a.lot_id == l.lot_id)
        kept = sum(r.units for r in plan.reserve_lots if r.lot_id == l.lot_id)
        assert assigned + plan.remaining_units[l.lot_id] + kept == l.units
    # 2) pasar del tope de 65 días solo por el envase entero: el caso queda marcado y con un envase menos bajaría del piso
    for pid, rows in plan.patients.items():
        for r in rows:
            c = (r.given_ui + r.substitute_equiv_ui) / r.need_ui
            if c > 65 / 60 + 1e-9:
                assert r.min_pen_exception or "ENVASE_ENTERO" in r.notes, r
                sizes = [a.ui / a.units for a in plan.assignments if a.patient_id == pid and a.for_ingredient == r.ingredient]
                assert (r.given_ui + r.substitute_equiv_ui) - min(sizes) < r.band_min * r.need_ui - 1e-6
    # 3) un prioritario bajo su piso nunca tiene causa «OTRO» (había envase y no se le dio)
    for rows in plan.patients.values():
        for r in rows:
            if r.outside_band and r.group <= 2 and r.min_shortfall_cause == "OTRO":
                pytest.fail(f"Prioritario bajo piso con causa OTRO: {r}")
