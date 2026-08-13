"""
tests/test_social_evaluation.py
================================
Suite de pruebas para el módulo de Evaluación Socioeconómica y Categorización
de Beneficiarios de la Fundación V.I.D.A. Plena.

Cubre:
  1. Motor de Categorización puro (unitario, sin DB)
  2. Motor Anti-Fraude puro (unitario, sin DB)
  3. Endpoint POST /social-evaluations/ (integración)
  4. Endpoint GET /social-evaluations/{patient_id} (integración)
  5. Endpoint GET /social-evaluations/ – listado SUPER_ADMIN (integración)
  6. Control de acceso – EVALUADOR_SOCIAL puede crear evaluaciones
  7. Control de acceso – PACIENTE no puede acceder al módulo
  8. Upsert – se sobreescribe la evaluación si ya existe una previa
"""

import io
import uuid
import pytest
import pytest_asyncio
from datetime import date
from sqlalchemy import select

from app import models
from app.api.endpoints import evaluations as evaluations_module
from app.api.endpoints.evaluations import _calcular_categoria, _evaluar_fraude


def _fake_upload(file_content, path, content_type):
    return f"https://fake-storage.test/{path}"


def _fake_file(filename="evidencia.jpg", content_type="image/jpeg"):
    return {"file": (filename, io.BytesIO(b"fake-image-bytes"), content_type)}

# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _crear_patient(db_session) -> models.Patient:
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
        nombres="María",
        ap_paterno="Quispe",
        ci=f"CI-{uuid.uuid4().hex[:6]}",
        fecha_nac=date(1985, 6, 15),
        tipo_sangre="A+",
        estado="ACTIVO",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


def _payload_base(patient_id: int, **overrides) -> dict:
    """Payload válido base para el endpoint de evaluación."""
    data = {
        "patient_id": patient_id,
        "departamento": "La Paz",
        "integrantes_hogar": 4,
        "dependientes": 2,
        "tipo_vivienda": "Alquilada",
        "monto_alquiler": 600.0,
        "tiene_seguro": False,
        "tipo_seguro": None,
        "condicion_laboral": "Independiente / Cuenta propia",
        "ingreso_titular": 1800.0,
        "ingreso_conyuge": 0.0,
        "habeas_data_accepted": True,
        "imagen_consent_accepted": True,
    }
    data.update(overrides)
    return data


# ─────────────────────────────────────────────────────────────────────────────
#  SECCIÓN 1: PRUEBAS UNITARIAS DEL MOTOR DE CATEGORIZACIÓN (sin DB, sin HTTP)
# ─────────────────────────────────────────────────────────────────────────────

class TestMotorCategorizacion:
    """Pruebas puras de la función _calcular_categoria."""

    def test_categoria_A_sin_seguro_bajo_umbral(self):
        """Per cápita < 500 Bs. y SIN seguro → Categoría A."""
        assert _calcular_categoria(400.0, tiene_seguro=False) == "A"

    def test_categoria_A_limite_inferior(self):
        """Per cápita = 1 Bs. y SIN seguro → Categoría A."""
        assert _calcular_categoria(1.0, tiene_seguro=False) == "A"

    def test_categoria_A_con_seguro_se_eleva_a_B(self):
        """
        Per cápita < 500 Bs. PERO tiene seguro → No aplica para A.
        El motor debe devolverla como B (está en rango <= 1200).
        """
        assert _calcular_categoria(300.0, tiene_seguro=True) == "B"

    def test_categoria_B_limite_inferior(self):
        """Per cápita exactamente 500 Bs. → Categoría B."""
        assert _calcular_categoria(500.0, tiene_seguro=False) == "B"

    def test_categoria_B_rango_medio(self):
        """Per cápita = 850 Bs. → Categoría B."""
        assert _calcular_categoria(850.0, tiene_seguro=False) == "B"

    def test_categoria_B_limite_superior(self):
        """Per cápita exactamente 1200 Bs. → Categoría B."""
        assert _calcular_categoria(1200.0, tiene_seguro=False) == "B"

    def test_categoria_C_limite_inferior(self):
        """Per cápita = 1201 Bs. → Categoría C."""
        assert _calcular_categoria(1201.0, tiene_seguro=False) == "C"

    def test_categoria_C_rango_medio(self):
        """Per cápita = 1800 Bs. → Categoría C."""
        assert _calcular_categoria(1800.0, tiene_seguro=False) == "C"

    def test_categoria_C_limite_superior(self):
        """Per cápita exactamente 2250 Bs. → Categoría C."""
        assert _calcular_categoria(2250.0, tiene_seguro=False) == "C"

    def test_categoria_N_sobre_limite(self):
        """Per cápita = 2251 Bs. → Categoría N (no elegible)."""
        assert _calcular_categoria(2251.0, tiene_seguro=False) == "N"

    def test_categoria_N_alto_ingreso(self):
        """Per cápita = 10000 Bs. → Categoría N."""
        assert _calcular_categoria(10_000.0, tiene_seguro=False) == "N"

    def test_per_capita_cero_sin_seguro(self):
        """Per cápita = 0 Bs. sin seguro → Categoría A (caso extremo de pobreza declarada)."""
        assert _calcular_categoria(0.0, tiene_seguro=False) == "A"


