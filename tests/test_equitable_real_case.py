"""Caso real del reparto del 22/11/2026 (sin datos personales): 408 tratamientos y 133 lotes.

Con ese stock la mixta no alcanza (15.600 UI para pisos de 28.086 UI): es imposible que todos lleguen a su
mínimo. En todas las demás insulinas el optimizador logra que nadie quede bajo su piso, y nadie queda en 0 %.
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


def test_nobody_is_at_zero_and_only_mixta_is_below_its_floor():
    t0 = time.time()
    plan = _plan()
    assert time.time() - t0 < 90
    rows = [r for rs in plan.patients.values() for r in rs]
    assert len(rows) == 408
    assert [r for r in rows if _coverage(r) < 1e-9] == []
    below = {r.ingredient for r in rows if _coverage(r) < r.band_min - 1e-6}
    assert below == {"Mixta"}
    # Menores y tipo 1 siempre llegan a su piso
    assert all(_coverage(r) >= r.band_min - 1e-6 for r in rows if r.group <= 2)
    assert not any("optimizador" in w for w in plan.warnings)


def test_the_missing_mixta_is_stated_exactly():
    plan = _plan()
    (gap,) = plan.minimum_gaps
    assert gap.ingredient == "Mixta"
    # pisos 28.086 UI - stock 15.600 UI = 12.486 UI como mínimo; con envases enteros sobran a lo sumo unos pocos
    assert 12486 - 1 <= gap.shortfall_ui <= 12486 + 1000
    assert gap.treatments > 0 and gap.pen_ui > 0


def test_the_approximate_split_is_flagged_as_not_guaranteeing_the_floors(monkeypatch):
    monkeypatch.setattr(equitable_milp, "HAS_SOLVER", False)
    plan = _plan()
    assert any("no garantiza que todos lleguen a su mínimo" in w for w in plan.warnings)
