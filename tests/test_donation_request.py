"""
Reporte de solicitud de cantidades requeridas de donación (GET /reports/donation-request).

La cuenta exacta se prueba sobre la función pura `build_donation_request`; el endpoint se prueba
con diferencias antes/después porque la BD de pruebas conserva las filas de corridas anteriores.
"""
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app import models
from app.core.donation_request import (
    SIN_CLASIFICAR, build_donation_request, plan_por_presentacion, validar_reparto, viales_10ml, viales_3ml,
)

URL = "/reports/donation-request"


def _ficha(pid, edad, tipo, tratamientos):
    return SimpleNamespace(
        id=pid,
        fecha_nac=date(2000, 1, 1),
        edad_calc=edad,
        medical=SimpleNamespace(tipo_diabetes=tipo) if tipo else None,
        treatments=[SimpleNamespace(nombre=n, dosis_diaria=d) for n, d in tratamientos],
    )


def test_suma_la_dosis_diaria_por_60_dias_y_por_tipo_de_insulina():
    fichas = [
        _ficha(1, 10, "Tipo 1", [("Glargina", 20), ("Lispro", 10)]),
        _ficha(2, 40, "Tipo 1", [("Lantus", 30)]),  # nombre comercial: cuenta como Glargina
        _ficha(3, 70, "Tipo 2", [("Mixta", 40), ("Glargina", 0)]),  # dosis 0: no cuenta
        _ficha(4, 30, "Tipo 2", []),  # sin insulina: cuenta en el total y en el perfil
    ]
    reporte = build_donation_request(fichas)

    assert reporte["dias"] == 60
    por_insulina = {i["insulina"]: i for i in reporte["insulinas"]}
    assert por_insulina["Glargina"]["cantidad_ui"] == (20 + 30) * 60
    assert por_insulina["Glargina"]["beneficiarios"] == 2
    assert por_insulina["Lispro"]["cantidad_ui"] == 10 * 60
    assert por_insulina["Mixta"]["cantidad_ui"] == 40 * 60
    # mayor cantidad primero
    assert [i["insulina"] for i in reporte["insulinas"]] == ["Glargina", "Mixta", "Lispro"]
    assert reporte["sin_insulina_registrada"] == 1


def test_viales_de_3_ml_por_concentracion_redondeando_hacia_arriba():
    # los ejemplos de la Fundación: Glargina 156.180 UI y NPH 113.820 UI
    assert viales_3ml(156180) == {"U100": 521, "U200": 261, "U300": 174}
    assert viales_3ml(113820) == {"U100": 380, "U200": 190, "U300": 127}
    # un múltiplo exacto no suma un vial de más, y un solo UI de más sí
    assert viales_3ml(1200) == {"U100": 4, "U200": 2, "U300": 2}
    assert viales_3ml(1201) == {"U100": 5, "U200": 3, "U300": 2}
    assert viales_3ml(900) == {"U100": 3, "U200": 2, "U300": 1}
    # el ruido de los decimales de la suma no cambia el resultado
    assert viales_3ml(0.1 * 12000) == {"U100": 4, "U200": 2, "U300": 2}
    assert viales_3ml(0) == {"U100": 0, "U200": 0, "U300": 0}


def test_viales_de_10_ml_solo_en_u100_redondeando_hacia_arriba():
    assert viales_10ml(156180) == {"U100": 157}  # 156,18 -> 157
    assert viales_10ml(113820) == {"U100": 114}  # 113,82 -> 114
    assert viales_10ml(1000) == {"U100": 1}      # exacto: no suma uno de más
    assert viales_10ml(1000.5) == {"U100": 2}
    assert viales_10ml(0.1 * 10000) == {"U100": 1}
    assert viales_10ml(0) == {"U100": 0}
    assert list(viales_10ml(5000)) == ["U100"]    # no hay U200 ni U300 en 10 ml


REPARTO_30 = {"10ml_U100": 30, "3ml_U100": 70 / 3, "3ml_U200": 70 / 3, "3ml_U300": 70 / 3}


