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
        _ficha(3, 70, "Tipo 2", [("Protamina", 40), ("Glargina", 0)]),  # dosis 0: no cuenta
        _ficha(4, 30, "Tipo 2", []),  # sin insulina: cuenta en el total y en el perfil
    ]
    reporte = build_donation_request(fichas)

    assert reporte["dias"] == 60
    por_insulina = {i["insulina"]: i for i in reporte["insulinas"]}
    assert por_insulina["Glargina"]["cantidad_ui"] == (20 + 30) * 60
    assert por_insulina["Glargina"]["beneficiarios"] == 2
    assert por_insulina["Lispro"]["cantidad_ui"] == 10 * 60
    assert por_insulina["Protamina"]["cantidad_ui"] == 40 * 60
    # mayor cantidad primero
    assert [i["insulina"] for i in reporte["insulinas"]] == ["Glargina", "Protamina", "Lispro"]
    assert reporte["sin_insulina_registrada"] == 1


def test_porcentajes_sobre_el_total_de_beneficiarios():
    fichas = [
        _ficha(1, 10, "Tipo 1", [("Glargina", 20)]),   # menor
        _ficha(2, 17, "Tipo 1", [("Glargina", 20)]),   # menor
        _ficha(3, 40, "Tipo 2", [("Glargina", 20)]),
        _ficha(4, 65, "Tipo 2", [("Glargina", 20)]),   # mayor de 65 (65 cuenta)
        _ficha(5, 64, "Tipo 2", [("Glargina", 20)]),   # 64: aún no
        _ficha(6, 80, "Otra", [("Glargina", 20)]),     # mayor, de otro tipo
        _ficha(7, 18, None, [("Glargina", 20)]),       # 18: ya no es menor; sin tipo
        _ficha(8, 30, "tipo 1", [("Glargina", 20)]),
    ]
    reporte = build_donation_request(fichas)
    assert reporte["total_beneficiarios"] == 8
    assert reporte["menores_18"] == {"cantidad": 2, "porcentaje": 25.0}
    assert reporte["mayores_65"] == {"cantidad": 2, "porcentaje": 25.0}
    assert reporte["diabeticos_tipo_1"] == {"cantidad": 3, "porcentaje": 37.5}
    assert reporte["diabeticos_tipo_2"] == {"cantidad": 3, "porcentaje": 37.5}


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
    assert despues["mayores_65"]["cantidad"] - antes["mayores_65"]["cantidad"] == 1
    assert despues["diabeticos_tipo_1"]["cantidad"] - antes["diabeticos_tipo_1"]["cantidad"] == 1
    assert despues["diabeticos_tipo_2"]["cantidad"] - antes["diabeticos_tipo_2"]["cantidad"] == 2


@pytest.mark.asyncio
async def test_solo_el_super_admin_ve_el_reporte(client, patient_token):
    resp = await client.get(URL)
    assert resp.status_code == 403
