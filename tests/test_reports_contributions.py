"""
tests/test_reports_contributions.py
===================================
GET /reports/contributions?periodo=YYYY-MM — historial de aportes solidarios
de un mes elegido, para que el staff pueda ver cuántos beneficiarios
hicieron su aporte ese periodo (control mensual).
"""
import uuid
from datetime import date

import pytest

from app import models


async def _crear_patient(db_session, **extra) -> models.Patient:
    suffix = uuid.uuid4().hex[:8]
    user = models.User(
        email=f"reporte_aportes_{suffix}@test.com",
        password_hash="fakehash",
        role="PACIENTE",
        estado="ACTIVO",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    patient = models.Patient(
        user_id=user.id,
        nombres=f"Reporte{suffix}",
        ap_paterno="Aportes",
        ci=f"CI-{suffix}",
        fecha_nac=date(1990, 1, 1),
        depto="La Paz",
        estado="ACTIVO",
        **extra,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


async def _crear_contribution(db_session, patient, periodo, estado="ACEPTADO", monto=100.0, metodo_pago="VOUCHER"):
    contrib = models.MonthlyContribution(
        patient_id=patient.id,
        periodo=periodo,
        fecha_pago=date.today(),
        monto=monto,
        url_comprobante="https://fake-storage.test/voucher.jpg" if metodo_pago == "VOUCHER" else None,
        metodo_pago=metodo_pago,
        estado=estado,
    )
    db_session.add(contrib)
    await db_session.commit()
    return contrib


@pytest.mark.asyncio
async def test_reporte_cuenta_por_estado_en_el_periodo_elegido(client, superuser_token, db_session):
    # Un periodo fijo puede acumular filas de corridas previas de la suite
    # (la BD compartida no se limpia entre ejecuciones — los commits
    # explícitos de un test quedan). Por eso las aserciones de conteo usan
    # ">=" y las de contenido verifican por patient_id, no por totales
    # exactos.
    periodo = "2031-07"
    aceptado1 = await _crear_patient(db_session)
    aceptado2 = await _crear_patient(db_session)
    declarado = await _crear_patient(db_session)
    observado = await _crear_patient(db_session)

    await _crear_contribution(db_session, aceptado1, periodo, estado="ACEPTADO")
    await _crear_contribution(db_session, aceptado2, periodo, estado="ACEPTADO", metodo_pago="EFECTIVO")
    await _crear_contribution(db_session, declarado, periodo, estado="DECLARADO")
    await _crear_contribution(db_session, observado, periodo, estado="OBSERVADO")

    resp = await client.get("/reports/contributions", params={"periodo": periodo})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["periodo"] == periodo
    assert body["total_aceptados"] >= 2
    assert body["total_declarados"] >= 1
    assert body["total_observados"] >= 1

    items_by_patient = {i["patient_id"]: i for i in body["items"]}
    assert items_by_patient[aceptado1.id]["estado"] == "ACEPTADO"
    assert items_by_patient[aceptado2.id]["estado"] == "ACEPTADO"
    assert items_by_patient[aceptado2.id]["metodo_pago"] == "EFECTIVO"
    assert items_by_patient[declarado.id]["estado"] == "DECLARADO"
    assert items_by_patient[observado.id]["estado"] == "OBSERVADO"


@pytest.mark.asyncio
async def test_reporte_no_mezcla_periodos_distintos(client, superuser_token, db_session):
    # Periodos propios de este test, distintos a los de los demás tests del
    # archivo — la BD compartida no se limpia entre tests (los commits
    # explícitos persisten), así que reutilizar un periodo entre tests
    # contaminaría el conteo del otro.
    mes_a, mes_b = "2032-03", "2032-04"
    patient_a = await _crear_patient(db_session)
    patient_b = await _crear_patient(db_session)
    await _crear_contribution(db_session, patient_a, mes_a, estado="ACEPTADO")
    await _crear_contribution(db_session, patient_b, mes_b, estado="ACEPTADO")

    resp_a = await client.get("/reports/contributions", params={"periodo": mes_a})
    assert resp_a.status_code == 200, resp_a.text
    ids_a = {i["patient_id"] for i in resp_a.json()["items"]}
    assert patient_a.id in ids_a
    assert patient_b.id not in ids_a

    resp_b = await client.get("/reports/contributions", params={"periodo": mes_b})
    assert resp_b.status_code == 200, resp_b.text
    ids_b = {i["patient_id"] for i in resp_b.json()["items"]}
    assert patient_b.id in ids_b
    assert patient_a.id not in ids_b


@pytest.mark.asyncio
async def test_reporte_periodo_sin_datos_devuelve_ceros(client, superuser_token):
    resp = await client.get("/reports/contributions", params={"periodo": "2019-01"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_aceptados"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_reporte_requiere_formato_de_periodo_valido(client, superuser_token):
    resp = await client.get("/reports/contributions", params={"periodo": "agosto-2026"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_reporte_no_accesible_para_paciente(client, patient_token):
    resp = await client.get("/reports/contributions", params={"periodo": "2026-08"})
    assert resp.status_code == 403
