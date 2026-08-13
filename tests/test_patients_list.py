"""
tests/test_patients_list.py
=============================
Pruebas del listado paginado de beneficiarios (`GET /patients/paginated`),
en particular el filtro opcional por `estado`.
"""
import uuid
from datetime import date

import pytest

from app import models


async def _crear_patient_con_estado(db_session, estado: str) -> models.Patient:
    suffix = uuid.uuid4().hex[:8]
    user = models.User(
        email=f"lista_{suffix}@test.com",
        password_hash="fakehash",
        role="PACIENTE",
        estado="ACTIVO",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    patient = models.Patient(
        user_id=user.id,
        nombres=f"Lista{suffix}",
        ap_paterno="Prueba",
        ci=f"CI-{suffix}",
        fecha_nac=date(1990, 1, 1),
        estado=estado,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


@pytest.mark.asyncio
async def test_paginated_patients_filtra_por_estado(client, db_session, superuser_token):
    """?estado=ACTIVO solo retorna pacientes en ese estado."""
    activo = await _crear_patient_con_estado(db_session, "ACTIVO")
    pendiente = await _crear_patient_con_estado(db_session, "PENDIENTE_DOC")

    resp = await client.get("/patients/paginated", params={"estado": "ACTIVO", "limit": 200})
    assert resp.status_code == 200
    data = resp.json()
    ids = {item["id"] for item in data["items"]}
    assert activo.id in ids
    assert pendiente.id not in ids
    assert all(item["estado"] == "ACTIVO" for item in data["items"])


@pytest.mark.asyncio
async def test_paginated_patients_sin_filtro_incluye_todos_los_estados(client, db_session, superuser_token):
    """Sin `estado`, el listado no filtra por estado (comportamiento previo intacto)."""
    activo = await _crear_patient_con_estado(db_session, "ACTIVO")
    pendiente = await _crear_patient_con_estado(db_session, "PENDIENTE_DOC")

    resp = await client.get("/patients/paginated", params={"limit": 200})
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert activo.id in ids
    assert pendiente.id in ids


@pytest.mark.asyncio
async def test_paginated_patients_combina_estado_y_busqueda(client, db_session, superuser_token):
    """`search` y `estado` se aplican juntos (AND), no solo uno de los dos."""
    patient = await _crear_patient_con_estado(db_session, "HABILITADO")

    resp_match = await client.get(
        "/patients/paginated",
        params={"search": patient.nombres, "estado": "HABILITADO", "limit": 200},
    )
    assert resp_match.status_code == 200
    assert any(item["id"] == patient.id for item in resp_match.json()["items"])

    resp_no_match = await client.get(
        "/patients/paginated",
        params={"search": patient.nombres, "estado": "ACTIVO", "limit": 200},
    )
    assert resp_no_match.status_code == 200
    assert all(item["id"] != patient.id for item in resp_no_match.json()["items"])


# ─────────────────────────────────────────────────────────────────────────────
#  Regresión: estos endpoints de datos de pacientes (lectura y escritura)
#  no exigían ningún login. Se restringieron a personal autorizado
#  (SUPER_ADMIN/REGISTRADOR/EVALUADOR_SOCIAL vía get_current_staff_user).
#  No se prueba cada uno de los 16 endpoints corregidos individualmente
#  porque comparten exactamente el mismo patrón de dependencia — esta es
#  una muestra representativa de lectura, listado, creación y escritura.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_patients_requires_auth(client, db_session):
    resp = await client.get("/patients/")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_paginated_patients_requires_auth(client, db_session):
    resp = await client.get("/patients/paginated")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_patient_requires_auth(client, db_session):
    patient = await _crear_patient_con_estado(db_session, "ACTIVO")
    resp = await client.get(f"/patients/{patient.id}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_patient_requires_auth(client, db_session):
    resp = await client.post("/patients/", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_add_patient_treatment_requires_auth(client, db_session):
    patient = await _crear_patient_con_estado(db_session, "ACTIVO")
    resp = await client.post(f"/patients/{patient.id}/treatments", json={})
    assert resp.status_code == 401
