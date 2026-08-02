import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app import models


async def _seed_beneficiary(db_session, nombres, ap_paterno, ap_materno=None, depto="La Paz"):
    beneficiary = models.PreregisteredBeneficiary(
        nombres=nombres, ap_paterno=ap_paterno, ap_materno=ap_materno, depto=depto
    )
    db_session.add(beneficiary)
    await db_session.commit()
    await db_session.refresh(beneficiary)
    return beneficiary


async def _seed_test_registration(db_session, nombres, ap_paterno, depto="La Paz"):
    """Simula un beneficiario del padrón ya reclamado por un paciente de prueba."""
    suffix = str(uuid.uuid4())[:8]
    user = models.User(
        email=f"paciente_{suffix}@test.com",
        password_hash="fakehash",
        role="PACIENTE",
        estado="ACTIVO",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    patient = models.Patient(
        user_id=user.id,
        nombres=nombres,
        ap_paterno=ap_paterno,
        fecha_nac=date(1990, 1, 1),
        estado="PENDIENTE_DOC",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    beneficiary = await _seed_beneficiary(db_session, nombres, ap_paterno, depto=depto)
    beneficiary.matched_patient_id = patient.id
    await db_session.commit()
    await db_session.refresh(beneficiary)

    return beneficiary, patient, user


@pytest.mark.asyncio
async def test_search_beneficiaries_requires_super_admin(client, db_session):
    suffix = str(uuid.uuid4())[:8]
    nombres = f"Incompleto{suffix}"
    await _seed_beneficiary(db_session, nombres, "Solo")

    res = await client.get("/patients/admin/beneficiaries", params={"q": nombres})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_search_and_fix_incomplete_beneficiary_name(client, db_session, superuser_token):
    suffix = str(uuid.uuid4())[:8]
    nombre_corto = f"Juan{suffix}"
    nombre_completo = f"Juan{suffix} Carlos"
    # Padrón precargado solo con un nombre; el beneficiario real usa dos
    # nombres al autoregistrarse, y como "nombres" exige coincidencia exacta
    # (a diferencia de los apellidos, que son tolerantes a datos faltantes),
    # la búsqueda no lo encuentra hasta que el SUPER_ADMIN corrige el padrón.
    beneficiary = await _seed_beneficiary(db_session, nombre_corto, "Mamani")

    res_search = await client.get("/patients/admin/beneficiaries", params={"q": nombre_corto})
    assert res_search.status_code == 200
    results = res_search.json()
    assert len(results) == 1
    assert results[0]["id"] == beneficiary.id
    assert results[0]["nombres"] == nombre_corto
    assert results[0]["already_registered"] is False

    check_before = await client.post("/patients/check-beneficiary", json={
        "nombres": nombre_completo, "ap_paterno": "Mamani"
    })
    assert check_before.json()["match"] is False

    # El SUPER_ADMIN corrige el padrón para incluir el segundo nombre.
    res_update = await client.put(
        f"/patients/admin/beneficiaries/{beneficiary.id}",
        json={"nombres": nombre_completo, "ap_paterno": "Mamani", "depto": "Cochabamba"},
    )
    assert res_update.status_code == 200
    updated = res_update.json()
    assert updated["nombres"] == nombre_completo
    assert updated["depto"] == "Cochabamba"

    # Ahora el autoregistro con el nombre completo sí coincide.
    check_after = await client.post("/patients/check-beneficiary", json={
        "nombres": nombre_completo, "ap_paterno": "Mamani"
    })
    assert check_after.json()["match"] is True


@pytest.mark.asyncio
async def test_update_beneficiary_requires_super_admin(client, db_session):
    suffix = str(uuid.uuid4())[:8]
    beneficiary = await _seed_beneficiary(db_session, f"SinAuth{suffix}", "Prueba")

    res = await client.put(
        f"/patients/admin/beneficiaries/{beneficiary.id}",
        json={"nombres": "Cambiado", "ap_paterno": "Prueba"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_update_beneficiary_not_found(client, db_session, superuser_token):
    res = await client.put(
        "/patients/admin/beneficiaries/999999999",
        json={"nombres": "NoExiste", "ap_paterno": "Prueba"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_reset_registration_deletes_test_patient_and_user(client, db_session, superuser_token):
    suffix = str(uuid.uuid4())[:8]
    nombres = f"Reset{suffix}"
    beneficiary, patient, user = await _seed_test_registration(db_session, nombres, "Prueba")
    patient_id = patient.id
    user_id = user.id

    res = await client.post(f"/patients/admin/beneficiaries/{beneficiary.id}/reset-registration")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["already_registered"] is False
    # El nombre/apellido/depto del padrón no debe tocarse.
    assert body["nombres"] == nombres
    assert body["ap_paterno"] == "Prueba"

    patient_check = await db_session.execute(select(models.Patient).where(models.Patient.id == patient_id))
    assert patient_check.scalar_one_or_none() is None

    user_check = await db_session.execute(select(models.User).where(models.User.id == user_id))
    assert user_check.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_reset_registration_noop_when_not_registered(client, db_session, superuser_token):
    suffix = str(uuid.uuid4())[:8]
    beneficiary = await _seed_beneficiary(db_session, f"Libre{suffix}", "Prueba")

    res = await client.post(f"/patients/admin/beneficiaries/{beneficiary.id}/reset-registration")
    assert res.status_code == 200, res.text
    assert res.json()["already_registered"] is False


@pytest.mark.asyncio
async def test_reset_registration_requires_super_admin(client, db_session):
    suffix = str(uuid.uuid4())[:8]
    beneficiary = await _seed_beneficiary(db_session, f"SinAuthReset{suffix}", "Prueba")

    res = await client.post(f"/patients/admin/beneficiaries/{beneficiary.id}/reset-registration")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_reset_registration_not_found(client, db_session, superuser_token):
    res = await client.post("/patients/admin/beneficiaries/999999999/reset-registration")
    assert res.status_code == 404
