"""
Paginación y separación por grupo en GET /users/.

La pantalla de Gestión de Usuarios mezclaba al personal de la fundación con
las cuentas de beneficiarios (que son la amplia mayoría), obligando a
recorrer toda la lista para encontrar a un responsable departamental. El
endpoint ahora devuelve {total, items} y admite `grupo` / `role`.

Las aserciones se escriben sobre propiedades invariantes (forma de la
respuesta, tamaño de página, coherencia del filtro) y no sobre totales
exactos, porque la suite corre contra una base compartida que ya trae datos
de otros tests y de la réplica de producción.
"""
import uuid

import pytest
from sqlalchemy import select

from app import models


async def _seed_user(db_session, role, depto_asignado=None):
    user = models.User(
        email=f"pag_{uuid.uuid4().hex[:8]}@test.com",
        password_hash="fakehash",
        role=role,
        estado="ACTIVO",
        depto_asignado=depto_asignado,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_list_users_returns_paginated_shape(client, superuser_token):
    res = await client.get("/users/", params={"skip": 0, "limit": 5})
    assert res.status_code == 200, res.text

    data = res.json()
    assert "total" in data and "items" in data
    assert isinstance(data["items"], list)
    assert len(data["items"]) <= 5
    assert data["total"] >= len(data["items"])


@pytest.mark.asyncio
async def test_limit_caps_page_size_and_skip_advances(client, superuser_token):
    primera = (await client.get("/users/", params={"skip": 0, "limit": 2})).json()
    segunda = (await client.get("/users/", params={"skip": 2, "limit": 2})).json()

    assert len(primera["items"]) <= 2
    assert len(segunda["items"]) <= 2
    # El orden es estable (por id), así que las páginas no deben solaparse.
    ids_primera = {u["id"] for u in primera["items"]}
    ids_segunda = {u["id"] for u in segunda["items"]}
    assert ids_primera.isdisjoint(ids_segunda)


@pytest.mark.asyncio
async def test_grupo_personal_excludes_pacientes(client, superuser_token, db_session):
    await _seed_user(db_session, "PACIENTE")
    await _seed_user(db_session, "REGISTRADOR")

    res = await client.get("/users/", params={"grupo": "PERSONAL", "limit": 100})
    assert res.status_code == 200, res.text
    roles = {u["role"] for u in res.json()["items"]}
    assert "PACIENTE" not in roles


@pytest.mark.asyncio
async def test_grupo_beneficiarios_returns_only_pacientes(client, superuser_token, db_session):
    await _seed_user(db_session, "PACIENTE")

    res = await client.get("/users/", params={"grupo": "BENEFICIARIOS", "limit": 100})
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert items, "Debe haber al menos la cuenta de paciente recién creada"
    assert all(u["role"] == "PACIENTE" for u in items)


@pytest.mark.asyncio
async def test_role_filter_takes_precedence_over_grupo(client, superuser_token, db_session):
    await _seed_user(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    # `grupo=BENEFICIARIOS` pediría solo PACIENTE, pero `role` manda.
    res = await client.get(
        "/users/",
        params={"role": "RESPONSABLE_DEPARTAMENTAL", "grupo": "BENEFICIARIOS", "limit": 100},
    )
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert items
    assert all(u["role"] == "RESPONSABLE_DEPARTAMENTAL" for u in items)


@pytest.mark.asyncio
async def test_search_is_resolved_server_side(client, superuser_token, db_session):
    user = await _seed_user(db_session, "REGISTRADOR")

    res = await client.get("/users/", params={"search": user.email})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["email"] == user.email


@pytest.mark.asyncio
async def test_search_combines_with_grupo(client, superuser_token, db_session):
    paciente = await _seed_user(db_session, "PACIENTE")

    # El mismo correo, pero pedido dentro del grupo equivocado, no aparece.
    res = await client.get("/users/", params={"search": paciente.email, "grupo": "PERSONAL"})
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_users_requires_super_admin(client, db_session):
    res = await client.get("/users/")
    assert res.status_code == 401
