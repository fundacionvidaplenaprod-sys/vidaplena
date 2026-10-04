"""
Endpoints que cambian el estado de un beneficiario: `PUT /patients/{id}/validate`
y `PUT /patients/{id}/change-status`. Guardan el cambio y devuelven la ficha, y
cada paso deja un evento en `patient_status_events` (el reporte de morosos toma
de ahí cuándo el beneficiario quedó ACTIVO).
"""
import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app import models


async def _paciente(db_session, estado="HABILITADO"):
    suffix = uuid.uuid4().hex[:8]
    patient = models.Patient(
        nombres=f"Estado{suffix}", ap_paterno="Prueba", ci=f"EST-{suffix}",
        fecha_nac=date(1990, 1, 1), estado=estado,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


async def _eventos(db_session, patient_id):
    return (await db_session.execute(
        select(models.PatientStatusEvent).where(models.PatientStatusEvent.patient_id == patient_id)
    )).scalars().all()


@pytest.mark.asyncio
@pytest.mark.parametrize("ruta", ["validate", "change-status"])
async def test_cambiar_estado_responde_con_la_ficha_y_deja_evento(client, superuser_token, db_session, ruta):
    p = await _paciente(db_session)
    pid = p.id
    # En producción cada petición abre su propia sesión y carga la ficha desde
    # cero. Los tests comparten sesión con la app, así que el paciente recién
    # sembrado quedaría en memoria sin sus relaciones y su serialización
    # fallaría por un motivo que no existe en producción.
    db_session.expunge_all()

    resp = await client.put(f"/patients/{pid}/{ruta}", json={"estado": "ACTIVO"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == pid
    assert body["estado"] == "ACTIVO"
    # Las relaciones se serializan (antes fallaban por estar expiradas).
    assert "tutor" in body and "medical" in body
    assert body["treatments"] == [] and body["complications"] == []

    eventos = await _eventos(db_session, pid)
    assert [(e.old_state, e.new_state) for e in eventos] == [("HABILITADO", "ACTIVO")]


@pytest.mark.asyncio
@pytest.mark.parametrize("ruta", ["validate", "change-status"])
async def test_cambiar_estado_de_paciente_inexistente_404(client, superuser_token, ruta):
    resp = await client.put(f"/patients/999999999/{ruta}", json={"estado": "ACTIVO"})
    assert resp.status_code == 404
