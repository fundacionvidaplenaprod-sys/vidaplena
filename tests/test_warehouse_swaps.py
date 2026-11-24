"""Intercambios equivalentes del reparto del almacén (lógica pura, sin base de datos)."""
import pytest

from app.core import warehouse_distribution as wd

LANTUS = wd.LotInfo(1, 10, "Glargina", "Lantus SoloStar 3 ml", 300.0, "L-LAN")
ABASAGLAR = wd.LotInfo(2, 20, "Glargina", "Abasaglar KwikPen 3 ml", 300.0, "L-ABA")
LEVEMIR = wd.LotInfo(3, 30, "Detemir", "Levemir FlexPen 3 ml", 300.0, "L-LEV")
TOUJEO = wd.LotInfo(4, 40, "Glargina", "Toujeo SoloStar 1,5 ml U300", 450.0, "L-TOU")
NPH = wd.LotInfo(5, 50, "NPH", "Humulin N 3 ml", 300.0, "L-NPH")
TRESIBA = wd.LotInfo(6, 60, "Degludec", "Tresiba FlexTouch 3 ml", 300.0, "L-TRE")
ABASAGLAR_2 = wd.LotInfo(7, 20, "Glargina", "Abasaglar KwikPen 3 ml", 300.0, "L-ABA-2")  # mismo producto, otro lote
LOTS = {l.lot_id: l for l in (LANTUS, ABASAGLAR, LEVEMIR, TOUJEO, NPH, TRESIBA, ABASAGLAR_2)}

MENOR = wd.Holder(1, "Glargina", 1)
ADULTO_GLARGINA = wd.Holder(2, "Glargina", 4)
ADULTO_DETEMIR = wd.Holder(3, "Detemir", 4)
ADULTO_NPH = wd.Holder(4, "NPH", 4)
MENOR_DEGLUDEC = wd.Holder(5, "Degludec", 1)
OTRO_GLARGINA = wd.Holder(6, "Glargina", 2)
HOLDERS = {(h.beneficiario_id, h.insulina): h for h in (MENOR, ADULTO_GLARGINA, ADULTO_DETEMIR, ADULTO_NPH, MENOR_DEGLUDEC, OTRO_GLARGINA)}


def _lines():
    return {
        (1, "Glargina", 1): 4,  # menor con Lantus
        (2, "Glargina", 2): 4,  # adulto con Abasaglar
        (3, "Detemir", 3): 4,  # adulto con Levemir
        (4, "NPH", 5): 3,  # adulto con NPH
        (5, "Degludec", 6): 3,  # menor con Tresiba
        (6, "Glargina", 4): 2,  # tipo 1 con Toujeo (900 UI)
    }


def test_compatible_insulins_follow_the_report_substitution_table():
    assert wd.compatible_insulins("Glargina", 4) == {"Glargina", "Detemir", "Degludec"}
    assert wd.compatible_insulins("Mixta", 4) == {"Mixta", "NPH", "Detemir", "Glargina"}
    assert wd.compatible_insulins("Degludec", 1) == {"Degludec"}  # un menor conserva la degludec
    assert wd.compatible_insulins("Degludec", 4) == {"Degludec", "Glargina"}


def test_swap_between_substitutable_insulins_with_equal_ui_is_valid_and_keeps_totals():
    lines = _lines()
    ui = wd.validate_swap(lines, LOTS, ADULTO_GLARGINA, 2, 1, ADULTO_DETEMIR, 3, 1)
    assert ui == 300
    before = {k: v for k, v in lines.items()}
    wd.apply_swap(lines, ADULTO_GLARGINA, 2, 1, ADULTO_DETEMIR, 3, 1)
    assert lines[(2, "Glargina", 2)] == 3 and lines[(2, "Glargina", 3)] == 1
    assert lines[(3, "Detemir", 3)] == 3 and lines[(3, "Detemir", 2)] == 1

    def ui_of(ls, bid):
        return sum(n * LOTS[k[2]].ui_por_envase for k, n in ls.items() if k[0] == bid)

    def by_lot(ls):
        out = {}
        for k, n in ls.items():
            out[k[2]] = out.get(k[2], 0) + n
        return out

    assert ui_of(lines, 2) == ui_of(before, 2) and ui_of(lines, 3) == ui_of(before, 3)  # la cobertura no cambia
    assert by_lot(lines) == by_lot(before)  # lo que sale de cada lote tampoco


def test_swap_with_different_envase_sizes_needs_the_same_ui():
    lines = _lines()
    # 3 pens de 300 UI (900) por 2 Toujeo de 450 UI (900): equivalente.
    assert wd.validate_swap(lines, LOTS, ADULTO_GLARGINA, 2, 3, OTRO_GLARGINA, 4, 2) == 900
    # 1 pen de 300 por 1 Toujeo de 450: no es equivalente.
    with pytest.raises(wd.SwapError, match="No es equivalente"):
        wd.validate_swap(lines, LOTS, ADULTO_GLARGINA, 2, 1, OTRO_GLARGINA, 4, 1)


