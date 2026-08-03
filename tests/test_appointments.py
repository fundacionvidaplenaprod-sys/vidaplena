import io
from datetime import date, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app import models
from app.api.endpoints import appointments as appointments_module


@pytest_asyncio.fixture(autouse=True)
async def cleanup_test_appointments(db_session):
    await db_session.execute(delete(models.Appointment).where(models.Appointment.ci.like("CI-%")))
    await db_session.commit()
    yield
    await db_session.execute(delete(models.Appointment).where(models.Appointment.ci.like("CI-%")))
    await db_session.commit()


def _next_valid_business_date(min_offset=1):
    """Primera fecha (weekday, no domingo) a partir de hoy+min_offset, dentro de la ventana de 15 días."""
    d = date.today() + timedelta(days=min_offset)
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d


async def _first_available_slot(client, fecha):
    res = await client.get("/appointments/availability", params={"fecha": fecha.isoformat()})
    data = res.json()
    for slot in data["slots"]:
        if slot["disponible"]:
            return slot["hora"]
    return None


def _fake_upload(file_content, path, content_type):
    return f"https://fake-storage.test/{path}"


def _make_ocr_match():
    now = datetime.now()

    def _fake_extract(file_bytes, content_type="image/jpeg"):
        return {"monto": 70.0, "fecha": now.date(), "hora": now.time(), "raw_text": "Bs. 70.00"}

    return _fake_extract


def _make_ocr_mismatch():
    def _fake_extract(file_bytes, content_type="image/jpeg"):
        return {"monto": 30.0, "fecha": date(2000, 1, 1), "hora": time(0, 0), "raw_text": "irrelevante"}

    return _fake_extract


def _booking_form(fecha_cita, hora_cita, ci_suffix):
    return {
        "nombres": "Paciente",
        "ap_paterno": "Prueba",
        "ap_materno": "",
        "ci": f"CI-{ci_suffix}",
        "fecha_nac": "1990-01-01",
        "fecha_cita": fecha_cita.isoformat(),
        "hora_cita": hora_cita,
    }


def _fake_file():
    return {"comprobante": ("comprobante.jpg", io.BytesIO(b"fake-image-bytes"), "image/jpeg")}


@pytest.mark.asyncio
async def test_availability_rejects_sunday_and_out_of_window(client):
    today = date.today()
    # Buscar el próximo domingo
    sunday = today + timedelta(days=(6 - today.weekday()) % 7 or 7)

    res = await client.get("/appointments/availability", params={"fecha": sunday.isoformat()})
    assert res.status_code == 200
    data = res.json()
    assert data["disponible"] is False

    too_far = (today + timedelta(days=30)).isoformat()
    res2 = await client.get("/appointments/availability", params={"fecha": too_far})
    assert res2.json()["disponible"] is False

    today_str = today.isoformat()
    res3 = await client.get("/appointments/availability", params={"fecha": today_str})
    assert res3.json()["disponible"] is False


@pytest.mark.asyncio
async def test_availability_respects_blocked_day(client, db_session):
    fecha = _next_valid_business_date(min_offset=10)
    await db_session.execute(delete(models.DoctorBlockedDay).where(models.DoctorBlockedDay.fecha == fecha))
    await db_session.commit()

    db_session.add(models.DoctorBlockedDay(fecha=fecha, motivo="Prueba"))
    await db_session.commit()

    res = await client.get("/appointments/availability", params={"fecha": fecha.isoformat()})
    data = res.json()
    assert data["disponible"] is False
    assert data["motivo"]

    # Limpiar el día bloqueado para no interferir con las siguientes pruebas
    await db_session.execute(delete(models.DoctorBlockedDay).where(models.DoctorBlockedDay.fecha == fecha))
    await db_session.commit()


