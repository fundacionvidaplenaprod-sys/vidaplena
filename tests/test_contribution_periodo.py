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
    # un aporte ya ACEPTADO nunca se reemplaza, ni siquiera confirmando
    forzado = await client.put(f"/contributions/{aporte.id}/periodo", json={"periodo": "2026-09", "reemplazar": True})
    assert forzado.status_code == 409

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


async def _caso_octubre_observado_y_voucher_corregido_en_noviembre(db_session):
    """El voucher de octubre fue observado; el beneficiario sube el corregido en noviembre."""
    patient = await _crear_patient(db_session)
    observado = await _crear_aporte(db_session, patient, "2026-10", estado="OBSERVADO")
    observado.observacion_admin = "El voucher no se lee"
    observado.url_comprobante = "https://fake-storage.test/voucher_viejo.jpg"
    db_session.add(observado)
    corregido = await _crear_aporte(db_session, patient, "2026-11")
    corregido.url_comprobante = "https://fake-storage.test/voucher_corregido.jpg"
    db_session.add(corregido)
    await db_session.commit()
    return patient, observado, corregido


async def _aportes_del(db_session, patient_id):
    res = await db_session.execute(
        select(models.MonthlyContribution)
        .where(models.MonthlyContribution.patient_id == patient_id)
        .order_by(models.MonthlyContribution.periodo)
        .execution_options(populate_existing=True)
    )
    return res.scalars().all()


@pytest.mark.asyncio
async def test_reasignar_a_un_periodo_con_aporte_observado_avisa_sin_tocar_nada(client, superuser_token, db_session):
    patient, observado, corregido = await _caso_octubre_observado_y_voucher_corregido_en_noviembre(db_session)

    resp = await client.put(f"/contributions/{corregido.id}/periodo", json={"periodo": "2026-10"})
    assert resp.status_code == 409
    detalle = resp.json()["detail"]
    assert detalle["code"] == "PERIODO_OCUPADO"
    assert "OBSERVADO" in detalle["message"] and "2026-10" in detalle["message"]
    assert detalle["existente"]["id"] == observado.id
    assert detalle["existente"]["observacion_admin"] == "El voucher no se lee"

    assert [(a.periodo, a.estado) for a in await _aportes_del(db_session, patient.id)] == [
        ("2026-10", "OBSERVADO"), ("2026-11", "DECLARADO"),
    ]


@pytest.mark.asyncio
async def test_confirmando_el_voucher_corregido_reemplaza_al_observado_y_queda_auditado(client, superuser_token, db_session):
    patient, observado, corregido = await _caso_octubre_observado_y_voucher_corregido_en_noviembre(db_session)
    observado_id, corregido_id = observado.id, corregido.id

    resp = await client.put(f"/contributions/{corregido_id}/periodo", json={"periodo": "2026-10", "reemplazar": True})
    assert resp.status_code == 200, resp.text
    assert (resp.json()["id"], resp.json()["periodo"], resp.json()["estado"]) == (corregido_id, "2026-10", "DECLARADO")

    # queda un solo aporte, el nuevo voucher en octubre, pendiente de revisión; noviembre queda libre
    [unico] = await _aportes_del(db_session, patient.id)
    assert (unico.id, unico.periodo, unico.estado) == (corregido_id, "2026-10", "DECLARADO")
    assert unico.url_comprobante.endswith("voucher_corregido.jpg")
    assert await db_session.get(models.MonthlyContribution, observado_id) is None

    log = (
        await db_session.execute(
            select(models.AuditLog).where(
                models.AuditLog.entidad == "monthly_contribution",
                models.AuditLog.entidad_id == corregido_id,
                models.AuditLog.accion == "CAMBIO_PERIODO_APORTE",
            )
        )
    ).scalars().first()
    assert (log.payload["periodo_anterior"], log.payload["periodo_nuevo"]) == ("2026-11", "2026-10")
    reemplazado = log.payload["aporte_reemplazado"]
    assert reemplazado["id"] == observado_id and reemplazado["estado"] == "OBSERVADO"
    assert reemplazado["observacion_admin"] == "El voucher no se lee"
    assert reemplazado["url_comprobante"].endswith("voucher_viejo.jpg")  # el voucher anterior se puede recuperar


@pytest.mark.asyncio
async def test_tambien_se_puede_reemplazar_un_aporte_declarado_sin_revisar_si_se_confirma(client, superuser_token, db_session):
    patient = await _crear_patient(db_session)
    declarado = await _crear_aporte(db_session, patient, "2026-10", estado="DECLARADO")
    otro = await _crear_aporte(db_session, patient, "2026-11")

    sin_confirmar = await client.put(f"/contributions/{otro.id}/periodo", json={"periodo": "2026-10"})
    assert sin_confirmar.status_code == 409 and sin_confirmar.json()["detail"]["existente"]["estado"] == "DECLARADO"

    ok = await client.put(f"/contributions/{otro.id}/periodo", json={"periodo": "2026-10", "reemplazar": True})
    assert ok.status_code == 200
    assert [a.id for a in await _aportes_del(db_session, patient.id)] == [otro.id]
    assert declarado.id != otro.id


@pytest.mark.asyncio
async def test_reemplazar_solo_afecta_al_mismo_beneficiario(client, superuser_token, db_session):
    patient, observado, corregido = await _caso_octubre_observado_y_voucher_corregido_en_noviembre(db_session)
    otro_beneficiario = await _crear_patient(db_session)
    ajeno = await _crear_aporte(db_session, otro_beneficiario, "2026-10", estado="OBSERVADO")

    resp = await client.put(f"/contributions/{corregido.id}/periodo", json={"periodo": "2026-10", "reemplazar": True})
    assert resp.status_code == 200
    assert await db_session.get(models.MonthlyContribution, ajeno.id) is not None  # el aporte ajeno sigue ahí
