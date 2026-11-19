"""Pruebas del motor de reparto de insulinas (puro, sin base de datos)."""
from datetime import date

from app.core.insulin_distribution import (
    DISTRIBUTION_DAYS as DAYS,
    INSULIN_GROUPS,
    PREMIX_INSULINS,
    PREMIX_REPLACEABLE,
    RESERVE_PCT,
    MINOR_DAILY_CAP_UI,
    COVERAGE_BANDS,
    insulin_group,
    split_group_conflicts,
    LotInput,
    PatientInput,
    is_type1_diabetes,
    plan_distribution,
)


def _lot(lot_id, ing, label, ui, units, expiry=None):
    return LotInput(lot_id, ing, label, ui, units, expiry)


def _units_by_patient(plan):
    out = {}
    for a in plan.assignments:
        out.setdefault(a.patient_id, {}).setdefault(a.lot_id, 0)
        out[a.patient_id][a.lot_id] += a.units
    return out


def _given(plan, pid, ing):
    return next(r.given_ui for r in plan.patients[pid] if r.ingredient == ing)


def test_reserve_is_five_percent_of_total_and_never_assigned():
    assert RESERVE_PCT == 0.05
    # Stock 10.000 UI, demanda 5.000: sobra de sobra, la reserva sale del sobrante.
    lots = [_lot(1, "Aspart", "NovoRapid", 1000, 10)]
    pats = [PatientInput(1, False, {"Aspart": 5000 / DAYS})]
    plan = plan_distribution(lots, pats)
    assert plan.reserve_pct == 0.05
    assert plan.reserve_target_ui == 500
    assert plan.reserve_ui == 1000  # un envase entero de 1.000 UI
    assert plan.allocated_ui == 5000
    assert sum(a.units for a in plan.assignments) + sum(r.units for r in plan.reserve_lots) <= 10


def test_reserve_cuts_allocation_when_demand_exceeds_stock():
    # Demanda = stock = 10.000. Para reservar el 5 % (un envase de 1.000 UI) se recorta lo asignado.
    lots = [_lot(1, "Aspart", "NovoRapid", 1000, 10)]
    pats = [PatientInput(1, False, {"Aspart": 10000 / DAYS})]
    plan = plan_distribution(lots, pats)
    assert plan.reserve_ui == 1000
    assert plan.allocated_ui == 9000


def test_reserve_comes_first_from_insulins_nobody_needs():
    lots = [
        _lot(1, "Aspart", "NovoRapid", 1000, 10),  # 10.000 UI, todo necesario
        _lot(2, "Glulisina", "Apidra", 900, 10),  # 9.000 UI, nadie la usa
    ]
    pats = [PatientInput(1, False, {"Aspart": 10000 / DAYS})]
    plan = plan_distribution(lots, pats)
    assert plan.reserve_target_ui == 950  # 5 % de 19.000 UI
    by_ing = {s.ingredient: s for s in plan.ingredients}
    assert by_ing["Aspart"].reserve_ui == 0
    # Reserva de 950 UI en envases de 900 UI: 2 envases = 1.800, no los 9.000.
    assert 950 <= by_ing["Glulisina"].reserve_ui <= 950 + 900
    assert plan.allocated_ui == 10000


def test_minors_are_served_first_and_adults_get_the_rest():
    lots = [_lot(1, "NPH", "Tresiba", 600, 10)]  # 6.000 UI, reserva 600
    need = 4500 / DAYS  # cada paciente necesita 4.500 UI
    pats = [
        PatientInput(1, False, {"NPH": need}),  # adulto, id menor
        PatientInput(2, True, {"NPH": need}),  # menor
    ]
    plan = plan_distribution(lots, pats, release_reserve=False)
    lo, hi = COVERAGE_BANDS[1]
    assert 4500 * lo <= _given(plan, 2, "NPH") <= 4500 * hi  # el menor dentro de su banda 80-120 %
    assert _given(plan, 1, "NPH") < 4500 * 0.75  # el adulto recibe lo que queda, que no alcanza
    assert plan.reserve_ui >= 600


def test_minors_take_lantus_first_adults_take_other_glargine_first():
    lots = [
        _lot(1, "Glargina", "Lantus SoloStar", 300, 20, date(2027, 1, 1)),
        _lot(2, "Glargina", "Abasaglar KwikPen", 300, 20, date(2027, 6, 1)),
    ]
    pats = [
        PatientInput(1, True, {"Glargina": 300 / DAYS}),  # menor: 1 envase
        PatientInput(2, False, {"Glargina": 300 / DAYS}),  # adulto: 1 envase
    ]
    plan = plan_distribution(lots, pats)
    got = _units_by_patient(plan)
    assert got[1] == {1: 1}  # menor -> Lantus
    assert got[2] == {2: 1}  # adulto -> Abasaglar aunque Lantus venza antes


