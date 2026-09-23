"""
tests/test_vouchers_report.py
===============================
Reporte de Control de Vouchers (Reportes > Control de Vouchers):
GET /contributions/vouchers/export.pdf — a diferencia del historial de un
beneficiario puntual o del reporte de vouchers sin imagen (/review/export.pdf,
usado en Revisión de Aportes), este incrusta la captura de cada comprobante
junto al nombre del beneficiario y la fecha de pago, para todos los
beneficiarios.

También cubre el filtro `periodo` agregado a GET /contributions/review, que
reutiliza el mismo helper que arma este reporte.
"""
import asyncio
import io
import uuid
from datetime import date

import httpx
import pytest
from PIL import Image as PILImage

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


async def _crear_patient(db_session) -> models.Patient:
    suffix = uuid.uuid4().hex[:8]
    user = models.User(
        email=f"voucher_report_{suffix}@test.com",
        password_hash="fakehash",
        role="PACIENTE",
        estado="ACTIVO",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    patient = models.Patient(
        user_id=user.id,
        nombres=f"Voucher{suffix}",
        ap_paterno="Report",
        ci=f"CI-{suffix}",
        fecha_nac=date(1990, 1, 1),
        estado="ACTIVO",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


async def _crear_contribution(db_session, patient, periodo, url_comprobante="https://fake-storage.test/v.jpg", estado="ACEPTADO"):
    contrib = models.MonthlyContribution(
        patient_id=patient.id,
        periodo=periodo,
        fecha_pago=date(2032, 1, 15),
        monto=100.0,
        url_comprobante=url_comprobante,
        estado=estado,
    )
    db_session.add(contrib)
    await db_session.commit()
    await db_session.refresh(contrib)
    return contrib


def _png_bytes(width=40, height=60) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), color="blue").save(buf, format="PNG")
    return buf.getvalue()


class _FakeHttpResponse:
    def __init__(self, content: bytes, content_type: str, ok: bool = True):
        self.content = content
        self.headers = {"content-type": content_type}
        self._ok = ok

    def raise_for_status(self):
        if not self._ok:
            raise httpx.HTTPStatusError("error", request=None, response=None)


class _FakeHttpClient:
    """Doble de prueba para el parámetro `http_client` de _fetch_voucher_thumbnail — no requiere red real."""

    def __init__(self, response=None, raise_exc=None):
        self._response = response
        self._raise_exc = raise_exc

    async def get(self, url, timeout=None):
        if self._raise_exc:
            raise self._raise_exc
        return self._response


# ─────────────────────────────────────────────────────────────────────────
#  _fetch_voucher_thumbnail (unitario, sin red)
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_thumbnail_sin_url_retorna_none():
    result = await contributions_module._fetch_voucher_thumbnail(
        _FakeHttpClient(), asyncio.Semaphore(1), None
    )
    assert result is None


@pytest.mark.asyncio
async def test_fetch_thumbnail_pdf_retorna_none():
    """Un comprobante subido como PDF no se puede incrustar como miniatura — cae a texto/enlace."""
    resp = _FakeHttpResponse(b"%PDF-1.4 fake content", "application/pdf")
    result = await contributions_module._fetch_voucher_thumbnail(
        _FakeHttpClient(resp), asyncio.Semaphore(1), "https://fake-storage.test/v.pdf"
    )
    assert result is None


@pytest.mark.asyncio
async def test_fetch_thumbnail_descarga_falla_retorna_none():
    client_fake = _FakeHttpClient(raise_exc=RuntimeError("network down"))
    result = await contributions_module._fetch_voucher_thumbnail(
        client_fake, asyncio.Semaphore(1), "https://fake-storage.test/v.jpg"
    )
    assert result is None


@pytest.mark.asyncio
async def test_fetch_thumbnail_contenido_no_es_imagen_retorna_none():
    resp = _FakeHttpResponse(b"esto no es una imagen", "image/jpeg")
    result = await contributions_module._fetch_voucher_thumbnail(
        _FakeHttpClient(resp), asyncio.Semaphore(1), "https://fake-storage.test/v.jpg"
    )
    assert result is None