# ─────────────────────────────────────────────────────────────────────────────
#  SECCIÓN 2: PRUEBAS UNITARIAS DEL MOTOR ANTI-FRAUDE (sin DB, sin HTTP)
# ─────────────────────────────────────────────────────────────────────────────

class TestMotorAntiFraude:
    """Pruebas puras de la función _evaluar_fraude."""

    def test_normal_caso_tipico(self):
        """Caso sin inconsistencias → NORMAL."""
        resultado = _evaluar_fraude(
            ingreso_total=1800.0,
            tiene_seguro=False,
            categoria="B",
            tipo_vivienda="Alquilada",
            monto_alquiler=600.0,
        )
        assert resultado == "NORMAL"

    def test_alerta_ingreso_cero_con_seguro(self):
        """
        FRAUDE CASO 1: Ingreso = 0 Bs. PERO tiene seguro médico activo.
        ¿Cómo paga el seguro si no tiene ingresos?
        """
        resultado = _evaluar_fraude(
            ingreso_total=0.0,
            tiene_seguro=True,
            categoria="A",
            tipo_vivienda="Alquilada",
            monto_alquiler=500.0,
        )
        assert resultado == "REVISIÓN MANUAL URGENTE"

    def test_alerta_categoria_A_vivienda_propia_sin_alquiler(self):
        """
        FRAUDE CASO 2: Categoría A (extrema pobreza) PERO vivienda es propia y alquiler = 0.
        Inconsistencia: si es tan pobre, ¿cómo tiene vivienda propia?
        """
        resultado = _evaluar_fraude(
            ingreso_total=1200.0,
            tiene_seguro=False,
            categoria="A",
            tipo_vivienda="Propia",
            monto_alquiler=0.0,
        )
        assert resultado == "REVISIÓN MANUAL URGENTE"

    def test_no_alerta_categoria_A_vivienda_alquilada(self):
        """Categoría A con vivienda alquilada → consistente, sin alerta."""
        resultado = _evaluar_fraude(
            ingreso_total=1200.0,
            tiene_seguro=False,
            categoria="A",
            tipo_vivienda="Alquilada",
            monto_alquiler=400.0,
        )
        assert resultado == "NORMAL"

    def test_no_alerta_categoria_B_vivienda_propia(self):
        """Categoría B con vivienda propia → coherente, sin alerta."""
        resultado = _evaluar_fraude(
            ingreso_total=3000.0,
            tiene_seguro=False,
            categoria="B",
            tipo_vivienda="Propia",
            monto_alquiler=0.0,
        )
        assert resultado == "NORMAL"

    def test_ingreso_cero_sin_seguro_no_genera_alerta(self):
        """Ingreso = 0 y SIN seguro → sin inconsistencia detectada."""
        resultado = _evaluar_fraude(
            ingreso_total=0.0,
            tiene_seguro=False,
            categoria="A",
            tipo_vivienda="Familiar / Prestada",
            monto_alquiler=0.0,
        )
        assert resultado == "NORMAL"

    def test_alerta_vivienda_propia_case_insensitive(self):
        """El chequeo de tipo_vivienda debe ser insensible a mayúsculas."""
        resultado = _evaluar_fraude(
            ingreso_total=500.0,
            tiene_seguro=False,
            categoria="A",
            tipo_vivienda="  PROPIA  ",
            monto_alquiler=0.0,
        )
        assert resultado == "REVISIÓN MANUAL URGENTE"


