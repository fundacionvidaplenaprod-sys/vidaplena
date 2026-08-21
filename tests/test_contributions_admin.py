"""
tests/test_contributions_admin.py
===================================
Pruebas de `POST /contributions/{patient_id}`: permite al SUPER_ADMIN
registrar un aporte que el beneficiario pagó (p. ej. depósito bancario) pero
nunca declaró por su cuenta en la app. Queda directamente ACEPTADO, porque
el staff ya lo verificó al registrarlo.
"""
import io
import uuid
from datetime import date

import pytest

from app import models
from app.api.endpoints import contributions as contributions_module


def _fake_upload(file_content, path, content_type):
    return f"https://fake-storage.test/{path}"


def _fake_file(filename="deposito.jpg", content_type="image/jpeg"):
    return {"comprobante": (filename, io.BytesIO(b"fake-receipt-bytes"), content_type)}


async def _crear_patient(db_session) -> models.Patient:
    suffix = uuid.uuid4().hex[:8]
    user = models.User(
        email=f"aporte_manual_{suffix}@test.com",
        password_hash="fakehash",
        role="PACIENTE",
        estado="ACTIVO",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    patient = models.Patient(
        user_id=user.id,
        nombres=f"Aporte{suffix}",
        ap_paterno="Manual",
        ci=f"CI-{suffix}",
        fecha_nac=date(1990, 1, 1),
        estado="ACTIVO",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


@pytest.mark.asyncio
async def test_super_admin_registra_aporte_queda_aceptado(client, superuser_token, db_session, monkeypatch):
    monkeypatch.setattr(contributions_module, "upload_file_to_firebase", _fake_upload)
    patient = await _crear_patient(db_session)

    resp = await client.post(
        f"/contributions/{patient.id}",
        data={"monto": "100.00", "periodo": "2026-08", "fecha_pago": "2026-08-05"},
        files=_fake_file(),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["estado"] == "ACEPTADO"
    assert body["monto"] == 100.0
    assert "Registrado manualmente" in body["observacion_admin"]


@pytest.mark.asyncio
async def test_registrar_aporte_requiere_super_admin(client, patient_token, db_session):
    patient = await _crear_patient(db_session)

    resp = await client.post(
        f"/contributions/{patient.id}",
        data={"monto": "100.00", "periodo": "2026-08", "fecha_pago": "2026-08-05"},
        files=_fake_file(),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_registrar_aporte_paciente_inexistente_404(client, superuser_token):
    resp = await client.post(
        "/contributions/999999999",
        data={"monto": "100.00", "periodo": "2026-08", "fecha_pago": "2026-08-05"},
        files=_fake_file(),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_registrar_aporte_no_coincide_con_monto_comprometido(client, superuser_token, db_session, monkeypatch):
    monkeypatch.setattr(contributions_module, "upload_file_to_firebase", _fake_upload)
    patient = await _crear_patient(db_session)
    patient.monto_aporte_comprometido = 180.0
    await db_session.commit()

    resp = await client.post(
        f"/contributions/{patient.id}",
        data={"monto": "100.00", "periodo": "2026-08", "fecha_pago": "2026-08-05"},
        files=_fake_file(),
    )
    assert resp.status_code == 400
    assert "180" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_registrar_aporte_reemplaza_declarado_pendiente(client, superuser_token, db_session, monkeypatch):
    """Si el beneficiario ya había declarado uno (DECLARADO/OBSERVADO), el registro manual lo reemplaza y aprueba."""
    monkeypatch.setattr(contributions_module, "upload_file_to_firebase", _fake_upload)
    patient = await _crear_patient(db_session)
    existing = models.MonthlyContribution(
        patient_id=patient.id,
        periodo="2026-08",
        fecha_pago=date(2026, 8, 1),
        monto=100.0,
        url_comprobante="https://old-storage.test/old.jpg",
        estado="OBSERVADO",
        observacion_admin="Comprobante ilegible.",
    )
    db_session.add(existing)
    await db_session.commit()

    resp = await client.post(
        f"/contributions/{patient.id}",
        data={"monto": "100.00", "periodo": "2026-08", "fecha_pago": "2026-08-05"},
        files=_fake_file(),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["estado"] == "ACEPTADO"
    assert body["id"] == existing.id


@pytest.mark.asyncio
async def test_registrar_aporte_no_reemplaza_ya_aceptado(client, superuser_token, db_session, monkeypatch):
    monkeypatch.setattr(contributions_module, "upload_file_to_firebase", _fake_upload)
    patient = await _crear_patient(db_session)
    existing = models.MonthlyContribution(
        patient_id=patient.id,
        periodo="2026-08",
        fecha_pago=date(2026, 8, 1),
        monto=100.0,
        url_comprobante="https://old-storage.test/old.jpg",
        estado="ACEPTADO",
    )
    db_session.add(existing)
    await db_session.commit()

    resp = await client.post(
        f"/contributions/{patient.id}",
        data={"monto": "100.00", "periodo": "2026-08", "fecha_pago": "2026-08-05"},
        files=_fake_file(),
    )
    assert resp.status_code == 400
