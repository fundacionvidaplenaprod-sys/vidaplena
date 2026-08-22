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


@pytest.mark.asyncio
async def test_paginated_patients_no_registrado_es_estado_real(client, db_session, superuser_token):
    """
    NO_REGISTRADO es un valor real de `patients.estado` (columna con FK a
    patient_states), no algo derivado en tiempo de lectura: se filtra igual
    que cualquier otro estado.
    """
    no_registrado = await _crear_patient_con_estado(db_session, "NO_REGISTRADO")
    pendiente = await _crear_patient_con_estado(db_session, "PENDIENTE_DOC")

    resp = await client.get("/patients/paginated", params={"estado": "NO_REGISTRADO", "limit": 200})
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert no_registrado.id in ids
    assert pendiente.id not in ids


@pytest.mark.asyncio
async def test_create_patient_sin_ci_ni_direccion_queda_no_registrado(client, db_session, superuser_token):
    """
    POST /patients/ sin CI ni dirección (solo nombres/apellidos/depto, como
    cuando el registrador precarga desde el padrón) arranca en NO_REGISTRADO.
    """
    resp = await client.post(
        "/patients/",
        json={"nombres": "SinDatos", "ap_paterno": "Prueba", "fecha_nac": "1990-01-01", "depto": "Cochabamba"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["estado"] == "NO_REGISTRADO"


@pytest.mark.asyncio
async def test_create_patient_con_ci_queda_pendiente_doc(client, db_session, superuser_token):
    """POST /patients/ con CI (o dirección) ya cargado arranca en PENDIENTE_DOC, como antes."""
    resp = await client.post(
        "/patients/",
        json={
            "nombres": "ConCI", "ap_paterno": "Prueba", "fecha_nac": "1990-01-01",
            "ci": f"CI-{uuid.uuid4().hex[:8]}",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["estado"] == "PENDIENTE_DOC"


@pytest.mark.asyncio
async def test_update_patient_no_registrado_pasa_a_pendiente_doc_al_cargar_ci(client, db_session, superuser_token):
    """Editar un NO_REGISTRADO y cargarle CI lo promueve automáticamente a PENDIENTE_DOC."""
    patient = await _crear_patient_con_estado(db_session, "NO_REGISTRADO")
    patient.ci = None
    await db_session.commit()

    resp = await client.put(f"/patients/{patient.id}", json={"ci": f"CI-{uuid.uuid4().hex[:8]}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["estado"] == "PENDIENTE_DOC"


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
