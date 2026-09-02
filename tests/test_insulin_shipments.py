"""
tests/test_insulin_shipments.py
================================
Etapa 1 del flujo de insulina: COORDINADOR_NACIONAL -> RESPONSABLE_DEPARTAMENTAL
(insulin_shipments). Solo el coordinador nacional (o SUPER_ADMIN) puede
originar un envío; el responsable destinatario solo ve en su historial lo
que le enviaron a él, nunca lo de otros responsables. Es solo un log de
control — no afecta stock de almacén. Un envío puede incluir más de un
tipo de insulina (`items`), igual que la entrega departamental.
"""
import uuid
from datetime import date, timedelta

import pytest

from app import models
from app.main import app
from app.api import deps


async def _switch_identity(db_session, role: str, depto_asignado: str | None = None) -> models.User:
    """Crea un usuario con el rol (y depto) dados y hace que `client` autentique como él."""
    user = models.User(
        email=f"{role.lower()}_{uuid.uuid4().hex[:8]}@test.com",
        password_hash="fakehash",
        role=role,
        depto_asignado=depto_asignado,
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


async def _crear_responsable(db_session, depto: str = "La Paz") -> models.User:
    suffix = uuid.uuid4().hex[:8]
    user = models.User(
        email=f"resp_{suffix}@test.com",
        password_hash="fakehash",
        role="RESPONSABLE_DEPARTAMENTAL",
        depto_asignado=depto,
        estado="ACTIVO",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ─────────────────────────────────────────────────────────────────────────
#  REGISTRO DE ENVÍOS: SOLO COORDINADOR NACIONAL / SUPER_ADMIN
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_coordinador_nacional_registra_envio(client, db_session):
    responsable = await _crear_responsable(db_session, depto="La Paz")
    actor = await _switch_identity(db_session, "COORDINADOR_NACIONAL")

    fecha_pasada = str(date.today() - timedelta(days=5))
    resp = await client.post("/departmental/envios-insulina", json={
        "recipient_user_id": responsable.id,
        "shipment_date": fecha_pasada,
        "items": [{"insulin_type": "Glargina", "presentacion": "Cartucho 3ml", "quantity": "20 frascos"}],
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["recipient_user_id"] == responsable.id
    assert body[0]["depto"] == "La Paz"
    assert body[0]["presentacion"] == "Cartucho 3ml"
    assert body[0]["shipment_date"] == fecha_pasada
    assert body[0]["recorded_by_email"] == actor.email


@pytest.mark.asyncio
async def test_coordinador_nacional_registra_envio_con_varios_tipos_de_insulina(client, db_session):
    """Un responsable puede necesitar recibir más de un tipo de insulina en el mismo envío."""
    responsable = await _crear_responsable(db_session, depto="La Paz")
    await _switch_identity(db_session, "COORDINADOR_NACIONAL")

    resp = await client.post("/departmental/envios-insulina", json={
        "recipient_user_id": responsable.id,
        "items": [
            {"insulin_type": "Glargina", "presentacion": "Frasco 10ml", "quantity": "20 frascos"},
            {"insulin_type": "Lispro", "presentacion": "Pen 3ml", "quantity": "5 plumas"},
        ],
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body) == 2
    tipos = {item["insulin_type"] for item in body}
    assert tipos == {"Glargina", "Lispro"}
    assert all(item["recipient_user_id"] == responsable.id for item in body)
    presentaciones = {item["insulin_type"]: item["presentacion"] for item in body}
    assert presentaciones["Glargina"] == "Frasco 10ml"
    assert presentaciones["Lispro"] == "Pen 3ml"


@pytest.mark.asyncio
async def test_envio_rechaza_tipo_de_insulina_repetido(client, db_session):
    responsable = await _crear_responsable(db_session, depto="La Paz")
    await _switch_identity(db_session, "COORDINADOR_NACIONAL")

    resp = await client.post("/departmental/envios-insulina", json={
        "recipient_user_id": responsable.id,
        "items": [
            {"insulin_type": "Glargina", "presentacion": "Frasco 10ml", "quantity": "1 frasco"},
            {"insulin_type": "Glargina", "presentacion": "Cartucho 3ml", "quantity": "1 frasco más"},
        ],
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_envio_rechaza_presentacion_invalida(client, db_session):
    responsable = await _crear_responsable(db_session, depto="La Paz")
    await _switch_identity(db_session, "COORDINADOR_NACIONAL")

    resp = await client.post("/departmental/envios-insulina", json={
        "recipient_user_id": responsable.id,
        "items": [{"insulin_type": "Glargina", "presentacion": "Ampolla 5ml", "quantity": "20 frascos"}],
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_envio_sin_fecha_usa_hoy(client, db_session):
    responsable = await _crear_responsable(db_session)
    await _switch_identity(db_session, "COORDINADOR_NACIONAL")

    resp = await client.post("/departmental/envios-insulina", json={
        "recipient_user_id": responsable.id,
        "items": [{"insulin_type": "Glargina", "presentacion": "Frasco 10ml", "quantity": "5 frascos"}],
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()[0]["shipment_date"] == str(date.today())


@pytest.mark.asyncio
async def test_responsable_departamental_no_puede_registrar_envio(client, db_session):
    responsable = await _crear_responsable(db_session)
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    resp = await client.post("/departmental/envios-insulina", json={
        "recipient_user_id": responsable.id,
        "items": [{"insulin_type": "Glargina", "presentacion": "Frasco 10ml", "quantity": "5 frascos"}],
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_destinatario_debe_ser_responsable_departamental(client, db_session):
    otro_coordinador = await _switch_identity(db_session, "COORDINADOR_NACIONAL")
    await _switch_identity(db_session, "COORDINADOR_NACIONAL")

    resp = await client.post("/departmental/envios-insulina", json={
        "recipient_user_id": otro_coordinador.id,
        "items": [{"insulin_type": "Glargina", "presentacion": "Frasco 10ml", "quantity": "5 frascos"}],
    })
    assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────
#  HISTORIAL: SCOPING POR DESTINATARIO
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_responsable_solo_ve_sus_propios_envios(client, db_session):
    resp_lp = await _crear_responsable(db_session, depto="La Paz")
    resp_cocha = await _crear_responsable(db_session, depto="Cochabamba")

    coordinador = await _switch_identity(db_session, "COORDINADOR_NACIONAL")
    for recipient in (resp_lp, resp_cocha):
        r = await client.post("/departmental/envios-insulina", json={
            "recipient_user_id": recipient.id,
            "items": [{"insulin_type": "Glargina", "presentacion": "Frasco 10ml", "quantity": "1 frasco"}],
        })
        assert r.status_code == 201, r.text

    # El filtro de "solo lectura de lo propio" se basa en el usuario
    # autenticado: forzamos que el actor actual SEA resp_lp.
    async def _as_resp_lp():
        return resp_lp
    app.dependency_overrides[deps.get_current_active_user] = _as_resp_lp
    app.dependency_overrides[deps.get_current_user] = _as_resp_lp

    resp = await client.get("/departmental/envios-insulina", params={"limit": 5000})
    assert resp.status_code == 200, resp.text
    recipient_ids = {item["recipient_user_id"] for item in resp.json()["items"]}
    assert resp_lp.id in recipient_ids
    assert resp_cocha.id not in recipient_ids


@pytest.mark.asyncio
async def test_coordinador_nacional_ve_todos_los_envios(client, db_session):
    resp_lp = await _crear_responsable(db_session, depto="La Paz")
    resp_cocha = await _crear_responsable(db_session, depto="Cochabamba")
    await _switch_identity(db_session, "COORDINADOR_NACIONAL")

    for recipient in (resp_lp, resp_cocha):
        r = await client.post("/departmental/envios-insulina", json={
            "recipient_user_id": recipient.id,
            "items": [{"insulin_type": "Glargina", "presentacion": "Frasco 10ml", "quantity": "1 frasco"}],
        })
        assert r.status_code == 201, r.text

    resp = await client.get("/departmental/envios-insulina", params={"limit": 5000})
    assert resp.status_code == 200, resp.text
    recipient_ids = {item["recipient_user_id"] for item in resp.json()["items"]}
    assert resp_lp.id in recipient_ids
    assert resp_cocha.id in recipient_ids


@pytest.mark.asyncio
async def test_listar_responsables_requiere_permiso_de_envio(client, db_session):
    await _crear_responsable(db_session, depto="La Paz")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="Cochabamba")

    resp = await client.get("/departmental/responsables")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_coordinador_nacional_lista_responsables(client, db_session):
    responsable = await _crear_responsable(db_session, depto="Santa Cruz")
    await _switch_identity(db_session, "COORDINADOR_NACIONAL")

    resp = await client.get("/departmental/responsables")
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()}
    assert responsable.id in ids
