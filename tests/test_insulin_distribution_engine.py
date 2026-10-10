"""Pruebas del motor de reparto de insulinas (puro, sin base de datos)."""
from datetime import date

from app.core.insulin_distribution import (
    DISTRIBUTION_DAYS as DAYS,
    INSULIN_GROUPS,
    PREMIX_INSULINS,
    MINOR_DAILY_CAP_UI,
    PRIORITY_MAX_COVERAGE,
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


def test_reserve_is_ten_percent_of_total_and_never_assigned():
    # Stock 10.000 UI, demanda 5.000: sobra de sobra, la reserva sale del sobrante.
    lots = [_lot(1, "Aspart", "NovoRapid", 1000, 10)]
    pats = [PatientInput(1, False, {"Aspart": 5000 / DAYS})]
    plan = plan_distribution(lots, pats)
    assert plan.reserve_target_ui == 1000
    assert plan.reserve_ui == 1000
    assert plan.allocated_ui == 5000
    assert sum(a.units for a in plan.assignments) + sum(r.units for r in plan.reserve_lots) <= 10


def test_reserve_cuts_allocation_when_demand_exceeds_stock():
    # Demanda = stock = 10.000. Para reservar 1.000 se recorta lo asignado.
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
    assert plan.reserve_target_ui == 1900
    by_ing = {s.ingredient: s for s in plan.ingredients}
    assert by_ing["Aspart"].reserve_ui == 0
    # Reserva de 1.900 UI en envases de 900 UI: 3 envases = 2.700 como máximo, no los 9.000.
    assert 1900 <= by_ing["Glulisina"].reserve_ui <= 1900 + 900
    assert plan.allocated_ui == 10000


def test_minors_are_served_first_and_complete_adults_get_the_rest():
    lots = [_lot(1, "NPH", "Tresiba", 600, 10)]  # 6.000 UI, reserva 600
    need = 4500 / DAYS  # cada paciente necesita 4.500 UI
    pats = [
        PatientInput(1, False, {"NPH": need}),  # adulto, id menor
        PatientInput(2, True, {"NPH": need}),  # menor
    ]
    plan = plan_distribution(lots, pats)
    assert _given(plan, 2, "NPH") >= 4500  # el menor completo
    assert _given(plan, 1, "NPH") < 4500  # el adulto recibe lo que queda
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


def test_shortage_is_proportional_within_the_group_and_spends_all_stock():
    lots = [_lot(1, "Aspart", "NovoRapid", 100, 10)]  # 1.000 UI
    pats = [
        PatientInput(1, False, {"Aspart": 600 / DAYS}),
        PatientInput(2, False, {"Aspart": 1200 / DAYS}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    u = {pid: sum(a.units for a in plan.assignments if a.patient_id == pid) for pid in (1, 2)}
    assert u[1] + u[2] == 10
    assert u[2] > u[1]  # quien necesita el doble recibe más
    assert u[1] >= 3


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


def test_minors_never_receive_the_detemir_substitute():
    lots = [_lot(1, "Detemir", "Levemir Penfill", 300, 50)]
    pats = [PatientInput(1, True, {"Glargina": 600 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert plan.assignments == []
    assert plan.patients[1][0].substitute is None
    gl = next(s for s in plan.ingredients if s.ingredient == "Glargina")
    assert gl.unmet_ui == 600 and gl.patients_unmet == 1


def test_adult_who_does_not_fit_in_glargine_moves_entirely_to_detemir():
    lots = [
        _lot(1, "Glargina", "Abasaglar", 300, 2),  # 600 UI: alcanza para 1 adulto de 600 UI
        _lot(2, "Detemir", "Levemir Penfill", 300, 50),
    ]
    pats = [PatientInput(1, False, {"Glargina": 600 / DAYS}), PatientInput(2, False, {"Glargina": 600 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    uno, dos = plan.patients[1][0], plan.patients[2][0]
    # Uno recibe toda su glargina y nada de detemir; el otro, todo en detemir y nada de glargina.
    assert (uno.given_ui, uno.substitute) == (600, None)
    assert (dos.given_ui, dos.substitute, dos.substitute_ui) == (0, "Detemir", 600)
    gl = next(s for s in plan.ingredients if s.ingredient == "Glargina")
    assert gl.unmet_ui == 0


def test_a_smaller_adult_can_still_use_the_glargine_left_after_one_that_did_not_fit():
    lots = [_lot(1, "Glargina", "Abasaglar", 300, 2), _lot(2, "Detemir", "Levemir", 300, 50)]  # 600 UI
    pats = [PatientInput(1, False, {"Glargina": 900 / DAYS}), PatientInput(2, False, {"Glargina": 300 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert plan.patients[1][0].given_ui == 0 and plan.patients[1][0].substitute == "Detemir"
    assert plan.patients[2][0].given_ui == 300 and plan.patients[2][0].substitute is None


def test_without_detemir_stock_glargine_is_still_shared_proportionally():
    lots = [_lot(1, "Glargina", "Abasaglar", 100, 10)]  # 1.000 UI
    pats = [PatientInput(1, False, {"Glargina": 600 / DAYS}), PatientInput(2, False, {"Glargina": 1200 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    got = {r.ingredient + str(pid): r.given_ui for pid, rs in plan.patients.items() for r in rs}
    assert got["Glargina1"] > 0 and got["Glargina2"] > got["Glargina1"]  # nadie queda en cero


def test_when_detemir_is_not_enough_leftover_glargine_goes_to_the_uncovered_adults():
    lots = [_lot(1, "Glargina", "Abasaglar", 300, 1), _lot(2, "Detemir", "Levemir", 300, 1)]
    pats = [PatientInput(1, False, {"Glargina": 600 / DAYS}), PatientInput(2, False, {"Glargina": 600 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    delivered = sum(a.ui for a in plan.assignments)
    assert delivered == 600  # se usó todo lo que había
    for pid in (1, 2):
        r = plan.patients[pid][0]
        assert r.given_ui + r.substitute_equiv_ui == 300  # cada uno recibe la mitad


def test_minors_keep_proportional_glargine_and_never_switch_to_detemir():
    lots = [_lot(1, "Glargina", "Abasaglar", 100, 10), _lot(2, "Detemir", "Levemir", 300, 50)]
    pats = [PatientInput(1, True, {"Glargina": 600 / DAYS}), PatientInput(2, True, {"Glargina": 1200 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    for pid in (1, 2):
        r = plan.patients[pid][0]
        assert r.substitute is None and r.given_ui > 0
    assert not any(a.lot_id == 2 for a in plan.assignments)


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
    assert own.given_ui == 900  # su propia insulina primero
    sub = next(r for r in plan.patients[1] if r.ingredient == "Glargina")
    assert sub.substitute_ui == 300  # solo queda 1 envase para el sustituto


def test_reserve_is_not_spent_on_substitution():
    lots = [_lot(1, "Detemir", "Levemir", 100, 10)]  # 1.000 UI -> reserva 100
    pats = [PatientInput(1, False, {"Glargina": 5000 / DAYS})]
    plan = plan_distribution(lots, pats)
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
    # Un beneficiario usa una sola insulina rápida y una sola basal: tres pacientes distintos.
    pats = [
        PatientInput(1, False, {"Glulisina": 300 / DAYS, "Glargina": 300 / DAYS}),
        PatientInput(2, False, {"Regular": 300 / DAYS}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    subs = {(pid, r.ingredient): r.substitute for pid, rs in plan.patients.items() for r in rs}
    assert subs == {(1, "Glulisina"): "Aspart", (1, "Glargina"): "Detemir", (2, "Regular"): "Lispro"}


def test_type1_adults_are_served_after_minors_and_before_other_adults():
    lots = [_lot(1, "Aspart", "NovoRapid", 100, 20)]  # 2.000 UI
    need = 1200 / DAYS  # cada uno necesita 1.200 UI
    pats = [
        PatientInput(1, False, {"Aspart": need}),  # adulto sin prioridad (id menor a propósito)
        PatientInput(2, False, {"Aspart": need}, is_type1=True),
        PatientInput(3, True, {"Aspart": need}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _given(plan, 3, "Aspart") == 1200  # menor completo
    assert _given(plan, 2, "Aspart") == 800  # tipo 1 recibe lo que queda
    assert _given(plan, 1, "Aspart") == 0


def test_type1_adults_are_served_complete_before_other_adults():
    lots = [_lot(1, "Aspart", "NovoRapid", 100, 20)]  # 2.000 UI
    need = 1200 / DAYS
    pats = [PatientInput(1, False, {"Aspart": need}), PatientInput(2, False, {"Aspart": need}, is_type1=True)]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _given(plan, 2, "Aspart") == 1200
    assert _given(plan, 1, "Aspart") == 800


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
    plan = plan_distribution(lots, [PatientInput(1, True, {"Aspart": 450 / DAYS})], reserve_pct=0)
    assert _units_by_patient(plan)[1] == {2: 2}  # 600 UI en pens, no un vial de 1.000


def test_rounding_of_other_adults_does_not_take_the_stock_a_substitute_needs():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 10)]  # 3.000 UI
    pats = [
        PatientInput(1, False, {"Aspart": 1350 / DAYS}),  # 4,5 envases
        PatientInput(2, False, {"Aspart": 1350 / DAYS}),
        PatientInput(3, False, {"Glulisina": 1200 / DAYS}),  # sin glulisina: necesita aspart
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    # Antes, el redondeo hacia arriba de 1 y 2 (5 envases cada uno) dejaba a 3 sin nada.
    assert plan.patients[3][0].substitute_ui >= 600
    assert _given(plan, 1, "Aspart") >= 1200 and _given(plan, 2, "Aspart") >= 1200


def test_extra_pen_goes_only_to_leftovers_in_patient_order():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 3)]  # 900 UI, justo para 2 x 450
    pats = [PatientInput(1, False, {"Aspart": 450 / DAYS}), PatientInput(2, False, {"Aspart": 450 / DAYS})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert (_given(plan, 1, "Aspart"), _given(plan, 2, "Aspart")) == (600, 300)  # el sobrante va al primero


def test_with_plenty_of_stock_everyone_still_gets_the_full_last_pen():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 100)]
    pats = [PatientInput(i, False, {"Aspart": 450 / DAYS}) for i in range(1, 6)]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert all(_given(plan, i, "Aspart") == 600 for i in range(1, 6))


def test_priority_groups_get_the_last_pen_before_other_adults_take_the_stock():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 4)]  # 1.200 UI
    pats = [
        PatientInput(1, False, {"Aspart": 450 / DAYS}),  # adulto sin prioridad
        PatientInput(2, False, {"Aspart": 450 / DAYS}, is_type1=True),
        PatientInput(3, True, {"Aspart": 450 / DAYS}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _given(plan, 3, "Aspart") == 600 and _given(plan, 2, "Aspart") == 600  # completos
    assert _given(plan, 1, "Aspart") == 0


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


def test_type1_adult_on_glulisine_gets_the_aspart_before_other_adults_use_it_as_their_own():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 4)]
    pats = [
        PatientInput(1, False, {"Aspart": 1200 / DAYS}),
        PatientInput(2, False, {"Glulisina": 900 / DAYS}, is_type1=True),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert plan.patients[2][0].substitute_equiv_ui == 900
    assert _given(plan, 1, "Aspart") == 300


def test_minor_substitute_comes_before_type1_adults_own_insulin():
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 4)]
    pats = [
        PatientInput(1, False, {"Aspart": 1200 / DAYS}, is_type1=True),
        PatientInput(2, True, {"Glulisina": 900 / DAYS}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert plan.patients[2][0].substitute_equiv_ui == 900
    assert _given(plan, 1, "Aspart") == 300


def test_every_priority_patient_is_completed_when_the_mixed_stock_is_enough():
    # 2 menores con glulisina y 1 adulto tipo 1 con regular; sin stock propio de ninguna.
    lots = [_lot(1, "Aspart", "NovoRapid", 300, 6), _lot(2, "Lispro", "Humalog", 300, 4)]
    pats = [
        PatientInput(1, True, {"Glulisina": 600 / DAYS}),
        PatientInput(2, True, {"Glulisina": 900 / DAYS}),
        PatientInput(3, False, {"Regular": 1200 / DAYS}, is_type1=True),
        PatientInput(4, False, {"Aspart": 3000 / DAYS}),  # adulto sin prioridad con mucha necesidad
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    for pid, ing in ((1, "Glulisina"), (2, "Glulisina"), (3, "Regular")):
        r = next(x for x in plan.patients[pid] if x.ingredient == ing)
        assert r.given_ui + r.substitute_equiv_ui >= r.need_ui, (pid, ing)


# --- Garantía 100 % sin pasar del 120 % para menores y adultos tipo 1 -------------------


def _coverage(plan, pid, ing):
    r = next(x for x in plan.patients[pid] if x.ingredient == ing)
    return (r.given_ui + r.substitute_equiv_ui) / r.need_ui


def test_priority_patient_is_guaranteed_100_percent_and_never_above_120_when_possible():
    # Necesidad 700 UI: 3 pens de 300 = 900 (128 %); 450 + 300 = 750 (107 %) entra en la ventana.
    lots = [_lot(1, "Glargina", "Abasaglar 3 ml", 300, 20), _lot(2, "Glargina", "Toujeo SoloStar 1.5 ml", 450, 20)]
    for is_minor, is_t1 in ((True, False), (False, True)):
        pats = [PatientInput(1, is_minor, {"Glargina": 700 / DAYS}, is_type1=is_t1)]
        plan = plan_distribution(lots, pats, reserve_pct=0)
        cov = _coverage(plan, 1, "Glargina")
        assert 1.0 <= cov <= PRIORITY_MAX_COVERAGE + 1e-9, cov
        assert sum(a.ui for a in plan.assignments) == 750


def test_window_is_met_exactly_when_two_sizes_add_up():
    lots = [_lot(1, "Glargina", "Abasaglar 3 ml", 300, 20), _lot(2, "Glargina", "Toujeo SoloStar 1.5 ml", 450, 20)]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 750 / DAYS})], reserve_pct=0)
    assert sum(a.ui for a in plan.assignments) == 750


def test_when_no_combination_fits_the_guarantee_wins_over_the_cap():
    # 360 UI con pens de 300: 1 pen = 83 % (no garantiza), 2 = 166 % (pasa de 120 %).
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 20)]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Aspart": 360 / DAYS})], reserve_pct=0)
    cov = _coverage(plan, 1, "Aspart")
    assert cov >= 1.0  # garantizado
    assert round(cov, 2) == 1.67  # y se avisa porque pasa de 120 %


def test_other_adults_are_not_forced_into_the_window_but_get_the_least_excess():
    lots = [_lot(1, "Aspart", "NovoRapid Penfill", 300, 20), _lot(2, "Aspart", "NovoRapid Dstfl 10 ml", 1000, 20)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Aspart": 1100 / DAYS})], reserve_pct=0)
    assert sum(a.ui for a in plan.assignments) == 1200  # 4 pens, no un vial + pen


def test_lantus_is_kept_for_minors_when_it_fits_the_window():
    lots = [
        _lot(1, "Glargina", "Lantus SoloStar", 300, 20),
        _lot(2, "Glargina", "Toujeo SoloStar 1.5 ml", 450, 20),
    ]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 600 / DAYS})], reserve_pct=0)
    assert _units_by_patient(plan)[1] == {1: 2}  # 2 pens de Lantus = 100 %


def test_lantus_gives_way_when_only_another_pen_reaches_the_window():
    # 500 UI: Lantus 2 pens = 600 (120 %, cabe); Toujeo 450 = 90 % (no garantiza)
    lots = [
        _lot(1, "Glargina", "Lantus SoloStar", 300, 20),
        _lot(2, "Glargina", "Toujeo SoloStar 1.5 ml", 450, 20),
    ]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 500 / DAYS})], reserve_pct=0)
    assert _units_by_patient(plan)[1] == {1: 2}
    # 360 UI: Lantus 2 = 166 %; Toujeo 1 = 125 % -> menor exceso, se cambia de marca
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 360 / DAYS})], reserve_pct=0)
    assert _units_by_patient(plan)[1] == {2: 1}


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
    lots = [_lot(1, "NPH", "Insulatard", 300, 100), _lot(2, "Protamina", "Mix", 300, 100), _lot(3, "Regular", "Actrapid", 300, 100), _lot(4, "Aspart", "NovoRapid", 300, 100)]
    pats = [
        PatientInput(1, True, {"NPH": 45.0, "Aspart": 25.0}),  # menor: basal sin tope + rápida bajo 30
        PatientInput(4, True, {"Protamina": 40.0, "Regular": 50.0}),  # menor: premezcla y regular sin tope
        PatientInput(2, False, {"Aspart": 45.0}),  # adulto
        PatientInput(3, False, {"Aspart": 45.0}, is_type1=True),  # adulto tipo 1
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    menor = {r.ingredient: r for r in plan.patients[1]}
    assert menor["NPH"].need_ui == 45 * DAYS
    assert menor["Aspart"].need_ui == 25 * DAYS and menor["Aspart"].daily_applied == 25.0
    otro = {r.ingredient: r for r in plan.patients[4]}
    assert otro["Protamina"].need_ui == 40 * DAYS
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


def test_brand_preference_is_left_when_it_would_exceed_120_percent():
    # 700 UI: solo Lantus = 3 pens (900 = 128 %, pasa de 120 %); mezclando con un Toujeo
    # se llega a 750 (107 %). La ventana del 120 % manda sobre la marca.
    lots = [
        _lot(1, "Glargina", "Lantus SoloStar", 300, 20),
        _lot(2, "Glargina", "Toujeo SoloStar 1.5 ml", 450, 20),
    ]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 700 / DAYS})], reserve_pct=0)
    assert sum(a.ui for a in plan.assignments) == 750
    assert 1.0 <= _coverage(plan, 1, "Glargina") <= PRIORITY_MAX_COVERAGE


# --- Nunca se cambia una insulina por otra fuera de las reglas definidas -------------


def test_degludec_and_nph_are_never_swapped_for_minors_or_anyone():
    # Hay stock de todo MENOS de degludec y NPH: nadie recibe una por la otra.
    lots = [
        _lot(1, "NPH", "Insulatard", 300, 50),
        _lot(2, "Glargina", "Lantus", 300, 50),
        _lot(3, "Detemir", "Levemir", 300, 50),
        _lot(4, "Aspart", "NovoRapid", 300, 50),
        _lot(5, "Lispro", "Humalog", 300, 50),
    ]
    pats = [
        PatientInput(1, True, {"Degludec": 20.0}),  # menor con degludec
        PatientInput(2, False, {"Degludec": 20.0}, is_type1=True),  # adulto tipo 1 con degludec
        PatientInput(3, True, {"Degludec": 20.0}),
    ]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    assert plan.assignments == []
    for pid in (1, 2, 3):
        assert plan.patients[pid][0].substitute is None
    # y al revés: quien usa NPH sin stock de NPH no recibe degludec
    lots_deg = [_lot(1, "Degludec", "Tresiba", 600, 50), _lot(2, "Glargina", "Lantus", 300, 50)]
    plan = plan_distribution(lots_deg, [PatientInput(1, True, {"NPH": 20.0})], reserve_pct=0)
    assert plan.assignments == [] and plan.patients[1][0].substitute is None


def test_the_only_substitutions_are_the_three_defined_rules():
    from app.core.insulin_distribution import DEFAULT_SUBSTITUTIONS

    assert {(r.source, r.target) for r in DEFAULT_SUBSTITUTIONS} == {
        ("Glargina", "Detemir"),
        ("Glulisina", "Aspart"),
        ("Regular", "Lispro"),
    }


# --- Una sola insulina de cada grupo (rápidas / basales) -------------------------------


def test_groups_are_the_two_defined_ones():
    assert INSULIN_GROUPS["RAPIDA"] == {"Lispro", "Aspart", "Glulisina", "Regular"}
    assert INSULIN_GROUPS["BASAL"] == {"Glargina", "Protamina", "NPH", "Detemir", "Degludec"}
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


def test_a_minor_is_not_routed_through_an_adults_only_substitution():
    # Glargina -> detemir es solo para adultos: para un menor no cuenta como disponible.
    lots = [_lot(1, "Detemir", "Levemir", 300, 50), _lot(2, "NPH", "Insulatard", 300, 50)]
    plan = plan_distribution(lots, [PatientInput(1, True, {"Glargina": 10.0, "Degludec": 10.0})], reserve_pct=0)
    assert _choice(plan, 1, "BASAL").reason == "SIN_STOCK"


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
    assert PREMIX_INSULINS == {"Protamina"}


def test_a_premix_registered_next_to_a_basal_is_discarded_even_with_more_stock():
    # Glargina sin stock; la premezcla tiene de sobra. La basal manda: la premezcla no la sustituye.
    lots = [_lot(1, "Protamina", "Humalog Mix 25", 300, 100)]
    pats = [PatientInput(1, False, {"Glargina": 20.0, "Protamina": 18.0})]
    plan = plan_distribution(lots, pats, reserve_pct=0)
    c = _choice(plan, 1, "BASAL")
    assert c.chosen == "Glargina" and c.premix_discarded is True and c.reason == "SIN_STOCK"
    assert [r.ingredient for r in plan.patients[1]] == ["Glargina"]
    assert plan.assignments == []  # y no se le dio la premezcla


def test_premix_loses_against_every_basal_in_its_group():
    for basal in ("Glargina", "NPH", "Detemir", "Degludec"):
        lots = [_lot(1, "Protamina", "Mix", 300, 100), _lot(2, basal, "Basal", 300, 100)]
        plan = plan_distribution(lots, [PatientInput(1, False, {basal: 10.0, "Protamina": 30.0})], reserve_pct=0)
        assert _choice(plan, 1, "BASAL").chosen == basal, basal
        assert _choice(plan, 1, "BASAL").premix_discarded


def test_with_a_premix_and_two_basals_only_the_basals_compete():
    lots = [
        _lot(1, "Protamina", "Mix", 300, 500),  # muchísimo stock
        _lot(2, "NPH", "Insulatard", 300, 1),  # casi nada
        _lot(3, "Detemir", "Levemir", 300, 100),
    ]
    pats = [PatientInput(1, False, {"NPH": 20.0, "Detemir": 20.0, "Protamina": 20.0})]
    plan = plan_distribution(lots, pats, reserve_pct=0, substitutions=())
    assert _choice(plan, 1, "BASAL").chosen == "Detemir"


def test_a_premix_alone_is_the_patients_own_insulin_and_is_distributed():
    lots = [_lot(1, "Protamina", "Humalog Mix 25", 300, 20)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Protamina": 10.0})], reserve_pct=0)
    assert plan.group_choices == []
    assert _given(plan, 1, "Protamina") == 10 * DAYS


def test_a_premix_never_covers_a_missing_basal_through_substitution():
    # Glargina sin stock ni detemir; sobran premezclas: el adulto queda sin cubrir.
    lots = [_lot(1, "Protamina", "Mix", 300, 100), _lot(2, "NPH", "Insulatard", 300, 100)]
    plan = plan_distribution(lots, [PatientInput(1, False, {"Glargina": 20.0})], reserve_pct=0)
    assert plan.assignments == []
    assert plan.patients[1][0].substitute is None


def test_a_substitution_rule_with_a_premix_as_target_is_rejected():
    from app.core.insulin_distribution import Substitution

    bad = [Substitution("Glargina", "Protamina", factor=1.0)]
    try:
        plan_distribution([_lot(1, "Protamina", "Mix", 300, 10)], [PatientInput(1, False, {"Glargina": 10.0})], substitutions=bad)
    except ValueError as exc:
        assert "premezcla" in str(exc).lower()
    else:
        raise AssertionError("debía rechazar una regla con una premezcla como destino")


def test_default_substitutions_never_target_a_premix():
    from app.core.insulin_distribution import DEFAULT_SUBSTITUTIONS

    assert all(r.target not in PREMIX_INSULINS for r in DEFAULT_SUBSTITUTIONS)