def test_reparto_por_porcentajes_30_por_ciento_en_10_ml_y_el_resto_en_partes_iguales_de_3_ml():
    plan = plan_por_presentacion(156180, validar_reparto(REPARTO_30))
    # 30 % = 46.854 UI -> 47 frascos de 1.000 UI
    assert (plan["10ml_U100"]["ui"], plan["10ml_U100"]["envases"]) == (46854.0, 47)
    # el 70 % restante, en tres partes iguales de 36.442 UI
    assert plan["3ml_U100"]["ui"] == 36442.0 and plan["3ml_U100"]["envases"] == 122  # 121,47 -> 122
    assert plan["3ml_U200"]["envases"] == 61                                          # 60,74 -> 61
    assert plan["3ml_U300"]["envases"] == 41                                          # 40,49 -> 41
    assert round(sum(p["ui"] for p in plan.values()), 1) == 156180.0
    # un reparto que cae exacto no suma envases de más
    exacto = plan_por_presentacion(10000, {"10ml_U100": 50, "3ml_U100": 50, "3ml_U200": 0, "3ml_U300": 0})
    assert (exacto["10ml_U100"]["envases"], exacto["3ml_U100"]["envases"], exacto["3ml_U200"]["envases"]) == (5, 17, 0)


def test_el_reparto_exige_las_cuatro_presentaciones_entre_0_y_100_y_sumando_100():
    validar_reparto(REPARTO_30)
    validar_reparto({"10ml_U100": 100, "3ml_U100": 0, "3ml_U200": 0, "3ml_U300": 0})
    validar_reparto({"10ml_U100": 30, "3ml_U100": 23.33, "3ml_U200": 23.33, "3ml_U300": 23.34})  # redondeos de pantalla
    with pytest.raises(ValueError, match="cuatro presentaciones"):
        validar_reparto({"10ml_U100": 100})
    with pytest.raises(ValueError, match="sumar 100"):
        validar_reparto({"10ml_U100": 30, "3ml_U100": 30, "3ml_U200": 30, "3ml_U300": 30})
    with pytest.raises(ValueError, match="entre 0 y 100"):
        validar_reparto({"10ml_U100": 150, "3ml_U100": -50, "3ml_U200": 0, "3ml_U300": 0})


def test_el_cuadro_trae_el_plan_solo_si_se_pide_el_reparto():
    fichas = [_ficha(1, 40, "Tipo 1", [("Glargina", 20)])]
    sin = build_donation_request(fichas)
    assert sin["reparto"] is None and "plan" not in sin["insulinas"][0]
    con = build_donation_request(fichas, reparto=REPARTO_30)
    glargina = con["insulinas"][0]
    assert glargina["plan"]["10ml_U100"] == {"pct": 30.0, "ui": 360.0, "envases": 1}
    assert con["reparto"]["10ml_U100"] == 30.0
    assert glargina["viales_3ml"]["U100"] == 4  # los escenarios siguen estando


def test_cada_insulina_del_cuadro_trae_sus_viales_por_concentracion():
    fichas = [
        _ficha(1, 40, "Tipo 1", [("Glargina", 20)]),
        _ficha(2, 40, "Tipo 1", [("Glargina", 15), ("Lispro", 3)]),
    ]
    por_insulina = {i["insulina"]: i for i in build_donation_request(fichas)["insulinas"]}
    assert por_insulina["Glargina"]["cantidad_ui"] == 2100  # (20 + 15) x 60
    assert por_insulina["Glargina"]["viales_3ml"] == {"U100": 7, "U200": 4, "U300": 3}
    assert por_insulina["Lispro"]["viales_3ml"] == {"U100": 1, "U200": 1, "U300": 1}  # 180 UI: un vial
    assert por_insulina["Glargina"]["viales_10ml"] == {"U100": 3}  # 2.100 UI: 2,1 frascos de 1.000 UI
    assert por_insulina["Lispro"]["viales_10ml"] == {"U100": 1}


