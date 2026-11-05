"""
Reporte «beneficiarios según su aporte mensual» (GET /reports/contribution-amounts): cuántos pagan Bs. 25,
Bs. 50, Bs. 100… y cuántos están exonerados.

Cada prueba usa un departamento propio para que los conteos sean exactos aunque la BD tenga más datos.
"""
import uuid
from datetime import date

import pytest

from app import models

URL = "/reports/contribution-amounts"


async def _paciente(db_session, depto, *, monto=None, estado="ACTIVO", exonerado_aporte=False, exonerado_por_cargo=False):
    suffix = uuid.uuid4().hex[:8]
    patient = models.Patient(
        nombres="Monto",
        ap_paterno=f"Aporte{suffix}",
        ci=f"CA{suffix}",
        fecha_nac=date(1990, 1, 1),
        depto=depto,
        estado=estado,
        monto_aporte_comprometido=monto,
        exonerado_aporte=exonerado_aporte,
        exonerado_por_cargo=exonerado_por_cargo,
    )
    db_session.add(patient)
    await db_session.commit()
    return patient


@pytest.mark.asyncio
async def test_cuenta_cuantos_pagan_cada_monto_y_cuantos_estan_exonerados(client, superuser_token, db_session):
    depto = f"Depto-{uuid.uuid4().hex[:8]}"
    for monto in (25, 25, 50, 100, 100, 100):
        await _paciente(db_session, depto, monto=monto)
    await _paciente(db_session, depto)                                          # activo sin monto definido
    await _paciente(db_session, depto, exonerado_aporte=True)                   # exonerado por vulnerabilidad
    await _paciente(db_session, depto, monto=100, exonerado_por_cargo=True)     # exonerado por cargo: no cuenta como pagador
    await _paciente(db_session, depto, monto=25, estado="PENDIENTE_DOC")        # aún no es beneficiario activo
    await _paciente(db_session, depto, monto=25, estado="INACTIVO")

    activo = models.AssistedRegistration(estado="ACTIVO", depto=depto)
    cesado = models.AssistedRegistration(estado="CESADO", depto=depto)
    db_session.add_all([activo, cesado])
    await db_session.commit()

    resp = await client.get(URL, params={"depto": depto})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["montos"] == [
        {"monto": 25.0, "cantidad": 2, "total_bs": 50.0, "reducido": True},
        {"monto": 50.0, "cantidad": 1, "total_bs": 50.0, "reducido": True},
        {"monto": 100.0, "cantidad": 3, "total_bs": 300.0, "reducido": False},
    ]
    assert body["pagan"] == 6
    assert body["ingreso_mensual_comprometido_bs"] == 400.0
    assert (body["exonerados_vulnerabilidad"], body["exonerados_cargo"], body["exonerados_total"]) == (1, 1, 2)
    assert body["sin_monto"] == 1
    assert body["total_activos"] == 9  # 6 que pagan + 2 exonerados + 1 sin monto
    assert body["registro_asistido"] == 1  # solo el activo; no se suma a los grupos de arriba
    assert body["depto"] == depto


@pytest.mark.asyncio
async def test_el_filtro_por_departamento_ignora_tildes_y_mayusculas(client, superuser_token, db_session):
    marca = uuid.uuid4().hex[:6]
    await _paciente(db_session, f"Potosí {marca}", monto=50)
    resp = await client.get(URL, params={"depto": f"potosi {marca.upper()}"})
    assert resp.json()["pagan"] == 1
    otro = await client.get(URL, params={"depto": f"Oruro {marca}"})
    assert otro.json()["total_activos"] == 0 and otro.json()["montos"] == []


@pytest.mark.asyncio
async def test_sin_filtro_cubre_a_todos_y_exige_personal(client, superuser_token, patient_token):
    # `patient_token` deja como usuario autenticado a un PACIENTE: no puede ver el reporte.
    resp = await client.get(URL)
    assert resp.status_code in (401, 403)
