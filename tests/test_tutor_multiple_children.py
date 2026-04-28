import pytest
import uuid
from app import models

@pytest.mark.asyncio
async def test_tutor_with_two_children_registration(client, db_session, superuser_token):
    """
    Escenario de prueba:
    1. Una tutora registra a su primera hija menor con el correo 'tutora+hija1@test.com' y su CI.
    2. La misma tutora registra a su segunda hija menor con el correo 'tutora+hija2@test.com' y su MISMO CI.
    3. Activar a ambas hijas.
    4. Verificar que existen dos pacientes distintos y tres usuarios (Tutor si se creó + 2 Hijas).
       Nota: El requerimiento inicial decía que el tutor también puede tener su propia cuenta.
    """
    
    random_suffix = str(uuid.uuid4())[:8]
    tutor_ci = f"{random_suffix}-TUTORA"
    tutor_email_base = f"tutora_{random_suffix}@test.com"
    
    hija1_email = f"tutora_{random_suffix}+hija1@test.com"
    hija2_email = f"tutora_{random_suffix}+hija2@test.com"
    
    # --- PASO 1: Registrar Primera Hija ---
    hija1_data = {
        "ci": f"{random_suffix}-H1",
        "nombres": "Hija Uno",
        "ap_paterno": "Perez",
        "fecha_nac": "2018-01-01",
        "tutor": {
            "nombres": "Maria",
            "apellidos": "Tutor",
            "ci": tutor_ci,
            "email": hija1_email,
            "parentesco": "MADRE"
        },
        "medical": { "tipo_diabetes": "TIPO 1" }
    }
    
    res1 = await client.post("/patients/", json=hija1_data)
    assert res1.status_code == 201, f"Error registrando hija 1: {res1.text}"
    h1_id = res1.json()["id"]

    # --- PASO 2: Registrar Segunda Hija (MISMO CI DE TUTOR) ---
    hija2_data = {
        "ci": f"{random_suffix}-H2",
        "nombres": "Hija Dos",
        "ap_paterno": "Perez",
        "fecha_nac": "2020-05-05",
        "tutor": {
            "nombres": "Maria",
            "apellidos": "Tutor",
            "ci": tutor_ci, # <--- MISMO CI QUE H1
            "email": hija2_email,
            "parentesco": "MADRE"
        },
        "medical": { "tipo_diabetes": "TIPO 1" }
    }
    
    res2 = await client.post("/patients/", json=hija2_data)
    assert res2.status_code == 201, f"Error registrando hija 2 (Debería permitir CI duplicado en Tutor): {res2.text}"
    h2_id = res2.json()["id"]

    # --- PASO 3: Activar ambas para generar usuarios ---
    # Activar H1
    act1 = await client.put(f"/patients/{h1_id}/activate", headers={"Authorization": f"Bearer {superuser_token}"})
    assert act1.status_code == 200
    assert act1.json()["email"] == hija1_email

    # Activar H2
    act2 = await client.put(f"/patients/{h2_id}/activate", headers={"Authorization": f"Bearer {superuser_token}"})
    assert act2.status_code == 200
    assert act2.json()["email"] == hija2_email

    # --- PASO 4: Verificar Inicio de Sesión de ambas con el MISMO CI del tutor ---
    # Login H1
    login_h1 = await client.post("/login/access-token", data={"username": hija1_email, "password": tutor_ci})
    assert login_h1.status_code == 200, "Hija 1 debería poder entrar con el CI de la madre"
    
    # Login H2
    login_h2 = await client.post("/login/access-token", data={"username": hija2_email, "password": tutor_ci})
    assert login_h2.status_code == 200, "Hija 2 debería poder entrar con el MISMO CI de la madre"

    print(f"\n✅ Prueba exitosa: Se registraron y activaron 2 hijas con la misma madre ({tutor_ci}) usando alias de correo.")
