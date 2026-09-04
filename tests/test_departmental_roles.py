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

    extra.setdefault("ci", f"CI-{suffix}")
    extra.setdefault("nombres", f"Depto{suffix}")
    patient = models.Patient(
        user_id=user.id,
        ap_paterno="Test",
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


# ─────────────────────────────────────────────────────────────────────────
#  OBSERVACIONES DE LA ENTREGA (campo abierto, editable solo por
#  COORDINADOR_NACIONAL/SUPER_ADMIN una vez consolidada la entrega)
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_responsable_registra_entrega_con_observaciones(client, db_session):
    patient = await _crear_patient(db_session, depto="La Paz")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
        "observaciones": "Beneficiario solicitó cambio a Lispro para la próxima entrega.",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()[0]["observaciones"] == "Beneficiario solicitó cambio a Lispro para la próxima entrega."


@pytest.mark.asyncio
async def test_entrega_sin_observaciones_queda_nula(client, db_session):
    patient = await _crear_patient(db_session, depto="La Paz")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()[0]["observaciones"] is None


@pytest.mark.asyncio
async def test_observaciones_se_aplica_a_todos_los_items_de_la_misma_entrega(client, db_session):
    patient = await _crear_patient(db_session, depto="La Paz")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [
            {"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"},
            {"presentacion": "Pen 3ml", "insulin_type": "Lispro", "quantity": "1 pluma"},
        ],
        "observaciones": "Posible reventa: retira más insulina de la que declara necesitar.",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body) == 2
    assert all(item["observaciones"] == "Posible reventa: retira más insulina de la que declara necesitar." for item in body)


@pytest.mark.asyncio
async def test_responsable_no_puede_editar_observacion_ya_consolidada(client, db_session):
    patient = await _crear_patient(db_session, depto="La Paz")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")
    create_resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
        "observaciones": "Nota original.",
    })
    delivery_id = create_resp.json()[0]["id"]

    resp = await client.put(
        f"/departmental/entregas-insulina/{delivery_id}/observaciones",
        json={"observaciones": "Intento de edición no autorizada."},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_coordinador_nacional_puede_editar_observacion_consolidada(client, db_session):
    patient = await _crear_patient(db_session, depto="La Paz")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")
    create_resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
        "observaciones": "Nota original.",
    })
    delivery_id = create_resp.json()[0]["id"]

    await _switch_identity(db_session, "COORDINADOR_NACIONAL")
    resp = await client.put(
        f"/departmental/entregas-insulina/{delivery_id}/observaciones",
        json={"observaciones": "Corregido por el coordinador nacional tras confirmar el caso."},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["observaciones"] == "Corregido por el coordinador nacional tras confirmar el caso."


@pytest.mark.asyncio
async def test_super_admin_puede_editar_observacion_consolidada(client, superuser_token, db_session):
    patient = await _crear_patient(db_session, depto="La Paz")
    create_resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })
    delivery_id = create_resp.json()[0]["id"]

    resp = await client.put(
        f"/departmental/entregas-insulina/{delivery_id}/observaciones",
        json={"observaciones": "Ajustado por SUPER_ADMIN."},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["observaciones"] == "Ajustado por SUPER_ADMIN."


@pytest.mark.asyncio
async def test_editar_observacion_de_entrega_inexistente_404(client, superuser_token):
    resp = await client.put(
        "/departmental/entregas-insulina/999999999/observaciones",
        json={"observaciones": "No debería aplicar."},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_paciente_no_puede_editar_observacion(client, patient_token, db_session):
    patient = await _crear_patient(db_session, depto="La Paz")
    await _switch_identity(db_session, "SUPER_ADMIN")
    create_resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })
    delivery_id = create_resp.json()[0]["id"]

    # Volvemos a autenticar como el PACIENTE de patient_token (la creación
    # de arriba, como SUPER_ADMIN, sobreescribió el override).
    async def _as_patient():
        return patient_token
    app.dependency_overrides[deps.get_current_active_user] = _as_patient
    app.dependency_overrides[deps.get_current_user] = _as_patient
    app.dependency_overrides.pop(deps.get_current_super_user, None)

    resp = await client.put(
        f"/departmental/entregas-insulina/{delivery_id}/observaciones",
        json={"observaciones": "No debería poder."},
    )
    assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────
