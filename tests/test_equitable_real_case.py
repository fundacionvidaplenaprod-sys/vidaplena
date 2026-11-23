"""Caso real del reparto del 22/11/2026 (sin datos personales): 408 tratamientos y 133 lotes.

Reglas: 75-100 % del requerimiento para todos (reglamento, art. 2) y nadie más de 65 días. Con ese stock alcanza para
todos: nadie queda en 0 % ni bajo el 75 % por falta de insulina. Para las dosis de 3, 4, 7, 8 y 9 UI/día no existe ningún
total de envases enteros entre el 75 % y los 65 días: manda el tope y esos tratamientos quedan con la menor diferencia
posible (los de 3 y 4 UI/día reciben un pen que pasa del tope: nadie en 0 %). Se informan con la nota ENVASE_ENTERO.
"""
import json
import time
from datetime import date
from pathlib import Path

import pytest

from app.core import equitable_milp
from app.core.equitable_distribution import DistributionConfig, plan_distribution
from app.core.insulin_distribution import LotInput, PatientInput

pytestmark = pytest.mark.skipif(not equitable_milp.HAS_SOLVER, reason="scipy no está instalado: no hay optimizador")

DATA = json.loads((Path(__file__).parent / "data" / "reparto_2026_11_22.json").read_text(encoding="utf-8"))


def _plan(**cfg):
    lots = [
        LotInput(i, ing, label, ui, units, date.fromisoformat(exp) if exp else None)
        for i, (ing, label, ui, units, exp) in enumerate(DATA["lotes"], start=1)
    ]
    pats = [
        PatientInput(i, g == 1, {ing: dose}, is_type1=g == 2, priority_group=g)
        for i, (g, ing, dose) in enumerate(DATA["tratamientos"], start=1)
    ]
    return plan_distribution(lots, pats, config=DistributionConfig(today=date(2026, 11, 22), **cfg))


def _coverage(r):
    return (r.given_ui + r.substitute_equiv_ui) / r.need_ui


def test_nobody_is_at_zero_and_only_the_whole_envase_cases_are_below_75_percent():
    t0 = time.time()
    plan = _plan()
    assert time.time() - t0 < 90
    rows = [r for rs in plan.patients.values() for r in rs]
    assert len(rows) == 408
    assert [r for r in rows if _coverage(r) < 1e-9] == []
    assert plan.minimum_gaps == []  # ninguna insulina queda corta de stock
    # lo único bajo el 75 % es lo que el envase entero obliga, y con la menor diferencia posible
    below = [r for r in rows if _coverage(r) < r.band_min - 1e-6]
    assert below and all(r.min_shortfall_cause == "ENVASE" and "ENVASE_ENTERO" in r.notes for r in below)
    assert {r.daily_applied for r in below} == {7.0, 8.0, 9.0}
    assert all(_coverage(r) >= 300 / r.need_ui - 1e-9 for r in below)  # el mayor total que cabe en 65 días (1 pen)
    assert not any("optimizador" in w for w in plan.warnings)


def test_more_than_65_days_only_when_the_whole_envase_forces_it():
    rows = [r for rs in _plan().patients.values() for r in rs]
    over = [r for r in rows if _coverage(r) > 65 / 60 + 1e-9]
    assert over and all(r.min_pen_exception or "ENVASE_ENTERO" in r.notes for r in over)
    # solo dosis de 3 y 4 UI/día: un pen de 300 UI ya pasa de 65 días y nadie puede quedar en 0 %
    assert {r.daily_applied for r in over} == {3.0, 4.0} and len(over) == 4
    # el resto se mantiene entre 75 % y 65 días, salvo los de envase entero (bajo el 75 %)
    assert all(
        0.75 - 1e-6 <= _coverage(r) <= 65 / 60 + 1e-9 for r in rows if r not in over and "ENVASE_ENTERO" not in r.notes
    )


def test_the_cap_of_30_ui_a_day_for_minors_applies():
    rows = [r for rs in _plan().patients.values() for r in rs if r.group == 1]
    assert all(r.daily_applied <= 30 for r in rows)
    assert any(r.daily_registered > 30 and r.daily_applied == 30 for r in rows)


def test_the_default_reserve_is_3_percent_of_the_stock():
    plan = _plan()
    assert plan.reserve_pct == 0.03 and 0.03 <= plan.reserve_ui / plan.total_stock_ui < 0.04


def test_without_the_mixta_substitution_the_missing_stock_is_stated_exactly():
    from app.core.equitable_distribution import EQUITABLE_SUBSTITUTIONS

    rules = [r for r in EQUITABLE_SUBSTITUTIONS if r.source != "Mixta"]
    lots = [
        LotInput(i, ing, label, ui, units, date.fromisoformat(exp) if exp else None)
        for i, (ing, label, ui, units, exp) in enumerate(DATA["lotes"], start=1)
    ]
    pats = [
        PatientInput(i, g == 1, {ing: dose}, is_type1=g == 2, priority_group=g)
        for i, (g, ing, dose) in enumerate(DATA["tratamientos"], start=1)
    ]
    plan = plan_distribution(lots, pats, config=DistributionConfig(today=date(2026, 11, 22)), substitutions=rules)
    (gap,) = plan.minimum_gaps
    # el 75 % de la necesidad de mixta (30.105 UI) menos el stock (15.600 UI) = 14.505 UI como mínimo
    assert gap.ingredient == "Mixta" and 14505 - 1 <= gap.shortfall_ui <= 14505 + 1000


def test_the_approximate_split_is_flagged_as_not_guaranteeing_the_floors(monkeypatch):
    monkeypatch.setattr(equitable_milp, "HAS_SOLVER", False)
    plan = _plan()
    assert any("no garantiza que todos lleguen a su mínimo" in w for w in plan.warnings)
