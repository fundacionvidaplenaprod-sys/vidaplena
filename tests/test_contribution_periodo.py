"""
Corrección del periodo (gestión) de un aporte por el SUPER_ADMIN.

El beneficiario elige el periodo al subir su voucher y a menudo se equivoca
(p. ej. sube en octubre un depósito de septiembre). Quien revisa el voucher —y
solo el SUPER_ADMIN— puede reasignarlo.
"""
import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app import models
from tests.test_contributions_admin import _crear_patient, _switch_identity


async def _releer(db_session, aporte_id):
    """Relee solo este aporte saltando la identity map (el endpoint lo cambió en otra sesión).
    Un expire_all() expiraría también los demás objetos y leer sus atributos dispararía IO fuera de contexto."""
    res = await db_session.execute(
        select(models.MonthlyContribution)
        .where(models.MonthlyContribution.id == aporte_id)
        .execution_options(populate_existing=True)
    )
    return res.scalars().first()


async def _crear_aporte(db_session, patient, periodo, estado="DECLARADO"):
    aporte = models.MonthlyContribution(
        patient_id=patient.id,
        periodo=periodo,
        fecha_pago=date(2026, 10, 4),
        monto=100.0,
        url_comprobante="https://fake-storage.test/voucher.jpg",
        estado=estado,
    )
    db_session.add(aporte)
    await db_session.commit()
    await db_session.refresh(aporte)
    return aporte


@pytest.mark.asyncio
async def test_super_admin_corrige_periodo_y_queda_auditado(client, superuser_token, db_session):
    patient = await _crear_patient(db_session)
    aporte = await _crear_aporte(db_session, patient, "2026-10")

    resp = await client.put(f"/contributions/{aporte.id}/periodo", json={"periodo": "2026-09"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["periodo"] == "2026-09"

    guardado = await _releer(db_session, aporte.id)
    assert guardado.periodo == "2026-09"
    # El resto del aporte no se toca: sigue pendiente de revisión.
    assert guardado.estado == "DECLARADO"

    log = (
        await db_session.execute(
            select(models.AuditLog).where(
                models.AuditLog.entidad == "monthly_contribution",
                models.AuditLog.entidad_id == aporte.id,
                models.AuditLog.accion == "CAMBIO_PERIODO_APORTE",
            )
        )
    ).scalars().first()
    assert log is not None
    assert log.payload["periodo_anterior"] == "2026-10"
    assert log.payload["periodo_nuevo"] == "2026-09"


@pytest.mark.asyncio
async def test_corregir_periodo_a_uno_ya_ocupado_es_409(client, superuser_token, db_session):
    patient = await _crear_patient(db_session)
    await _crear_aporte(db_session, patient, "2026-09", estado="ACEPTADO")
    aporte = await _crear_aporte(db_session, patient, "2026-10")

    resp = await client.put(f"/contributions/{aporte.id}/periodo", json={"periodo": "2026-09"})
    assert resp.status_code == 409
    assert "2026-09" in resp.json()["detail"]

    assert (await _releer(db_session, aporte.id)).periodo == "2026-10"


@pytest.mark.asyncio
async def test_registrador_no_puede_corregir_periodo(client, db_session):
    patient = await _crear_patient(db_session)
    aporte = await _crear_aporte(db_session, patient, "2026-10")
    await _switch_identity(db_session, "REGISTRADOR")

    resp = await client.put(f"/contributions/{aporte.id}/periodo", json={"periodo": "2026-09"})
    assert resp.status_code in (401, 403)

    assert (await _releer(db_session, aporte.id)).periodo == "2026-10"


@pytest.mark.asyncio
async def test_paciente_no_puede_corregir_su_propio_periodo(client, patient_token, db_session):
    patient = await _crear_patient(db_session)
    aporte = await _crear_aporte(db_session, patient, "2026-10")

    resp = await client.put(f"/contributions/{aporte.id}/periodo", json={"periodo": "2026-09"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
@pytest.mark.parametrize("periodo", ["2026-13", "2026-00", "26-09", "septiembre", "2026-9", ""])
async def test_periodo_con_formato_invalido_es_422(client, superuser_token, db_session, periodo):
    patient = await _crear_patient(db_session)
    aporte = await _crear_aporte(db_session, patient, "2026-10")

    resp = await client.put(f"/contributions/{aporte.id}/periodo", json={"periodo": periodo})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_corregir_periodo_de_aporte_inexistente_404(client, superuser_token):
    resp = await client.put("/contributions/999999999/periodo", json={"periodo": "2026-09"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mismo_periodo_no_hace_nada(client, superuser_token, db_session):
    patient = await _crear_patient(db_session)
    aporte = await _crear_aporte(db_session, patient, "2026-10")

    resp = await client.put(f"/contributions/{aporte.id}/periodo", json={"periodo": "2026-10"})
    assert resp.status_code == 200

    logs = (
        await db_session.execute(
            select(models.AuditLog).where(
                models.AuditLog.entidad_id == aporte.id,
                models.AuditLog.accion == "CAMBIO_PERIODO_APORTE",
            )
        )
    ).scalars().all()
    assert logs == []