#  BENEFICIARIOS ACTIVOS: EXONERADO EXPLÍCITO Y MES ANTERIOR
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_beneficiario_exonerado_expone_flag_explicito(client, db_session):
    exonerado = await _crear_patient(db_session, depto="La Paz", exonerado_aporte=True)
    no_exonerado = await _crear_patient(db_session, depto="La Paz")

    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")
    resp = await client.get("/departmental/beneficiarios/activos", params={"limit": 5000})
    assert resp.status_code == 200, resp.text
    by_id = {item["id"]: item for item in resp.json()["items"]}

    assert by_id[exonerado.id]["exonerado_aporte"] is True
    assert by_id[no_exonerado.id]["exonerado_aporte"] is False


@pytest.mark.asyncio
async def test_al_dia_aporte_mes_anterior(client, db_session):
    hoy = date.today()
    primer_dia_mes_actual = hoy.replace(day=1)
    ultimo_dia_mes_anterior = primer_dia_mes_actual - timedelta(days=1)
    periodo_anterior = f"{ultimo_dia_mes_anterior.year}-{ultimo_dia_mes_anterior.month:02d}"

    pago_mes_anterior = await _crear_patient(db_session, depto="La Paz")
    await _crear_contribution(db_session, pago_mes_anterior, periodo_anterior, estado="ACEPTADO")

    debe_mes_anterior = await _crear_patient(db_session, depto="La Paz")

    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")
    resp = await client.get("/departmental/beneficiarios/activos", params={"limit": 5000})
    assert resp.status_code == 200, resp.text
    by_id = {item["id"]: item for item in resp.json()["items"]}

    assert by_id[pago_mes_anterior.id]["periodo_anterior"] == periodo_anterior
    assert by_id[pago_mes_anterior.id]["al_dia_mes_anterior"] is True
    assert by_id[debe_mes_anterior.id]["al_dia_mes_anterior"] is False


# ─────────────────────────────────────────────────────────────────────────
#  DOCUMENTOS PENDIENTES: DETALLE DE CUÁLES FALTAN
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pendientes_docs_expone_documentos_faltantes(client, db_session):
    patient = await _crear_patient(
        db_session, depto="La Paz", estado="PENDIENTE_DOC",
        url_ci_paciente="https://fake-storage.test/ci.jpg",
        url_declaracion_aporte="https://fake-storage.test/compromiso.jpg",
        # url_certificado_medico y url_foto_paciente quedan sin subir.
    )

    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")
    resp = await client.get("/departmental/beneficiarios/pendientes-docs", params={"limit": 5000})
    assert resp.status_code == 200, resp.text
    item = next(i for i in resp.json()["items"] if i["id"] == patient.id)

    assert "Certificado Médico" in item["documentos_pendientes"]
    assert "Foto Actual (Paciente)" in item["documentos_pendientes"]
    assert "Cédula de Identidad (Paciente)" not in item["documentos_pendientes"]
    assert "Compromiso Firmado" not in item["documentos_pendientes"]


@pytest.mark.asyncio
async def test_pendientes_docs_no_exige_ci_si_paciente_nunca_lo_registro(client, db_session):
    """Un menor sin CI (opcional en su registro) no debe figurar como con ese documento pendiente."""
    patient = await _crear_patient(db_session, depto="La Paz", estado="PENDIENTE_DOC", ci=None)

    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")
    resp = await client.get("/departmental/beneficiarios/pendientes-docs", params={"limit": 5000})
    assert resp.status_code == 200, resp.text
    item = next(i for i in resp.json()["items"] if i["id"] == patient.id)

    assert "Cédula de Identidad (Paciente)" not in item["documentos_pendientes"]


