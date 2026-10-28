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
from app.core.donation_request import SIN_CLASIFICAR, build_donation_request

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
    assert reporte["insulinas"] == [{"insulina": SIN_CLASIFICAR, "cantidad_ui": 600.0, "beneficiarios": 1}]

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
