"""
tests/test_social_evaluation_extraordinaria.py
================================================
Evaluación social extraordinaria: vía alternativa exclusiva de
EVALUADOR_SOCIAL/SUPER_ADMIN para beneficiarios imposibilitados (a varios
niveles) de completar el formulario digital estándar. Reemplaza el
cuestionario de ingresos/vivienda/servicios por una justificación explícita
y un informe basado en una entrevista telefónica; a diferencia del flujo
normal, la creación (POST /social-evaluations/extraordinaria) YA es la
decisión final — no pasa por un aval posterior separado.
"""
import uuid
from datetime import date, timedelta

import pytest

from app import models
from app.main import app
from app.api import deps


async def _crear_patient(db_session, depto: str = "La Paz") -> models.Patient:
    """Crea un paciente ACTIVO mínimo para usar en tests de evaluación."""
    user = models.User(
        email=f"patient_{uuid.uuid4().hex[:8]}@test.com",
        password_hash="fakehash",
        role="PACIENTE",
        estado="ACTIVO",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    patient = models.Patient(
        user_id=user.id,
        nombres="Juana",
        ap_paterno="Mamani",
        ci=f"CI-{uuid.uuid4().hex[:6]}",
        fecha_nac=date(1950, 1, 1),
        depto=depto,
        tipo_sangre="O+",
        estado="ACTIVO",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


async def _switch_identity(db_session, role: str) -> models.User:
    """Crea un usuario con el rol dado y hace que `client` autentique como él."""
    user = models.User(
        email=f"{role.lower()}_{uuid.uuid4().hex[:8]}@test.com",
        password_hash="fakehash",
        role=role,
        estado="ACTIVO",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    async def override():
        return user

    app.dependency_overrides[deps.get_current_active_user] = override
    app.dependency_overrides[deps.get_current_user] = override
    return user


def _payload(patient_id: int, **overrides) -> dict:
    data = {
        "patient_id": patient_id,
        "justificacion_extraordinaria": "Persona adulta mayor sin acceso a internet ni celular propio.",
        "informe_entrevista": "Se conversó por llamada telefónica el 03/09: vive sola, sin ingresos fijos.",
        "responsabilidad_aceptada": True,
        "habeas_data_accepted": True,
        "decision": "APROBADO",
        "categoria_final": "ALTA",
    }
    data.update(overrides)
    return data


# ─────────────────────────────────────────────────────────────────────────
#  CREACIÓN — DECISIÓN FINAL EN UN SOLO PASO
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_evaluador_social_registra_extraordinaria_aprobada_alta(client, db_session):
    patient = await _crear_patient(db_session)
    actor = await _switch_identity(db_session, "EVALUADOR_SOCIAL")

    resp = await client.post("/social-evaluations/extraordinaria", json=_payload(patient.id))
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["patient_id"] == patient.id
    assert data["es_extraordinaria"] is True
    assert data["responsabilidad_aceptada"] is True
    assert data["estado_revision"] == "APROBADO"
    assert data["categoria_final"] == "ALTA"
    assert data["reviewer_id"] is not None
    assert data["entrevista_realizada"] is True
    assert data["entrevista_notas"] == _payload(patient.id)["informe_entrevista"]
    assert data["justificacion_extraordinaria"] == _payload(patient.id)["justificacion_extraordinaria"]

    await db_session.refresh(patient)
    assert patient.exonerado_aporte is True
    assert patient.evaluacion_bloqueada_hasta is not None


@pytest.mark.asyncio
async def test_extraordinaria_aprobada_media_fija_monto(client, db_session):
    patient = await _crear_patient(db_session)
    await _switch_identity(db_session, "EVALUADOR_SOCIAL")

    resp = await client.post(
        "/social-evaluations/extraordinaria",
        json=_payload(patient.id, categoria_final="MEDIA", monto_comprometido=150.0),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["categoria_final"] == "MEDIA"

    await db_session.refresh(patient)
    assert patient.exonerado_aporte is False
    assert float(patient.monto_aporte_comprometido) == 150.0


@pytest.mark.asyncio
async def test_extraordinaria_aprobada_media_sin_monto_falla(client, db_session):
    patient = await _crear_patient(db_session)
    await _switch_identity(db_session, "EVALUADOR_SOCIAL")

    resp = await client.post(
        "/social-evaluations/extraordinaria",
        json=_payload(patient.id, categoria_final="MEDIA"),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_extraordinaria_rechazada_exige_motivo(client, db_session):
    patient = await _crear_patient(db_session)
    await _switch_identity(db_session, "EVALUADOR_SOCIAL")

    resp = await client.post(
        "/social-evaluations/extraordinaria",
        json=_payload(patient.id, decision="RECHAZADO", categoria_final=None),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_extraordinaria_rechazada_estandar_aplica_cooldown(client, db_session):
    patient = await _crear_patient(db_session)
    await _switch_identity(db_session, "EVALUADOR_SOCIAL")

    resp = await client.post(
        "/social-evaluations/extraordinaria",
        json=_payload(patient.id, decision="RECHAZADO", categoria_final=None, motivo="Inconsistencias graves."),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["estado_revision"] == "RECHAZADO"
    assert resp.json()["motivo_rechazo"] == "Inconsistencias graves."

    await db_session.refresh(patient)
    assert patient.exonerado_aporte is False
    assert patient.evaluacion_bloqueada_hasta is not None
    assert patient.estado_beneficio != "SUSPENDIDO"


@pytest.mark.asyncio
async def test_extraordinaria_rechazada_fraude_suspende_beneficiario(client, db_session):
    patient = await _crear_patient(db_session)
    await _switch_identity(db_session, "EVALUADOR_SOCIAL")

    resp = await client.post(
        "/social-evaluations/extraordinaria",
        json=_payload(
            patient.id, decision="RECHAZADO_FRAUDE", categoria_final=None,
            motivo="Falsedad detectada durante la llamada.",
        ),
    )
    assert resp.status_code == 201, resp.text

    await db_session.refresh(patient)
    assert patient.estado_beneficio == "SUSPENDIDO"


# ─────────────────────────────────────────────────────────────────────────
#  VALIDACIONES OBLIGATORIAS DEL MODO EXTRAORDINARIO
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extraordinaria_requiere_responsabilidad_aceptada_true(client, db_session):
    patient = await _crear_patient(db_session)
    await _switch_identity(db_session, "EVALUADOR_SOCIAL")

    resp = await client.post(
        "/social-evaluations/extraordinaria",
        json=_payload(patient.id, responsabilidad_aceptada=False),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_extraordinaria_requiere_habeas_data_true(client, db_session):
    patient = await _crear_patient(db_session)
    await _switch_identity(db_session, "EVALUADOR_SOCIAL")

    resp = await client.post(
        "/social-evaluations/extraordinaria",
        json=_payload(patient.id, habeas_data_accepted=False),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_extraordinaria_requiere_justificacion_minima(client, db_session):
    patient = await _crear_patient(db_session)
    await _switch_identity(db_session, "EVALUADOR_SOCIAL")

    resp = await client.post(
        "/social-evaluations/extraordinaria",
        json=_payload(patient.id, justificacion_extraordinaria="Muy corta"),
    )
    assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────
#  CONTROL DE ACCESO Y CASOS DE BORDE
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_paciente_no_puede_registrar_extraordinaria(client, db_session):
    patient = await _crear_patient(db_session)
    await _switch_identity(db_session, "PACIENTE")

    resp = await client.post("/social-evaluations/extraordinaria", json=_payload(patient.id))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_puede_registrar_extraordinaria(client, db_session):
    patient = await _crear_patient(db_session)
    await _switch_identity(db_session, "SUPER_ADMIN")

    resp = await client.post("/social-evaluations/extraordinaria", json=_payload(patient.id))
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_extraordinaria_paciente_inexistente_404(client, db_session):
    await _switch_identity(db_session, "EVALUADOR_SOCIAL")

    resp = await client.post("/social-evaluations/extraordinaria", json=_payload(999999999))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_extraordinaria_respeta_cooldown_de_elegibilidad(client, db_session):
    """Un beneficiario en cooldown (rechazo previo) no puede recibir una nueva evaluación, ni por esta vía."""
    patient = await _crear_patient(db_session)
    patient.evaluacion_bloqueada_hasta = date.today() + timedelta(days=90)
    await db_session.commit()

    await _switch_identity(db_session, "EVALUADOR_SOCIAL")
    resp = await client.post("/social-evaluations/extraordinaria", json=_payload(patient.id))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_extraordinaria_queda_en_historial_de_auditoria(client, db_session):
    patient = await _crear_patient(db_session)
    await _switch_identity(db_session, "EVALUADOR_SOCIAL")

    resp = await client.post("/social-evaluations/extraordinaria", json=_payload(patient.id))
    assert resp.status_code == 201, resp.text

    history_resp = await client.get(f"/social-evaluations/{patient.id}/history")
    assert history_resp.status_code == 200, history_resp.text
    entries = history_resp.json()
    assert len(entries) >= 1
    ultimo = entries[0]
    assert ultimo["accion"] == "APROBADO"
    assert ultimo["payload"]["es_extraordinaria"] is True
    assert ultimo["payload"]["justificacion_extraordinaria"]
