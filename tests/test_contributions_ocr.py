import io
from datetime import date, time

import pytest

from app.api.endpoints import contributions as contributions_module


def _fake_file():
    return {"comprobante": ("comprobante.jpg", io.BytesIO(b"fake-image-bytes"), "image/jpeg")}


def _fake_ocr_success(file_bytes, content_type="image/jpeg"):
    return {"monto": 55.5, "fecha": date(2026, 1, 15), "hora": time(10, 0), "raw_text": "Bs. 55.50"}


def _fake_ocr_no_monto(file_bytes, content_type="image/jpeg"):
    return {"monto": None, "fecha": date(2026, 1, 15), "hora": None, "raw_text": "texto irrelevante"}


@pytest.mark.asyncio
async def test_ocr_preview_returns_detected_amount_not_restricted_to_70(client, monkeypatch, patient_token):
    monkeypatch.setattr(contributions_module, "extract_receipt_data", _fake_ocr_success)

    res = await client.post("/contributions/ocr-preview", files=_fake_file())
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["monto"] == 55.5
    assert body["fecha"] == "2026-01-15"


@pytest.mark.asyncio
async def test_ocr_preview_handles_undetected_amount_gracefully(client, monkeypatch, patient_token):
    monkeypatch.setattr(contributions_module, "extract_receipt_data", _fake_ocr_no_monto)

    res = await client.post("/contributions/ocr-preview", files=_fake_file())
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["monto"] is None
    assert body["fecha"] == "2026-01-15"


@pytest.mark.asyncio
async def test_ocr_preview_requires_authentication(client, monkeypatch):
    monkeypatch.setattr(contributions_module, "extract_receipt_data", _fake_ocr_success)

    res = await client.post("/contributions/ocr-preview", files=_fake_file())
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_ocr_preview_rejects_invalid_file_type(client, patient_token):
    files = {"comprobante": ("archivo.txt", io.BytesIO(b"hola"), "text/plain")}
    res = await client.post("/contributions/ocr-preview", files=files)
    assert res.status_code == 400