@pytest.mark.asyncio
async def test_fetch_thumbnail_imagen_valida_se_escala_dentro_de_la_caja():
    resp = _FakeHttpResponse(_png_bytes(400, 600), "image/png")
    result = await contributions_module._fetch_voucher_thumbnail(
        _FakeHttpClient(resp), asyncio.Semaphore(1), "https://fake-storage.test/v.png"
    )
    assert result is not None
    assert result.drawWidth <= contributions_module.VOUCHER_THUMB_MAX_WIDTH
    assert result.drawHeight <= contributions_module.VOUCHER_THUMB_MAX_HEIGHT


# ─────────────────────────────────────────────────────────────────────────
#  GET /contributions/vouchers/export.pdf
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_vouchers_pdf_requiere_staff(client, patient_token):
    resp = await client.get("/contributions/vouchers/export.pdf")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_export_vouchers_pdf_registrador_puede_acceder(client, db_session):
    await _switch_identity(db_session, "REGISTRADOR")
    resp = await client.get("/contributions/vouchers/export.pdf")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"


@pytest.mark.asyncio
async def test_export_vouchers_pdf_sin_datos_no_falla(client, superuser_token):
    resp = await client.get("/contributions/vouchers/export.pdf", params={"periodo": "1999-01"})
    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(b"%PDF")


def _patch_external_get(monkeypatch, client, fake_response):
    """
    Parchea httpx.AsyncClient.get SOLO para el cliente externo que crea el
    endpoint (para descargar el voucher) — las llamadas del propio `client`
    de prueba (que golpea la app vía ASGITransport) siguen su camino real,
    ya que si no, se interceptarían entre sí (misma clase).
    """
    original_get = httpx.AsyncClient.get

    async def fake_get(self, url, *args, **kwargs):
        if self is client:
            return await original_get(self, url, *args, **kwargs)
        return fake_response

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


@pytest.mark.asyncio
async def test_export_vouchers_pdf_con_imagen_real(client, superuser_token, db_session, monkeypatch):
    _patch_external_get(monkeypatch, client, _FakeHttpResponse(_png_bytes(), "image/png"))

    patient = await _crear_patient(db_session)
    await _crear_contribution(db_session, patient, "2032-03")

    resp = await client.get("/contributions/vouchers/export.pdf", params={"periodo": "2032-03"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_export_vouchers_pdf_imagen_no_decodificable_no_rompe_el_reporte(client, superuser_token, db_session, monkeypatch):
    """Si la descarga 'funciona' pero el contenido no es una imagen válida, el reporte igual se genera (con texto de reemplazo)."""
    _patch_external_get(monkeypatch, client, _FakeHttpResponse(b"bytes-invalidos", "image/jpeg"))

    patient = await _crear_patient(db_session)
    await _crear_contribution(db_session, patient, "2032-04")

    resp = await client.get("/contributions/vouchers/export.pdf", params={"periodo": "2032-04"})
    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(b"%PDF")


# ─────────────────────────────────────────────────────────────────────────
#  GET /contributions/review?periodo=... (filtro reutilizado por el reporte)
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_review_filtra_por_periodo(client, superuser_token, db_session):
    patient = await _crear_patient(db_session)
    await _crear_contribution(db_session, patient, "2032-05")
    await _crear_contribution(db_session, patient, "2032-06")

    resp = await client.get("/contributions/review", params={"periodo": "2032-05"})
    assert resp.status_code == 200, resp.text
    periodos = {item["periodo"] for item in resp.json() if item["patient_id"] == patient.id}
    assert periodos == {"2032-05"}


@pytest.mark.asyncio
async def test_review_sin_periodo_trae_todos(client, superuser_token, db_session):
    patient = await _crear_patient(db_session)
    await _crear_contribution(db_session, patient, "2032-07")
    await _crear_contribution(db_session, patient, "2032-08")

    resp = await client.get("/contributions/review")
    assert resp.status_code == 200, resp.text
    periodos = {item["periodo"] for item in resp.json() if item["patient_id"] == patient.id}
    assert periodos == {"2032-07", "2032-08"}