# ─────────────────────────────────────────────────────────────────────────────
#  SECCIÓN 3: PRUEBAS DE INTEGRACIÓN – ENDPOINTS HTTP
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_evaluacion_super_admin(client, superuser_token, db_session):
    """SUPER_ADMIN puede crear una evaluación socioeconómica."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(patient.id)

    resp = await client.post("/social-evaluations/", json=payload)

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["patient_id"] == patient.id
    assert data["departamento"] == "La Paz"
    assert data["integrantes_hogar"] == 4


@pytest.mark.asyncio
async def test_motor_categorizacion_en_endpoint(client, superuser_token, db_session):
    """
    El motor de categorización calcula correctamente el per cápita
    y asigna la categoría al guardar en la DB.

    Ingreso titular = 1800, cónyuge = 0, integrantes = 4
    Per cápita = 1800 / 4 = 450 → Categoría A (sin seguro).
    """
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=1800.0,
        ingreso_conyuge=0.0,
        integrantes_hogar=4,
        tiene_seguro=False,
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["ingreso_per_capita"] == 450.0
    assert data["categoria_asignada"] == "A"


@pytest.mark.asyncio
async def test_motor_categoriza_B(client, superuser_token, db_session):
    """Per cápita = 2000 / 4 = 500 → Categoría B."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=2000.0,
        ingreso_conyuge=0.0,
        integrantes_hogar=4,
        tiene_seguro=False,
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["ingreso_per_capita"] == 500.0
    assert data["categoria_asignada"] == "B"


@pytest.mark.asyncio
async def test_motor_categoriza_C(client, superuser_token, db_session):
    """Per cápita = 6000 / 4 = 1500 → Categoría C."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=6000.0,
        ingreso_conyuge=0.0,
        integrantes_hogar=4,
        tiene_seguro=False,
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["ingreso_per_capita"] == 1500.0
    assert data["categoria_asignada"] == "C"


@pytest.mark.asyncio
async def test_motor_categoriza_N(client, superuser_token, db_session):
    """Per cápita = 10000 / 2 = 5000 → Categoría N."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=10_000.0,
        ingreso_conyuge=0.0,
        integrantes_hogar=2,
        tiene_seguro=False,
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["ingreso_per_capita"] == 5000.0
    assert data["categoria_asignada"] == "N"


@pytest.mark.asyncio
async def test_anti_fraude_ingreso_cero_con_seguro(client, superuser_token, db_session):
    """Ingreso = 0 y tiene seguro → estado_alerta = REVISIÓN MANUAL URGENTE."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=0.0,
        ingreso_conyuge=0.0,
        integrantes_hogar=3,
        tiene_seguro=True,
        tipo_seguro="Caja Nacional de Salud (CNS)",
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["estado_alerta"] == "REVISIÓN MANUAL URGENTE"


@pytest.mark.asyncio
async def test_anti_fraude_categoria_A_vivienda_propia(client, superuser_token, db_session):
    """Categoría A con vivienda Propia y alquiler 0 → REVISIÓN MANUAL URGENTE."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=1200.0,
        ingreso_conyuge=0.0,
        integrantes_hogar=4,   # per cápita = 300 → A
        tiene_seguro=False,
        tipo_vivienda="Propia",
        monto_alquiler=0.0,
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["categoria_asignada"] == "A"
    assert data["estado_alerta"] == "REVISIÓN MANUAL URGENTE"


