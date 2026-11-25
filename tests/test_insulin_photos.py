"""Fotos de control del beneficiario (insulinas ya usadas y hemoglobina glucosilada): se suben desde el portal aunque
todavía no haya un reparto, y el SUPER_ADMIN las aprueba u observa.

Cada prueba corre dentro de una transacción que se revierte (los `commit` se vuelven `flush`).
"""
import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app import models
from app.api import deps
from app.api.endpoints import insulin_photos as photos_module
from app.api.endpoints import patients as patients_module
from app.main import app

JPG = {"foto": ("plumas.jpg", b"\xff\xd8\xff jpeg", "image/jpeg")}
PDF = {"foto": ("hba1c.pdf", b"%PDF-1.4", "application/pdf")}


@pytest_asyncio.fixture
async def sesion(client, superuser_token, db_session):
    db_session.commit = db_session.flush
    yield db_session
    await db_session.rollback()


@pytest.fixture
def storage(monkeypatch):
    """Firebase en memoria: lo que se subió y lo que se borró."""
    registro = {"subidas": [], "borradas": []}

    def subir(content, path, content_type):
        registro["subidas"].append(path)
        return f"https://storage.test/{path}"

    monkeypatch.setattr(photos_module, "upload_file_to_firebase", subir)
    monkeypatch.setattr(photos_module, "delete_file_from_firebase_by_url", registro["borradas"].append)
    return registro


async def _beneficiario(db, nombres="Ana", ap_paterno="Pérez"):
    user = models.User(email=f"foto_{uuid.uuid4().hex[:8]}@test.com", password_hash="x", role="PACIENTE", estado="ACTIVO")
    db.add(user)
    await db.flush()
    patient = models.Patient(
        user_id=user.id, nombres=nombres, ap_paterno=ap_paterno, ci=f"CI{uuid.uuid4().hex[:6].upper()}",
        fecha_nac=date(1980, 1, 1), tipo_sangre="O+", estado="ACTIVO",
    )
    db.add(patient)
    await db.flush()
    return user, patient


