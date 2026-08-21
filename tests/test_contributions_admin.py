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
from app.main import app
from app.api import deps
from app.api.endpoints import contributions as contributions_module


async def _switch_identity(db_session, role: str) -> models.User:
    """Crea un usuario con el rol dado y hace que el `client` autentique como él."""
    user = models.User(
        email=f"{role.lower()}_{uuid.uuid4().hex[:8]}@test.com",
        password_hash="fakehash",
        role=role,
        estado="ACTIVO",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    async def _override():
        return user

    app.dependency_overrides[deps.get_current_active_user] = _override
    app.dependency_overrides[deps.get_current_user] = _override
    if role == "SUPER_ADMIN":
        app.dependency_overrides[deps.get_current_super_user] = _override
    return user


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


@pytest.mark.asyncio
async def test_historial_de_aportes_de_un_beneficiario(client, superuser_token, db_session):
    """
    GET /contributions/patient/{id} trae todos los periodos/estados de UN
    beneficiario, para verificar/certificar si subió su voucher de un mes
    puntual sin buscarlo en la lista general.
    """
    patient = await _crear_patient(db_session)
    otro_patient = await _crear_patient(db_session)

    db_session.add_all([
        models.MonthlyContribution(
            patient_id=patient.id, periodo="2026-07", fecha_pago=date(2026, 7, 3),
            monto=100.0, url_comprobante="https://fake-storage.test/julio.jpg", estado="ACEPTADO",
        ),
        models.MonthlyContribution(
            patient_id=patient.id, periodo="2026-08", fecha_pago=date(2026, 8, 4),
            monto=100.0, url_comprobante="https://fake-storage.test/agosto.jpg", estado="DECLARADO",
        ),
        # De otro beneficiario: no debe aparecer en el historial de `patient`.
        models.MonthlyContribution(
            patient_id=otro_patient.id, periodo="2026-08", fecha_pago=date(2026, 8, 4),
            monto=100.0, url_comprobante="https://fake-storage.test/otro.jpg", estado="ACEPTADO",
        ),
    ])
    await db_session.commit()

    resp = await client.get(f"/contributions/patient/{patient.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 2
    periodos = {item["periodo"]: item["estado"] for item in body}
    assert periodos == {"2026-07": "ACEPTADO", "2026-08": "DECLARADO"}
    assert all(item["patient_id"] == patient.id for item in body)


@pytest.mark.asyncio
async def test_historial_de_aportes_requiere_staff(client, patient_token, db_session):
    patient = await _crear_patient(db_session)
    resp = await client.get(f"/contributions/patient/{patient.id}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_historial_de_aportes_paciente_inexistente_404(client, superuser_token):
    resp = await client.get("/contributions/patient/999999999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_voucher_declarado_por_beneficiario_aparece_en_revision_filtrada(
    client, db_session, monkeypatch
):
    """
    Reproduce el reclamo: un beneficiario declara su voucher (queda DECLARADO,
    igual que el flujo real desde `/contributions/me`, no el registro manual de
    un admin). Ese voucher debe verse tanto en el historial del beneficiario
    (`/contributions/patient/{id}`) como en la revisión general filtrando por
    `estado=DECLARADO` (`/contributions/review`) — ambos deben coincidir.
    """
    monkeypatch.setattr(contributions_module, "upload_file_to_firebase", _fake_upload)

    patient_user = await _switch_identity(db_session, "PACIENTE")
    patient = models.Patient(
        user_id=patient_user.id,
        nombres="Voucher",
        ap_paterno="Declarado",
        ci=f"CI-{uuid.uuid4().hex[:6]}",
        fecha_nac=date(1990, 1, 1),
        estado="ACTIVO",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    declare_resp = await client.post(
        "/contributions/me",
        data={"monto": "100.00", "periodo": "2026-09", "fecha_pago": "2026-09-05"},
        files=_fake_file(),
    )
    assert declare_resp.status_code == 201, declare_resp.text
    assert declare_resp.json()["estado"] == "DECLARADO"

    await _switch_identity(db_session, "SUPER_ADMIN")

    review_resp = await client.get("/contributions/review", params={"estado": "DECLARADO"})
    assert review_resp.status_code == 200, review_resp.text
    review_ids = {item["id"] for item in review_resp.json()}

    history_resp = await client.get(f"/contributions/patient/{patient.id}")
    assert history_resp.status_code == 200, history_resp.text
    history_declarados = {
        item["id"] for item in history_resp.json() if item["estado"] == "DECLARADO"
    }

    assert history_declarados, "El historial del paciente debería mostrar el voucher recién declarado."
    assert history_declarados.issubset(review_ids), (
        "El voucher aparece en el historial del paciente pero no en la revisión general "
        "filtrada por DECLARADO — este es exactamente el síntoma reportado."
    )


@pytest.mark.asyncio
async def test_revision_no_falla_si_algun_beneficiario_no_tiene_ci(
    client, db_session, monkeypatch
):
    """
    `Patient.ci` es nullable en la BD (un beneficiario puede estar registrado
    sin CI todavía), pero `ContributionReviewResponse.patient_ci` exigía un
    str obligatorio. Bastaba UN beneficiario con `ci=None` y un voucher
    DECLARADO/OBSERVADO para que `GET /contributions/review` reventara con
    500 al construir la lista completa — afectando también a "Todos", pero
    no a filtrar por ACEPTADO si esa fila puntual no estaba en ese estado.
    Este es el bug real detrás del reclamo de producción.
    """
    monkeypatch.setattr(contributions_module, "upload_file_to_firebase", _fake_upload)

    patient_user = await _switch_identity(db_session, "PACIENTE")
    patient_sin_ci = models.Patient(
        user_id=patient_user.id,
        nombres="SinCI",
        ap_paterno="Registrado",
        ci=None,
        fecha_nac=date(1990, 1, 1),
        estado="PENDIENTE_DOC",
    )
    db_session.add(patient_sin_ci)
    await db_session.commit()
    await db_session.refresh(patient_sin_ci)

    declare_resp = await client.post(
        "/contributions/me",
        data={"monto": "100.00", "periodo": "2026-09", "fecha_pago": "2026-09-05"},
        files=_fake_file(),
    )
    assert declare_resp.status_code == 201, declare_resp.text

    await _switch_identity(db_session, "SUPER_ADMIN")

    resp_declarado = await client.get("/contributions/review", params={"estado": "DECLARADO"})
    assert resp_declarado.status_code == 200, resp_declarado.text
    assert any(item["patient_id"] == patient_sin_ci.id for item in resp_declarado.json())

    resp_todos = await client.get("/contributions/review")
    assert resp_todos.status_code == 200, resp_todos.text

    resp_historial = await client.get(f"/contributions/patient/{patient_sin_ci.id}")
    assert resp_historial.status_code == 200, resp_historial.text
    assert resp_historial.json()[0]["patient_ci"] is None
