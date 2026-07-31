import io
from datetime import date, datetime, time, timedelta

import pytest

from app import models
from app.api.endpoints import appointments as appointments_module


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
    db_session.add(models.DoctorBlockedDay(fecha=fecha, motivo="Prueba"))
    await db_session.commit()

    res = await client.get("/appointments/availability", params={"fecha": fecha.isoformat()})
    data = res.json()
    assert data["disponible"] is False
    assert data["motivo"]


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
