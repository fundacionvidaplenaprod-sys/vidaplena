import uuid

import pytest

from app import models


async def _seed_beneficiary(db_session, nombres, ap_paterno, ap_materno=None, depto="La Paz"):
    beneficiary = models.PreregisteredBeneficiary(
        nombres=nombres, ap_paterno=ap_paterno, ap_materno=ap_materno, depto=depto
    )
    db_session.add(beneficiary)
    await db_session.commit()
    await db_session.refresh(beneficiary)
    return beneficiary


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
