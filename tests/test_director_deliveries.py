import pytest
from datetime import date


@pytest.mark.asyncio
async def test_create_director_delivery_success(client, superuser_token):
    payload = {
        "patient_nombres": "  maría ",
        "patient_ap_paterno": " perez  ",
        "patient_ap_materno": "gomez",
        "insulin_type": "Insulina Glargina",
        "quantity": "2 frascos",
        "delivery_date": date.today().isoformat(),
    }
    res = await client.post("/api/director-deliveries/", json=payload)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["patient_nombres"] == "MARÍA"
    assert data["patient_ap_paterno"] == "PEREZ"
    assert data["patient_ap_materno"] == "GOMEZ"
    assert data["quantity"] == "2 frascos"
    assert data["insulin_type"] == "Insulina Glargina"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_director_delivery_unauthorized_for_patient(client, patient_token):
    payload = {
        "patient_nombres": "Ana",
        "patient_ap_paterno": "Lopez",
        "insulin_type": "Insulina NPH",
        "quantity": "1 frasco",
    }
    res = await client.post("/api/director-deliveries/", json=payload)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_search_last_delivery_case_insensitive(client, superuser_token):
    # Crear entrega previa
    payload = {
        "patient_nombres": "CARLOS",
        "patient_ap_paterno": "MAMANI",
        "patient_ap_materno": "QUISPE",
        "insulin_type": "Insulina Aspart",
        "quantity": "3 frascos",
        "delivery_date": date.today().isoformat(),
    }
    res_create = await client.post("/api/director-deliveries/", json=payload)
    assert res_create.status_code == 200

    # Búsqueda con minúsculas
    res_search = await client.get(
        "/api/director-deliveries/search",
        params={"nombres": "carlos", "ap_paterno": "mamani", "ap_materno": "quispe"},
    )
    assert res_search.status_code == 200
    data = res_search.json()
    assert data is not None
    assert data["patient_nombres"] == "CARLOS"
    assert data["quantity"] == "3 frascos"


@pytest.mark.asyncio
async def test_update_director_pin(client, superuser_token):
    # PIN válido de 4 dígitos
    res = await client.put("/api/director-deliveries/pin", json={"pin": "5678"})
    assert res.status_code == 200, res.text
    assert res.json() == {"msg": "PIN updated successfully"}

    # PIN inválido de 3 dígitos -> debe ser rechazado
    res_invalid = await client.put("/api/director-deliveries/pin", json={"pin": "123"})
    assert res_invalid.status_code == 400
    assert "exactly 4 digits" in res_invalid.json()["detail"]
