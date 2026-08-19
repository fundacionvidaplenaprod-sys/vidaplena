"""
tests/test_commitment_template.py
===================================
Pruebas de `GET /patients/me/commitment-template`, en particular el caso en
que la evaluación socioeconómica quedó en categoría MEDIA: el evaluador fija
un monto de aporte reducido, y ese es el monto con el que se genera el
compromiso que el beneficiario descarga, imprime, firma y vuelve a subir —
no puede elegir otro.
"""
import uuid
from datetime import date

import pytest

from app import models
from app.main import app
from app.api import deps

PDF_MAGIC = b"%PDF"


def _self_payload_base(**overrides) -> dict:
    data = {
        "departamento": "La Paz",
        "integrantes_hogar": 2,
        "dependientes": 0,
        "tipo_vivienda": "Alquilada",
        "monto_alquiler": 600.0,
        "tiene_seguro": False,
        "tipo_seguro": None,
        "condicion_laboral": "Independiente",
        "ingreso_titular": 3000.0,
        "ingreso_conyuge": 0.0,
        "ingreso_otros_familiares": 0.0,
        "tiene_agua": False, "monto_agua": 0.0,
        "tiene_luz": False, "monto_luz": 0.0,
        "tiene_gas_domiciliario": False, "monto_gas_domiciliario": 0.0,
        "tiene_internet": False, "monto_internet": 0.0,
        "monto_transporte": 0.0,
        "tiene_deudas_comprometen_ingresos": False,
        "monto_deuda_mensual": 0.0,
        "habeas_data_accepted": True,
        "imagen_consent_accepted": True,
    }
    data.update(overrides)
    return data


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


@pytest.mark.asyncio
async def test_media_fija_monto_y_beneficiario_descarga_con_ese_monto(client, db_session):
    """
    El evaluador aprueba con MEDIA y fija Bs. 180 de aporte. El beneficiario
    descarga su compromiso con ese monto exacto (no otro), y el PDF
    generado corresponde a ese monto ya cerrado.
    """
    patient_user = await _switch_identity(db_session, "PACIENTE")
    patient = models.Patient(
        user_id=patient_user.id,
        nombres="Compromiso",
        ap_paterno="Prueba",
        ci=f"CI-{uuid.uuid4().hex[:6]}",
        fecha_nac=date(1990, 1, 1),
        estado="PENDIENTE_DOC",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    resp_create = await client.post("/social-evaluations/me", json=_self_payload_base())
    assert resp_create.status_code == 201, resp_create.text

    await _switch_identity(db_session, "SUPER_ADMIN")
    resp_interview = await client.put(
        f"/social-evaluations/{patient.id}/interview", json={"notas": "Entrevista OK."}
    )
    assert resp_interview.status_code == 200, resp_interview.text

    resp_review = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO", "categoria_final": "MEDIA", "monto_comprometido": 180.0},
    )
    assert resp_review.status_code == 200, resp_review.text

    await db_session.refresh(patient)
    assert patient.exonerado_aporte is False
    assert float(patient.monto_aporte_comprometido) == 180.0

    # El beneficiario vuelve a autenticarse y descarga su compromiso con el
    # monto que fijó el evaluador.
    await _switch_identity(db_session, "PACIENTE")
    app.dependency_overrides[deps.get_current_active_user] = lambda: patient_user
    app.dependency_overrides[deps.get_current_user] = lambda: patient_user

    resp_pdf = await client.get(
        "/patients/me/commitment-template", params={"monto_compromiso": 180.0}
    )
    assert resp_pdf.status_code == 200, resp_pdf.text
    assert resp_pdf.headers["content-type"] == "application/pdf"
    assert resp_pdf.content.startswith(PDF_MAGIC)


@pytest.mark.asyncio
async def test_beneficiario_no_puede_elegir_otro_monto_distinto_al_fijado(client, db_session):
    """
    Una vez que el monto quedó cerrado (por el evaluador en MEDIA, o por el
    propio beneficiario en su primera descarga), un monto distinto es 400.
    """
    patient_user = await _switch_identity(db_session, "PACIENTE")
    patient = models.Patient(
        user_id=patient_user.id,
        nombres="Compromiso",
        ap_paterno="Cerrado",
        ci=f"CI-{uuid.uuid4().hex[:6]}",
        fecha_nac=date(1990, 1, 1),
        estado="PENDIENTE_DOC",
    )
    db_session.add(patient)
    await client.post("/social-evaluations/me", json=_self_payload_base())
    await db_session.commit()
    await db_session.refresh(patient)

    await _switch_identity(db_session, "SUPER_ADMIN")
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "OK"})
    resp_review = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO", "categoria_final": "MEDIA", "monto_comprometido": 180.0},
    )
    assert resp_review.status_code == 200, resp_review.text

    app.dependency_overrides[deps.get_current_active_user] = lambda: patient_user
    app.dependency_overrides[deps.get_current_user] = lambda: patient_user

    resp_wrong = await client.get(
        "/patients/me/commitment-template", params={"monto_compromiso": 100.0}
    )
    assert resp_wrong.status_code == 400
    assert "180" in resp_wrong.json()["detail"]


@pytest.mark.asyncio
async def test_media_permite_monto_menor_a_100(client, db_session):
    """
    El objetivo de MEDIA es justamente permitir un aporte por debajo del
    mínimo estándar de Bs. 100 (p. ej. alguien que solo puede pagar Bs. 50).
    """
    patient_user = await _switch_identity(db_session, "PACIENTE")
    patient = models.Patient(
        user_id=patient_user.id,
        nombres="Compromiso",
        ap_paterno="Bajo",
        ci=f"CI-{uuid.uuid4().hex[:6]}",
        fecha_nac=date(1990, 1, 1),
        estado="PENDIENTE_DOC",
    )
    db_session.add(patient)
    await client.post("/social-evaluations/me", json=_self_payload_base())
    await db_session.commit()
    await db_session.refresh(patient)

    await _switch_identity(db_session, "SUPER_ADMIN")
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "OK"})
    resp_review = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO", "categoria_final": "MEDIA", "monto_comprometido": 50.0},
    )
    assert resp_review.status_code == 200, resp_review.text

    app.dependency_overrides[deps.get_current_active_user] = lambda: patient_user
    app.dependency_overrides[deps.get_current_user] = lambda: patient_user

    resp_pdf = await client.get(
        "/patients/me/commitment-template", params={"monto_compromiso": 50.0}
    )
    assert resp_pdf.status_code == 200, resp_pdf.text


@pytest.mark.asyncio
async def test_sin_evaluacion_sigue_exigiendo_minimo_100(client, db_session):
    """
    Sin evaluación de por medio (monto_aporte_comprometido aún sin fijar),
    el mínimo estándar de Bs. 100 se mantiene: no es que cualquiera pueda
    pedir un monto bajo sin pasar por la evaluación.
    """
    patient_user = await _switch_identity(db_session, "PACIENTE")
    patient = models.Patient(
        user_id=patient_user.id,
        nombres="SinEvaluar",
        ap_paterno="Prueba",
        ci=f"CI-{uuid.uuid4().hex[:6]}",
        fecha_nac=date(1990, 1, 1),
        estado="PENDIENTE_DOC",
    )
    db_session.add(patient)
    await db_session.commit()

    resp = await client.get(
        "/patients/me/commitment-template", params={"monto_compromiso": 50.0}
    )
    assert resp.status_code == 400
    assert "100" in resp.json()["detail"]