@pytest.mark.asyncio
async def test_book_appointment_success_when_ocr_matches(client, monkeypatch):
    monkeypatch.setattr(appointments_module, "upload_file_to_firebase", _fake_upload)
    monkeypatch.setattr(appointments_module, "extract_receipt_data", _make_ocr_match())

    fecha = _next_valid_business_date(min_offset=2)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None

    res = await client.post(
        "/appointments/book",
        data=_booking_form(fecha, hora, "OK1"),
        files=_fake_file(),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["security_code"]
    assert body["fecha_cita"] == fecha.isoformat()
    assert body["hora_cita"] == f"{hora}:00"


@pytest.mark.asyncio
async def test_book_appointment_rejected_when_ocr_mismatches(client, monkeypatch):
    monkeypatch.setattr(appointments_module, "upload_file_to_firebase", _fake_upload)
    monkeypatch.setattr(appointments_module, "extract_receipt_data", _make_ocr_mismatch())

    fecha = _next_valid_business_date(min_offset=3)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None

    res = await client.post(
        "/appointments/book",
        data=_booking_form(fecha, hora, "BAD1"),
        files=_fake_file(),
    )
    assert res.status_code == 400
    assert "WhatsApp" in res.json()["detail"] or "whatsapp" in res.json()["detail"].lower()

    # No debe haber ocupado el horario (quedó RECHAZADA, no CONFIRMADA)
    res_avail = await client.get("/appointments/availability", params={"fecha": fecha.isoformat()})
    slot = next(s for s in res_avail.json()["slots"] if s["hora"] == hora)
    assert slot["disponible"] is True


@pytest.mark.asyncio
async def test_double_booking_same_slot_returns_409(client, monkeypatch):
    monkeypatch.setattr(appointments_module, "upload_file_to_firebase", _fake_upload)
    monkeypatch.setattr(appointments_module, "extract_receipt_data", _make_ocr_match())

    fecha = _next_valid_business_date(min_offset=4)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None

    res1 = await client.post(
        "/appointments/book",
        data=_booking_form(fecha, hora, "DUP1"),
        files=_fake_file(),
    )
    assert res1.status_code == 201, res1.text

    res2 = await client.post(
        "/appointments/book",
        data=_booking_form(fecha, hora, "DUP2"),
        files=_fake_file(),
    )
    assert res2.status_code == 409


@pytest.mark.asyncio
async def test_ficha_requires_correct_code_and_confirmed_state(client, monkeypatch):
    monkeypatch.setattr(appointments_module, "upload_file_to_firebase", _fake_upload)
    monkeypatch.setattr(appointments_module, "extract_receipt_data", _make_ocr_match())

    fecha = _next_valid_business_date(min_offset=5)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None

    res = await client.post(
        "/appointments/book",
        data=_booking_form(fecha, hora, "FICHA1"),
        files=_fake_file(),
    )
    body = res.json()

    ok = await client.get(f"/appointments/{body['id']}/ficha.pdf", params={"code": body["security_code"]})
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "application/pdf"

    bad_code = await client.get(f"/appointments/{body['id']}/ficha.pdf", params={"code": "WRONG"})
    assert bad_code.status_code == 404


@pytest.mark.asyncio
async def test_admin_endpoints_require_authentication(client):
    res1 = await client.get("/appointments/blocked-days")
    assert res1.status_code == 401

    res2 = await client.get("/appointments/agenda", params={"fecha": date.today().isoformat()})
    assert res2.status_code == 401

    res3 = await client.get("/appointments/history", params={"ci": "12345"})
    assert res3.status_code == 401


@pytest.mark.asyncio
async def test_super_admin_can_manage_blocked_days_and_clinical_notes(client, monkeypatch, superuser_token):
    monkeypatch.setattr(appointments_module, "upload_file_to_firebase", _fake_upload)
    monkeypatch.setattr(appointments_module, "extract_receipt_data", _make_ocr_match())

    # Bloquear y desbloquear un día
    fecha_bloqueo = (date.today() + timedelta(days=20)).isoformat()
    res = await client.post("/appointments/blocked-days", json={"fecha": fecha_bloqueo, "motivo": "Vacaciones"})
    assert res.status_code == 201, res.text

    res_list = await client.get("/appointments/blocked-days")
    assert any(b["fecha"] == fecha_bloqueo for b in res_list.json())

    res_del = await client.delete(f"/appointments/blocked-days/{fecha_bloqueo}")
    assert res_del.status_code == 204

    # Crear una cita confirmada y escribirle una nota de consulta
    fecha = _next_valid_business_date(min_offset=6)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None
    res_book = await client.post(
        "/appointments/book",
        data=_booking_form(fecha, hora, "NOTE1"),
        files=_fake_file(),
    )
    appointment_id = res_book.json()["id"]

    res_agenda = await client.get("/appointments/agenda", params={"fecha": fecha.isoformat()})
    assert res_agenda.status_code == 200
    assert any(item["id"] == appointment_id for item in res_agenda.json())

    res_note = await client.put(f"/appointments/{appointment_id}/clinical-note", json={"nota": "Se recetó insulina."})
    assert res_note.status_code == 200
    assert res_note.json()["nota_consulta"] == "Se recetó insulina."

    res_history = await client.get("/appointments/history", params={"ci": "CI-NOTE1"})
    assert res_history.status_code == 200
    assert res_history.json()[0]["nota_consulta"] == "Se recetó insulina."


async def _book_rejected(client, monkeypatch, fecha, hora, ci_suffix):
    """Agenda una cita cuyo OCR no coincide (queda RECHAZADA) y devuelve su id."""
    monkeypatch.setattr(appointments_module, "upload_file_to_firebase", _fake_upload)
    monkeypatch.setattr(appointments_module, "extract_receipt_data", _make_ocr_mismatch())

    res = await client.post(
        "/appointments/book",
        data=_booking_form(fecha, hora, ci_suffix),
        files=_fake_file(),
    )
    assert res.status_code == 400

    result = await client.get("/appointments/history", params={"ci": f"CI-{ci_suffix}"})
    # /appointments/history requiere SUPER_ADMIN; el llamador debe tener el token activo.
    appointment_id = result.json()[0]["id"]
    return appointment_id


@pytest.mark.asyncio
async def test_approve_rejected_appointment_confirms_and_issues_ficha(client, monkeypatch, superuser_token):
    fecha = _next_valid_business_date(min_offset=7)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None

    appointment_id = await _book_rejected(client, monkeypatch, fecha, hora, "APR1")

    res_history_before = await client.get("/appointments/history", params={"ci": "CI-APR1"})
    assert res_history_before.json()[0]["estado"] == "RECHAZADA"
    assert res_history_before.json()[0]["security_code"] is None

    res_approve = await client.post(f"/appointments/{appointment_id}/approve")
    assert res_approve.status_code == 200, res_approve.text
    body = res_approve.json()
    assert body["estado"] == "CONFIRMADA"
    assert body["security_code"]
    assert body["revisado_manualmente_at"] is not None

    # Ahora la ficha debe poder descargarse con el código emitido.
    ficha = await client.get(
        f"/appointments/{appointment_id}/ficha.pdf", params={"code": body["security_code"]}
    )
    assert ficha.status_code == 200
    assert ficha.headers["content-type"] == "application/pdf"

    # El horario aprobado ahora debe figurar como ocupado.
    res_avail = await client.get("/appointments/availability", params={"fecha": fecha.isoformat()})
    slot = next(s for s in res_avail.json()["slots"] if s["hora"] == hora)
    assert slot["disponible"] is False


@pytest.mark.asyncio
async def test_approve_requires_super_admin(client, db_session):
    fecha = _next_valid_business_date(min_offset=8)
    appointment = models.Appointment(
        nombres="Paciente", ap_paterno="Prueba", ci="CI-APR2",
        fecha_nac=date(1990, 1, 1), fecha_cita=fecha, hora_cita=time(9, 0),
        estado="RECHAZADA", motivo_rechazo="Prueba",
    )
    db_session.add(appointment)
    await db_session.commit()
    await db_session.refresh(appointment)

    res = await client.post(f"/appointments/{appointment.id}/approve")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_approve_nonexistent_appointment(client, superuser_token):
    res = await client.post("/appointments/999999999/approve")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_approve_already_confirmed_appointment_rejected(client, monkeypatch, superuser_token):
    monkeypatch.setattr(appointments_module, "upload_file_to_firebase", _fake_upload)
    monkeypatch.setattr(appointments_module, "extract_receipt_data", _make_ocr_match())

    fecha = _next_valid_business_date(min_offset=9)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None
    res_book = await client.post(
        "/appointments/book",
        data=_booking_form(fecha, hora, "APR3"),
        files=_fake_file(),
    )
    appointment_id = res_book.json()["id"]

    res = await client.post(f"/appointments/{appointment_id}/approve")
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_approve_rejects_when_slot_taken_by_another_confirmed(client, monkeypatch, superuser_token):
    fecha = _next_valid_business_date(min_offset=10)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None

    # Primero, una reserva rechazada para ese horario.
    appointment_id = await _book_rejected(client, monkeypatch, fecha, hora, "APR4")

    # Luego, otra persona reserva y confirma ese mismo horario legítimamente.
    monkeypatch.setattr(appointments_module, "upload_file_to_firebase", _fake_upload)
    monkeypatch.setattr(appointments_module, "extract_receipt_data", _make_ocr_match())
    res_book2 = await client.post(
        "/appointments/book",
        data=_booking_form(fecha, hora, "APR4B"),
        files=_fake_file(),
    )
    assert res_book2.status_code == 201, res_book2.text

    res_approve = await client.post(f"/appointments/{appointment_id}/approve")
    assert res_approve.status_code == 409


@pytest.mark.asyncio
async def test_approve_social_case_confirms_without_voucher_and_issues_ficha(client, monkeypatch, superuser_token):
    fecha = _next_valid_business_date(min_offset=11)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None

    appointment_id = await _book_rejected(client, monkeypatch, fecha, hora, "SOC1")

    res_approve = await client.post(
        f"/appointments/{appointment_id}/approve-social-case", json={"motivo": "Sin recursos tras evaluación"}
    )
    assert res_approve.status_code == 200, res_approve.text
    body = res_approve.json()
    assert body["estado"] == "CONFIRMADA"
    assert body["security_code"]
    assert body["eximido_at"] is not None
    assert body["motivo_exencion"] == "Sin recursos tras evaluación"

    ficha = await client.get(
        f"/appointments/{appointment_id}/ficha.pdf", params={"code": body["security_code"]}
    )
    assert ficha.status_code == 200


@pytest.mark.asyncio
async def test_approve_social_case_defaults_motivo(client, monkeypatch, superuser_token):
    fecha = _next_valid_business_date(min_offset=12)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None
    appointment_id = await _book_rejected(client, monkeypatch, fecha, hora, "SOC2")

    res_approve = await client.post(f"/appointments/{appointment_id}/approve-social-case", json={})
    assert res_approve.status_code == 200, res_approve.text
    assert res_approve.json()["motivo_exencion"] == "Caso Social"


@pytest.mark.asyncio
async def test_approve_social_case_requires_super_admin(client, db_session):
    fecha = _next_valid_business_date(min_offset=13)
    appointment = models.Appointment(
        nombres="Paciente", ap_paterno="Prueba", ci="CI-SOC3",
        fecha_nac=date(1990, 1, 1), fecha_cita=fecha, hora_cita=time(9, 0),
        estado="RECHAZADA", motivo_rechazo="Prueba",
    )
    db_session.add(appointment)
    await db_session.commit()
    await db_session.refresh(appointment)

    res = await client.post(f"/appointments/{appointment.id}/approve-social-case", json={})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_approve_social_case_not_found(client, superuser_token):
    res = await client.post("/appointments/999999999/approve-social-case", json={})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_approve_social_case_already_confirmed_rejected(client, monkeypatch, superuser_token):
    monkeypatch.setattr(appointments_module, "upload_file_to_firebase", _fake_upload)
    monkeypatch.setattr(appointments_module, "extract_receipt_data", _make_ocr_match())

    fecha = _next_valid_business_date(min_offset=14)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None
    res_book = await client.post(
        "/appointments/book",
        data=_booking_form(fecha, hora, "SOC4"),
        files=_fake_file(),
    )
    appointment_id = res_book.json()["id"]

    res = await client.post(f"/appointments/{appointment_id}/approve-social-case", json={})
    assert res.status_code == 400


def _admin_social_case_payload(fecha_cita, hora_cita, ci_suffix, motivo=None):
    payload = {
        "nombres": "Paciente",
        "ap_paterno": "TrabajoSocial",
        "ap_materno": "",
        "ci": f"CI-{ci_suffix}",
        "fecha_nac": "1990-01-01",
        "fecha_cita": fecha_cita.isoformat(),
        "hora_cita": hora_cita,
    }
    if motivo is not None:
        payload["motivo"] = motivo
    return payload


@pytest.mark.asyncio
async def test_admin_create_social_case_creates_confirmed_appointment_and_issues_ficha(client, superuser_token):
    fecha = _next_valid_business_date(min_offset=1)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None

    res = await client.post(
        "/appointments/admin-create-social-case",
        json=_admin_social_case_payload(fecha, hora, "ADMSOC1", motivo="Sin recursos, evaluación presencial"),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["security_code"]
    assert body["fecha_cita"] == fecha.isoformat()
    assert body["hora_cita"] == f"{hora}:00"
    assert body["nombre_completo"] == "Paciente TrabajoSocial"

    result = await client.get(
        f"/appointments/{body['id']}/ficha.pdf", params={"code": body["security_code"]}
    )
    assert result.status_code == 200

    hist = await client.get("/appointments/history", params={"ci": "CI-ADMSOC1"})
    hist_body = hist.json()
    assert hist_body[0]["estado"] == "CONFIRMADA"
    assert hist_body[0]["motivo_exencion"] == "Sin recursos, evaluación presencial"
    assert hist_body[0]["eximido_at"] is not None


@pytest.mark.asyncio
async def test_admin_create_social_case_defaults_motivo(client, superuser_token):
    fecha = _next_valid_business_date(min_offset=2)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None

    res = await client.post(
        "/appointments/admin-create-social-case",
        json=_admin_social_case_payload(fecha, hora, "ADMSOC2"),
    )
    assert res.status_code == 201, res.text

    hist = await client.get("/appointments/history", params={"ci": "CI-ADMSOC2"})
    assert hist.json()[0]["motivo_exencion"] == "Evaluación Socioeconómica / Trabajo Social"


@pytest.mark.asyncio
async def test_admin_create_social_case_requires_super_admin(client):
    fecha = _next_valid_business_date(min_offset=3)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None

    res = await client.post(
        "/appointments/admin-create-social-case",
        json=_admin_social_case_payload(fecha, hora, "ADMSOC3"),
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_admin_create_social_case_rejects_invalid_date(client, superuser_token):
    fecha_fuera_ventana = date.today() + timedelta(days=30)

    res = await client.post(
        "/appointments/admin-create-social-case",
        json=_admin_social_case_payload(fecha_fuera_ventana, "09:00", "ADMSOC4"),
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_admin_create_social_case_rejects_taken_slot(client, monkeypatch, superuser_token):
    monkeypatch.setattr(appointments_module, "upload_file_to_firebase", _fake_upload)
    monkeypatch.setattr(appointments_module, "extract_receipt_data", _make_ocr_match())

    fecha = _next_valid_business_date(min_offset=4)
    hora = await _first_available_slot(client, fecha)
    assert hora is not None

    res_book = await client.post(
        "/appointments/book",
        data=_booking_form(fecha, hora, "ADMSOC5"),
        files=_fake_file(),
    )
    assert res_book.status_code == 201, res_book.text

    res = await client.post(
        "/appointments/admin-create-social-case",
        json=_admin_social_case_payload(fecha, hora, "ADMSOC6"),
    )
    assert res.status_code == 409