@pytest.mark.asyncio
async def test_evaluacion_estado_alerta_normal(client, superuser_token, db_session):
    """Caso coherente → estado_alerta = NORMAL."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=3000.0,
        ingreso_conyuge=1000.0,
        integrantes_hogar=4,   # per cápita = 1000 → B
        tiene_seguro=False,
        tipo_vivienda="Alquilada",
        monto_alquiler=800.0,
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["estado_alerta"] == "NORMAL"


@pytest.mark.asyncio
async def test_obtener_evaluacion_por_patient_id(client, superuser_token, db_session):
    """GET /social-evaluations/{patient_id} retorna la evaluación guardada."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(patient.id)

    # Primero crear
    await client.post("/social-evaluations/", json=payload)

    # Luego consultar
    resp = await client.get(f"/social-evaluations/{patient.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["patient_id"] == patient.id
    assert data["departamento"] == "La Paz"


@pytest.mark.asyncio
async def test_obtener_evaluacion_no_existente_retorna_404(client, superuser_token, db_session):
    """GET /social-evaluations/{patient_id} sin evaluación previa → 404."""
    patient = await _crear_patient(db_session)
    resp = await client.get(f"/social-evaluations/{patient.id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upsert_sobreescribe_evaluacion_previa(client, superuser_token, db_session):
    """
    Si el mismo paciente ya tiene evaluación, el POST la actualiza (upsert).
    No debe crear un duplicado — la tabla tiene restricción UNIQUE en patient_id.
    """
    patient = await _crear_patient(db_session)
    payload_inicial = _payload_base(patient.id, departamento="Cochabamba")
    payload_actualizado = _payload_base(patient.id, departamento="Santa Cruz")

    # Primera evaluación
    r1 = await client.post("/social-evaluations/", json=payload_inicial)
    assert r1.status_code == 201

    # Segunda evaluación para el mismo paciente → debe actualizarse, no fallar
    r2 = await client.post("/social-evaluations/", json=payload_actualizado)
    assert r2.status_code == 201
    assert r2.json()["departamento"] == "Santa Cruz"

    # Verificar que solo existe una evaluación consultando por patient_id
    r3 = await client.get(f"/social-evaluations/{patient.id}")
    assert r3.status_code == 200
    assert r3.json()["departamento"] == "Santa Cruz"


@pytest.mark.asyncio
async def test_crear_evaluacion_paciente_inexistente_retorna_404(client, superuser_token, db_session):
    """POST con patient_id inexistente → 404."""
    payload = _payload_base(patient_id=999999)
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_crear_evaluacion_integrantes_cero_es_invalido(client, superuser_token, db_session):
    """integrantes_hogar = 0 viola la restricción ge=1 del schema → 422 Unprocessable."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(patient.id, integrantes_hogar=0)
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_listar_evaluaciones_super_admin(client, superuser_token, db_session):
    """GET /social-evaluations/ retorna lista de evaluaciones para SUPER_ADMIN."""
    # Crear al menos una evaluación
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))

    resp = await client.get("/social-evaluations/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_listar_evaluaciones_filtro_alerta_urgente(client, superuser_token, db_session):
    """
    GET /social-evaluations/?alerta_urgente=true
    Solo retorna evaluaciones en REVISIÓN MANUAL URGENTE.
    """
    patient = await _crear_patient(db_session)
    payload_alerta = _payload_base(
        patient.id,
        ingreso_titular=0.0,
        ingreso_conyuge=0.0,
        integrantes_hogar=3,
        tiene_seguro=True,
        tipo_seguro="SUS",
    )
    await client.post("/social-evaluations/", json=payload_alerta)

    resp = await client.get("/social-evaluations/", params={"alerta_urgente": True})
    assert resp.status_code == 200
    data = resp.json()
    assert all(e["estado_alerta"] == "REVISIÓN MANUAL URGENTE" for e in data)


# ─────────────────────────────────────────────────────────────────────────────
#  SECCIÓN 4: CONTROL DE ACCESO POR ROL
# ─────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def evaluador_token(client, db_session):
    """Fixture: usuario con rol EVALUADOR_SOCIAL activo."""
    from app.main import app as the_app
    from app.api import deps
    from app.api.endpoints.evaluations import get_evaluator_or_admin

    evaluador = models.User(
        email=f"evaluador_{uuid.uuid4().hex[:8]}@test.com",
        password_hash="fakehash",
        role="EVALUADOR_SOCIAL",
        estado="ACTIVO",
    )
    db_session.add(evaluador)
    await db_session.commit()
    await db_session.refresh(evaluador)

    async def override():
        return evaluador

    the_app.dependency_overrides[get_evaluator_or_admin] = override
    the_app.dependency_overrides[deps.get_current_active_user] = override
    the_app.dependency_overrides[deps.get_current_user] = override

    yield evaluador

    the_app.dependency_overrides.pop(get_evaluator_or_admin, None)
    the_app.dependency_overrides.pop(deps.get_current_active_user, None)
    the_app.dependency_overrides.pop(deps.get_current_user, None)


@pytest.mark.asyncio
async def test_evaluador_social_puede_crear_evaluacion(client, evaluador_token, db_session):
    """EVALUADOR_SOCIAL puede crear una evaluación sin restricciones."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(patient.id)
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201
    assert resp.json()["patient_id"] == patient.id


@pytest.mark.asyncio
async def test_evaluador_social_puede_consultar_evaluacion(client, evaluador_token, db_session):
    """EVALUADOR_SOCIAL puede consultar su propia evaluación creada."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(patient.id)
    await client.post("/social-evaluations/", json=payload)

    resp = await client.get(f"/social-evaluations/{patient.id}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_paciente_no_puede_acceder_al_modulo(client, patient_token, db_session):
    """
    El rol PACIENTE no debe tener acceso al módulo de evaluación.
    Se espera 403 Forbidden.
    """
    from app.main import app as the_app
    from app.api.endpoints.evaluations import get_evaluator_or_admin

    # Restaurar el override para que use la validación real de rol
    the_app.dependency_overrides.pop(get_evaluator_or_admin, None)

    patient = await _crear_patient(db_session)
    payload = _payload_base(patient.id)
    resp = await client.post("/social-evaluations/", json=payload)
    # El paciente no es SUPER_ADMIN ni EVALUADOR_SOCIAL → 403
    assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
#  SECCIÓN 5: AUTOSERVICIO DEL BENEFICIARIO (rol PACIENTE) — /social-evaluations/me
# ─────────────────────────────────────────────────────────────────────────────

def _self_payload_base(**overrides) -> dict:
    """Payload válido base para los endpoints de autoservicio (sin patient_id)."""
    data = {
        "departamento": "La Paz",
        "integrantes_hogar": 4,
        "dependientes": 2,
        "tipo_vivienda": "Alquilada",
        "monto_alquiler": 600.0,
        "tiene_seguro": False,
        "tipo_seguro": None,
        "condicion_laboral": "Independiente / Cuenta propia",
        "ingreso_titular": 1800.0,
        "ingreso_conyuge": 0.0,
        "habeas_data_accepted": True,
        "imagen_consent_accepted": True,
    }
    data.update(overrides)
    return data


@pytest_asyncio.fixture
async def own_patient(db_session, patient_token) -> models.Patient:
    """Ficha de Patient asociada al usuario PACIENTE de la fixture `patient_token`."""
    patient = models.Patient(
        user_id=patient_token.id,
        nombres="Ana",
        ap_paterno="Flores",
        ci=f"CI-{uuid.uuid4().hex[:6]}",
        fecha_nac=date(1990, 3, 10),
        estado="PENDIENTE_DOC",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


@pytest.mark.asyncio
async def test_paciente_crea_su_propia_evaluacion(client, patient_token, own_patient):
    """El beneficiario autenticado puede crear su propia evaluación vía /me."""
    resp = await client.post("/social-evaluations/me", json=_self_payload_base())
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["patient_id"] == own_patient.id
    assert data["estado_revision"] == "PENDIENTE"
    assert data["evaluator_id"] is None
    assert data["categoria_asignada"] == "A"  # 1800/4 = 450, sin seguro


@pytest.mark.asyncio
async def test_paciente_sin_ficha_no_puede_crear_evaluacion(client, patient_token):
    """Un usuario PACIENTE sin ficha de Patient asociada recibe 404."""
    resp = await client.post("/social-evaluations/me", json=_self_payload_base())
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_paciente_obtiene_su_propia_evaluacion(client, patient_token, own_patient):
    """GET /social-evaluations/me retorna la evaluación del beneficiario autenticado."""
    await client.post("/social-evaluations/me", json=_self_payload_base())
    resp = await client.get("/social-evaluations/me")
    assert resp.status_code == 200
    assert resp.json()["patient_id"] == own_patient.id


@pytest.mark.asyncio
async def test_paciente_sin_evaluacion_get_me_retorna_404(client, patient_token, own_patient):
    """Sin evaluación previa, GET /social-evaluations/me retorna 404 (sin borrador)."""
    resp = await client.get("/social-evaluations/me")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_paciente_reenvio_tras_rechazo_resetea_a_pendiente(client, patient_token, own_patient, db_session):
    """Reenviar la evaluación tras un rechazo la vuelve a dejar PENDIENTE, limpiando el motivo."""
    await client.post("/social-evaluations/me", json=_self_payload_base())

    result = await db_session.execute(
        select(models.SocialEvaluation).where(models.SocialEvaluation.patient_id == own_patient.id)
    )
    evaluation = result.scalars().first()
    evaluation.estado_revision = "RECHAZADO"
    evaluation.motivo_rechazo = "Fotos ilegibles, vuelva a subirlas."
    await db_session.commit()

    resp = await client.post("/social-evaluations/me", json=_self_payload_base(departamento="Oruro"))
    assert resp.status_code == 201
    data = resp.json()
    assert data["estado_revision"] == "PENDIENTE"
    assert data["motivo_rechazo"] is None
    assert data["departamento"] == "Oruro"


@pytest.mark.asyncio
async def test_staff_no_puede_usar_endpoint_de_autoservicio(client, superuser_token):
    """El endpoint /me es exclusivo del rol PACIENTE; SUPER_ADMIN recibe 403."""
    resp = await client.post("/social-evaluations/me", json=_self_payload_base())
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_paciente_sube_documento_de_evaluacion(client, patient_token, own_patient, monkeypatch):
    """POST /me/upload-document sube a Firebase y retorna la URL pública, sin tocar la BD."""
    monkeypatch.setattr(evaluations_module, "upload_file_to_firebase", _fake_upload)

    resp = await client.post(
        "/social-evaluations/me/upload-document",
        data={"doc_type": "fachada"},
        files=_fake_file(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "fachada"
    assert body["url"].startswith("https://fake-storage.test/")
    assert f"pacientes/{own_patient.id}/" in body["url"]


@pytest.mark.asyncio
async def test_paciente_sube_documento_tipo_invalido(client, patient_token, own_patient, monkeypatch):
    """Un doc_type fuera del catálogo permitido retorna 400."""
    monkeypatch.setattr(evaluations_module, "upload_file_to_firebase", _fake_upload)

    resp = await client.post(
        "/social-evaluations/me/upload-document",
        data={"doc_type": "no_existe"},
        files=_fake_file(),
    )
    assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  SECCIÓN 6: REVISIÓN / AVAL DEL STAFF — PUT /{patient_id}/review
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_aprobar_evaluacion_exonera_al_paciente(client, superuser_token, db_session):
    """Aprobar la evaluación marca estado_revision=APROBADO y exonera al paciente del aporte."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "Entrevista sin novedades."})

    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["estado_revision"] == "APROBADO"
    assert data["reviewer_id"] is not None
    assert data["revisado_at"] is not None

    await db_session.refresh(patient)
    assert patient.exonerado_aporte is True


@pytest.mark.asyncio
async def test_rechazar_evaluacion_exige_motivo(client, superuser_token, db_session):
    """Rechazar sin motivo retorna 422."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))

    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "RECHAZADO"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_rechazar_evaluacion_con_motivo_no_exonera(client, superuser_token, db_session):
    """Rechazar con motivo guarda el motivo y no exonera al paciente."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "Entrevista realizada."})

    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "RECHAZADO", "motivo": "Datos inconsistentes con las fotos."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["estado_revision"] == "RECHAZADO"
    assert data["motivo_rechazo"] == "Datos inconsistentes con las fotos."

    await db_session.refresh(patient)
    assert patient.exonerado_aporte is False


@pytest.mark.asyncio
async def test_review_evaluacion_inexistente_retorna_404(client, superuser_token, db_session):
    """Revisar un patient_id sin evaluación previa retorna 404."""
    patient = await _crear_patient(db_session)
    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_paciente_no_puede_revisar_evaluaciones(client, patient_token, db_session):
    """El rol PACIENTE no puede llamar al endpoint de revisión staff."""
    from app.main import app as the_app
    from app.api.endpoints.evaluations import get_evaluator_or_admin

    the_app.dependency_overrides.pop(get_evaluator_or_admin, None)

    patient = await _crear_patient(db_session)
    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_evaluador_social_puede_listar_evaluaciones(client, evaluador_token, db_session):
    """EVALUADOR_SOCIAL puede listar evaluaciones (antes solo SUPER_ADMIN podía)."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))

    resp = await client.get("/social-evaluations/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_listar_evaluaciones_filtro_estado_revision(client, superuser_token, db_session):
    """GET /social-evaluations/?estado_revision=APROBADO solo retorna las avaladas."""
    patient_a = await _crear_patient(db_session)
    patient_b = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient_a.id))
    await client.post("/social-evaluations/", json=_payload_base(patient_b.id))
    await client.put(f"/social-evaluations/{patient_a.id}/interview", json={"notas": "OK"})

    await client.put(f"/social-evaluations/{patient_a.id}/review", json={"decision": "APROBADO"})

    resp = await client.get("/social-evaluations/", params={"estado_revision": "APROBADO"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert all(e["estado_revision"] == "APROBADO" for e in data)


# ─────────────────────────────────────────────────────────────────────────────
#  SECCIÓN 7: ENTREVISTA VIRTUAL PREVIA AL VEREDICTO — PUT /{patient_id}/interview
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_review_sin_entrevista_retorna_422(client, superuser_token, db_session):
    """No se puede avalar/rechazar sin haber registrado antes la entrevista."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))

    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO"},
    )
    assert resp.status_code == 422
    assert "entrevista" in resp.json()["detail"].lower()

    await db_session.refresh(patient)
    assert patient.exonerado_aporte is False


@pytest.mark.asyncio
async def test_registrar_entrevista_guarda_notas_y_fecha(client, superuser_token, db_session):
    """PUT /{patient_id}/interview marca entrevista_realizada=True y guarda notas/fecha."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))

    resp = await client.put(
        f"/social-evaluations/{patient.id}/interview",
        json={"notas": "Beneficiario confirma situación declarada por videollamada."},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["entrevista_realizada"] is True
    assert data["entrevista_fecha"] is not None
    assert data["entrevista_notas"] == "Beneficiario confirma situación declarada por videollamada."


@pytest.mark.asyncio
async def test_entrevista_habilita_el_veredicto(client, superuser_token, db_session):
    """Tras registrar la entrevista, el review ya no retorna 422."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "Sin observaciones."})

    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_registrar_entrevista_evaluacion_inexistente_retorna_404(client, superuser_token, db_session):
    """Registrar entrevista para un patient_id sin evaluación previa retorna 404."""
    patient = await _crear_patient(db_session)
    resp = await client.put(
        f"/social-evaluations/{patient.id}/interview",
        json={"notas": "N/A"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_evaluador_social_puede_registrar_entrevista(client, evaluador_token, db_session):
    """EVALUADOR_SOCIAL puede registrar la entrevista."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))

    resp = await client.put(
        f"/social-evaluations/{patient.id}/interview",
        json={"notas": "Entrevista realizada por videollamada."},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_paciente_no_puede_registrar_entrevista(client, patient_token, db_session):
    """El rol PACIENTE no puede llamar al endpoint de entrevista del staff."""
    from app.main import app as the_app
    from app.api.endpoints.evaluations import get_evaluator_or_admin

    the_app.dependency_overrides.pop(get_evaluator_or_admin, None)

    patient = await _crear_patient(db_session)
    resp = await client.put(
        f"/social-evaluations/{patient.id}/interview",
        json={"notas": "N/A"},
    )
    assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
#  SECCIÓN 8: AYUDA DE OTRA INSTITUCIÓN Y DESCUENTO POR DEUDAS (20%)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deudas_descuentan_20_por_ciento_para_la_categoria(client, superuser_token, db_session):
    """
    Ingreso = 2000, integrantes = 4 → sin deudas, per cápita = 500 (Categoría B).
    Con deudas que comprometen ingresos, se descuenta 20%: 2000*0.8 = 1600 / 4 = 400 → Categoría A.
    """
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=2000.0,
        ingreso_conyuge=0.0,
        integrantes_hogar=4,
        tiene_seguro=False,
        tiene_deudas_comprometen_ingresos=True,
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["ingreso_per_capita"] == 400.0
    assert data["categoria_asignada"] == "A"
    assert data["tiene_deudas_comprometen_ingresos"] is True


@pytest.mark.asyncio
async def test_sin_deudas_no_aplica_descuento(client, superuser_token, db_session):
    """Sin deudas declaradas, el per cápita usa el ingreso íntegro (sin descuento)."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=2000.0,
        ingreso_conyuge=0.0,
        integrantes_hogar=4,
        tiene_seguro=False,
        tiene_deudas_comprometen_ingresos=False,
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["ingreso_per_capita"] == 500.0
    assert data["categoria_asignada"] == "B"


@pytest.mark.asyncio
async def test_deudas_no_afecta_deteccion_de_fraude(client, superuser_token, db_session):
    """
    El módulo anti-fraude debe seguir usando el ingreso real declarado (no el
    descontado por deudas) para detectar inconsistencias.
    Ingreso = 0, tiene seguro, con deudas → sigue siendo REVISIÓN MANUAL URGENTE
    (0 * 0.8 sigue siendo 0, pero el chequeo usa el ingreso bruto de todas formas).
    """
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=0.0,
        ingreso_conyuge=0.0,
        integrantes_hogar=3,
        tiene_seguro=True,
        tipo_seguro="SUS",
        tiene_deudas_comprometen_ingresos=True,
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201
    assert resp.json()["estado_alerta"] == "REVISIÓN MANUAL URGENTE"


@pytest.mark.asyncio
async def test_ayuda_de_otra_institucion_se_guarda(client, superuser_token, db_session):
    """recibe_ayuda_otra_institucion y nombre_institucion_ayuda se guardan y devuelven."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        recibe_ayuda_otra_institucion=True,
        nombre_institucion_ayuda="Fundación Solidaria XYZ",
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["recibe_ayuda_otra_institucion"] is True
    assert data["nombre_institucion_ayuda"] == "Fundación Solidaria XYZ"


@pytest.mark.asyncio
async def test_ayuda_de_otra_institucion_default_false(client, superuser_token, db_session):
    """Sin especificar el campo, por defecto no recibe ayuda de otra institución."""
    patient = await _crear_patient(db_session)
    resp = await client.post("/social-evaluations/", json=_payload_base(patient.id))
    assert resp.status_code == 201
    data = resp.json()
    assert data["recibe_ayuda_otra_institucion"] is False
    assert data["nombre_institucion_ayuda"] is None


@pytest.mark.asyncio
async def test_paciente_self_service_deudas_y_ayuda_institucion(client, patient_token, own_patient):
    """El beneficiario también puede declarar deudas y ayuda de otra institución vía /me."""
    resp = await client.post(
        "/social-evaluations/me",
        json=_self_payload_base(
            ingreso_titular=2000.0,
            integrantes_hogar=4,
            tiene_deudas_comprometen_ingresos=True,
            recibe_ayuda_otra_institucion=True,
            nombre_institucion_ayuda="ONG Diabetes Bolivia",
        ),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["ingreso_per_capita"] == 400.0  # 2000*0.8/4
    assert data["categoria_asignada"] == "A"
    assert data["recibe_ayuda_otra_institucion"] is True
    assert data["nombre_institucion_ayuda"] == "ONG Diabetes Bolivia"
