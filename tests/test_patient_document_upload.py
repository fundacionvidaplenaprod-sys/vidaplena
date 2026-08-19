"""
tests/test_patient_document_upload.py
======================================
Pruebas de `POST /patients/{patient_id}/upload-document`: permite al
SUPER_ADMIN subir o reemplazar un documento del paciente en su nombre,
cuando el beneficiario no puede volver a subir el archivo por su cuenta.
"""
import io
import uuid
from datetime import date

import pytest

from app import models
from app.api.endpoints import patients as patients_module


def _fake_upload(file_content, path, content_type):
    return f"https://fake-storage.test/{path}"


def _fake_file(filename="documento.jpg", content_type="image/jpeg"):
    return {"file": (filename, io.BytesIO(b"fake-image-bytes"), content_type)}


async def _crear_patient(db_session) -> models.Patient:
    suffix = uuid.uuid4().hex[:8]
    user = models.User(
        email=f"docupload_{suffix}@test.com",
        password_hash="fakehash",
        role="PACIENTE",
        estado="ACTIVO",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    patient = models.Patient(
        user_id=user.id,
        nombres=f"Doc{suffix}",
        ap_paterno="Prueba",
        ci=f"CI-{suffix}",
        fecha_nac=date(1990, 1, 1),
        estado="PENDIENTE_DOC",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


@pytest.mark.asyncio
async def test_super_admin_sube_documento_de_paciente(client, superuser_token, db_session, monkeypatch):
    """El SUPER_ADMIN puede subir/reemplazar un documento del paciente."""
    monkeypatch.setattr(patients_module, "upload_file_to_firebase", _fake_upload)
    patient = await _crear_patient(db_session)

    resp = await client.post(
        f"/patients/{patient.id}/upload-document",
        data={"doc_type": "ci"},
        files=_fake_file(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "ci"
    assert body["url"].startswith("https://fake-storage.test/")
    assert f"pacientes/{patient.id}/" in body["url"]

    await db_session.refresh(patient)
    assert patient.url_ci_paciente == body["url"]


@pytest.mark.asyncio
async def test_super_admin_reemplaza_documento_existente(client, superuser_token, db_session, monkeypatch):
    """Subir el mismo doc_type dos veces sobrescribe la URL anterior."""
    monkeypatch.setattr(patients_module, "upload_file_to_firebase", _fake_upload)
    patient = await _crear_patient(db_session)

    await client.post(
        f"/patients/{patient.id}/upload-document",
        data={"doc_type": "medico"},
        files=_fake_file(filename="viejo.pdf", content_type="application/pdf"),
    )
    resp = await client.post(
        f"/patients/{patient.id}/upload-document",
        data={"doc_type": "medico"},
        files=_fake_file(filename="nuevo.pdf", content_type="application/pdf"),
    )
    assert resp.status_code == 200, resp.text

    await db_session.refresh(patient)
    assert "cert_medico" in patient.url_certificado_medico


@pytest.mark.asyncio
async def test_upload_documento_tipo_invalido(client, superuser_token, db_session, monkeypatch):
    monkeypatch.setattr(patients_module, "upload_file_to_firebase", _fake_upload)
    patient = await _crear_patient(db_session)

    resp = await client.post(
        f"/patients/{patient.id}/upload-document",
        data={"doc_type": "no_existe"},
        files=_fake_file(),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_documento_paciente_inexistente(client, superuser_token):
    resp = await client.post(
        "/patients/999999999/upload-document",
        data={"doc_type": "ci"},
        files=_fake_file(),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upload_documento_requiere_super_admin(client, patient_token, db_session):
    """Un usuario PACIENTE no puede usar el endpoint de admin (403)."""
    patient = await _crear_patient(db_session)

    resp = await client.post(
        f"/patients/{patient.id}/upload-document",
        data={"doc_type": "ci"},
        files=_fake_file(),
    )
    assert resp.status_code == 403