def test_porcentajes_por_rango_etario_y_tipo_de_diabetes_sobre_el_total():
    fichas = [
        _ficha(1, 10, "Tipo 1", [("Glargina", 20)]),   # menor
        _ficha(2, 17, "Tipo 1", [("Glargina", 20)]),   # menor
        _ficha(3, 40, "Tipo 2", [("Glargina", 20)]),
        _ficha(4, 60, "Tipo 2", [("Glargina", 20)]),   # 60: todavía entre 18 y 60
        _ficha(5, 61, "Tipo 2", [("Glargina", 20)]),   # 61: adulto mayor
        _ficha(6, 80, "Otra", [("Glargina", 20)]),     # adulto mayor, de otro tipo
        _ficha(7, 18, None, [("Glargina", 20)]),       # 18: ya no es menor; sin tipo
        _ficha(8, 30, "tipo 1", [("Glargina", 20)]),
        _ficha(9, 50, "Tipo 2", []),                   # tipo 2 sin insulina: no es «insulino requirente»
    ]
    reporte = build_donation_request(fichas)
    assert reporte["total_beneficiarios"] == 9
    assert reporte["menores_18"] == {"cantidad": 2, "porcentaje": 22.2}
    assert reporte["entre_18_y_60"] == {"cantidad": 5, "porcentaje": 55.6}
    assert reporte["mayores_61"] == {"cantidad": 2, "porcentaje": 22.2}
    assert reporte["diabeticos_tipo_1"] == {"cantidad": 3, "porcentaje": 33.3}
    assert reporte["diabeticos_tipo_2"] == {"cantidad": 3, "porcentaje": 33.3}  # sin la ficha 9
    # los tres rangos de edad cubren a todos
    assert reporte["menores_18"]["cantidad"] + reporte["entre_18_y_60"]["cantidad"] + reporte["mayores_61"]["cantidad"] == 9


def test_la_protamina_pasa_a_llamarse_mixta_y_el_nombre_anterior_se_sigue_reconociendo():
    from app.core.insulin_catalog import normalize_insulin_name

    for nombre in ("Mixta", "Protamina", "protamina", "Humalog Mix 25", "Insulina bifásica"):
        assert normalize_insulin_name(nombre) == "Mixta", nombre
    reporte = build_donation_request([_ficha(1, 30, "Tipo 1", [("Protamina", 10)])])  # ficha anterior a la migración
    assert [i["insulina"] for i in reporte["insulinas"]] == ["Mixta"]


def test_una_insulina_fuera_del_catalogo_se_cuenta_aparte_y_sin_beneficiarios_no_divide_por_cero():
    reporte = build_donation_request([_ficha(1, 30, "Tipo 1", [("Marca desconocida", 10)])])
    assert reporte["insulinas"] == [
        {
            "insulina": SIN_CLASIFICAR,
            "cantidad_ui": 600.0,
            "viales_3ml": {"U100": 2, "U200": 1, "U300": 1},
            "viales_10ml": {"U100": 1},
            "beneficiarios": 1,
        }
    ]

    vacio = build_donation_request([])
    assert vacio["total_beneficiarios"] == 0
    assert vacio["insulinas"] == []
    assert vacio["menores_18"] == {"cantidad": 0, "porcentaje": 0.0}


