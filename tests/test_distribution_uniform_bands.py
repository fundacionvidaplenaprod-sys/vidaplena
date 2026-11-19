"""Reglas vigentes del reparto de insulinas: margen único por insulina, menores primero y reparto parejo."""
import pytest

from app.core.insulin_distribution import (
    BAND_SHORTAGE,
    BAND_SUFFICIENT,
    DISTRIBUTION_DAYS as DAYS,
    LotInput,
    PatientInput,
    plan_distribution,
)

PEN = 300  # UI de un pen de 3 ml U100


def _pens(lot_id, ing, count):
    return LotInput(lot_id, ing, f"{ing} pen", PEN, count, None)


def _cov(plan, pid, ing="Aspart"):
    r = next(r for r in plan.patients[pid] if r.ingredient == ing)
    return (r.given_ui + r.substitute_equiv_ui) / r.need_ui


def _summary(plan, ing):
    return next(s for s in plan.ingredients if s.ingredient == ing)


def test_the_margins_are_the_agreed_ones():
    assert BAND_SHORTAGE == (0.75, 1.00)
    assert BAND_SUFFICIENT == (0.85, 1.25)


def test_when_the_insulin_is_short_everybody_gets_the_same_margin_and_the_cap_is_100():
    # 5 adultos que necesitan 3.600 UI cada uno (18.000) y 40 pens (12.000 UI): falta stock.
    pats = [PatientInput(i, False, {"Aspart": 60}) for i in range(1, 6)]
    plan = plan_distribution([_pens(1, "Aspart", 40)], pats, reserve_pct=0)
    s = _summary(plan, "Aspart")
    assert s.shortage is True
    assert (s.band_min, s.band_max) == BAND_SHORTAGE
    covs = [_cov(plan, i) for i in range(1, 6)]
    assert all(c <= 1.0 + 1e-9 for c in covs)
    # parejo: la diferencia entre el que más y el que menos recibe es, a lo sumo, un envase
    assert max(covs) - min(covs) <= PEN / 3600 + 1e-9
    assert plan.allocated_ui == 12000


def test_when_the_insulin_is_short_nobody_is_left_at_zero_while_there_are_pens():
    # 10 beneficiarios con necesidad muy distinta y 12 pens: todos reciben al menos uno.
    pats = [PatientInput(i, False, {"Aspart": 20 + 5 * i}) for i in range(1, 11)]
    plan = plan_distribution([_pens(1, "Aspart", 12)], pats, reserve_pct=0)
    assert _summary(plan, "Aspart").shortage is True
    assert all(_cov(plan, i) > 0 for i in range(1, 11))


def test_the_priority_group_gives_no_advantage_except_to_minors():
    # Un tipo 1 adulto y un tipo 2 adulto, misma dosis, y no alcanza para los dos.
    pats = [
        PatientInput(1, False, {"Aspart": 60}, is_type1=True),
        PatientInput(2, False, {"Aspart": 60}),
    ]
    plan = plan_distribution([_pens(1, "Aspart", 16)], pats, reserve_pct=0)
    assert abs(_cov(plan, 1) - _cov(plan, 2)) <= PEN / 3600 + 1e-9
    assert _cov(plan, 2) > 0


def test_minors_are_covered_first_and_in_full():
    pats = [
        PatientInput(1, True, {"Aspart": 40}),  # menor
        PatientInput(2, False, {"Aspart": 40}),
        PatientInput(3, False, {"Aspart": 40}),
    ]
    # Necesitan 2.400 UI cada uno (7.200); hay 5.400 UI (18 pens): falta.
    plan = plan_distribution([_pens(1, "Aspart", 18)], pats, reserve_pct=0)
    assert _summary(plan, "Aspart").shortage is True
    assert _cov(plan, 1) >= 1.0 - 1e-9  # el menor, completo
    assert _cov(plan, 2) < 1.0 and _cov(plan, 3) < 1.0
    assert abs(_cov(plan, 2) - _cov(plan, 3)) <= PEN / 2400 + 1e-9


def test_when_the_insulin_suffices_the_margin_is_85_to_125():
    # 8 UI/día = 480 UI: un pen es 62,5 % y dos son 125 %: con stock de sobra se aceptan los dos.
    pats = [PatientInput(1, False, {"Aspart": 8})]
    plan = plan_distribution([_pens(1, "Aspart", 20)], pats, reserve_pct=0)
    s = _summary(plan, "Aspart")
    assert s.shortage is False
    assert (s.band_min, s.band_max) == BAND_SUFFICIENT
    assert _cov(plan, 1) == pytest.approx(1.25)


def test_nobody_gets_more_than_the_margin_maximum():
    pats = [PatientInput(i, False, {"Aspart": 30}) for i in range(1, 5)]
    plan = plan_distribution([_pens(1, "Aspart", 200)], pats, reserve_pct=0)
    assert _summary(plan, "Aspart").shortage is False
    assert all(_cov(plan, i) <= BAND_SUFFICIENT[1] + 1e-9 for i in range(1, 5))
    assert all(_cov(plan, i) >= BAND_SUFFICIENT[0] - 1e-9 for i in range(1, 5))


def test_the_profile_counts_the_reserve():
    # Stock justo para la necesidad (3.000 UI); con 3 % de reserva ya no alcanza y se pasa al margen de escasez.
    pats = [PatientInput(1, False, {"Aspart": 50})]
    plan = plan_distribution([_pens(1, "Aspart", 10)], pats, reserve_pct=0.1)
    assert _summary(plan, "Aspart").shortage is True or _summary(plan, "Aspart").reserve_released_ui > 0
    assert DAYS == 60


def test_the_rules_by_group_still_work_when_bands_are_passed():
    from app.core.insulin_distribution import COVERAGE_BANDS

    pats = [PatientInput(i, False, {"Aspart": 60}) for i in range(1, 4)]
    plan = plan_distribution([_pens(1, "Aspart", 20)], pats, reserve_pct=0, bands=COVERAGE_BANDS)
    s = _summary(plan, "Aspart")
    assert s.shortage is None and s.band_min is None