def test_adults_fall_back_to_lantus_when_other_glargine_runs_out():
    lots = [
        _lot(1, "Glargina", "Lantus SoloStar", 300, 20),
        _lot(2, "Glargina", "Abasaglar KwikPen", 300, 1),
    ]
    pats = [PatientInput(1, False, {"Glargina": 600 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert _units_by_patient(plan)[1] == {2: 1, 1: 1}


def test_fefo_within_same_preference():
    lots = [
        _lot(1, "Aspart", "NovoRapid A", 1000, 5, date(2028, 1, 1)),
        _lot(2, "Aspart", "NovoRapid B", 1000, 5, date(2026, 12, 1)),
    ]
    pats = [PatientInput(1, False, {"Aspart": 1000 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert _units_by_patient(plan)[1] == {2: 1}


def test_concentration_is_handled_in_ui_not_in_packages():
    # Toujeo 1,5 ml U300 = 450 UI; un paciente de 900 UI necesita 2 envases.
    lots = [_lot(1, "Glargina", "Toujeo SoloStar", 450, 10)]
    pats = [PatientInput(1, False, {"Glargina": 900 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert _units_by_patient(plan)[1] == {1: 2}


def test_shortage_fills_the_smaller_need_into_its_band_and_spends_all_stock():
    lots = [_lot(1, "Aspart", "NovoRapid", 100, 10)]  # 1.000 UI
    pats = [
        PatientInput(1, False, {"Aspart": 600 / DAYS}),
        PatientInput(2, False, {"Aspart": 1200 / DAYS}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    u = {pid: sum(a.units for a in plan.assignments if a.patient_id == pid) for pid in (1, 2)}
    assert u[1] + u[2] == 10
    assert 4 <= u[1] <= 6  # 65-100 % de 600 UI, con el mínimo de envases (4 = 400 UI)
    assert u[2] >= 4  # y el otro recibe el resto: no queda en cero


def test_unmet_need_is_reported_per_insulin_when_there_is_no_stock():
    lots = [_lot(1, "Aspart", "NovoRapid", 1000, 10)]
    pats = [PatientInput(1, False, {"Detemir": 20})]
    plan = plan_distribution(lots, pats)
    assert plan.assignments == []
    detemir = next(s for s in plan.ingredients if s.ingredient == "Detemir")
    assert detemir.unmet_ui == 20 * DAYS and detemir.patients_unmet == 1


def test_never_assigns_more_than_available_and_is_deterministic():
    lots = [_lot(i, "Lispro", f"Humalog {i}", 300, 3) for i in range(1, 6)]
    pats = [PatientInput(i, i % 3 == 0, {"Lispro": 25 + i}) for i in range(1, 30)]
    first = plan_distribution(lots, pats)
    second = plan_distribution(lots, pats)
    assert first.assignments == second.assignments
    used = {}
    for a in first.assignments:
        used[a.lot_id] = used.get(a.lot_id, 0) + a.units
    for r in first.reserve_lots:
        used[r.lot_id] = used.get(r.lot_id, 0) + r.units
    assert all(used[lot.lot_id] <= lot.units for lot in lots)


# --- Sustitución: adultos sin glargina reciben detemir -----------------------


def _by_for(plan, pid, for_ing):
    return [(a.lot_id, a.units) for a in plan.assignments if a.patient_id == pid and a.for_ingredient == for_ing]


def test_adult_without_glargine_stock_gets_detemir():
    lots = [_lot(1, "Detemir", "Levemir Penfill", 300, 50)]
    pats = [PatientInput(1, False, {"Glargina": 600 / DAYS})]  # 600 UI = 2 envases
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert _by_for(plan, 1, "Glargina") == [(1, 2)]
    res = plan.patients[1][0]
    assert res.ingredient == "Glargina" and res.given_ui == 0
    assert res.substitute == "Detemir" and res.substitute_ui == 600 and res.substitute_equiv_ui == 600
    gl = next(s for s in plan.ingredients if s.ingredient == "Glargina")
    assert gl.unmet_ui == 0 and gl.patients_unmet == 0 and gl.substituted_out_ui == 600
    de = next(s for s in plan.ingredients if s.ingredient == "Detemir")
    assert de.substituted_in_ui == 600


def test_minors_also_receive_the_substitutes_of_the_table():
    # La tabla no distingue edad: un menor sin glargina recibe detemir.
    lots = [_lot(1, "Detemir", "Levemir Penfill", 300, 50)]
    pats = [PatientInput(1, True, {"Glargina": 600 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    r = plan.patients[1][0]
    assert r.substitute == "Detemir" and r.substitute_equiv_ui == 600


def test_adult_who_cannot_be_completed_with_glargine_switches_whole_to_detemir():
    lots = [
        _lot(1, "Glargina", "Abasaglar", 300, 2),  # 600 UI para dos adultos de 600 UI
        _lot(2, "Detemir", "Levemir Penfill", 300, 50),
    ]
    pats = [PatientInput(1, False, {"Glargina": 600 / DAYS}), PatientInput(2, False, {"Glargina": 600 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    r1, r2 = plan.patients[1][0], plan.patients[2][0]
    # Uno conserva su glargina y el otro pasa entero a detemir: nadie mezcla dos basales.
    assert r1.given_ui == 600 and r1.substitute is None
    assert r2.given_ui == 0 and r2.substitute == "Detemir" and r2.substitute_equiv_ui == 600


def test_both_adults_end_inside_their_band_when_one_switches_to_detemir():
    lots = [_lot(1, "Glargina", "Abasaglar", 300, 2), _lot(2, "Detemir", "Levemir", 300, 50)]  # 600 UI
    pats = [PatientInput(1, False, {"Glargina": 900 / DAYS}), PatientInput(2, False, {"Glargina": 300 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    for pid, need in ((1, 900), (2, 300)):
        r = plan.patients[pid][0]
        assert r.given_ui + r.substitute_equiv_ui >= 0.75 * need, pid
        assert not r.outside_band, pid
    assert plan.patients[2][0].given_ui == 300  # el de menor necesidad queda con su glargina
    assert plan.patients[1][0].substitute == "Detemir"  # el otro pasa entero


def test_without_detemir_stock_the_smaller_adult_gets_its_band_and_nobody_stays_at_zero():
    lots = [_lot(1, "Glargina", "Abasaglar", 100, 10)]  # 1.000 UI
    pats = [PatientInput(1, False, {"Glargina": 600 / DAYS}), PatientInput(2, False, {"Glargina": 1200 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    got = {pid: plan.patients[pid][0].given_ui for pid in (1, 2)}
    assert 390 <= got[1] <= 600  # dentro de su banda 65-100 %
    assert got[2] > 0 and got[1] + got[2] == 1000


def test_glargine_and_detemir_are_combined_when_neither_alone_reaches_the_band():
    lots = [_lot(1, "Glargina", "Abasaglar", 300, 1), _lot(2, "Detemir", "Levemir", 300, 1)]
    pats = [PatientInput(1, False, {"Glargina": 600 / DAYS}), PatientInput(2, False, {"Glargina": 600 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert sum(a.ui for a in plan.assignments) == 600  # se usó todo lo que había
    r1, r2 = plan.patients[1][0], plan.patients[2][0]
    # Con dos envases solo uno llega a su banda: la prioridad entre iguales es el orden de la ficha.
    assert r1.given_ui == 300 and r1.substitute == "Detemir" and r1.substitute_equiv_ui == 300
    assert r2.given_ui + r2.substitute_equiv_ui == 0


def test_minors_keep_their_own_glargine_and_only_the_rest_comes_from_the_substitute():
    lots = [_lot(1, "Glargina", "Abasaglar", 100, 10), _lot(2, "Detemir", "Levemir", 300, 50)]  # 1.000 UI de glargina
    pats = [PatientInput(1, True, {"Glargina": 600 / DAYS}), PatientInput(2, True, {"Glargina": 1200 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    r1, r2 = plan.patients[1][0], plan.patients[2][0]
    assert r1.given_ui == 500 and r1.substitute is None  # su insulina específica, en su banda (80-120 %)
    assert r2.given_ui == 500 and r2.substitute == "Detemir"  # lo que quedaba de glargina + el faltante
    assert 1200 * 0.80 <= r2.given_ui + r2.substitute_equiv_ui <= 1200 * 1.2


def test_full_glargine_coverage_does_not_touch_detemir():
    lots = [_lot(1, "Glargina", "Abasaglar", 300, 10), _lot(2, "Detemir", "Levemir", 300, 10)]
    pats = [PatientInput(1, False, {"Glargina": 600 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert _by_for(plan, 1, "Glargina") == [(1, 2)]
    assert plan.patients[1][0].substitute is None


def test_detemir_users_are_served_before_anyone_gets_it_as_a_substitute():
    lots = [_lot(1, "Detemir", "Levemir", 300, 4)]  # 1.200 UI
    pats = [
        PatientInput(1, False, {"Glargina": 1200 / DAYS}),  # adulto sin glargina: quiere 1.200 de sustituto
        PatientInput(2, False, {"Detemir": 900 / DAYS}),  # usa detemir: 900 UI propias
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    own = next(r for r in plan.patients[2] if r.ingredient == "Detemir")
    assert own.given_ui == 600  # su propia insulina primero: 600 UI = 67 %, dentro de su banda (65-100 %)
    sub = next(r for r in plan.patients[1] if r.ingredient == "Glargina")
    assert sub.substitute_ui == 600  # y el resto del detemir va al sustituto
    assert sum(a.ui for a in plan.assignments) == 1200


def test_reserve_is_not_spent_on_substitution():
    lots = [_lot(1, "Detemir", "Levemir", 100, 10)]  # 1.000 UI -> reserva 100
    pats = [PatientInput(1, False, {"Glargina": 5000 / DAYS})]
    plan = plan_distribution(lots, pats, release_reserve=False)
    sub = plan.patients[1][0]
    assert sub.substitute_ui <= 900
    assert plan.reserve_ui >= 100
    assert sum(a.units for a in plan.assignments) + sum(r.units for r in plan.reserve_lots) <= 10


def test_substitution_can_be_disabled():
    lots = [_lot(1, "Detemir", "Levemir", 300, 50)]
    pats = [PatientInput(1, False, {"Glargina": 600 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert plan.assignments == []


def test_substitution_factor_converts_doses():
    from app.core.insulin_distribution import Substitution

    lots = [_lot(1, "Detemir", "Levemir", 100, 100)]
    pats = [PatientInput(1, False, {"Glargina": 600 / DAYS})]
    plan = plan_distribution(
        lots, pats, reserve_pct=0, substitutions=[Substitution("Glargina", "Detemir", factor=1.5)]
    )
    res = plan.patients[1][0]
    assert res.substitute_ui == 900  # 600 UI de glargina -> 900 UI de detemir
    assert res.substitute_equiv_ui == 600


# --- Horizonte, glulisina -> aspart y prioridad de diabetes tipo 1 ----------


def test_default_horizon_is_60_days():
    assert DAYS == 60
    plan = plan_distribution([_lot(1, "Aspart", "NovoRapid", 100, 100)], [PatientInput(1, False, {"Aspart": 10})])
    assert plan.days == 60
    assert plan.patients[1][0].need_ui == 600


def test_minors_and_adults_without_glulisine_both_get_aspart():
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 50)]
    pats = [PatientInput(1, False, {"Glulisina": 600 / DAYS}), PatientInput(2, True, {"Glulisina": 600 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    for pid in (1, 2):
        r = plan.patients[pid][0]
        assert r.substitute == "Aspart" and r.substitute_ui == 600 and r.substitute_equiv_ui == 600
        assert _by_for(plan, pid, "Glulisina") == [(1, 2)]


def test_regular_insulin_is_replaced_with_lispro_for_minors_and_adults():
    lots = [_lot(1, "Lispro", "Humalog KwikPen", 300, 50)]
    pats = [PatientInput(1, False, {"Regular": 600 / DAYS}), PatientInput(2, True, {"Regular": 300 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert plan.patients[1][0].substitute == "Lispro" and plan.patients[1][0].substitute_ui == 600
    assert plan.patients[2][0].substitute == "Lispro" and plan.patients[2][0].substitute_ui == 300
    reg = next(s for s in plan.ingredients if s.ingredient == "Regular")
    assert reg.unmet_ui == 0 and reg.substituted_out_ui == 900


def test_lispro_users_are_served_before_regular_gets_it_as_a_substitute():
    lots = [_lot(1, "Lispro", "Humalog", 300, 3)]  # 900 UI
    pats = [PatientInput(1, False, {"Regular": 900 / DAYS}), PatientInput(2, False, {"Lispro": 600 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert _given(plan, 2, "Lispro") == 600
    assert plan.patients[1][0].substitute_ui == 300


def test_all_default_substitutions_work_together():
    lots = [
        _lot(1, "Aspart", "NovoRapid", 300, 20),
        _lot(2, "Detemir", "Levemir", 300, 20),
        _lot(3, "Lispro", "Humalog", 300, 20),
    ]
    # Un beneficiario usa una sola insulina rápida y una sola basal.
    pats = [
        PatientInput(1, False, {"Glulisina": 300 / DAYS, "Glargina": 300 / DAYS}),
        PatientInput(2, False, {"Regular": 300 / DAYS}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    subs = {(pid, r.ingredient): r.substitute for pid, rs in plan.patients.items() for r in rs}
    assert subs == {(1, "Glulisina"): "Aspart", (1, "Glargina"): "Detemir", (2, "Regular"): "Aspart"}


def test_minor_is_guaranteed_first_then_type1_and_the_other_adult_gets_what_is_left():
    lots = [_lot(1, "Aspart", "NovoRapid", 100, 20)]  # 2.000 UI
    need = 1200 / DAYS  # cada uno necesita 1.200 UI
    pats = [
        PatientInput(1, False, {"Aspart": need}),  # adulto sin prioridad (id menor a propósito)
        PatientInput(2, False, {"Aspart": need}, is_type1=True),
        PatientInput(3, True, {"Aspart": need}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert 1200 * 0.80 <= _given(plan, 3, "Aspart") <= 1200 * 1.2  # el menor dentro de su banda
    assert _given(plan, 3, "Aspart") == 1000 and _given(plan, 2, "Aspart") == 900  # sus mínimos (80 y 75 %)
    assert _given(plan, 1, "Aspart") == 100  # al último le queda un envase: nadie en cero


def test_type1_adult_gets_its_band_before_the_other_adult_and_the_leftover_tops_it_up():
    lots = [_lot(1, "Aspart", "NovoRapid", 100, 20)]  # 2.000 UI
    need = 1200 / DAYS
    pats = [PatientInput(1, False, {"Aspart": need}), PatientInput(2, False, {"Aspart": need}, is_type1=True)]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _given(plan, 1, "Aspart") == 800  # el resto: su mínimo del 65 % (780 UI -> 800 con envases de 100)
    assert _given(plan, 2, "Aspart") == 1200  # tipo 1: su mínimo (75 %) y lo que sobra lo lleva al 100 %


def test_type1_adults_do_not_get_the_minors_lantus_preference():
    lots = [
        _lot(1, "Glargina", "Lantus SoloStar", 300, 20, date(2027, 1, 1)),
        _lot(2, "Glargina", "Abasaglar KwikPen", 300, 20, date(2027, 6, 1)),
    ]
    pats = [PatientInput(1, False, {"Glargina": 300 / DAYS}, is_type1=True)]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert _units_by_patient(plan)[1] == {2: 1}  # Lantus queda para menores


def test_type1_adult_still_gets_substitute_when_glargine_is_short():
    lots = [_lot(1, "Detemir", "Levemir", 300, 20)]
    pats = [PatientInput(1, False, {"Glargina": 600 / DAYS}, is_type1=True)]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert plan.patients[1][0].substitute == "Detemir"


def test_is_type1_diabetes_reads_free_text():
    for raw in ("Tipo 1", "TIPO 1", "tipo1", "Tipo I", " Diabetes tipo 1 ", "DM1", "Diabetes Mellitus tipo 1"):
        assert is_type1_diabetes(raw), raw
    for raw in ("Tipo 2", "Gestacional", "Otra", "Tipo 10", "", None):
        assert not is_type1_diabetes(raw), raw


# --- Redondeo: los envases enteros no le quitan stock a quien le falta ---------


def test_last_pen_is_chosen_to_waste_the_least_not_the_first_by_expiry():
    lots = [
        _lot(1, "Aspart", "NovoRapid Dstfl 10 ml", 1000, 5, date(2027, 1, 1)),  # vence antes
        _lot(2, "Aspart", "NovoRapid Penfill", 300, 5, date(2028, 1, 1)),
    ]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Aspart": 600 / DAYS})], reserve_pct=0)
    assert _units_by_patient(plan)[1] == {2: 2}  # 600 UI en pens, no un vial de 1.000


def test_rounding_of_other_adults_does_not_take_the_stock_a_substitute_needs():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 11)]  # 3.300 UI: 4 + 4 + 3 envases
    pats = [
        PatientInput(1, False, {"Aspart": 1350 / DAYS}),  # 4,5 envases
        PatientInput(2, False, {"Aspart": 1350 / DAYS}),
        PatientInput(3, False, {"Glulisina": 1200 / DAYS}),  # sin glulisina: necesita aspart
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    # Cada uno recibe el mínimo de envases de su banda: el redondeo hacia arriba no deja a 3 sin nada.
    assert plan.patients[3][0].substitute_ui >= 900
    assert _given(plan, 1, "Aspart") >= 900 and _given(plan, 2, "Aspart") >= 900
    assert plan.patients[3][0].substitute_ui + _given(plan, 1, "Aspart") + _given(plan, 2, "Aspart") == 3300
    assert not any(r.outside_band for rs in plan.patients.values() for r in rs)


def test_a_leftover_pen_is_not_forced_on_anyone_when_it_would_pass_the_max():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 3)]  # 900 UI para 2 x 450
    pats = [PatientInput(1, False, {"Aspart": 450 / DAYS}), PatientInput(2, False, {"Aspart": 450 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    # 300 UI = 67 % entra en su banda (65-100 %); un segundo envase sería 133 %, así que sobra.
    assert (_given(plan, 1, "Aspart"), _given(plan, 2, "Aspart")) == (300, 300)
    assert plan.remaining_units[1] == 1


def test_with_plenty_of_stock_an_adult_is_not_taken_above_its_max_to_complete_a_pen():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 100)]
    pats = [PatientInput(i, False, {"Aspart": 450 / DAYS}) for i in range(1, 6)]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    # 450 UI de necesidad: 1 pen = 67 % (dentro de 65-100 %); 2 pens = 133 %, fuera del máximo.
    assert all(_given(plan, i, "Aspart") == 300 for i in range(1, 6))
    assert not any(r.outside_band for rs in plan.patients.values() for r in rs)


def test_no_one_passes_120_percent_even_if_that_leaves_them_below_their_minimum():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 4)]  # 1.200 UI
    pats = [
        PatientInput(1, False, {"Aspart": 450 / DAYS}),  # adulto sin prioridad
        PatientInput(2, False, {"Aspart": 450 / DAYS}, is_type1=True),
        PatientInput(3, True, {"Aspart": 450 / DAYS}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    # Con envases de 300 UI, 1 envase = 67 % y 2 = 133 %: pasar del 120 % está prohibido, así que
    # menor y tipo 1 quedan con un envase, bajo su mínimo; el adulto (65-100 %) sí entra en su banda.
    assert [_given(plan, pid, "Aspart") for pid in (1, 2, 3)] == [300, 300, 300]
    assert plan.patients[3][0].outside_band and plan.patients[2][0].outside_band
    assert not plan.patients[1][0].outside_band
    assert plan.remaining_units[1] == 1  # el cuarto envase no se entrega: llevaría a alguien al 133 %


# --- La prioridad vale entre insulinas, no solo dentro de cada una ----------------


def test_minor_on_glulisine_gets_the_aspart_before_other_adults_use_it_as_their_own():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 4)]  # 1.200 UI
    pats = [
        PatientInput(1, False, {"Aspart": 1200 / DAYS}),  # adulto sin prioridad, usa aspart
        PatientInput(2, True, {"Glulisina": 600 / DAYS}),  # menor sin glulisina: aspart como sustituto
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    menor = plan.patients[2][0]
    assert menor.substitute == "Aspart" and menor.substitute_equiv_ui == 600  # tratamiento completo
    assert _given(plan, 1, "Aspart") == 600  # el adulto recibe lo que queda


def test_type1_adult_on_glulisine_and_other_adult_on_aspart_both_get_some_aspart():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 4)]
    pats = [
        PatientInput(1, False, {"Aspart": 1200 / DAYS}),
        PatientInput(2, False, {"Glulisina": 900 / DAYS}, is_type1=True),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert plan.patients[2][0].substitute_equiv_ui >= 300  # el tipo 1 con glulisina no queda en 0
    assert _given(plan, 1, "Aspart") >= 300  # ni el usuario propio de aspart
    assert plan.patients[2][0].substitute_equiv_ui + _given(plan, 1, "Aspart") == 1200  # y se usó todo


def test_minor_substitute_comes_before_type1_adults_own_insulin():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 4)]
    pats = [
        PatientInput(1, False, {"Aspart": 1200 / DAYS}, is_type1=True),
        PatientInput(2, True, {"Glulisina": 900 / DAYS}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert plan.patients[2][0].substitute_equiv_ui == 900
    assert _given(plan, 1, "Aspart") == 300


def test_minors_are_completed_and_nobody_else_is_left_at_zero_when_stock_is_mixed():
    # 2 menores con glulisina, 1 adulto tipo 1 con regular y 1 adulto con mucha necesidad de aspart.
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 6), _lot(2, "Lispro", "Humalog", 300, 4)]
    pats = [
        PatientInput(1, True, {"Glulisina": 600 / DAYS}),
        PatientInput(2, True, {"Glulisina": 900 / DAYS}),
        PatientInput(3, False, {"Regular": 1200 / DAYS}, is_type1=True),
        PatientInput(4, False, {"Aspart": 3000 / DAYS}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    for pid, ing in ((1, "Glulisina"), (2, "Glulisina")):
        r = next(x for x in plan.patients[pid] if x.ingredient == ing)
        assert r.given_ui + r.substitute_equiv_ui >= r.need_ui, (pid, ing)  # menores completos
    for pid in (3, 4):
        r = plan.patients[pid][0]
        assert r.given_ui + r.substitute_equiv_ui > 0, pid  # nadie en 0


# --- Garantía 100 % sin pasar del 120 % para menores y adultos tipo 1 -------------------


def _coverage(plan, pid, ing):
    r = next(x for x in plan.patients[pid] if x.ingredient == ing)
    return (r.given_ui + r.substitute_equiv_ui) / r.need_ui


def test_priority_patient_lands_inside_its_band_when_a_combination_fits():
    # Necesidad 700 UI: 3 pens de 300 = 900 (128 %) no entra; 2 pens = 600 (86 %) sí entra en la banda
    # de un menor (80-120 %) y en la de un tipo 1 (75-110 %), con el mínimo de envases.
    lots = [_lot(1, "Glargina", "Abasaglar 3 ml", 300, 20), _lot(2, "Glargina", "Toujeo SoloStar 1.5 ml", 450, 20)]
    minor = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 700 / DAYS})], reserve_pct=0)
    assert sum(a.ui for a in minor.assignments) == 600
    assert not minor.patients[1][0].outside_band
    type1 = plan_distribution(lots, [PatientInput(1, False, {"Glargina": 700 / DAYS}, is_type1=True)], reserve_pct=0)
    assert sum(a.ui for a in type1.assignments) == 600
    assert 0.8 <= _coverage(type1, 1, "Glargina") <= 1.1 and not type1.patients[1][0].outside_band


def test_window_is_met_exactly_when_two_sizes_add_up():
    lots = [_lot(1, "Glargina", "Abasaglar 3 ml", 300, 20), _lot(2, "Glargina", "Toujeo SoloStar 1.5 ml", 450, 20)]
    # Necesidad 900 UI, banda de menor 720-1.080: 450 + 300 = 750 (83 %) es la combinación mixta más
    # cercana al mínimo; 3 pens iguales (900) también entran pero el motor prefiere acercarse al mínimo.
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 900 / DAYS})], reserve_pct=0)
    assert sum(a.ui for a in plan.assignments) == 750


def test_when_no_combination_fits_the_120_percent_cap_wins_over_the_minimum():
    # 400 UI con pens de 300: 1 pen = 75 % (bajo el 80 %), 2 = 150 % (pasa del 120 %, prohibido).
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 20)]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Aspart": 400 / DAYS})], reserve_pct=0)
    assert round(_coverage(plan, 1, "Aspart"), 2) == 0.75
    assert plan.patients[1][0].outside_band and not plan.patients[1][0].min_pen_exception


def test_a_vial_is_not_given_to_a_dose_where_it_would_pass_the_cap_pens_are():
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 20), _lot(2, "Aspart", "NovoRapid Dstfl 10 ml", 1000, 20)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Aspart": 12.0})], reserve_pct=0)
    # 12 UI/día = 720 UI: un vial sería 139 %; 2 pens = 600 (83 %) entran en la banda 65-100 %.
    assert sum(a.ui for a in plan.assignments) == 600
    assert all(a.lot_id == 1 for a in plan.assignments)


def test_lantus_is_kept_for_minors_when_it_fits_the_window():
    lots = [
        _lot(1, "Glargina", "Lantus SoloStar", 300, 20),
        _lot(2, "Glargina", "Toujeo SoloStar 1.5 ml", 450, 20),
    ]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 600 / DAYS})], reserve_pct=0)
    assert _units_by_patient(plan)[1] == {1: 2}  # 2 pens de Lantus = 100 %


def test_lantus_gives_way_when_only_another_pen_reaches_the_window():
    # 500 UI: Lantus 2 pens = 600 (120 %) cabe en la banda y se prefiere sobre un Toujeo de 450 (90 %)
    lots = [
        _lot(1, "Glargina", "Lantus SoloStar", 300, 20),
        _lot(2, "Glargina", "Toujeo SoloStar 1.5 ml", 450, 20),
    ]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 500 / DAYS})], reserve_pct=0)
    assert _units_by_patient(plan)[1] == {1: 2}
    # 360 UI: Lantus 2 = 167 % y Toujeo 1 = 125 % pasan del 120 %: queda con un Lantus (83 %)
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 360 / DAYS})], reserve_pct=0)
    assert _units_by_patient(plan)[1] == {1: 1}


# --- Tope de 30 UI/día para menores en seis insulinas ----------------------------------


def test_minors_daily_dose_is_capped_at_30_in_the_six_insulins_whatever_is_registered():
    assert MINOR_DAILY_CAP_UI == 30
    for ing in ("Glargina", "Lispro", "Glulisina", "Aspart", "Detemir", "Degludec"):
        lots = [_lot(1, ing, "Producto", 300, 100)]
        plan = plan_distribution(lots, [PatientInput(1, True, {ing: 48.0})], reserve_pct=0, substitutions=())
        r = plan.patients[1][0]
        assert r.need_ui == 30 * DAYS, ing
        assert (r.daily_registered, r.daily_applied) == (48.0, 30.0)


def test_cap_does_not_apply_to_other_insulins_adults_or_doses_below_30():
    lots = [_lot(1, "NPH", "Insulatard", 300, 100), _lot(2, "Mixta", "Mix", 300, 100), _lot(3, "Regular", "Actrapid", 300, 100), _lot(4, "Aspart", "NovoRapid", 300, 100)]
    pats = [
        PatientInput(1, True, {"NPH": 45.0, "Aspart": 25.0}),  # menor: basal sin tope + rápida bajo 30
        PatientInput(4, True, {"Mixta": 40.0, "Regular": 50.0}),  # menor: premezcla y regular sin tope
        PatientInput(2, False, {"Aspart": 45.0}),  # adulto
        PatientInput(3, False, {"Aspart": 45.0}, is_type1=True),  # adulto tipo 1
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    menor = {r.ingredient: r for r in plan.patients[1]}
    assert menor["NPH"].need_ui == 45 * DAYS
    assert menor["Aspart"].need_ui == 25 * DAYS and menor["Aspart"].daily_applied == 25.0
    otro = {r.ingredient: r for r in plan.patients[4]}
    assert otro["Mixta"].need_ui == 40 * DAYS
    assert otro["Regular"].need_ui == 50 * DAYS
    assert plan.patients[2][0].need_ui == 45 * DAYS and plan.patients[3][0].need_ui == 45 * DAYS


def test_cap_applies_per_insulin_line_and_exactly_30_is_unchanged():
    lots = [_lot(1, "Glargina", "Lantus", 300, 100), _lot(2, "Aspart", "NovoRapid", 300, 100)]
    pats = [PatientInput(1, True, {"Glargina": 30.0, "Aspart": 31.0})]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    r = {x.ingredient: x for x in plan.patients[1]}
    assert r["Glargina"].need_ui == 30 * DAYS and r["Aspart"].need_ui == 30 * DAYS


def test_cap_can_be_turned_off():
    lots = [_lot(1, "Glargina", "Lantus", 300, 100)]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 48.0})], reserve_pct=0, minor_daily_cap_ui=None)
    assert plan.patients[1][0].need_ui == 48 * DAYS


def test_preferred_brand_wins_a_tie_between_brands():
    # 900 UI: 3 Lantus de 300 o 2 Toujeo de 450, ambos exactos; para menores va Lantus.
    lots = [
        _lot(1, "Glargina", "Lantus SoloStar", 300, 20),
        _lot(2, "Glargina", "Toujeo SoloStar 1.5 ml", 450, 20),
    ]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 900 / DAYS})], reserve_pct=0)
    assert _units_by_patient(plan)[1] == {1: 3}


def test_brand_preference_is_left_when_it_would_break_the_band():
    # 400 UI (banda de menor 85-120 % = 340 a 480): Lantus da 300 (75 %) o 600 (150 %), ninguno entra;
    # un Toujeo de 450 UI (112 %) sí. La banda manda sobre la marca.
    lots = [
        _lot(1, "Glargina", "Lantus SoloStar", 300, 20),
        _lot(2, "Glargina", "Toujeo SoloStar 1.5 ml", 450, 20),
    ]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 400 / DAYS})], reserve_pct=0)
    assert _units_by_patient(plan)[1] == {2: 1}
    assert sum(a.ui for a in plan.assignments) == 450
    assert COVERAGE_BANDS[1][0] <= _coverage(plan, 1, "Glargina") <= COVERAGE_BANDS[1][1]


# --- Nunca se cambia una insulina por otra fuera de las reglas definidas -------------


def test_degludec_is_never_replaced_with_nph_but_nph_can_be_replaced_with_degludec():
    # Hay stock de NPH, detemir, aspart y lispro pero NO de degludec ni de glargina: nadie
    # recibe NPH por degludec (ni detemir, que no está en su fila de la tabla).
    lots = [
        _lot(1, "NPH", "Insulatard", 300, 50),
        _lot(2, "Detemir", "Levemir", 300, 50),
        _lot(3, "Aspart", "NovoRapid", 300, 50),
        _lot(4, "Lispro", "Humalog", 300, 50),
    ]
    pats = [
        PatientInput(1, True, {"Degludec": 20.0}),
        PatientInput(2, False, {"Degludec": 20.0}, is_type1=True),
        PatientInput(3, True, {"Degludec": 20.0}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert plan.assignments == []
    for pid in (1, 2, 3):
        assert plan.patients[pid][0].substitute is None
    # al revés sí: la tabla permite NPH -> degludec (y nunca glargina, que no está en la fila de NPH)
    lots_deg = [_lot(1, "Degludec", "Tresiba", 600, 50), _lot(2, "Glargina", "Lantus", 300, 50)]
    plan = plan_distribution(lots_deg, [PatientInput(1, True, {"NPH": 20.0})], reserve_pct=0)
    assert plan.patients[1][0].substitute == "Degludec"
    assert {a.lot_id for a in plan.assignments} == {1}


def test_default_substitutions_are_exactly_the_foundation_table():
    from app.core.insulin_distribution import DEFAULT_SUBSTITUTIONS

    pares = [(r.source, r.target) for r in DEFAULT_SUBSTITUTIONS]
    assert pares == [
        ("Glargina", "Detemir"),
        ("Glargina", "Degludec"),
        ("Detemir", "Glargina"),
        ("Detemir", "Degludec"),
        ("Degludec", "Glargina"),
        ("Glulisina", "Aspart"),
        ("Glulisina", "Lispro"),
        ("Lispro", "Aspart"),
        ("Lispro", "Glulisina"),
        ("Aspart", "Lispro"),
        ("Aspart", "Glulisina"),
        ("Regular", "Aspart"),
        ("Regular", "Lispro"),
        ("NPH", "Degludec"),
        ("NPH", "Detemir"),
        ("NPH", "Mixta"),
    ]


# --- Una sola insulina de cada grupo (rápidas / basales) -------------------------------


def test_groups_are_the_two_defined_ones():
    assert INSULIN_GROUPS["RAPIDA"] == {"Lispro", "Aspart", "Glulisina", "Regular"}
    assert INSULIN_GROUPS["BASAL"] == {"Glargina", "Mixta", "NPH", "Detemir", "Degludec"}
    assert insulin_group("Aspart") == "RAPIDA" and insulin_group("Degludec") == "BASAL"
    assert insulin_group("Otra") is None


def test_one_insulin_per_group_is_fine_and_so_is_a_single_insulin():
    clean, conflicts = split_group_conflicts({"Glargina": 20.0, "Lispro": 10.0})
    assert clean == {"Glargina": 20.0, "Lispro": 10.0} and conflicts == {}
    assert split_group_conflicts({"NPH": 30.0})[1] == {}


def test_two_different_insulins_of_the_same_group_are_a_conflict():
    clean, conflicts = split_group_conflicts({"Lispro": 28.0, "Aspart": 28.0, "Glargina": 27.0})
    assert clean == {"Glargina": 27.0}  # la basal sí se reparte
    assert conflicts == {"RAPIDA": {"Lispro": 28.0, "Aspart": 28.0}}
    clean, conflicts = split_group_conflicts({"Degludec": 10.0, "NPH": 40.0, "Regular": 8.0})
    assert clean == {"Regular": 8.0} and conflicts == {"BASAL": {"Degludec": 10.0, "NPH": 40.0}}


def test_both_groups_can_conflict_at_once():
    clean, conflicts = split_group_conflicts(
        {"Glulisina": 10.0, "Aspart": 16.0, "NPH": 40.0, "Glargina": 40.0}
    )
    assert clean == {} and set(conflicts) == {"RAPIDA", "BASAL"}


def _choice(plan, pid, group="RAPIDA"):
    return next(c for c in plan.group_choices if c.patient_id == pid and c.group == group)


def test_with_two_of_the_same_group_only_one_is_used_the_one_with_more_stock():
    lots = [_lot(1, "Lispro", "Humalog", 300, 100), _lot(2, "Aspart", "NovoRapid", 300, 10)]
    pats = [PatientInput(1, False, {"Lispro": 20.0, "Aspart": 20.0})]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert [r.ingredient for r in plan.patients[1]] == ["Lispro"]  # una sola, nunca las dos
    c = _choice(plan, 1)
    assert (c.chosen, c.reason) == ("Lispro", "STOCK") and set(c.options) == {"Lispro", "Aspart"}


def test_the_insulin_that_has_stock_wins_even_with_a_lower_dose():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 50)]  # no hay lispro en la donación
    pats = [PatientInput(1, False, {"Lispro": 40.0, "Aspart": 10.0})]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert [r.ingredient for r in plan.patients[1]] == ["Aspart"]
    assert plan.patients[1][0].need_ui == 10 * DAYS  # se calcula con la dosis de la elegida


def test_basal_group_picks_the_one_that_is_not_short():
    lots = [_lot(1, "Glargina", "Lantus", 300, 1), _lot(2, "NPH", "Insulatard", 300, 100)]
    pats = [PatientInput(1, False, {"Glargina": 20.0, "NPH": 20.0})]  # 1.200 UI: la glargina no alcanza
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _choice(plan, 1, "BASAL").chosen == "NPH"


def test_a_known_substitution_counts_as_availability():
    # Ni glulisina ni lispro tienen stock; la glulisina se cubre con aspart (regla conocida).
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 50)]
    pats = [PatientInput(1, False, {"Glulisina": 10.0, "Lispro": 10.0})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    c = _choice(plan, 1)
    assert (c.chosen, c.reason, c.substitute) == ("Glulisina", "SUSTITUTO", "Aspart")
    assert plan.patients[1][0].substitute == "Aspart"


def test_an_adult_is_routed_through_the_substitution_table_when_choosing():
    # Glargina y degludec registradas, sin stock propio; hay detemir: glargina se cubre con detemir.
    lots = [_lot(1, "Detemir", "Levemir", 300, 50), _lot(2, "NPH", "Insulatard", 300, 50)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Glargina": 10.0, "Degludec": 10.0})], reserve_pct=0)
    c = _choice(plan, 1, "BASAL")
    assert c.reason == "SUSTITUTO" and c.substitute == "Detemir" and c.chosen == "Glargina"


def test_when_nothing_can_cover_either_the_higher_registered_dose_is_used():
    plan = plan_distribution([], [PatientInput(1, False, {"Lispro": 10.0, "Aspart": 30.0})], reserve_pct=0)
    c = _choice(plan, 1)
    assert (c.chosen, c.reason) == ("Aspart", "SIN_STOCK")
    assert [r.ingredient for r in plan.patients[1]] == ["Aspart"]


def test_availability_is_measured_after_the_people_with_no_doubt():
    # Hay aspart justo para el paciente 1; el paciente 2 duda entre aspart y lispro.
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 4), _lot(2, "Lispro", "Humalog", 300, 20)]
    pats = [
        PatientInput(1, False, {"Aspart": 1200 / DAYS}),
        PatientInput(2, False, {"Aspart": 20.0, "Lispro": 20.0}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _choice(plan, 2).chosen == "Lispro"
    assert _given(plan, 1, "Aspart") == 1200  # el paciente sin duda conserva su aspart


def test_ambiguous_patients_are_decided_in_priority_order():
    # Stock de aspart para uno solo: lo recibe el menor; el adulto se va a la lispro.
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 4), _lot(2, "Lispro", "Humalog", 300, 4)]
    pats = [
        PatientInput(1, False, {"Aspart": 1200 / DAYS, "Lispro": 1200 / DAYS}),  # adulto, id menor
        PatientInput(2, True, {"Aspart": 1200 / DAYS, "Lispro": 1200 / DAYS}),  # menor
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _choice(plan, 2).chosen in ("Aspart", "Lispro")
    assert {_choice(plan, 1).chosen, _choice(plan, 2).chosen} == {"Aspart", "Lispro"}  # cada uno su stock
    assert _given(plan, 1, _choice(plan, 1).chosen) == 1200 and _given(plan, 2, _choice(plan, 2).chosen) == 1200


def test_both_groups_in_conflict_are_resolved_separately():
    lots = [
        _lot(1, "Glulisina", "Apidra", 300, 50),
        _lot(2, "Glargina", "Lantus", 300, 50),
        _lot(3, "Aspart", "NovoRapid", 300, 1),
        _lot(4, "NPH", "Insulatard", 300, 1),
    ]
    pats = [PatientInput(1, False, {"Glulisina": 10.0, "Aspart": 10.0, "NPH": 40.0, "Glargina": 40.0})]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert {r.ingredient for r in plan.patients[1]} == {"Glulisina", "Glargina"}
    assert len(plan.group_choices) == 2


def test_no_conflict_means_no_choice_recorded():
    lots = [_lot(1, "Glargina", "Lantus", 300, 20), _lot(2, "Aspart", "NovoRapid", 300, 20)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Glargina": 20.0, "Aspart": 10.0})], reserve_pct=0)
    assert plan.group_choices == []


def test_the_same_insulin_registered_twice_is_summed_not_a_conflict():
    # Dos líneas de glargina (mañana y noche) llegan ya sumadas por quien arma el paciente.
    lots = [_lot(1, "Glargina", "Lantus", 300, 20)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Glargina": 20.0})], reserve_pct=0)
    assert plan.patients[1][0].need_ui == 20 * DAYS


def test_every_default_substitution_stays_inside_its_group():
    from app.core.insulin_distribution import DEFAULT_SUBSTITUTIONS

    for rule in DEFAULT_SUBSTITUTIONS:
        assert insulin_group(rule.source) == insulin_group(rule.target), rule


def test_whole_switch_rescue_does_not_fail_when_nobody_uses_the_source_insulin():
    # Hay detemir en la donación pero nadie usa glargina ni hay glargina: no debe fallar.
    lots = [_lot(1, "Detemir", "Levemir", 300, 10)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Aspart": 10.0})], reserve_pct=0)
    assert plan.assignments == []


def test_stock_already_needed_by_others_does_not_count_as_available():
    # El aspart (6.000 UI) parece abundante, pero el paciente 1 ya necesita 5.400. Para el
    # paciente 2 queda más holgura en lispro (3.000 UI), así que decide lispro.
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 20), _lot(2, "Lispro", "Humalog", 300, 10)]
    pats = [
        PatientInput(1, False, {"Aspart": 5400 / DAYS}),
        PatientInput(2, False, {"Aspart": 10.0, "Lispro": 10.0}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _choice(plan, 2).chosen == "Lispro"


def test_the_minor_decides_before_the_adult_when_both_want_the_same_insulin():
    # Aspart tiene más holgura (1.500 UI) que lispro (1.200 UI) y alcanza para uno solo.
    # El menor decide primero y se queda el aspart, aunque su id sea el que sigue.
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 5), _lot(2, "Lispro", "Humalog", 300, 4)]
    pats = [
        PatientInput(1, True, {"Aspart": 1200 / DAYS, "Lispro": 1200 / DAYS}),  # menor
        PatientInput(2, False, {"Aspart": 1200 / DAYS, "Lispro": 1200 / DAYS}),  # adulto
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _choice(plan, 1).chosen == "Aspart"
    assert _choice(plan, 2).chosen == "Lispro"

    # y con los ids al revés el menor sigue decidiendo primero
    pats = [
        PatientInput(1, False, {"Aspart": 1200 / DAYS, "Lispro": 1200 / DAYS}),  # adulto
        PatientInput(2, True, {"Aspart": 1200 / DAYS, "Lispro": 1200 / DAYS}),  # menor
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _choice(plan, 2).chosen == "Aspart"
    assert _choice(plan, 1).chosen == "Lispro"


# --- Una premezcla nunca sustituye a una basal -----------------------------------------


def test_premix_set_is_protamina():
    assert PREMIX_INSULINS == {"Mixta"}


def test_a_premix_registered_next_to_a_basal_is_discarded_even_with_more_stock():
    # Glargina sin stock; la premezcla tiene de sobra. La basal manda: la premezcla no la sustituye.
    lots = [_lot(1, "Mixta", "Humalog Mix 25", 300, 100)]
    pats = [PatientInput(1, False, {"Glargina": 20.0, "Mixta": 18.0})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    c = _choice(plan, 1, "BASAL")
    assert c.chosen == "Glargina" and c.premix_discarded is True and c.reason == "SIN_STOCK"
    assert [r.ingredient for r in plan.patients[1]] == ["Glargina"]
    assert plan.assignments == []  # y no se le dio la premezcla


def test_premix_loses_against_every_basal_in_its_group():
    for basal in ("Glargina", "NPH", "Detemir", "Degludec"):
        lots = [_lot(1, "Mixta", "Mix", 300, 100), _lot(2, basal, "Basal", 300, 100)]
        plan = plan_distribution(lots, [PatientInput(1, False, {basal: 10.0, "Mixta": 30.0})], reserve_pct=0)
        assert _choice(plan, 1, "BASAL").chosen == basal, basal
        assert _choice(plan, 1, "BASAL").premix_discarded


def test_with_a_premix_and_two_basals_only_the_basals_compete():
    lots = [
        _lot(1, "Mixta", "Mix", 300, 500),  # muchísimo stock
        _lot(2, "NPH", "Insulatard", 300, 1),  # casi nada
        _lot(3, "Detemir", "Levemir", 300, 100),
    ]
    pats = [PatientInput(1, False, {"NPH": 20.0, "Detemir": 20.0, "Mixta": 20.0})]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _choice(plan, 1, "BASAL").chosen == "Detemir"


def test_a_premix_alone_is_the_patients_own_insulin_and_is_distributed():
    lots = [_lot(1, "Mixta", "Humalog Mix 25", 300, 20)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Mixta": 10.0})], reserve_pct=0)
    assert plan.group_choices == []
    assert _given(plan, 1, "Mixta") == 10 * DAYS


def test_a_premix_never_covers_a_missing_basal_through_substitution():
    # Glargina sin stock ni detemir; sobran premezclas: el adulto queda sin cubrir.
    lots = [_lot(1, "Mixta", "Mix", 300, 100), _lot(2, "NPH", "Insulatard", 300, 100)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Glargina": 20.0})], reserve_pct=0)
    assert plan.assignments == []
    assert plan.patients[1][0].substitute is None


def test_a_substitution_rule_with_a_premix_as_target_is_rejected():
    from app.core.insulin_distribution import Substitution

    bad = [Substitution("Glargina", "Mixta", factor=1.0)]
    try:
        plan_distribution([_lot(1, "Mixta", "Mix", 300, 10)], [PatientInput(1, False, {"Glargina": 10.0})], substitutions=bad)
    except ValueError as exc:
        assert "premezcla" in str(exc).lower()
    else:
        raise AssertionError("debía rechazar una regla con una premezcla como destino")


def test_default_substitutions_never_target_a_premix():
    from app.core.insulin_distribution import DEFAULT_SUBSTITUTIONS

    # Una premezcla solo es destino de la NPH: nunca de una basal análoga.
    for r in DEFAULT_SUBSTITUTIONS:
        if r.target in PREMIX_INSULINS:
            assert r.source in PREMIX_REPLACEABLE, r


def test_the_dose_does_not_depend_on_the_concentration_only_the_units_per_pen_do():
    """40 UI son 40 UI sea U100 o U300: la necesidad es la misma; cambia cuántos envases hacen falta."""
    need = 40 * DAYS  # 2.400 UI, banda 75-100 % = 1.800 a 2.400
    casos = {  # UI por envase -> envases esperados sin pasar del 100 %
        300: 8,  # 3 ml U100: 2.400 exactas
        600: 4,  # 3 ml U200: 2.400 exactas
        450: 5,  # 1,5 ml U300: 2.250 (94 %); 6 envases pasarían del 100 %
        900: 2,  # 3 ml U300: 1.800 (75 %); 3 envases serían 112 %
    }
    for ui_por_envase, envases in casos.items():
        lots = [_lot(1, "Glargina", "Insulina", ui_por_envase, 100)]
        plan = plan_distribution(lots, [PatientInput(1, False, {"Glargina": 40.0})], reserve_pct=0)
        r = plan.patients[1][0]
        assert r.need_ui == need, ui_por_envase  # la necesidad NO cambia con la concentración
        assert sum(a.units for a in plan.assignments) == envases, ui_por_envase
        assert 0.75 * need <= r.given_ui <= need and not r.outside_band



# --- Tabla de sustituciones de la Fundación, fila por fila ---------------------------------


def _covered_by(source, stocked, dose=20.0):
    """A quién se le da si falta `source` y solo hay stock de las insulinas de `stocked`."""
    lots = [_lot(i + 1, ing, f"Producto {ing}", 300, 100) for i, ing in enumerate(stocked)]
    plan = plan_distribution(lots, [PatientInput(1, False, {source: dose})], reserve_pct=0)
    r = plan.patients[1][0]
    return r.substitute, (r.given_ui + r.substitute_equiv_ui) / r.need_ui


def test_each_row_of_the_table_substitutes_with_every_listed_insulin():
    tabla = {
        "Glargina": ("Detemir", "Degludec"),
        "Detemir": ("Glargina", "Degludec"),
        "Degludec": ("Glargina",),
        "Glulisina": ("Aspart", "Lispro"),
        "Lispro": ("Aspart", "Glulisina"),
        "Aspart": ("Lispro", "Glulisina"),
        "Regular": ("Aspart", "Lispro"),
        "NPH": ("Degludec", "Detemir", "Mixta"),
    }
    for source, targets in tabla.items():
        for target in targets:
            sub, cov = _covered_by(source, [target])
            assert sub == target and cov >= 1.0, (source, target)


def test_insulins_outside_the_table_are_never_used_as_substitutes():
    nada_en_la_tabla = {
        "Degludec": ["Detemir", "NPH", "Mixta", "Aspart"],  # degludec solo por glargina
        "Glargina": ["NPH", "Mixta", "Aspart"],
        "Detemir": ["NPH", "Mixta", "Lispro"],
        "Glulisina": ["Regular", "Glargina", "NPH"],
        "Lispro": ["Regular", "Glargina", "Detemir"],
        "Aspart": ["Regular", "Glargina", "NPH"],
        "Regular": ["Glulisina", "Glargina", "NPH"],  # regular solo por aspart o lispro
    }
    for source, otros in nada_en_la_tabla.items():
        sub, cov = _covered_by(source, otros)
        assert sub is None and cov == 0, (source, otros)


def test_a_single_substitute_is_preferred_to_mixing_two_basals():
    # Glargina por detemir o degludec. El detemir (2 envases) no alcanza solo, el degludec sí:
    # el adulto pasa entero a degludec y el detemir queda para otro.
    lots = [_lot(1, "Detemir", "Levemir", 300, 2), _lot(2, "Degludec", "Tresiba", 300, 50)]
    pats = [PatientInput(1, False, {"Glargina": 1500 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    r = plan.patients[1][0]
    assert r.substitute == "Degludec"
    assert r.given_ui + r.substitute_equiv_ui == 1500
    assert {a.lot_id for a in plan.assignments} == {2}


def test_substitutes_are_combined_in_table_order_when_none_reaches_alone():
    lots = [_lot(1, "Detemir", "Levemir", 300, 2), _lot(2, "Degludec", "Tresiba", 300, 3)]  # 600 + 900
    pats = [PatientInput(1, False, {"Glargina": 1500 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    r = plan.patients[1][0]
    assert r.substitute == "Detemir + Degludec"  # el orden de la tabla
    assert r.given_ui + r.substitute_equiv_ui == 1500
    por_lote = {a.lot_id: a.ui for a in plan.assignments}
    assert por_lote[1] == 600  # el detemir se usó completo primero


def test_the_first_listed_substitute_is_used_when_there_is_enough():
    lots = [_lot(1, "Detemir", "Levemir", 300, 50), _lot(2, "Degludec", "Tresiba", 300, 50)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Glargina": 600 / DAYS})], reserve_pct=0)
    assert plan.patients[1][0].substitute == "Detemir"
    assert {a.lot_id for a in plan.assignments} == {1}


def test_regular_prefers_aspart_then_lispro():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 50), _lot(2, "Lispro", "Humalog", 300, 50)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Regular": 600 / DAYS})], reserve_pct=0)
    assert plan.patients[1][0].substitute == "Aspart"
    # sin aspart, lispro
    plan = plan_distribution([_lot(2, "Lispro", "Humalog", 300, 50)], [PatientInput(1, False, {"Regular": 600 / DAYS})], reserve_pct=0)
    assert plan.patients[1][0].substitute == "Lispro"


def test_a_premix_is_only_a_substitute_of_nph_in_the_table():
    from app.core.insulin_distribution import DEFAULT_SUBSTITUTIONS, PREMIX_INSULINS

    assert [(r.source, r.target) for r in DEFAULT_SUBSTITUTIONS if r.target in PREMIX_INSULINS] == [("NPH", "Mixta")]
    assert all(r.source not in PREMIX_INSULINS for r in DEFAULT_SUBSTITUTIONS)  # y una premezcla no se sustituye


# --- Piso solidario: nadie queda en 0 % mientras quede un envase -------------------------


def test_solidarity_floor_gives_everyone_a_pen_before_sharing_proportionally():
    # Necesidades 300, 300 y 3.000 UI con 3 envases: en proporción las dos pequeñas
    # tocaban 0 envases; con el piso cada una recibe uno.
    lots = [_lot(1, "NPH", "Insulatard", 300, 3)]
    pats = [
        PatientInput(1, False, {"NPH": 300 / DAYS}),
        PatientInput(2, False, {"NPH": 300 / DAYS}),
        PatientInput(3, False, {"NPH": 3000 / DAYS}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    for pid in (1, 2, 3):
        assert _given(plan, pid, "NPH") >= 300, pid  # nadie en 0


def test_with_fewer_pens_than_patients_each_pen_goes_to_a_different_patient():
    lots = [_lot(1, "NPH", "Insulatard", 300, 2)]
    pats = [
        PatientInput(1, False, {"NPH": 3000 / DAYS}),
        PatientInput(2, False, {"NPH": 300 / DAYS}),
        PatientInput(3, False, {"NPH": 600 / DAYS}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    got = sorted(_given(plan, pid, "NPH") for pid in (1, 2, 3))
    assert got == [0, 300, 300]  # nadie recibe dos envases mientras otro no recibió ninguno


def test_priority_groups_are_still_completed_before_the_floor_reaches_the_others():
    lots = [_lot(1, "NPH", "Insulatard", 300, 4)]  # 1.200 UI
    pats = [
        PatientInput(1, False, {"NPH": 900 / DAYS}),
        PatientInput(2, True, {"NPH": 900 / DAYS}),  # menor: se completa primero
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _given(plan, 2, "NPH") == 900 and _given(plan, 1, "NPH") == 300


def test_the_scarce_substitute_completes_one_patient_instead_of_splitting_two_below_the_band():
    # 2 envases de sustituto para dos pacientes con la misma necesidad (600 UI): uno entra en su
    # banda y el otro queda sin nada; repartir 300/300 dejaría a los dos bajo el mínimo.
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 2)]
    pats = [
        PatientInput(1, False, {"Glulisina": 600 / DAYS}),
        PatientInput(2, False, {"Glulisina": 600 / DAYS}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    cov = {pid: plan.patients[pid][0].substitute_equiv_ui for pid in (1, 2)}
    assert cov == {1: 600, 2: 0}



# --- Reparto por prioridad dentro de la banda de cada grupo ---------------------------------


def test_each_group_gets_its_minimum_before_anyone_is_topped_up():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 9)]  # 2.700 UI
    need = 1200 / DAYS
    pats = [
        PatientInput(1, True, {"Aspart": 600 / DAYS}),  # menor: 600
        PatientInput(2, False, {"Aspart": need}, is_type1=True),
        PatientInput(3, False, {"Aspart": need}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _given(plan, 1, "Aspart") == 600  # el menor completo
    assert _given(plan, 3, "Aspart") == 900  # el resto, su piso del 75 %
    assert _given(plan, 2, "Aspart") == 1200  # y con el sobrante se completa al tipo 1


def test_minors_are_never_limited_to_make_room_for_the_rest():
    lots = [_lot(1, "NPH", "Insulatard", 300, 5)]  # 1.500 UI
    pats = [
        PatientInput(1, True, {"NPH": 1200 / DAYS}),
        PatientInput(2, False, {"NPH": 1200 / DAYS}),
        PatientInput(3, False, {"NPH": 1200 / DAYS}, is_type1=True),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _given(plan, 1, "NPH") == 1200  # el menor completo aunque a los demás no les llegue al 75 %
    assert _given(plan, 2, "NPH") + _given(plan, 3, "NPH") == 300


def test_nobody_is_left_at_zero_while_there_are_pens():
    lots = [_lot(1, "NPH", "Insulatard", 300, 5)]
    pats = [PatientInput(i, False, {"NPH": 3000 / DAYS}) for i in range(1, 5)]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert all(_given(plan, i, "NPH") >= 300 for i in range(1, 5))
    assert sum(_given(plan, i, "NPH") for i in range(1, 5)) == 1500


def test_the_bands_never_touch_the_reserve_when_release_is_off():
    lots = [_lot(1, "NPH", "Insulatard", 300, 10)]  # 3.000 UI, reserva 5 % = 150 -> 1 envase de 300
    pats = [PatientInput(i, False, {"NPH": 3000 / DAYS}) for i in range(1, 4)]
    plan = plan_distribution(lots, pats, release_reserve=False)
    assert plan.reserve_ui >= 300
    assert sum(_given(plan, i, "NPH") for i in range(1, 4)) <= 2700


def test_substitute_stock_feeds_the_band_of_those_without_own_insulin():
    # Nadie usa glulisina en stock: los adultos con glulisina o regular salen por la tabla.
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 8), _lot(2, "Lispro", "Humalog", 300, 8)]
    pats = [
        PatientInput(1, False, {"Glulisina": 1200 / DAYS}),
        PatientInput(2, False, {"Regular": 1200 / DAYS}, is_type1=True),
        PatientInput(3, False, {"Aspart": 1200 / DAYS}),
        PatientInput(4, False, {"Lispro": 1200 / DAYS}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    for pid in (1, 2, 3, 4):
        r = plan.patients[pid][0]
        assert (r.given_ui + r.substitute_equiv_ui) / r.need_ui >= 0.75, pid


# --- Prioridades con margen de cobertura que no se debe romper ---------------------------------

from app.core.insulin_distribution import (  # noqa: E402
    PRIORITY_MINOR,
    PRIORITY_OLDER_TYPE2,
    PRIORITY_TYPE1,
    PRIORITY_TYPE2,
    is_type2_diabetes,
    priority_group_for,
)


def _p(pid, group, dose, ing="NPH"):
    return PatientInput(pid, group == PRIORITY_MINOR, {ing: dose}, is_type1=group == PRIORITY_TYPE1, priority_group=group)


def test_bands_are_the_foundation_ones():
    assert COVERAGE_BANDS == {
        PRIORITY_MINOR: (0.80, 1.20),
        PRIORITY_TYPE1: (0.75, 1.10),
        PRIORITY_OLDER_TYPE2: (0.65, 1.00),
        PRIORITY_TYPE2: (0.65, 1.00),
    }


def test_is_type2_diabetes_reads_free_text():
    for raw in ("Tipo 2", "TIPO 2", "tipo2", "Tipo II", " Diabetes tipo 2 ", "DM2", "Diabetes Mellitus tipo 2"):
        assert is_type2_diabetes(raw), raw
    for raw in ("Tipo 1", "Gestacional", "Otra", "Tipo 20", "", None):
        assert not is_type2_diabetes(raw), raw


def test_priority_group_is_derived_from_age_and_diabetes_type():
    assert priority_group_for(0, "Tipo 2") == PRIORITY_MINOR
    assert priority_group_for(17, "Tipo 1") == PRIORITY_MINOR
    assert priority_group_for(18, "Tipo 1") == PRIORITY_TYPE1
    assert priority_group_for(70, "Tipo 1") == PRIORITY_TYPE1  # un tipo 1 mayor sigue siendo tipo 1
    assert priority_group_for(59, "Tipo 2") == PRIORITY_TYPE2
    assert priority_group_for(60, "Tipo 2") == PRIORITY_OLDER_TYPE2
    assert priority_group_for(60, None) == PRIORITY_TYPE2  # sin tipo de diabetes: el último grupo
    assert priority_group_for(45, "Gestacional") == PRIORITY_TYPE2
    assert priority_group_for(None, "Tipo 2") == PRIORITY_TYPE2


def test_patient_group_defaults_to_minor_type1_or_type2():
    assert PatientInput(1, True, {}).group == PRIORITY_MINOR
    assert PatientInput(1, False, {}, is_type1=True).group == PRIORITY_TYPE1
    assert PatientInput(1, False, {}).group == PRIORITY_TYPE2


def test_every_group_lands_inside_its_own_band_with_ample_stock():
    lots = [_lot(1, "NPH", "Insulatard", 100, 1000)]
    for group, (lo, hi) in COVERAGE_BANDS.items():
        plan = plan_distribution(lots, [_p(1, group, 1000 / DAYS)], reserve_pct=0, substitutions=())
        r = plan.patients[1][0]
        cov = r.given_ui / r.need_ui
        assert lo - 1e-9 <= cov <= hi + 1e-9, (group, cov)
        assert (r.group, r.band_min, r.band_max, r.outside_band) == (group, lo, hi, False)


def test_with_ample_stock_the_leftover_brings_everyone_to_100_percent_when_pens_allow():
    lots = [_lot(1, "NPH", "Insulatard", 100, 1000)]
    for group in COVERAGE_BANDS:
        plan = plan_distribution(lots, [_p(1, group, 1000 / DAYS)], reserve_pct=0, substitutions=())
        assert plan.patients[1][0].given_ui == 1000, group


def test_a_treatment_is_never_taken_above_its_max_when_a_combination_fits():
    # 700 UI con envases de 300: 600 (86 %) cabe en 75-100 %; 900 (129 %) no se da.
    lots = [_lot(1, "NPH", "Insulatard", 300, 100)]
    plan = plan_distribution(lots, [_p(1, PRIORITY_TYPE2, 700 / DAYS)], reserve_pct=0, substitutions=())
    assert plan.patients[1][0].given_ui == 600


def test_strict_priority_under_scarcity_minor_then_type1_then_older_then_type2():
    lots = [_lot(1, "NPH", "Insulatard", 100, 29)]  # 2.900 UI
    dose = 1000 / DAYS  # cada uno necesita 1.000 UI
    pats = [
        _p(1, PRIORITY_TYPE2, dose),
        _p(2, PRIORITY_OLDER_TYPE2, dose),
        _p(3, PRIORITY_TYPE1, dose),
        _p(4, PRIORITY_MINOR, dose),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    got = {pid: _given(plan, pid, "NPH") for pid in (1, 2, 3, 4)}
    assert got[4] == 800  # menor: su mínimo (80 % = 800 UI)
    assert got[3] == 800  # tipo 1: su mínimo (75 % = 750 UI -> 800 con envases de 100)
    assert got[2] == 700  # adulto mayor tipo 2: su mínimo (65 % = 650 UI -> 700)
    assert got[1] == 600  # el último grupo recibe lo que queda, bajo su mínimo (65 %)
    assert plan.patients[1][0].outside_band and not plan.patients[4][0].outside_band


def test_a_lower_group_never_takes_stock_a_higher_group_needs_for_its_minimum():
    lots = [_lot(1, "NPH", "Insulatard", 100, 16)]  # 1.600 UI = justo el mínimo de dos (800 + 800)
    pats = [_p(1, PRIORITY_TYPE2, 1000 / DAYS), _p(2, PRIORITY_TYPE1, 1000 / DAYS), _p(3, PRIORITY_MINOR, 1000 / DAYS)]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _given(plan, 3, "NPH") == 800 and _given(plan, 2, "NPH") == 800
    assert _given(plan, 1, "NPH") == 0


def test_older_type2_is_served_before_other_type2_even_with_a_later_id():
    lots = [_lot(1, "NPH", "Insulatard", 100, 8)]  # 800 UI: solo uno llega a su mínimo (650 UI)
    pats = [_p(1, PRIORITY_TYPE2, 1000 / DAYS), _p(2, PRIORITY_OLDER_TYPE2, 1000 / DAYS)]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    # El adulto mayor llega a su mínimo (700 UI); al otro le queda un envase, no cero.
    assert _given(plan, 2, "NPH") == 700 and _given(plan, 1, "NPH") == 100
    assert not plan.patients[2][0].outside_band and plan.patients[1][0].outside_band


def test_when_no_combination_fits_the_minimum_wins_and_the_case_is_flagged():
    # 400 UI con envases de 300: 1 envase = 75 % (bajo el 80 %), 2 = 150 % (sobre el 120 %, prohibido).
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 20)]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Aspart": 400 / DAYS})], reserve_pct=0)
    r = plan.patients[1][0]
    assert r.given_ui == 300 and r.outside_band
    assert (r.band_min, r.band_max) == (0.80, 1.20)


def test_a_minor_does_not_get_an_adult_only_priority_over_its_own_insulin():
    # Un menor con su insulina en stock no recibe sustituto aunque el sustituto sobre.
    lots = [_lot(1, "Glargina", "Lantus", 300, 4), _lot(2, "Detemir", "Levemir", 300, 40)]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 1200 / DAYS})], reserve_pct=0)
    r = plan.patients[1][0]
    assert r.given_ui == 1200 and r.substitute is None


def test_outside_band_counts_too_few_and_too_many():
    lots = [_lot(1, "NPH", "Insulatard", 300, 100)]
    ok = plan_distribution(lots, [_p(1, PRIORITY_TYPE1, 600 / DAYS)], reserve_pct=0, substitutions=())
    assert not ok.patients[1][0].outside_band
    short = plan_distribution(
        [_lot(1, "NPH", "Insulatard", 300, 1)], [_p(1, PRIORITY_TYPE1, 3000 / DAYS)], reserve_pct=0, substitutions=()
    )
    assert short.patients[1][0].outside_band  # un envase de 3.000 UI no llega al 80 %


def test_patients_unmet_counts_treatments_below_their_band_minimum():
    lots = [_lot(1, "NPH", "Insulatard", 100, 16)]  # 1.600 UI: justo el mínimo del menor (800) y del tipo 1 (800)
    pats = [_p(1, PRIORITY_TYPE2, 1000 / DAYS), _p(2, PRIORITY_TYPE1, 1000 / DAYS), _p(3, PRIORITY_MINOR, 1000 / DAYS)]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    nph = next(i for i in plan.ingredients if i.ingredient == "NPH")
    assert nph.patients_with_need == 3
    assert nph.patients_unmet == 1  # solo el tipo 2, que se queda sin stock
    assert nph.leftover_ui == 0


# --- NPH reemplazable por la premezcla (Mixta) ----------------------------------------------


def test_nph_is_replaced_by_the_premix_when_there_is_no_nph():
    lots = [_lot(1, "Mixta", "Mixtard 30", 300, 50)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"NPH": 600 / DAYS})], reserve_pct=0)
    r = plan.patients[1][0]
    assert r.ingredient == "NPH" and r.given_ui == 0
    assert r.substitute == "Mixta" and r.substitute_ui == 600 and r.substitute_equiv_ui == 600
    assert _by_for(plan, 1, "NPH") == [(1, 2)]


def test_nph_uses_its_own_insulin_first_and_only_the_missing_part_comes_from_the_premix():
    lots = [_lot(1, "NPH", "Insulatard", 300, 2), _lot(2, "Mixta", "Mixtard 30", 300, 50)]
    plan = plan_distribution(lots, [PatientInput(1, True, {"NPH": 1200 / DAYS})], reserve_pct=0)
    r = plan.patients[1][0]
    assert r.given_ui == 600 and r.substitute == "Mixta" and r.substitute_equiv_ui == 600


def test_the_premix_never_replaces_an_analog_basal_but_does_replace_nph():
    lots = [_lot(1, "Mixta", "Mixtard 30", 300, 100)]
    for source in ("Glargina", "Detemir", "Degludec"):
        plan = plan_distribution(lots, [PatientInput(1, False, {source: 20.0})], reserve_pct=0)
        assert plan.assignments == [], source
    plan = plan_distribution(lots, [PatientInput(1, False, {"NPH": 20.0})], reserve_pct=0)
    assert plan.patients[1][0].substitute == "Mixta"


def test_nph_is_not_given_as_a_substitute_of_the_premix():
    # La regla es de un solo sentido: quien usa la premezcla no recibe NPH.
    lots = [_lot(1, "NPH", "Insulatard", 300, 100)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Mixta": 20.0})], reserve_pct=0)
    assert plan.assignments == [] and plan.patients[1][0].substitute is None


def test_the_nph_exception_does_not_open_the_door_to_other_premix_rules():
    from app.core.insulin_distribution import Substitution

    bad = [Substitution("Detemir", "Mixta", factor=1.0)]
    try:
        plan_distribution([_lot(1, "Mixta", "Mix", 300, 10)], [PatientInput(1, False, {"Detemir": 10.0})], substitutions=bad)
    except ValueError as exc:
        assert "premezcla" in str(exc).lower()
    else:
        raise AssertionError("debía rechazar una premezcla como destino de una basal análoga")


def test_nph_prefers_degludec_and_the_premix_completes_when_degludec_runs_out():
    lots = [_lot(1, "Degludec", "Tresiba", 300, 2), _lot(2, "Mixta", "Mixtard 30", 300, 50)]  # degludec: 600 UI
    plan = plan_distribution(lots, [PatientInput(1, False, {"NPH": 1500 / DAYS})], reserve_pct=0)
    r = plan.patients[1][0]
    # La protamina sola alcanza la banda: el adulto pasa entero a la premezcla en vez de mezclar dos insulinas.
    assert r.substitute == "Mixta"
    plan = plan_distribution(
        [_lot(1, "Degludec", "Tresiba", 300, 50), _lot(2, "Mixta", "Mixtard 30", 300, 50)],
        [PatientInput(1, False, {"NPH": 1500 / DAYS})],
        reserve_pct=0,
    )
    assert plan.patients[1][0].substitute == "Degludec"  # con ambas en stock, primero degludec
    assert {a.lot_id for a in plan.assignments} == {1}


def test_degludec_users_and_nph_users_share_degludec_and_both_reach_their_minimum():
    # Con stock para ambos, quien la usa por receta y quien la recibe por la NPH llegan a su mínimo.
    lots = [_lot(1, "Degludec", "Tresiba", 300, 4)]  # 1.200 UI
    pats = [PatientInput(1, False, {"Degludec": 600 / DAYS}), PatientInput(2, False, {"NPH": 600 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert _given(plan, 1, "Degludec") >= 0.65 * 600
    assert plan.patients[2][0].substitute == "Degludec" and plan.patients[2][0].substitute_equiv_ui >= 0.65 * 600


# --- Tope absoluto del 120 % ---------------------------------------------------------------------


def test_coverage_never_passes_120_percent_with_mixed_pen_sizes():
    from app.core.insulin_distribution import MAX_COVERAGE

    assert MAX_COVERAGE == 1.20
    lots = [
        _lot(1, "Aspart", "NovoRapid Dstfl 10 ml", 1000, 50),
        _lot(2, "Aspart", "NovoRapid Penfill", 300, 6),
        _lot(3, "Lispro", "Humalog Dstfl 10 ml", 1000, 50),
    ]
    pats = [PatientInput(i, i % 3 == 0, {"Aspart": (5 + 3 * i) / 1.0}, is_type1=i % 2 == 0) for i in range(1, 25)]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    for rs in plan.patients.values():
        for r in rs:
            cov = (r.given_ui + r.substitute_equiv_ui) / r.need_ui
            assert cov <= 1.20 + 1e-9 or r.min_pen_exception, (r, cov)


def test_a_10_ml_vial_is_not_given_to_a_low_dose_when_the_pens_ran_out():
    # 10 UI/día = 600 UI: un vial de 1.000 UI sería 167 %. Los pens se agotaron con el primero.
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 2), _lot(2, "Aspart", "NovoRapid Dstfl 10 ml", 1000, 10)]
    pats = [PatientInput(1, False, {"Aspart": 600 / DAYS}), PatientInput(2, False, {"Aspart": 600 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert _given(plan, 1, "Aspart") == 600
    assert _given(plan, 2, "Aspart") == 0  # el vial no se entrega: pasaría del 120 %
    assert not plan.patients[2][0].min_pen_exception  # hay pens de 300 UI en la donación: no es la excepción


def test_a_very_low_dose_gets_one_smallest_pen_when_no_pen_fits_120_percent():
    # 4 UI/día = 240 UI: el envase más chico (300 UI) es 125 %. Un envase no se parte: recibe uno solo.
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 10), _lot(2, "Aspart", "NovoRapid Dstfl 10 ml", 1000, 10)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Aspart": 4.0})], reserve_pct=0)
    r = plan.patients[1][0]
    assert _units_by_patient(plan)[1] == {1: 1}  # el pen de 300 UI, nunca el vial
    assert r.min_pen_exception and r.outside_band


def test_the_low_dose_exception_never_hands_out_a_bigger_envase_when_the_small_ones_ran_out():
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 1), _lot(2, "Aspart", "NovoRapid Dstfl 10 ml", 1000, 10)]
    pats = [PatientInput(1, True, {"Aspart": 4.0}), PatientInput(2, True, {"Aspart": 4.0})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    got = sorted(_given(plan, pid, "Aspart") for pid in (1, 2))
    assert got == [0, 300]  # uno recibe el único pen; al otro no se le da un vial de 1.000 UI


def test_a_minor_without_a_combination_between_80_and_120_gets_the_closest_to_100_percent():
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 50)]
    casos = {  # UI/día -> (envases, cobertura, fuera de banda)
        6.0: (1, 300 / 360, False),  # 1 pen = 83 % ya entra en 80-120 %
        8.0: (2, 600 / 480, True),  # 1 pen = 62,5 % frente a 2 = 125 %: más cerca el 125 %
        12.0: (2, 600 / 720, False),  # 2 pens = 83 % ya entra en 80-120 %
        4.0: (1, 300 / 240, True),  # 1 pen = 125 %: el envase no se parte
    }
    for dosis, (envases, cobertura, fuera) in casos.items():
        plan = plan_distribution(lots, [PatientInput(1, True, {"Aspart": dosis})], reserve_pct=0)
        assert sum(a.units for a in plan.assignments) == envases, dosis
        assert abs(_coverage(plan, 1, "Aspart") - cobertura) < 1e-9, dosis
        assert plan.patients[1][0].outside_band is fuera, dosis


def test_closest_to_100_percent_is_only_for_minors():
    # Un tipo 1 de 8 UI/día (480 UI, banda 75-110 %): 2 pens = 125 % pasarían del 120 %; queda con 1.
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 50)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Aspart": 8.0}, is_type1=True)], reserve_pct=0)
    assert sum(a.units for a in plan.assignments) == 1


# --- Viales primero, a quienes usan insulina rápida con 14-20 UI/día --------------------------------


def _vial_lots(vials, pens=0):
    lots = [_lot(1, "Aspart", "NovoRapid Dstfl 10 ml", 1000, vials)]
    if pens:
        lots.append(_lot(2, "Aspart", "NovoRapid Penfill", 300, pens))
    return lots


def _vials_of(plan, pid):
    return sum(a.units for a in plan.assignments if a.patient_id == pid and a.lot_id == 1)


def test_the_vial_range_is_14_to_20_units_a_day():
    from app.core.insulin_distribution import VIAL_DOSE_RANGE, VIAL_MIN_UI

    assert VIAL_DOSE_RANGE == (14.0, 20.0) and VIAL_MIN_UI == 1000.0


def test_vials_go_first_to_rapid_insulin_users_between_14_and_20_units_a_day():
    pats = [PatientInput(i, False, {"Aspart": dose}) for i, dose in ((1, 13.0), (2, 14.0), (3, 17.0), (4, 20.0), (5, 21.0))]
    plan = plan_distribution(_vial_lots(vials=10, pens=40), pats, reserve_pct=0)
    # 13 y 21 UI/día quedan fuera del rango: no reciben vial en esta fase.
    assert [_vials_of(plan, pid) for pid in (2, 3, 4)] == [1, 1, 1]
    assert _vials_of(plan, 1) == 0


def test_the_vial_phase_runs_after_the_reserve_and_does_not_touch_it():
    # El único vial va a la reserva (5 % de 1.000 UI = un envase entero): la fase de viales no lo toca.
    plan = plan_distribution(_vial_lots(vials=1), [PatientInput(1, False, {"Aspart": 17.0})], release_reserve=False)
    assert sum(r.units for r in plan.reserve_lots) == 1
    assert _vials_of(plan, 1) == 0
    # Con la liberación activa, ese vial sale de la reserva para quien estaba en 0 %.
    plan = plan_distribution(_vial_lots(vials=1), [PatientInput(1, False, {"Aspart": 17.0})])
    assert _vials_of(plan, 1) == 1 and plan.reserve_ui == 0


def test_vials_follow_priority_order_and_then_the_closest_to_100_percent():
    # Un solo vial para tres candidatos del mismo grupo: gana quien queda más cerca del 100 % (17 UI/día).
    pats = [PatientInput(1, False, {"Aspart": 14.0}), PatientInput(2, False, {"Aspart": 17.0}), PatientInput(3, False, {"Aspart": 20.0})]
    plan = plan_distribution(_vial_lots(vials=1), pats, reserve_pct=0)
    assert _vials_of(plan, 2) == 1 and _vials_of(plan, 1) == 0 and _vials_of(plan, 3) == 0
    # Con un menor y un adulto de igual dosis, el vial es del menor aunque tenga el id mayor.
    pats = [PatientInput(1, False, {"Aspart": 17.0}), PatientInput(2, True, {"Aspart": 17.0})]
    plan = plan_distribution(_vial_lots(vials=1), pats, reserve_pct=0)
    assert _vials_of(plan, 2) == 1 and _vials_of(plan, 1) == 0


def test_regular_and_glulisine_users_receive_the_aspart_vial_through_the_table():
    pats = [PatientInput(1, False, {"Regular": 15.0}), PatientInput(2, False, {"Glulisina": 18.0})]
    plan = plan_distribution(_vial_lots(vials=2), pats, reserve_pct=0)
    assert plan.patients[1][0].substitute == "Aspart" and plan.patients[2][0].substitute == "Aspart"
    assert _vials_of(plan, 1) == 1 and _vials_of(plan, 2) == 1


def test_a_vial_user_still_reaches_its_band_minimum_with_what_is_left():
    # Menor de 20 UI/día = 1.200 UI: el vial es 83 % (bajo su mínimo de 85 %); se completa con un pen (108 %).
    plan = plan_distribution(_vial_lots(vials=1, pens=5), [PatientInput(1, True, {"Aspart": 20.0})], reserve_pct=0)
    assert _vials_of(plan, 1) == 1
    assert _given(plan, 1, "Aspart") == 1300 and not plan.patients[1][0].outside_band


def test_without_vials_in_the_donation_the_vial_phase_changes_nothing():
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 40)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Aspart": 17.0})], reserve_pct=0)
    assert _given(plan, 1, "Aspart") == 900  # 3 pens, 88 % de 1.020 UI: dentro de su banda 65-100 %


def test_regular_user_gets_the_aspart_vial_in_the_vial_phase_even_when_pens_are_available():
    # Con pens de sobra, el vial va igual a quien tiene 14-20 UI/día: no se gasta un pen en quien un vial le sirve.
    plan = plan_distribution(_vial_lots(vials=1, pens=40), [PatientInput(1, False, {"Regular": 15.0})], reserve_pct=0)
    assert _vials_of(plan, 1) == 1
    assert plan.patients[1][0].substitute == "Aspart"


def test_a_vial_that_would_cover_more_than_120_percent_through_a_substitution_factor_is_not_given():
    from app.core.insulin_distribution import Substitution

    # Con factor 0,5 un vial de aspart (1.000 UI) equivale a 2.000 UI de regular: 238 % de 840 UI.
    plan = plan_distribution(
        _vial_lots(vials=1, pens=40),
        [PatientInput(1, False, {"Regular": 14.0})],
        reserve_pct=0,
        substitutions=[Substitution("Regular", "Aspart", factor=0.5)],
    )
    assert _vials_of(plan, 1) == 0
    assert plan.patients[1][0].substitute_ui > 0  # sí recibe pens


# --- NPH también puede reemplazarse por detemir ----------------------------------------------------


def test_nph_can_be_replaced_with_detemir_when_there_is_no_degludec():
    lots = [_lot(1, "Detemir", "Levemir", 300, 50), _lot(2, "Mixta", "Mixtard 30", 300, 50)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"NPH": 600 / DAYS})], reserve_pct=0)
    r = plan.patients[1][0]
    assert r.substitute == "Detemir"  # antes que la premezcla
    assert {a.lot_id for a in plan.assignments} == {1}


def test_the_nph_alternatives_follow_degludec_then_detemir_then_the_premix():
    from app.core.insulin_distribution import SUBSTITUTION_TABLE

    assert SUBSTITUTION_TABLE["NPH"] == ("Degludec", "Detemir", "Mixta")
    todos = [
        _lot(1, "Degludec", "Tresiba", 300, 50),
        _lot(2, "Detemir", "Levemir", 300, 50),
        _lot(3, "Mixta", "Mixtard 30", 300, 50),
    ]
    plan = plan_distribution(todos, [PatientInput(1, False, {"NPH": 600 / DAYS})], reserve_pct=0)
    assert plan.patients[1][0].substitute == "Degludec"
    plan = plan_distribution(todos[1:], [PatientInput(1, False, {"NPH": 600 / DAYS})], reserve_pct=0)
    assert plan.patients[1][0].substitute == "Detemir"
    plan = plan_distribution(todos[2:], [PatientInput(1, False, {"NPH": 600 / DAYS})], reserve_pct=0)
    assert plan.patients[1][0].substitute == "Mixta"


def test_detemir_users_never_receive_nph():
    lots = [_lot(1, "NPH", "Insulatard", 300, 50)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Detemir": 20.0})], reserve_pct=0)
    assert plan.assignments == [] and plan.patients[1][0].substitute is None


# --- Liberación de la reserva: lo necesario para llegar a los mínimos ---------------------------------


def test_the_reserve_is_untouched_when_everyone_reaches_their_minimum():
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 10)]  # 3.000 UI, reserva 5 % = 1 envase
    pats = [PatientInput(i, False, {"Aspart": 900 / DAYS}) for i in range(1, 4)]  # 3 x 900 = 9 envases
    plan = plan_distribution(lots, pats)
    assert plan.reserve_ui == 300 and plan.reserve_released_ui == 0
    assert all(not r.outside_band for rs in plan.patients.values() for r in rs)


def test_the_reserve_is_released_only_as_far_as_needed_to_reach_the_minimum():
    # 3 adultos de 1.500 UI (mínimo 65 % = 975): con 9 envases libres, dos llegan a 1.200 y el tercero a 300.
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 10)]
    pats = [PatientInput(i, False, {"Aspart": 1500 / DAYS}) for i in range(1, 4)]
    off = plan_distribution(lots, pats, release_reserve=False)
    assert [_given(off, i, "Aspart") for i in (1, 2, 3)] == [1200, 1200, 300]
    assert off.reserve_ui == 300 and off.reserve_released_ui == 0
    on = plan_distribution(lots, pats)
    # El envase de la reserva se reparte al que seguía más abajo; no alcanza su mínimo pero mejora.
    assert [_given(on, i, "Aspart") for i in (1, 2, 3)] == [1200, 1200, 600]
    assert on.reserve_ui == 0 and on.reserve_released_ui == 300
    assert sum(a.units for a in on.assignments) == 10


def test_only_the_needed_envases_of_the_reserve_are_used_and_the_rest_stays():
    lots = [_lot(1, "NPH", "Insulatard", 300, 10)]  # 3.000 UI
    # reserva del 20 % = 600 UI = 2 envases; un paciente en 0 % necesita 1 envase para su mínimo (65 % de 450)
    pats = [PatientInput(1, False, {"NPH": 2400 / DAYS}), PatientInput(2, False, {"NPH": 450 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0.20)
    assert plan.reserve_target_ui == 600
    assert _given(plan, 2, "NPH") == 300 and not plan.patients[2][0].outside_band
    assert plan.reserve_released_ui == 0  # alcanzó con lo libre: no se usó reserva
    pats = [PatientInput(1, False, {"NPH": 7200 / DAYS}), PatientInput(2, False, {"NPH": 450 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0.20)
    assert plan.reserve_released_ui <= 600
    assert plan.reserve_ui + plan.reserve_released_ui == 600


def test_the_released_reserve_follows_the_priority_order():
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 3)]  # 900 UI: 1 envase de reserva (5 % de 900 = 45)
    pats = [
        PatientInput(1, False, {"Aspart": 900 / DAYS}),  # tipo 2, id menor
        PatientInput(2, True, {"Aspart": 900 / DAYS}),  # menor
    ]
    plan = plan_distribution(lots, pats)
    # 2 envases libres + 1 de reserva: el menor llega a su mínimo (80 % = 720 -> 900) antes que el adulto
    assert _given(plan, 2, "Aspart") >= 720
    assert not plan.patients[2][0].outside_band


def test_a_treatment_in_zero_percent_gets_a_reserve_envase():
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 7)]  # 2.100 UI, reserva 5 % = 1 envase
    pats = [PatientInput(1, False, {"Aspart": 1800 / DAYS}), PatientInput(2, False, {"Aspart": 1800 / DAYS}),
            PatientInput(3, False, {"Aspart": 600 / DAYS})]
    off = plan_distribution(lots, pats, release_reserve=False)
    assert min(_given(off, i, "Aspart") for i in (1, 2, 3)) == 0  # alguien en cero
    on = plan_distribution(lots, pats)
    assert min(_given(on, i, "Aspart") for i in (1, 2, 3)) > 0  # con la reserva nadie queda en cero
    assert on.reserve_released_ui == 300


def test_the_released_reserve_is_reported_per_ingredient():
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 10), _lot(2, "Degludec", "Tresiba", 300, 20)]
    pats = [PatientInput(i, False, {"Aspart": 1500 / DAYS}) for i in range(1, 4)]
    pats.append(PatientInput(9, False, {"Degludec": 6000 / DAYS}))  # sin sobrante: la reserva sale de ambas
    plan = plan_distribution(lots, pats)
    by_ing = {s.ingredient: s for s in plan.ingredients}
    assert by_ing["Aspart"].reserve_released_ui == plan.reserve_released_ui > 0
    assert by_ing["Degludec"].reserve_released_ui == 0
    assert by_ing["Degludec"].reserve_ui > 0  # la reserva de degludec sigue guardada


def test_release_can_be_turned_off():
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 10)]
    pats = [PatientInput(i, False, {"Aspart": 1500 / DAYS}) for i in range(1, 4)]
    plan = plan_distribution(lots, pats, release_reserve=False)
    assert plan.reserve_released_ui == 0 and plan.reserve_ui == 300


# --- Lantus para la glargina de los menores y degludec que los menores mantienen siempre -------------


def test_the_reserve_is_taken_from_other_glargine_brands_before_lantus():
    lots = [
        _lot(1, "Glargina", "Lantus SoloStar", 300, 20, date(2028, 6, 1)),  # vence más tarde: iría primero
        _lot(2, "Glargina", "Abasaglar KwikPen", 300, 20, date(2027, 6, 1)),
    ]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 300 / DAYS})], release_reserve=False)
    assert plan.reserve_lots and {r.lot_id for r in plan.reserve_lots} == {2}  # Lantus queda libre para menores


def test_lantus_covers_the_minors_glargine_even_when_the_reserve_is_large():
    lots = [
        _lot(1, "Glargina", "Lantus SoloStar", 300, 10, date(2028, 6, 1)),
        _lot(2, "Glargina", "Abasaglar KwikPen", 300, 30, date(2027, 6, 1)),
    ]
    pats = [PatientInput(i, True, {"Glargina": 300 / DAYS}) for i in range(1, 6)]
    plan = plan_distribution(lots, pats, reserve_pct=0.5, release_reserve=False)
    got = _units_by_patient(plan)
    assert all(set(got[i]) == {1} for i in range(1, 6))  # todos los menores con Lantus


def test_a_minor_keeps_degludec_and_it_is_never_replaced_by_another_insulin():
    # Hay glargina de sobra pero no degludec: el menor no recibe glargina en su lugar (a un adulto sí).
    lots = [_lot(1, "Glargina", "Lantus", 300, 50), _lot(2, "Degludec", "Tresiba", 300, 0)]
    minor = plan_distribution(lots, [PatientInput(1, True, {"Degludec": 20.0})], reserve_pct=0)
    assert minor.assignments == [] and minor.patients[1][0].substitute is None
    adult = plan_distribution(lots, [PatientInput(1, False, {"Degludec": 20.0})], reserve_pct=0)
    assert adult.patients[1][0].substitute == "Glargina"


def test_a_minor_with_degludec_and_another_basal_keeps_degludec_even_without_stock():
    lots = [_lot(1, "NPH", "Insulatard", 300, 50)]  # solo hay NPH
    plan = plan_distribution(lots, [PatientInput(1, True, {"Degludec": 10.0, "NPH": 20.0})], reserve_pct=0)
    c = _choice(plan, 1, "BASAL")
    assert c.chosen == "Degludec" and c.reason == "MENOR_DEGLUDEC"
    assert [r.ingredient for r in plan.patients[1]] == ["Degludec"]
    # un adulto con las mismas insulinas elige la que tiene stock
    plan = plan_distribution(lots, [PatientInput(1, False, {"Degludec": 10.0, "NPH": 20.0})], reserve_pct=0)
    assert _choice(plan, 1, "BASAL").chosen == "NPH"


def test_the_minors_degludec_is_completed_before_nph_users_take_it_as_a_substitute():
    # 5 envases de degludec (1.500 UI): el menor necesita 1.500 (mínimo 1.200) y un adulto tipo 1 con NPH
    # (600 UI) recibiría degludec por la tabla. El menor queda completo y el adulto no se lleva el 5.º envase.
    lots = [_lot(1, "Degludec", "Tresiba", 300, 5)]
    pats = [
        PatientInput(1, True, {"Degludec": 1500 / DAYS}),
        PatientInput(2, False, {"NPH": 600 / DAYS}, is_type1=True),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, release_reserve=False)
    assert _given(plan, 1, "Degludec") == 1500
    assert sum(a.ui for a in plan.assignments if a.patient_id == 2) == 0


# --- Nadie bajo el mínimo: reubicar a quien recibe como sustituto y explicar lo que falta --------------


def test_a_substitute_holder_is_moved_to_another_alternative_to_free_the_only_insulin_a_user_has():
    # La protamina (4 envases) se la llevó el paciente con NPH; el usuario de protamina quedaba en 25 %.
    # El detemir (en gran parte en la reserva) alcanza para el de NPH: pasa a detemir y libera la protamina.
    lots = [_lot(1, "Mixta", "Mixtard 30", 300, 4), _lot(2, "Detemir", "Levemir", 300, 4)]
    pats = [PatientInput(1, False, {"NPH": 1200 / DAYS}), PatientInput(2, False, {"Mixta": 1200 / DAYS})]
    off = plan_distribution(lots, pats, reserve_pct=0.2, release_reserve=False)
    assert _given(off, 2, "Mixta") == 300 and off.patients[2][0].outside_band
    on = plan_distribution(lots, pats, reserve_pct=0.2)
    assert _given(on, 2, "Mixta") == 1200 and not on.patients[2][0].outside_band
    assert on.patients[1][0].substitute == "Detemir" and not on.patients[1][0].outside_band
    assert on.reserve_released_ui == 300  # solo lo que hizo falta de la reserva


def test_the_shortfall_cause_is_stock_when_nothing_is_left_of_the_insulin_or_its_substitutes():
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 1)]
    pats = [PatientInput(1, False, {"Aspart": 20.0}), PatientInput(2, False, {"Aspart": 20.0})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    r = plan.patients[2][0]
    assert r.given_ui == 0 and r.min_shortfall_cause == "STOCK"
    assert round(r.min_shortfall_ui) == 780  # 65 % de 1.200 UI


def test_the_shortfall_cause_is_pen_when_the_next_envase_would_pass_the_cap():
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 10)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Aspart": 8.0}, is_type1=True)], reserve_pct=0)
    r = plan.patients[1][0]
    assert r.given_ui == 300 and r.min_shortfall_cause == "ENVASE" and round(r.min_shortfall_ui) == 60  # 75 % de 480


def test_there_is_no_shortfall_when_the_minimum_is_reached():
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 50)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Aspart": 20.0})], reserve_pct=0)
    r = plan.patients[1][0]
    assert r.min_shortfall_ui == 0 and r.min_shortfall_cause is None