def test_swap_rejects_an_insulin_that_is_not_a_substitute():
    with pytest.raises(wd.SwapError, match="no sirve para el tratamiento"):
        # Glargina no puede recibir NPH (no está en su tabla de sustitutos) ni la NPH glargina.
        wd.validate_swap(_lines(), LOTS, ADULTO_GLARGINA, 2, 1, ADULTO_NPH, 5, 1)


def test_minor_keeps_lantus_and_does_not_receive_a_new_substitute():
    lines = _lines()
    with pytest.raises(wd.SwapError, match="conserva Lantus"):
        wd.validate_swap(lines, LOTS, MENOR, 1, 1, ADULTO_GLARGINA, 2, 1)
    with pytest.raises(wd.SwapError, match="requiere aval médico"):
        wd.validate_swap(lines, LOTS, MENOR, 1, 1, ADULTO_DETEMIR, 3, 1)
    with pytest.raises(wd.SwapError, match="la conserva siempre"):
        wd.validate_swap(lines, LOTS, MENOR_DEGLUDEC, 6, 1, ADULTO_GLARGINA, 2, 1)
    # Un adulto sí puede entregar su Abasaglar a cambio de la Lantus... solo si el menor no pierde la Lantus: no.
    with pytest.raises(wd.SwapError):
        wd.validate_swap(lines, LOTS, ADULTO_GLARGINA, 2, 1, MENOR, 1, 1)


def test_swap_rejects_same_person_same_product_and_missing_envases():
    lines = _lines()
    with pytest.raises(wd.SwapError, match="dos beneficiarios distintos"):
        wd.validate_swap(lines, LOTS, ADULTO_GLARGINA, 2, 1, ADULTO_GLARGINA, 2, 1)
    lines[(6, "Glargina", 7)] = 1
    with pytest.raises(wd.SwapError, match="mismo producto"):
        wd.validate_swap(lines, LOTS, ADULTO_GLARGINA, 2, 1, OTRO_GLARGINA, 7, 1)
    with pytest.raises(wd.SwapError, match="no tiene 9 envase"):
        wd.validate_swap(lines, LOTS, ADULTO_GLARGINA, 2, 9, ADULTO_DETEMIR, 3, 9)


def test_swap_options_list_only_valid_equivalent_exchanges():
    opciones = wd.swap_options(_lines(), LOTS, HOLDERS, ADULTO_GLARGINA, 2, 3)
    pares = {(o["beneficiario_id"], o["lot_id"], o["envases"]) for o in opciones}
    assert (3, 3, 3) in pares  # 3 Abasaglar por 3 Levemir (sustitutos entre sí)
    assert (6, 4, 2) in pares  # 3 Abasaglar (900 UI) por 2 Toujeo (900 UI)
    assert not any(o["beneficiario_id"] == 1 for o in opciones)  # el menor conserva la Lantus
    assert not any(o["beneficiario_id"] == 4 for o in opciones)  # NPH no sustituye a glargina
    assert not any(o["beneficiario_id"] == 5 for o in opciones)  # menor con degludec
    toujeo = next(o for o in opciones if o["lot_id"] == 4)
    assert toujeo["misma_insulina"] and toujeo["ui"] == 900


def test_rebuild_result_updates_lots_substitute_and_notes_but_not_coverage():
    lines = _lines()
    resultado = {
        "pacientes": [
            {
                "patient_id": 2, "grupo_prioridad": 4,
                "insulinas": [{"insulina": "Glargina", "necesidad_ui": 1200, "entregado_ui": 1200, "cobertura_pct": 100.0,
                               "sustituto": None, "sustituto_ui": 0, "notas": [], "lotes": []}],
            },
            {
                "patient_id": 3, "grupo_prioridad": 4,
                "insulinas": [{"insulina": "Detemir", "necesidad_ui": 1200, "entregado_ui": 1200, "cobertura_pct": 100.0,
                               "sustituto": None, "sustituto_ui": 0, "notas": ["FICHA_POR_CORREGIR"], "lotes": []}],
            },
        ],
        "bajo_minimo": [],
        "insulinas": [{"insulina": "Glargina"}, {"insulina": "Detemir"}],
    }
    wd.apply_swap(lines, ADULTO_GLARGINA, 2, 1, ADULTO_DETEMIR, 3, 1)
    out = wd.rebuild_result(resultado, lines, LOTS)
    a = out["pacientes"][0]["insulinas"][0]
    b = out["pacientes"][1]["insulinas"][0]
    assert a["entregado_ui"] == 1200 and a["cobertura_pct"] == 100.0
    assert a["sustituto"] == "Detemir" and a["sustituto_ui"] == 300 and "SUSTITUCION" in a["notas"]
    assert {(l["producto"], l["unidades"]) for l in a["lotes"]} == {("Abasaglar KwikPen 3 ml", 3), ("Levemir FlexPen 3 ml", 1)}
    assert b["sustituto"] == "Glargina" and b["notas"] == ["FICHA_POR_CORREGIR", "SUSTITUCION"]
    glargina = out["insulinas"][0]
    assert glargina["sustituido_ui"] == 300 and glargina["entregado_como_sustituto_ui"] == 300
