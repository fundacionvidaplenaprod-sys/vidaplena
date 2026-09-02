"""
tests/test_departmental_roles.py
===================================
RESPONSABLE_DEPARTAMENTAL: visibilidad y acciones acotadas estrictamente a su
propio departamento (users.depto_asignado). COORDINADOR_NACIONAL: misma
visibilidad a nivel nacional, pero estrictamente de solo lectura (no puede
registrar entregas de insulina). El registro de entregas es solo un log de
control — no afecta stock de almacén.
"""
import uuid
from datetime import date

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


async def _crear_patient(db_session, estado: str = "ACTIVO", depto: str = "La Paz", **extra) -> models.Patient:
    suffix = uuid.uuid4().hex[:8]
    user = models.User(
        email=f"depto_test_{suffix}@test.com",
        password_hash="fakehash",
        role="PACIENTE",
        estado="ACTIVO",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    patient = models.Patient(
        user_id=user.id,
        nombres=f"Depto{suffix}",
        ap_paterno="Test",
        ci=f"CI-{suffix}",
        fecha_nac=date(1990, 1, 1),
        depto=depto,
        estado=estado,
        **extra,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


async def _crear_contribution(db_session, patient, periodo, estado="ACEPTADO"):
    contrib = models.MonthlyContribution(
        patient_id=patient.id,
        periodo=periodo,
        fecha_pago=date.today(),
        monto=100.0,
        url_comprobante="https://fake-storage.test/voucher.jpg",
        estado=estado,
    )
    db_session.add(contrib)
    await db_session.commit()
    return contrib


def _current_periodo():
    today = date.today()
    return f"{today.year}-{today.month:02d}"


# ─────────────────────────────────────────────────────────────────────────
#  CREACIÓN DE USUARIOS
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_responsable_departamental_requiere_depto_valido(client, superuser_token):
    resp = await client.post("/users/", json={
        "email": f"resp_{uuid.uuid4().hex[:8]}@test.com",
        "password": "Segura123",
        "role": "RESPONSABLE_DEPARTAMENTAL",
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_crear_responsable_departamental_con_depto_invalido(client, superuser_token):
    resp = await client.post("/users/", json={
        "email": f"resp_{uuid.uuid4().hex[:8]}@test.com",
        "password": "Segura123",
        "role": "RESPONSABLE_DEPARTAMENTAL",
        "depto_asignado": "Narnia",
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_crear_responsable_departamental_exitoso(client, superuser_token):
    resp = await client.post("/users/", json={
        "email": f"resp_{uuid.uuid4().hex[:8]}@test.com",
        "password": "Segura123",
        "role": "RESPONSABLE_DEPARTAMENTAL",
        "depto_asignado": "La Paz",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["depto_asignado"] == "La Paz"


@pytest.mark.asyncio
async def test_crear_coordinador_nacional_no_exige_depto(client, superuser_token):
    resp = await client.post("/users/", json={
        "email": f"coord_{uuid.uuid4().hex[:8]}@test.com",
        "password": "Segura123",
        "role": "COORDINADOR_NACIONAL",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["depto_asignado"] is None


@pytest.mark.asyncio
async def test_cambiar_rol_fuera_de_responsable_limpia_depto(client, superuser_token, db_session):
    create_resp = await client.post("/users/", json={
        "email": f"resp_{uuid.uuid4().hex[:8]}@test.com",
        "password": "Segura123",
        "role": "RESPONSABLE_DEPARTAMENTAL",
        "depto_asignado": "Oruro",
    })
    user_id = create_resp.json()["id"]

    update_resp = await client.put(f"/users/{user_id}", json={"role": "REGISTRADOR"})
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["depto_asignado"] is None


# ─────────────────────────────────────────────────────────────────────────
#  BENEFICIARIOS ACTIVOS: SCOPING POR DEPARTAMENTO
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_responsable_solo_ve_su_departamento(client, db_session):
    periodo = _current_periodo()
    la_paz = await _crear_patient(db_session, depto="La Paz")
    cocha = await _crear_patient(db_session, depto="Cochabamba")
    await _crear_contribution(db_session, la_paz, periodo)
    await _crear_contribution(db_session, cocha, periodo)

    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    # limit alto: la BD de desarrollo trae miles de pacientes ACTIVO de
    # ejecuciones previas de la suite — no es un bug del endpoint.
    resp = await client.get("/departmental/beneficiarios/activos", params={"limit": 5000})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert la_paz.id in ids
    assert cocha.id not in ids


@pytest.mark.asyncio
async def test_responsable_no_puede_forzar_otro_depto_por_query_param(client, db_session):
    cocha = await _crear_patient(db_session, depto="Cochabamba")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    resp = await client.get("/departmental/beneficiarios/activos", params={"depto": "Cochabamba", "limit": 5000})
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert cocha.id not in ids


@pytest.mark.asyncio
async def test_coordinador_nacional_ve_todos_los_departamentos(client, db_session):
    la_paz = await _crear_patient(db_session, depto="La Paz")
    cocha = await _crear_patient(db_session, depto="Cochabamba")
    await _switch_identity(db_session, "COORDINADOR_NACIONAL")

    # limit alto: la BD de desarrollo ya trae miles de pacientes ACTIVO de
    # ejecuciones previas de la suite, así que la paginación por defecto no
    # alcanza a estos dos — no es un bug del endpoint, es volumen de datos.
    resp = await client.get("/departmental/beneficiarios/activos", params={"limit": 5000})
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert la_paz.id in ids
    assert cocha.id in ids


@pytest.mark.asyncio
async def test_coordinador_nacional_puede_filtrar_por_depto(client, db_session):
    la_paz = await _crear_patient(db_session, depto="La Paz")
    cocha = await _crear_patient(db_session, depto="Cochabamba")
    await _switch_identity(db_session, "COORDINADOR_NACIONAL")

    resp = await client.get("/departmental/beneficiarios/activos", params={"depto": "La Paz", "limit": 5000})
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert la_paz.id in ids
    assert cocha.id not in ids


@pytest.mark.asyncio
async def test_paciente_no_puede_acceder_al_modulo_departamental(client, patient_token):
    resp = await client.get("/departmental/beneficiarios/activos")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_pacientes_no_activos_no_aparecen_en_activos(client, db_session):
    pendiente = await _crear_patient(db_session, depto="La Paz", estado="PENDIENTE_DOC")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    resp = await client.get("/departmental/beneficiarios/activos")
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert pendiente.id not in ids


@pytest.mark.asyncio
async def test_al_dia_aporte_refleja_contribucion_aceptada(client, db_session):
    periodo = _current_periodo()
    al_dia = await _crear_patient(db_session, depto="La Paz")
    await _crear_contribution(db_session, al_dia, periodo, estado="ACEPTADO")

    sin_aporte = await _crear_patient(db_session, depto="La Paz")

    exonerado = await _crear_patient(db_session, depto="La Paz", exonerado_aporte=True)

    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")
    resp = await client.get("/departmental/beneficiarios/activos", params={"limit": 5000})
    assert resp.status_code == 200, resp.text
    by_id = {item["id"]: item for item in resp.json()["items"]}

    assert by_id[al_dia.id]["al_dia_aporte"] is True
    assert by_id[sin_aporte.id]["al_dia_aporte"] is False
    assert by_id[exonerado.id]["al_dia_aporte"] is True


# ─────────────────────────────────────────────────────────────────────────
#  DOCUMENTOS PENDIENTES: SCOPING POR DEPARTAMENTO
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pendientes_docs_scoping_por_departamento(client, db_session):
    la_paz = await _crear_patient(db_session, depto="La Paz", estado="PENDIENTE_DOC")
    cocha = await _crear_patient(db_session, depto="Cochabamba", estado="PENDIENTE_DOC")
    activo = await _crear_patient(db_session, depto="La Paz", estado="ACTIVO")

    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")
    resp = await client.get("/departmental/beneficiarios/pendientes-docs", params={"limit": 5000})
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert la_paz.id in ids
    assert cocha.id not in ids
    assert activo.id not in ids


# ─────────────────────────────────────────────────────────────────────────
#  REGISTRO DE ENTREGAS DE INSULINA
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_responsable_registra_entrega_en_su_departamento(client, db_session):
    patient = await _crear_patient(db_session, depto="La Paz")
    actor = await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "delivery_date": str(date.today()),
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "2 frascos"}],
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["patient_id"] == patient.id
    assert body[0]["depto"] == "La Paz"
    assert body[0]["recorded_by_email"] == actor.email


@pytest.mark.asyncio
async def test_responsable_registra_entrega_con_varios_tipos_de_insulina(client, db_session):
    """Un beneficiario puede necesitar más de un tipo de insulina en la misma visita."""
    patient = await _crear_patient(db_session, depto="La Paz")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [
            {"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "2 frascos"},
            {"presentacion": "Pen 3ml", "insulin_type": "Lispro", "quantity": "1 pluma"},
        ],
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body) == 2
    tipos = {item["insulin_type"] for item in body}
    assert tipos == {"Glargina", "Lispro"}
    assert all(item["patient_id"] == patient.id for item in body)
    presentaciones = {item["insulin_type"]: item["presentacion"] for item in body}
    assert presentaciones["Glargina"] == "Frasco 10ml"
    assert presentaciones["Lispro"] == "Pen 3ml"
    # Cada tipo queda como su propia fila en el historial.
    ids = {item["id"] for item in body}
    assert len(ids) == 2


@pytest.mark.asyncio
async def test_registrar_entrega_rechaza_presentacion_invalida(client, db_session):
    patient = await _crear_patient(db_session, depto="La Paz")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [{"presentacion": "Ampolla 1ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_registrar_entrega_rechaza_tipo_de_insulina_repetido(client, db_session):
    patient = await _crear_patient(db_session, depto="La Paz")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [
            {"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"},
            {"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco más"},
        ],
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_responsable_no_puede_registrar_entrega_fuera_de_su_departamento(client, db_session):
    otro_depto = await _crear_patient(db_session, depto="Cochabamba")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": otro_depto.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_no_se_puede_registrar_entrega_a_paciente_no_activo(client, db_session):
    pendiente = await _crear_patient(db_session, depto="La Paz", estado="PENDIENTE_DOC")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": pendiente.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_coordinador_nacional_no_puede_registrar_entrega(client, db_session):
    """El núcleo de la restricción 'solo lectura' del Coordinador Nacional."""
    patient = await _crear_patient(db_session, depto="La Paz")
    await _switch_identity(db_session, "COORDINADOR_NACIONAL")

    resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_puede_registrar_entrega_en_cualquier_departamento(client, superuser_token, db_session):
    patient = await _crear_patient(db_session, depto="Pando")
    resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Lispro", "quantity": "3 frascos"}],
    })
    assert resp.status_code == 201, resp.text


# ─────────────────────────────────────────────────────────────────────────
#  HISTORIAL DE ENTREGAS: LECTURA
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_historial_entregas_scoping_por_departamento(client, db_session):
    la_paz = await _crear_patient(db_session, depto="La Paz")
    cocha = await _crear_patient(db_session, depto="Cochabamba")

    await _switch_identity(db_session, "SUPER_ADMIN")
    await client.post("/departmental/entregas-insulina", json={
        "patient_id": la_paz.id, "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })
    await client.post("/departmental/entregas-insulina", json={
        "patient_id": cocha.id, "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })

    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")
    resp = await client.get("/departmental/entregas-insulina", params={"limit": 5000})
    assert resp.status_code == 200, resp.text
    patient_ids = {item["patient_id"] for item in resp.json()["items"]}
    assert la_paz.id in patient_ids
    assert cocha.id not in patient_ids


@pytest.mark.asyncio
async def test_coordinador_nacional_lee_historial_de_todos_los_departamentos(client, db_session):
    la_paz = await _crear_patient(db_session, depto="La Paz")
    cocha = await _crear_patient(db_session, depto="Cochabamba")

    await _switch_identity(db_session, "SUPER_ADMIN")
    await client.post("/departmental/entregas-insulina", json={
        "patient_id": la_paz.id, "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })
    await client.post("/departmental/entregas-insulina", json={
        "patient_id": cocha.id, "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })

    await _switch_identity(db_session, "COORDINADOR_NACIONAL")
    resp = await client.get("/departmental/entregas-insulina", params={"limit": 5000})
    assert resp.status_code == 200, resp.text
    patient_ids = {item["patient_id"] for item in resp.json()["items"]}
    assert la_paz.id in patient_ids
    assert cocha.id in patient_ids