# ─────────────────────────────────────────────────────────────────────────
#  CORRECCIÓN DE UNA ENTREGA YA REGISTRADA (abierto para
#  RESPONSABLE_DEPARTAMENTAL/SUPER_ADMIN mientras siguen en campo)
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_responsable_corrige_su_propia_entrega(client, db_session):
    patient = await _crear_patient(db_session, depto="La Paz")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    create_resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
        "observaciones": "Nota original.",
    })
    delivery_id = create_resp.json()[0]["id"]

    resp = await client.put(f"/departmental/entregas-insulina/{delivery_id}", json={
        "insulin_type": "Lispro",
        "presentacion": "Pen 3ml",
        "quantity": "2 plumas",
        "observaciones": "Corregido: era Lispro, no Glargina.",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["insulin_type"] == "Lispro"
    assert body["presentacion"] == "Pen 3ml"
    assert body["quantity"] == "2 plumas"
    assert body["observaciones"] == "Corregido: era Lispro, no Glargina."


@pytest.mark.asyncio
async def test_responsable_no_puede_corregir_entrega_de_otro_departamento(client, db_session):
    patient = await _crear_patient(db_session, depto="Cochabamba")
    await _switch_identity(db_session, "SUPER_ADMIN")
    create_resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })
    delivery_id = create_resp.json()[0]["id"]

    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")
    resp = await client.put(f"/departmental/entregas-insulina/{delivery_id}", json={
        "insulin_type": "Lispro",
        "presentacion": "Pen 3ml",
        "quantity": "1 pluma",
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_coordinador_nacional_no_puede_corregir_entrega_completa(client, db_session):
    """Coordinador Nacional sigue siendo de solo lectura para la entrega en sí — solo puede tocar la observación."""
    patient = await _crear_patient(db_session, depto="La Paz")
    await _switch_identity(db_session, "SUPER_ADMIN")
    create_resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })
    delivery_id = create_resp.json()[0]["id"]

    await _switch_identity(db_session, "COORDINADOR_NACIONAL")
    resp = await client.put(f"/departmental/entregas-insulina/{delivery_id}", json={
        "insulin_type": "Lispro",
        "presentacion": "Pen 3ml",
        "quantity": "1 pluma",
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_corrige_entrega_de_cualquier_departamento(client, superuser_token, db_session):
    patient = await _crear_patient(db_session, depto="Cochabamba")
    create_resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })
    delivery_id = create_resp.json()[0]["id"]

    resp = await client.put(f"/departmental/entregas-insulina/{delivery_id}", json={
        "insulin_type": "NPH",
        "presentacion": "Cartucho 3ml",
        "quantity": "3 cartuchos",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["insulin_type"] == "NPH"


@pytest.mark.asyncio
async def test_corregir_entrega_inexistente_404(client, superuser_token):
    resp = await client.put("/departmental/entregas-insulina/999999999", json={
        "insulin_type": "Glargina",
        "presentacion": "Frasco 10ml",
        "quantity": "1 frasco",
    })
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_corregir_entrega_conserva_fecha_si_no_se_manda(client, db_session):
    patient = await _crear_patient(db_session, depto="La Paz")
    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")

    fecha_original = str(date(2026, 1, 15))
    create_resp = await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "delivery_date": fecha_original,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })
    delivery_id = create_resp.json()[0]["id"]

    resp = await client.put(f"/departmental/entregas-insulina/{delivery_id}", json={
        "insulin_type": "Glargina",
        "presentacion": "Cartucho 3ml",
        "quantity": "2 frascos",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["delivery_date"] == fecha_original


# ─────────────────────────────────────────────────────────────────────────
#  HISTORIAL: BÚSQUEDA POR BENEFICIARIO
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_historial_busca_por_nombre_de_beneficiario(client, db_session):
    juan = await _crear_patient(db_session, depto="La Paz", nombres="Juan Buscable")
    otro = await _crear_patient(db_session, depto="La Paz", nombres="Otro Paciente")

    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")
    for p in (juan, otro):
        r = await client.post("/departmental/entregas-insulina", json={
            "patient_id": p.id,
            "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
        })
        assert r.status_code == 201, r.text

    resp = await client.get("/departmental/entregas-insulina", params={"search": "Buscable", "limit": 5000})
    assert resp.status_code == 200, resp.text
    patient_ids = {item["patient_id"] for item in resp.json()["items"]}
    assert juan.id in patient_ids
    assert otro.id not in patient_ids


@pytest.mark.asyncio
async def test_historial_busca_por_ci_de_beneficiario(client, db_session):
    ci_unico = f"CI-BUSCAME-{uuid.uuid4().hex[:8]}"
    patient = await _crear_patient(db_session, depto="La Paz", ci=ci_unico)

    await _switch_identity(db_session, "RESPONSABLE_DEPARTAMENTAL", depto_asignado="La Paz")
    await client.post("/departmental/entregas-insulina", json={
        "patient_id": patient.id,
        "items": [{"presentacion": "Frasco 10ml", "insulin_type": "Glargina", "quantity": "1 frasco"}],
    })

    resp = await client.get("/departmental/entregas-insulina", params={"search": ci_unico, "limit": 5000})
    assert resp.status_code == 200, resp.text
    patient_ids = {item["patient_id"] for item in resp.json()["items"]}
    assert patient.id in patient_ids
