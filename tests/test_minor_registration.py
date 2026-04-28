import pytest
import uuid
from app import models

@pytest.mark.asyncio
async def test_minor_and_tutor_registration_scenario(client, db_session, superuser_token):
    """
    Escenario de prueba:
    1. Crear un usuario independiente para el Tutor.
    2. Crear un paciente menor de edad con el correo '[tutor]+hija@mail.com' en el campo del tutor.
    3. Activar al paciente menor.
    4. Verificar que existen dos usuarios distintos en la tabla 'users'.
    """
    
    random_suffix = str(uuid.uuid4())[:8]
    tutor_email = f"tutor_{random_suffix}@test.com"
    minor_tutor_field_email = f"tutor_{random_suffix}+hija@test.com"
    tutor_ci = f"{random_suffix}-TUT"
    minor_ci = f"{random_suffix}-MIN"
    
    # --- PASO 1: Crear usuario independiente para el Tutor ---
    # Nota: Usamos el endpoint de creación de usuarios (POST /users/)
    tutor_user_data = {
        "email": tutor_email,
        "password": tutor_ci,  # Siguiendo la regla: password = CI
        "role": "PACIENTE"
    }
    
    response_tutor = await client.post("/users/", json=tutor_user_data, headers={"Authorization": f"Bearer {superuser_token}"})
    assert response_tutor.status_code == 201, f"Error creando tutor independiente: {response_tutor.text}"
    tutor_user_id = response_tutor.json()["id"]

    # --- PASO 2: Crear paciente menor de edad ---
    # Usamos POST /patients/
    minor_patient_data = {
        "ci": minor_ci,
        "nombres": "Ana",
        "ap_paterno": "Perez",
        "fecha_nac": "2015-05-20", # 10-11 años aprox
        "tutor": {
            "nombres": "Juan",
            "apellidos": "Perez",
            "ci": tutor_ci,
            "email": minor_tutor_field_email,
            "parentesco": "PADRE"
        },
        "medical": {
            "tipo_diabetes": "TIPO 1"
        }
    }
    
    response_minor = await client.post("/patients/", json=minor_patient_data)
    assert response_minor.status_code == 201, f"Error creando paciente menor: {response_minor.text}"
    minor_patient_id = response_minor.json()["id"]

    # --- PASO 3: Activar al paciente menor ---
    # Esto debería generar un usuario automático con el correo del tutor especificado en el registro del menor
    response_activation = await client.put(f"/patients/{minor_patient_id}/activate", headers={"Authorization": f"Bearer {superuser_token}"})
    assert response_activation.status_code == 200, f"Error activando paciente menor: {response_activation.text}"
    
    activated_user_email = response_activation.json()["email"]
    assert activated_user_email == minor_tutor_field_email, "El email del usuario activado no coincide con el sub-addressing"

    # --- PASO 4: Verificar Inicio de Sesión con CI (Factor Crítico) ---
    # Probamos loguear a la menor usando el CI del tutor como password
    login_data_minor = {
        "username": minor_tutor_field_email,
        "password": tutor_ci
    }
    # OAuth2PasswordRequestForm espera 'username' y 'password' como form-data
    response_login_minor = await client.post("/login/access-token", data=login_data_minor)
    assert response_login_minor.status_code == 200, f"Error: No se pudo loguear a la menor con el CI del tutor: {response_login_minor.text}"
    assert "access_token" in response_login_minor.json()

    # Probamos loguear al tutor independiente usando su propio CI
    login_data_tutor = {
        "username": tutor_email,
        "password": tutor_ci
    }
    response_login_tutor = await client.post("/login/access-token", data=login_data_tutor)
    assert response_login_tutor.status_code == 200, f"Error: No se pudo loguear al tutor con su CI: {response_login_tutor.text}"
    assert "access_token" in response_login_tutor.json()

    # --- PASO 5: Verificación Final de Registros en DB ---
    # Verificar que ambos usuarios son distintos y coexisten
    from sqlalchemy import select
    query = select(models.User).where(models.User.email.in_([tutor_email, minor_tutor_field_email]))
    result = await db_session.execute(query)
    users = result.scalars().all()
    
    assert len(users) == 2, f"Se esperaban 2 usuarios distintos, se encontraron {len(users)}"
    
    emails_found = [u.email for u in users]
    assert tutor_email in emails_found
    assert minor_tutor_field_email in emails_found
    
    print("\n✅ Prueba exitosa: Se crearon usuarios independientes para el tutor y la menor usando '+hija'.")