async def _beneficiario(db_session, estado, nacimiento, tipo, tratamientos):
    sufijo = uuid.uuid4().hex[:8]
    patient = models.Patient(
        nombres="Req",
        ap_paterno=f"Donacion{sufijo}",
        ci=f"RD{sufijo}",
        fecha_nac=nacimiento,
        depto="La Paz",
        estado=estado,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    db_session.add(models.PatientMedical(patient_id=patient.id, tipo_diabetes=tipo))
    for nombre, dosis in tratamientos:
        db_session.add(models.PatientTreatment(patient_id=patient.id, nombre=nombre, dosis_diaria=dosis))
    await db_session.commit()
    return patient


@pytest.mark.asyncio
async def test_el_endpoint_cuenta_a_todos_sin_mirar_aporte_ni_documentos_pero_no_a_los_inactivos(
    client, superuser_token, db_session
):
    antes = (await client.get(URL)).json()
    base = {i["insulina"]: i["cantidad_ui"] for i in antes["insulinas"]}

    hoy = date.today()
    await _beneficiario(db_session, "ACTIVO", hoy - timedelta(days=365 * 10), "Tipo 1", [("Degludec", 5)])
    await _beneficiario(db_session, "PENDIENTE_DOC", hoy - timedelta(days=365 * 70), "Tipo 2", [("Degludec", 5)])
    await _beneficiario(db_session, "HABILITADO", hoy - timedelta(days=365 * 30), "Tipo 2", [("Degludec", 5)])
    await _beneficiario(db_session, "INACTIVO", hoy - timedelta(days=365 * 30), "Tipo 1", [("Degludec", 500)])

    despues = (await client.get(URL)).json()
    nuevo = {i["insulina"]: i["cantidad_ui"] for i in despues["insulinas"]}
    assert nuevo["Degludec"] - base.get("Degludec", 0.0) == 3 * 5 * 60  # el inactivo no suma
    assert despues["total_beneficiarios"] - antes["total_beneficiarios"] == 3
    assert despues["menores_18"]["cantidad"] - antes["menores_18"]["cantidad"] == 1
    assert despues["entre_18_y_60"]["cantidad"] - antes["entre_18_y_60"]["cantidad"] == 1
    assert despues["mayores_61"]["cantidad"] - antes["mayores_61"]["cantidad"] == 1
    assert despues["diabeticos_tipo_1"]["cantidad"] - antes["diabeticos_tipo_1"]["cantidad"] == 1
    assert despues["diabeticos_tipo_2"]["cantidad"] - antes["diabeticos_tipo_2"]["cantidad"] == 2


@pytest.mark.asyncio
async def test_solo_el_super_admin_ve_el_reporte(client, patient_token):
    resp = await client.get(URL)
    assert resp.status_code == 403


def _asistido(aid, *, nacimiento=None, edad=None, rango=None, tipo=None, tratamientos=()):
    return SimpleNamespace(
        id=aid,
        fecha_nacimiento=nacimiento,
        edad_aproximada=edad,
        rango_edad=rango,
        tipo_diabetes=tipo,
        treatments=[SimpleNamespace(insulina=n, dosis_diaria=d) for n, d in tratamientos],
    )


def test_las_personas_del_registro_asistido_tambien_se_cuentan():
    ordinarios = [_ficha(1, 40, "Tipo 2", [("Glargina", 20)])]
    asistidos = [
        _asistido(1, nacimiento=date(date.today().year - 10, 1, 1), tipo="Tipo 1", tratamientos=[("Glargina", 10), ("Lispro", 5)]),
        _asistido(2, edad=70, tipo="Tipo 2", tratamientos=[("Mixta", 30)]),
        _asistido(3, rango="12-17", tipo=None, tratamientos=[("NPH", 8)]),
        _asistido(4),  # no se sabe nada: cuenta en el total y no suma insulina
    ]
    reporte = build_donation_request(ordinarios, assisted=asistidos)

    # el id 1 del ordinario y el id 1 del asistido no se confunden
    por_insulina = {i["insulina"]: i for i in reporte["insulinas"]}
    assert por_insulina["Glargina"]["cantidad_ui"] == (20 + 10) * 60
    assert por_insulina["Glargina"]["beneficiarios"] == 2
    assert por_insulina["Mixta"]["cantidad_ui"] == 30 * 60
    assert por_insulina["NPH"]["cantidad_ui"] == 8 * 60
    assert por_insulina["Lispro"]["cantidad_ui"] == 5 * 60

    assert reporte["total_beneficiarios"] == 5
    assert reporte["asistidos_incluidos"] == 4
    assert reporte["sin_insulina_registrada"] == 1
    # edades: 10 años (fecha de nacimiento) y 15 (rango 12-17) → menores; 40 → adulto; 70 → mayor; el último sin dato
    assert reporte["menores_18"]["cantidad"] == 2
    assert reporte["entre_18_y_60"]["cantidad"] == 1
    assert reporte["mayores_61"]["cantidad"] == 1
    assert reporte["diabeticos_tipo_1"]["cantidad"] == 1
    assert reporte["diabeticos_tipo_2"]["cantidad"] == 2  # el ordinario y el asistido de 70 años, ambos con insulina


def test_la_edad_del_asistido_prefiere_la_fecha_de_nacimiento_luego_la_aproximada_y_al_final_el_rango():
    hoy = date.today()
    cumple_ayer = date(hoy.year - 30, hoy.month, hoy.day) - timedelta(days=1)
    reg = _asistido(1, nacimiento=cumple_ayer, edad=70, rango="0-11")
    assert build_donation_request([], assisted=[reg])["entre_18_y_60"]["cantidad"] == 1  # 30 años por la fecha
    reg = _asistido(1, edad=70, rango="0-11")
    assert build_donation_request([], assisted=[reg])["mayores_61"]["cantidad"] == 1  # 70 por la edad aproximada
    reg = _asistido(1, rango="60+")
    assert build_donation_request([], assisted=[reg])["mayores_61"]["cantidad"] == 1  # del rango
    reg = _asistido(1)
    reporte = build_donation_request([], assisted=[reg])
    assert reporte["total_beneficiarios"] == 1
    assert (reporte["menores_18"]["cantidad"], reporte["entre_18_y_60"]["cantidad"], reporte["mayores_61"]["cantidad"]) == (0, 0, 0)


@pytest.mark.asyncio
async def test_el_endpoint_suma_los_asistidos_activos_y_no_los_cesados(client, superuser_token, db_session):
    antes = (await client.get(URL)).json()
    base = {i["insulina"]: i["cantidad_ui"] for i in antes["insulinas"]}

    def asistido(estado, dosis):
        reg = models.AssistedRegistration(estado=estado, tipo_diabetes="Tipo 1", edad_aproximada=10)
        reg.treatments = [models.AssistedTreatment(insulina="Detemir", dosis_diaria=dosis)]
        return reg

    activo, cesado = asistido("ACTIVO", 7), asistido("CESADO", 700)
    db_session.add_all([activo, cesado])
    await db_session.commit()

    despues = (await client.get(URL)).json()
    nuevo = {i["insulina"]: i["cantidad_ui"] for i in despues["insulinas"]}
    assert nuevo["Detemir"] - base.get("Detemir", 0.0) == 7 * 60
    assert despues["total_beneficiarios"] - antes["total_beneficiarios"] == 1
    assert despues["asistidos_incluidos"] - antes["asistidos_incluidos"] == 1
    assert despues["menores_18"]["cantidad"] - antes["menores_18"]["cantidad"] == 1
    assert despues["diabeticos_tipo_1"]["cantidad"] - antes["diabeticos_tipo_1"]["cantidad"] == 1


@pytest.mark.asyncio
async def test_el_endpoint_acepta_el_reparto_por_porcentajes_y_lo_valida(client, superuser_token):
    ok = await client.get(URL, params={"pct_10ml_u100": 30, "pct_3ml_u100": 70 / 3, "pct_3ml_u200": 70 / 3, "pct_3ml_u300": 70 / 3})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["reparto"]["10ml_U100"] == 30
    assert all(set(i["plan"]) == {"3ml_U100", "3ml_U200", "3ml_U300", "10ml_U100"} for i in body["insulinas"])

    sin_reparto = (await client.get(URL)).json()
    assert sin_reparto["reparto"] is None

    incompleto = await client.get(URL, params={"pct_10ml_u100": 30})
    assert incompleto.status_code == 422
    no_suma = await client.get(URL, params={"pct_10ml_u100": 30, "pct_3ml_u100": 30, "pct_3ml_u200": 30, "pct_3ml_u300": 30})
    assert no_suma.status_code == 422 and "sumar 100" in no_suma.json()["detail"]