def _como(user):
    """Las rutas del beneficiario responden como `user`; las del SUPER_ADMIN siguen como el administrador."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: user


@pytest.mark.asyncio
async def test_the_beneficiary_uploads_photos_even_without_a_distribution(client, sesion, storage):
    user, ana = await _beneficiario(sesion)
    _, otro = await _beneficiario(sesion, "Otro")
    assert (await client.get("/donations/insulin-photos/me")).status_code == 403  # el personal no tiene fotos

    _como(user)
    assert (await client.get("/donations/insulin-photos/me")).json() == {"foto_envases": None, "foto_hba1c": None}
    res = await client.post("/donations/insulin-photos/me/envases", files=JPG)
    assert res.status_code == 200, res.text
    primera = res.json()
    assert primera["estado"] == "PENDIENTE" and primera["subida_at"] and primera["revisada_por"] is None
    assert primera["url"].startswith(f"https://storage.test/pacientes/{ana.id}/fotos_control/insulinas_usadas_")
    assert primera["url"].endswith(".jpg")
    fila = await sesion.get(models.InsulinControlPhoto, primera["id"])
    assert fila.patient_id == ana.id and fila.notice_id is None  # todavía no tiene un reparto

    # La HbA1c puede ser el PDF del laboratorio; las insulinas usadas, solo una foto.
    assert (await client.post("/donations/insulin-photos/me/envases", files=PDF)).status_code == 400
    hba1c = await client.post("/donations/insulin-photos/me/hba1c", files=PDF)
    assert hba1c.status_code == 200 and "/hemoglobina_glucosilada_" in hba1c.json()["url"]

    # Mientras está por revisar, otra la reemplaza (misma foto, archivo nuevo) y la anterior se borra.
    otra = (await client.post("/donations/insulin-photos/me/envases", files={"foto": ("p.png", b"\x89PNG", "image/png")})).json()
    assert otra["id"] == primera["id"] and otra["url"] != primera["url"] and otra["url"].endswith(".png")
    assert storage["borradas"] == [primera["url"]]

    # Vacía, demasiado grande o de un tipo que no existe: no se sube nada.
    assert (await client.post("/donations/insulin-photos/me/envases", files={"foto": ("v.jpg", b"", "image/jpeg")})).status_code == 400
    grande = {"foto": ("g.jpg", b"\xff" * (photos_module.PHOTO_MAX_BYTES + 1), "image/jpeg")}
    assert (await client.post("/donations/insulin-photos/me/envases", files=grande)).status_code == 413
    assert (await client.post("/donations/insulin-photos/me/receta", files=JPG)).status_code == 422
    assert len(storage["subidas"]) == 3

    mias = (await client.get("/donations/insulin-photos/me")).json()
    assert (mias["foto_envases"]["url"], mias["foto_hba1c"]["url"]) == (otra["url"], hba1c.json()["url"])

    # Cada uno ve solo las suyas.
    _como(await sesion.get(models.User, otro.user_id))
    assert (await client.get("/donations/insulin-photos/me")).json() == {"foto_envases": None, "foto_hba1c": None}

    # Si se borra al beneficiario, sus fotos se borran con sus demás documentos.
    urls = await patients_module._collect_patient_document_urls(sesion, ana)
    assert {otra["url"], hba1c.json()["url"]} <= set(urls)


@pytest.mark.asyncio
async def test_with_a_distribution_notice_the_photo_remembers_it(client, sesion, storage):
    user, ana = await _beneficiario(sesion)
    reparto = models.InsulinDistribution(estado="CONSOLIDADO", dias=60, resultado={}, propuesta=[], stock_calculado={})
    sesion.add(reparto)
    await sesion.flush()
    aviso = models.InsulinDistributionNotice(distribution_id=reparto.id, patient_id=ana.id)
    sesion.add(aviso)
    await sesion.flush()

    _como(user)
    foto = (await client.post("/donations/insulin-photos/me/hba1c", files=JPG)).json()
    assert (await sesion.get(models.InsulinControlPhoto, foto["id"])).notice_id == aviso.id


@pytest.mark.asyncio
async def test_the_super_admin_approves_or_observes_and_an_approved_photo_stays(client, sesion, storage):
    user, ana = await _beneficiario(sesion)
    _como(user)
    primera = (await client.post("/donations/insulin-photos/me/envases", files=JPG)).json()
    revision = lambda foto_id: f"/donations/insulin-photos/{foto_id}/revision"  # noqa: E731

    assert (await client.post(revision(999999999), json={"estado": "APROBADA"})).status_code == 404
    apr = await client.post(revision(primera["id"]), json={"estado": "APROBADA", "observacion": "se ignora"})
    assert apr.status_code == 200, apr.text
    assert apr.json()["estado"] == "APROBADA" and apr.json()["observacion"] is None and apr.json()["revisada_por"]

    # Aprobada, queda en el historial: la próxima (para la siguiente entrega) es otra foto.
    segunda = (await client.post("/donations/insulin-photos/me/envases", files=JPG)).json()
    assert segunda["id"] != primera["id"] and segunda["estado"] == "PENDIENTE"
    assert storage["borradas"] == []
    assert (await sesion.get(models.InsulinControlPhoto, primera["id"])).estado == "APROBADA"
    assert (await client.get("/donations/insulin-photos/me")).json()["foto_envases"]["id"] == segunda["id"]

    # Observar exige decir qué corregir; el beneficiario ve el motivo (no quién la revisó).
    sin_motivo = await client.post(revision(segunda["id"]), json={"estado": "OBSERVADA", "observacion": "  "})
    assert sin_motivo.status_code == 422
    obs = await client.post(revision(segunda["id"]), json={"estado": "OBSERVADA", "observacion": "  Está borrosa  "})
    assert obs.status_code == 200 and obs.json()["observacion"] == "Está borrosa"
    mia = (await client.get("/donations/insulin-photos/me")).json()["foto_envases"]
    assert (mia["estado"], mia["observacion"], mia["revisada_por"]) == ("OBSERVADA", "Está borrosa", None)

    # La observada se reemplaza y vuelve a quedar por revisar.
    tercera = (await client.post("/donations/insulin-photos/me/envases", files=JPG)).json()
    assert tercera["id"] == segunda["id"] and tercera["estado"] == "PENDIENTE"
    assert tercera["observacion"] is None and tercera["revisada_at"] is None
    assert storage["borradas"] == [segunda["url"]]

    revisiones = (
        await sesion.execute(
            select(models.AuditLog.payload).where(
                models.AuditLog.accion == "REVIEW_INSULIN_CONTROL_PHOTO", models.AuditLog.entidad_id.in_([primera["id"], segunda["id"]])
            ).order_by(models.AuditLog.id)
        )
    ).scalars().all()
    assert [(r["patient_id"], r["estado"]) for r in revisiones] == [(ana.id, "APROBADA"), (ana.id, "OBSERVADA")]


@pytest.mark.asyncio
async def test_the_super_admin_lists_the_photos_to_review(client, sesion):
    _, jose = await _beneficiario(sesion, "José", "Mamani")
    _, rosa = await _beneficiario(sesion, "Rosa", "Quispe")
    momento = lambda dia: datetime(2026, 11, dia, 10, tzinfo=timezone.utc)  # noqa: E731
    sesion.add_all([
        models.InsulinControlPhoto(patient_id=rosa.id, tipo="hba1c", url="u1", subida_at=momento(3)),
        models.InsulinControlPhoto(patient_id=jose.id, tipo="envases", url="u2", subida_at=momento(1)),
        models.InsulinControlPhoto(patient_id=jose.id, tipo="hba1c", url="u3", subida_at=momento(2), estado="APROBADA"),
        models.InsulinControlPhoto(patient_id=rosa.id, tipo="envases", url="u4", subida_at=momento(4), estado="OBSERVADA",
                                   observacion="borrosa"),
    ])
    await sesion.flush()
    nuestras = {jose.id, rosa.id}

    async def lista(**params):
        res = await client.get("/donations/insulin-photos", params=params)
        assert res.status_code == 200, res.text
        return [(f["url"], f["nombre_completo"]) for f in res.json() if f["beneficiario_id"] in nuestras]

    # Por revisar: de la más antigua a la más nueva, con de quién es.
    assert await lista(estado="PENDIENTE") == [("u2", "José Mamani"), ("u1", "Rosa Quispe")]
    assert await lista(estado="OBSERVADA") == [("u4", "Rosa Quispe")]
    # Todas: de la más nueva a la más antigua.
    assert [u for u, _ in await lista()] == ["u4", "u1", "u3", "u2"]
    # Por nombre sin tildes ni mayúsculas, o por C.I.
    assert [u for u, _ in await lista(q="jose mamani")] == ["u3", "u2"]
    assert [u for u, _ in await lista(q=rosa.ci.lower())] == ["u4", "u1"]


@pytest.mark.asyncio
async def test_only_the_super_admin_reviews_photos(client, patient_token):
    for method, url, kwargs in (
        ("get", "/donations/insulin-photos", {}),
        ("post", "/donations/insulin-photos/1/revision", {"json": {"estado": "APROBADA"}}),
    ):
        res = await getattr(client, method)(url, **kwargs)
        assert res.status_code in (401, 403), (url, res.status_code)
