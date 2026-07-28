import pytest
import uuid
from datetime import date
from app import models


async def _seed_beneficiary(db_session, nombres, ap_paterno, ap_materno=None, depto="La Paz"):
    beneficiary = models.PreregisteredBeneficiary(
        nombres=nombres, ap_paterno=ap_paterno, ap_materno=ap_materno, depto=depto
    )
    db_session.add(beneficiary)
    await db_session.commit()
    return beneficiary


@pytest.mark.asyncio
async def test_check_beneficiary_match_and_no_match(client, db_session):
    suffix = str(uuid.uuid4())[:8]
    nombres = f"Zzztest{suffix}"
    await _seed_beneficiary(db_session, nombres, "Padron", "Materno")

    # Coincide (tolerante a mayúsculas/tildes)
    res_match = await client.post("/patients/check-beneficiary", json={
        "nombres": nombres.upper(), "ap_paterno": "padron", "ap_materno": "MATERNO"
    })
    assert res_match.status_code == 200
    assert res_match.json()["match"] is True

    # No coincide
    res_no_match = await client.post("/patients/check-beneficiary", json={
        "nombres": "NombreInventadoQueNoExiste", "ap_paterno": "ApellidoFalso"
    })
    assert res_no_match.status_code == 200
    assert res_no_match.json()["match"] is False


@pytest.mark.asyncio
async def test_self_register_adult_happy_path(client, db_session):
    suffix = str(uuid.uuid4())[:8]
    nombres = f"Adulto{suffix}"
    await _seed_beneficiary(db_session, nombres, "Prueba")

    email = f"adulto_{suffix}@test.com"
    ci = f"CI-{suffix}"

    payload = {
        "email": email,
        "password": ci,
        "ci": ci,
        "nombres": nombres,
        "ap_paterno": "Prueba",
        "fecha_nac": "1990-01-01",
        "medical": {"tipo_diabetes": "Tipo 1"},
        "treatments": [{"nombre": "Glargina", "dosis_diaria": 10}],
        "complications": [],
    }

    response = await client.post("/patients/self-register", json=payload)
    assert response.status_code == 201, response.text
    assert "access_token" in response.json()

    # Puede loguearse de inmediato con el CI como contraseña
    login_res = await client.post("/login/access-token", data={"username": email, "password": ci})
    assert login_res.status_code == 200


@pytest.mark.asyncio
async def test_self_register_rejects_when_no_match(client, db_session):
    payload = {
        "email": f"noexiste_{uuid.uuid4().hex[:8]}@test.com",
        "password": "1234567",
        "ci": "1234567",
        "nombres": "PersonaQueNoEstaEnLaLista",
        "ap_paterno": "Inventado",
        "fecha_nac": "1990-01-01",
        "medical": {"tipo_diabetes": "Tipo 1"},
    }
    response = await client.post("/patients/self-register", json=payload)
    assert response.status_code == 400
    assert "beneficiarios" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_self_register_adult_requires_ci(client, db_session):
    suffix = str(uuid.uuid4())[:8]
    nombres = f"SinCI{suffix}"
    await _seed_beneficiary(db_session, nombres, "Prueba")

    payload = {
        "email": f"sinci_{suffix}@test.com",
        "password": "algunaclave",
        "ci": None,
        "nombres": nombres,
        "ap_paterno": "Prueba",
        "fecha_nac": "1990-01-01",
        "medical": {"tipo_diabetes": "Tipo 1"},
    }
    response = await client.post("/patients/self-register", json=payload)
    assert response.status_code == 400
    assert "carnet" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_self_register_minor_without_ci_uses_custom_password(client, db_session):
    suffix = str(uuid.uuid4())[:8]
    nombres = f"Menor{suffix}"
    await _seed_beneficiary(db_session, nombres, "Prueba")

    email = f"menor_{suffix}@test.com"
    custom_password = "clavePersonalizada123"
    tutor_ci = f"TUT-{suffix}"

    payload = {
        "email": email,
        "password": custom_password,
        "ci": None,
        "nombres": nombres,
        "ap_paterno": "Prueba",
        "fecha_nac": date.today().replace(year=date.today().year - 10).isoformat(),
        "tutor": {
            "nombres": "Tutor",
            "apellidos": "DePrueba",
            "ci": tutor_ci,
            "telefonos": "70000000",
            "direccion": "Calle Falsa 123",
        },
        "medical": {"tipo_diabetes": "Tipo 1"},
    }
    response = await client.post("/patients/self-register", json=payload)
    assert response.status_code == 201, response.text

    login_res = await client.post("/login/access-token", data={"username": email, "password": custom_password})
    assert login_res.status_code == 200
