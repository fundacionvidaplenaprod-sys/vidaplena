"""
tests/test_social_evaluation.py
================================
Suite de pruebas para el módulo de Evaluación Socioeconómica y Categorización
de Beneficiarios de la Fundación V.I.D.A. Plena.

Motor de categorización: Capacidad Financiera Neta Residual (CFNR) =
Ingresos Totales - (Canasta Básica Familiar + Vivienda/Servicios/Salud +
Transporte + Deudas). Ver `_build_categorization` en
app/api/endpoints/evaluations.py.

Cubre:
  1. Motor de Categorización CFNR puro (unitario, sin DB)
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
from datetime import date, timedelta
from sqlalchemy import select

from app import models
from app.api.endpoints import evaluations as evaluations_module
from app.api.endpoints.evaluations import (
    _calcular_categoria_cfnr,
    _canasta_familiar,
    _costo_vivienda,
    _evaluar_fraude,
)


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
    """
    Payload válido base para el endpoint de evaluación.
    Con estos valores por defecto: canasta(4)=3200, vivienda=600,
    salud/educación=2*275=550 → costo_vida=4350; ingreso_total=1800 →
    CFNR=-2550 (ALTA).
    """
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
        "ingreso_otros_familiares": 0.0,
        "monto_agua": 0.0,
        "monto_luz": 0.0,
        "monto_gas_domiciliario": 0.0,
        "monto_internet": 0.0,
        "monto_transporte": 0.0,
        "tiene_deudas_comprometen_ingresos": False,
        "monto_deuda_mensual": 0.0,
        "habeas_data_accepted": True,
        "imagen_consent_accepted": True,
    }
    data.update(overrides)
    return data


# ─────────────────────────────────────────────────────────────────────────────
#  SECCIÓN 1: PRUEBAS UNITARIAS DEL MOTOR DE CATEGORIZACIÓN (sin DB, sin HTTP)
# ─────────────────────────────────────────────────────────────────────────────

class TestCanastaFamiliar:
    """Pruebas puras de la escala de la canasta básica familiar por tamaño de hogar."""

    def test_una_persona(self):
        assert _canasta_familiar(1) == 1000.0

    def test_dos_personas(self):
        assert _canasta_familiar(2) == 1800.0

    def test_cuatro_personas(self):
        assert _canasta_familiar(4) == 3200.0

    def test_tres_personas_interpolado(self):
        """Entre 2 y 4 personas, +700 Bs por persona adicional."""
        assert _canasta_familiar(3) == 2500.0

    def test_integrantes_cero_se_trata_como_uno(self):
        assert _canasta_familiar(0) == _canasta_familiar(1)


class TestCostoVivienda:
    """Pruebas puras del costo de vivienda (alquiler declarado o mantenimiento estimado)."""

    def test_vivienda_alquilada_usa_monto_declarado(self):
        assert _costo_vivienda("Alquilada", 600.0) == 600.0

    def test_vivienda_propia_usa_mantenimiento_estimado(self):
        assert _costo_vivienda("Propia", 0.0) == 225.0

    def test_vivienda_propia_case_insensitive(self):
        assert _costo_vivienda("  PROPIA  ", 0.0) == 225.0

    def test_vivienda_familiar_usa_monto_declarado(self):
        assert _costo_vivienda("Familiar / Prestada", 0.0) == 0.0


class TestMotorCategorizacionCFNR:
    """Pruebas puras de la función _calcular_categoria_cfnr (Capacidad Financiera Neta Residual)."""

    def test_cfnr_negativo_es_alta(self):
        """CFNR negativo (déficit) → Vulnerabilidad ALTA."""
        assert _calcular_categoria_cfnr(-1300.0) == "ALTA"

    def test_cfnr_cero_es_alta(self):
        """CFNR exactamente 0 → ALTA (saldo cero, sin margen)."""
        assert _calcular_categoria_cfnr(0.0) == "ALTA"

    def test_cfnr_apenas_positivo_es_media(self):
        """CFNR = 1 Bs. → MEDIA."""
        assert _calcular_categoria_cfnr(1.0) == "MEDIA"

    def test_cfnr_rango_medio(self):
        """CFNR = 950 Bs. (ejemplo B del criterio) → MEDIA."""
        assert _calcular_categoria_cfnr(950.0) == "MEDIA"

    def test_cfnr_limite_superior_media(self):
        """CFNR exactamente 1500 Bs. → MEDIA (límite inclusivo)."""
        assert _calcular_categoria_cfnr(1500.0) == "MEDIA"

    def test_cfnr_sobre_limite_es_baja(self):
        """CFNR = 1501 Bs. → BAJA."""
        assert _calcular_categoria_cfnr(1501.0) == "BAJA"

    def test_cfnr_alto_es_baja(self):
        """CFNR muy alto → BAJA/Nula (situación acomodada)."""
        assert _calcular_categoria_cfnr(10_000.0) == "BAJA"


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
            categoria="MEDIA",
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
            categoria="ALTA",
            tipo_vivienda="Alquilada",
            monto_alquiler=500.0,
        )
        assert resultado == "REVISIÓN MANUAL URGENTE"

    def test_alerta_categoria_alta_vivienda_propia_sin_alquiler(self):
        """
        FRAUDE CASO 2: Vulnerabilidad ALTA (déficit) PERO vivienda es propia y alquiler = 0.
        Inconsistencia: si el déficit es tan alto, ¿cómo tiene vivienda propia?
        """
        resultado = _evaluar_fraude(
            ingreso_total=1200.0,
            tiene_seguro=False,
            categoria="ALTA",
            tipo_vivienda="Propia",
            monto_alquiler=0.0,
        )
        assert resultado == "REVISIÓN MANUAL URGENTE"

    def test_no_alerta_categoria_alta_vivienda_alquilada(self):
        """Vulnerabilidad ALTA con vivienda alquilada → consistente, sin alerta."""
        resultado = _evaluar_fraude(
            ingreso_total=1200.0,
            tiene_seguro=False,
            categoria="ALTA",
            tipo_vivienda="Alquilada",
            monto_alquiler=400.0,
        )
        assert resultado == "NORMAL"

    def test_no_alerta_categoria_media_vivienda_propia(self):
        """Vulnerabilidad MEDIA con vivienda propia → coherente, sin alerta."""
        resultado = _evaluar_fraude(
            ingreso_total=3000.0,
            tiene_seguro=False,
            categoria="MEDIA",
            tipo_vivienda="Propia",
            monto_alquiler=0.0,
        )
        assert resultado == "NORMAL"

    def test_ingreso_cero_sin_seguro_no_genera_alerta(self):
        """Ingreso = 0 y SIN seguro → sin inconsistencia detectada."""
        resultado = _evaluar_fraude(
            ingreso_total=0.0,
            tiene_seguro=False,
            categoria="ALTA",
            tipo_vivienda="Familiar / Prestada",
            monto_alquiler=0.0,
        )
        assert resultado == "NORMAL"

    def test_alerta_vivienda_propia_case_insensitive(self):
        """El chequeo de tipo_vivienda debe ser insensible a mayúsculas."""
        resultado = _evaluar_fraude(
            ingreso_total=500.0,
            tiene_seguro=False,
            categoria="ALTA",
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
    El motor de categorización calcula la CFNR y asigna la categoría al
    guardar en la DB.

    Con los valores base (integrantes=4, dependientes=2, vivienda alquilada
    600, sin servicios/transporte/deuda declarados): costo_vida = canasta(4)
    3200 + vivienda 600 + salud/educación 550 = 4350.
    Ingreso titular = 1800 → CFNR = 1800 - 4350 = -2550 → ALTA.
    Ingreso per cápita (dato de referencia) = 1800 / 4 = 450.
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
    assert data["costo_vida_estimado"] == 4350.0
    assert data["cfnr"] == -2550.0
    assert data["categoria_asignada"] == "ALTA"


@pytest.mark.asyncio
async def test_motor_categoriza_media(client, superuser_token, db_session):
    """
    Mismos costos base (4350), ingreso titular = 5000 →
    CFNR = 5000 - 4350 = 650 → MEDIA.
    """
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=5000.0,
        ingreso_conyuge=0.0,
        integrantes_hogar=4,
        tiene_seguro=False,
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["cfnr"] == 650.0
    assert data["categoria_asignada"] == "MEDIA"


@pytest.mark.asyncio
async def test_motor_categoriza_baja(client, superuser_token, db_session):
    """
    Mismos costos base (4350), ingreso titular = 7000 →
    CFNR = 7000 - 4350 = 2650 → BAJA (> 1500).
    """
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=7000.0,
        ingreso_conyuge=0.0,
        integrantes_hogar=4,
        tiene_seguro=False,
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["cfnr"] == 2650.0
    assert data["categoria_asignada"] == "BAJA"


@pytest.mark.asyncio
async def test_motor_categoriza_baja_ingreso_muy_alto(client, superuser_token, db_session):
    """Un ingreso muy alto también cae en BAJA (no existe una cuarta categoría)."""
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
    assert data["categoria_asignada"] == "BAJA"


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
async def test_anti_fraude_categoria_alta_vivienda_propia(client, superuser_token, db_session):
    """Vulnerabilidad ALTA (déficit) con vivienda Propia y alquiler 0 → REVISIÓN MANUAL URGENTE."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=1200.0,
        ingreso_conyuge=0.0,
        integrantes_hogar=4,   # costo_vida=3975 (canasta 3200+vivienda 225+salud/educ 550) → CFNR=-2775 → ALTA
        tiene_seguro=False,
        tipo_vivienda="Propia",
        monto_alquiler=0.0,
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["categoria_asignada"] == "ALTA"
    assert data["estado_alerta"] == "REVISIÓN MANUAL URGENTE"


@pytest.mark.asyncio
async def test_evaluacion_estado_alerta_normal(client, superuser_token, db_session):
    """Caso coherente → estado_alerta = NORMAL."""
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=3000.0,
        ingreso_conyuge=1000.0,
        integrantes_hogar=4,   # vivienda alquilada → el chequeo #2 (vivienda propia) no aplica
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
async def test_registrador_puede_consultar_evaluacion(client, db_session):
    """
    REGISTRADOR puede LEER la evaluación de un paciente — el expediente del
    beneficiario (visible para todo el staff) muestra el informe del
    evaluador social, aunque REGISTRADOR no pueda crear/revisar evaluaciones.
    """
    from app.main import app as the_app
    from app.api import deps

    registrador = models.User(
        email=f"registrador_{uuid.uuid4().hex[:8]}@test.com",
        password_hash="fakehash",
        role="REGISTRADOR",
        estado="ACTIVO",
    )
    db_session.add(registrador)
    await db_session.commit()
    await db_session.refresh(registrador)

    async def override():
        return registrador

    the_app.dependency_overrides[deps.get_current_active_user] = override
    the_app.dependency_overrides[deps.get_current_user] = override

    try:
        patient = await _crear_patient(db_session)

        # Crear la evaluación como SUPER_ADMIN (REGISTRADOR no puede crearla).
        the_app.dependency_overrides.pop(deps.get_current_active_user, None)
        the_app.dependency_overrides.pop(deps.get_current_user, None)
        admin = models.User(
            email=f"admin_{uuid.uuid4().hex[:8]}@test.com",
            password_hash="fakehash", role="SUPER_ADMIN", estado="ACTIVO",
        )
        db_session.add(admin)
        await db_session.commit()
        await db_session.refresh(admin)

        async def override_admin():
            return admin

        from app.api.endpoints.evaluations import get_evaluator_or_admin
        the_app.dependency_overrides[get_evaluator_or_admin] = override_admin
        the_app.dependency_overrides[deps.get_current_active_user] = override_admin
        the_app.dependency_overrides[deps.get_current_user] = override_admin
        await client.post("/social-evaluations/", json=_payload_base(patient.id))
        the_app.dependency_overrides.pop(get_evaluator_or_admin, None)

        # REGISTRADOR consulta (solo lectura) esa misma evaluación.
        the_app.dependency_overrides[deps.get_current_active_user] = override
        the_app.dependency_overrides[deps.get_current_user] = override
        resp = await client.get(f"/social-evaluations/{patient.id}")
        assert resp.status_code == 200, resp.text

        # Pero no puede crear/revisar (queda restringido a evaluador/admin).
        resp_forbidden = await client.post("/social-evaluations/", json=_payload_base(patient.id))
        assert resp_forbidden.status_code == 403
    finally:
        the_app.dependency_overrides.pop(deps.get_current_active_user, None)
        the_app.dependency_overrides.pop(deps.get_current_user, None)


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
    """
    Payload válido base para los endpoints de autoservicio (sin patient_id).
    Mismos valores/CFNR que `_payload_base` (costo_vida=4350, CFNR=-2550, ALTA).
    """
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
        "ingreso_otros_familiares": 0.0,
        "monto_agua": 0.0,
        "monto_luz": 0.0,
        "monto_gas_domiciliario": 0.0,
        "monto_internet": 0.0,
        "monto_transporte": 0.0,
        "tiene_deudas_comprometen_ingresos": False,
        "monto_deuda_mensual": 0.0,
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
    assert data["categoria_asignada"] == "ALTA"  # CFNR = 1800 - 4350 = -2550


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
        json={"decision": "APROBADO", "categoria_final": "ALTA"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["estado_revision"] == "APROBADO"
    assert data["reviewer_id"] is not None
    assert data["categoria_final"] == "ALTA"
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
        json={"decision": "APROBADO", "categoria_final": "ALTA"},
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

    await client.put(
        f"/social-evaluations/{patient_a.id}/review",
        json={"decision": "APROBADO", "categoria_final": "MEDIA", "monto_comprometido": 150.0},
    )

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
        json={"decision": "APROBADO", "categoria_final": "ALTA"},
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
async def test_registrar_entrevista_admite_notas_largas(client, superuser_token, db_session):
    """
    Regresión: `notas` tenía un tope de 2000 caracteres que rechazaba (422)
    apreciaciones detalladas del evaluador social — la columna en BD es
    Text (sin límite práctico), así que el tope debe ser generoso.
    """
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))

    notas_largas = "Apreciación detallada del evaluador social. " * 100  # ~4600 caracteres
    assert len(notas_largas) > 2000

    resp = await client.put(
        f"/social-evaluations/{patient.id}/interview",
        json={"notas": notas_largas},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["entrevista_notas"] == notas_largas


@pytest.mark.asyncio
async def test_entrevista_habilita_el_veredicto(client, superuser_token, db_session):
    """Tras registrar la entrevista, el review ya no retorna 422."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "Sin observaciones."})

    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO", "categoria_final": "ALTA"},
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
#  SECCIÓN 8: AYUDA DE OTRA INSTITUCIÓN Y DEUDAS EN EL CFNR
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_monto_deuda_mensual_se_resta_del_cfnr(client, superuser_token, db_session):
    """
    1 integrante, sin dependientes, vivienda propia (canasta 1000 + mantenimiento 225 = 1225).
    Ingreso = 1300 → sin deudas: CFNR = 1300 - 1225 = 75 → MEDIA.
    Declarando una cuota de deuda de Bs. 500/mes: CFNR = 1300 - 1725 = -425 → ALTA.
    """
    patient = await _crear_patient(db_session)
    base_kwargs = dict(
        ingreso_titular=1300.0, ingreso_conyuge=0.0, integrantes_hogar=1, dependientes=0,
        tipo_vivienda="Propia", monto_alquiler=0.0, tiene_seguro=False,
    )

    payload_sin_deuda = _payload_base(patient.id, **base_kwargs, tiene_deudas_comprometen_ingresos=False)
    resp1 = await client.post("/social-evaluations/", json=payload_sin_deuda)
    assert resp1.status_code == 201, resp1.text
    data1 = resp1.json()
    assert data1["cfnr"] == 75.0
    assert data1["categoria_asignada"] == "MEDIA"

    payload_con_deuda = _payload_base(
        patient.id, **base_kwargs,
        tiene_deudas_comprometen_ingresos=True, monto_deuda_mensual=500.0,
    )
    resp2 = await client.post("/social-evaluations/", json=payload_con_deuda)
    assert resp2.status_code == 201, resp2.text
    data2 = resp2.json()
    assert data2["cfnr"] == -425.0
    assert data2["categoria_asignada"] == "ALTA"
    assert data2["tiene_deudas_comprometen_ingresos"] is True


@pytest.mark.asyncio
async def test_monto_deuda_ignorado_si_no_declara_deudas(client, superuser_token, db_session):
    """
    Si tiene_deudas_comprometen_ingresos es False, el backend ignora cualquier
    monto_deuda_mensual recibido (evita que un monto quede "colgado" en la BD).
    """
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        ingreso_titular=1300.0, ingreso_conyuge=0.0, integrantes_hogar=1, dependientes=0,
        tipo_vivienda="Propia", monto_alquiler=0.0, tiene_seguro=False,
        tiene_deudas_comprometen_ingresos=False, monto_deuda_mensual=999.0,
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["cfnr"] == 75.0
    assert data["categoria_asignada"] == "MEDIA"


@pytest.mark.asyncio
async def test_deudas_no_afecta_deteccion_de_fraude(client, superuser_token, db_session):
    """
    El módulo anti-fraude sigue usando el ingreso real declarado (no el CFNR)
    para detectar inconsistencias. Ingreso = 0, tiene seguro, con deudas →
    sigue siendo REVISIÓN MANUAL URGENTE.
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
        monto_deuda_mensual=200.0,
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
    """
    El beneficiario también puede declarar deudas y ayuda de otra institución vía /me.
    costo_vida = canasta(4) 3200 + vivienda 600 + salud/educ 550 + deuda 300 = 4650.
    CFNR = 2000 - 4650 = -2650 → ALTA.
    """
    resp = await client.post(
        "/social-evaluations/me",
        json=_self_payload_base(
            ingreso_titular=2000.0,
            integrantes_hogar=4,
            tiene_deudas_comprometen_ingresos=True,
            monto_deuda_mensual=300.0,
            recibe_ayuda_otra_institucion=True,
            nombre_institucion_ayuda="ONG Diabetes Bolivia",
        ),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["ingreso_per_capita"] == 500.0  # 2000/4, dato de referencia
    assert data["cfnr"] == -2650.0
    assert data["categoria_asignada"] == "ALTA"
    assert data["recibe_ayuda_otra_institucion"] is True
    assert data["nombre_institucion_ayuda"] == "ONG Diabetes Bolivia"


# ─────────────────────────────────────────────────────────────────────────────
#  SECCIÓN 9: RECHAZO EN DOS NIVELES (cooldown / suspensión) + HISTORIAL
# ─────────────────────────────────────────────────────────────────────────────

async def _aprobar_o_rechazar(client, patient, decision, motivo=None):
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "Entrevista."})
    payload = {"decision": decision}
    if motivo:
        payload["motivo"] = motivo
    return await client.put(f"/social-evaluations/{patient.id}/review", json=payload)


@pytest.mark.asyncio
async def test_rechazo_estandar_aplica_cooldown_6_meses(client, superuser_token, db_session):
    """Un rechazo RECHAZADO (Nivel 1) bloquea el reenvío por 6 meses desde hoy."""
    patient = await _crear_patient(db_session)
    resp = await _aprobar_o_rechazar(client, patient, "RECHAZADO", "No cumple criterios.")
    assert resp.status_code == 200, resp.text

    await db_session.refresh(patient)
    assert patient.estado_beneficio == "ACTIVO"
    assert patient.evaluacion_bloqueada_hasta is not None
    # Diferencia de ~6 meses (tolerante a variaciones de longitud de mes).
    delta_dias = (patient.evaluacion_bloqueada_hasta - date.today()).days
    assert 175 <= delta_dias <= 186


@pytest.mark.asyncio
async def test_rechazo_por_falsedad_suspende_permanentemente(client, superuser_token, db_session):
    """RECHAZADO_FRAUDE (Nivel 2) suspende al paciente y no aplica cooldown temporal."""
    patient = await _crear_patient(db_session)
    resp = await _aprobar_o_rechazar(client, patient, "RECHAZADO_FRAUDE", "Documentos falsificados.")
    assert resp.status_code == 200, resp.text
    assert resp.json()["estado_revision"] == "RECHAZADO_FRAUDE"

    await db_session.refresh(patient)
    assert patient.estado_beneficio == "SUSPENDIDO"
    assert patient.evaluacion_bloqueada_hasta is None
    assert patient.exonerado_aporte is False


@pytest.mark.asyncio
async def test_rechazo_por_falsedad_exige_motivo(client, superuser_token, db_session):
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "Entrevista."})

    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "RECHAZADO_FRAUDE"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_reenvio_bloqueado_durante_cooldown(client, patient_token, own_patient, db_session):
    """Tras un rechazo estándar, /me devuelve 403 con la fecha de reactivación."""
    own_patient.evaluacion_bloqueada_hasta = date.today() + timedelta(days=90)
    await db_session.commit()
    resp = await client.post("/social-evaluations/me", json=_self_payload_base())
    assert resp.status_code == 403
    assert "someterse a evaluación" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_reenvio_bloqueado_si_suspendido(client, patient_token, own_patient, db_session):
    """Un paciente suspendido no puede enviar una nueva evaluación."""
    own_patient.estado_beneficio = "SUSPENDIDO"
    await db_session.commit()
    resp = await client.post("/social-evaluations/me", json=_self_payload_base())
    assert resp.status_code == 403
    assert "suspendido" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_staff_no_puede_crear_evaluacion_para_paciente_bloqueado(client, superuser_token, db_session):
    """El endpoint staff también respeta el bloqueo (no es una vía para saltarlo)."""
    patient = await _crear_patient(db_session)
    patient.estado_beneficio = "SUSPENDIDO"
    await db_session.commit()

    resp = await client.post("/social-evaluations/", json=_payload_base(patient.id))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_eligibility_refleja_cooldown(client, patient_token, own_patient, db_session):
    own_patient.evaluacion_bloqueada_hasta = date.today() + timedelta(days=30)
    await db_session.commit()
    resp = await client.get("/social-evaluations/me/eligibility")
    assert resp.status_code == 200
    data = resp.json()
    assert data["puede_evaluar"] is False
    assert data["suspendido"] is False
    assert data["bloqueado_hasta"] == own_patient.evaluacion_bloqueada_hasta.isoformat()


@pytest.mark.asyncio
async def test_eligibility_refleja_suspension(client, patient_token, own_patient, db_session):
    own_patient.estado_beneficio = "SUSPENDIDO"
    await db_session.commit()
    resp = await client.get("/social-evaluations/me/eligibility")
    assert resp.status_code == 200
    data = resp.json()
    assert data["puede_evaluar"] is False
    assert data["suspendido"] is True


@pytest.mark.asyncio
async def test_eligibility_activo_puede_evaluar(client, patient_token, own_patient):
    resp = await client.get("/social-evaluations/me/eligibility")
    assert resp.status_code == 200
    assert resp.json()["puede_evaluar"] is True


@pytest.mark.asyncio
async def test_reactivar_permite_reenvio(client, superuser_token, db_session, patient_token, own_patient):
    """SUPER_ADMIN reactiva a un paciente suspendido y este ya puede volver a enviar su evaluación."""
    own_patient.estado_beneficio = "SUSPENDIDO"
    await db_session.commit()

    resp_reactivar = await client.put(f"/social-evaluations/{own_patient.id}/reactivate")
    assert resp_reactivar.status_code == 200, resp_reactivar.text
    assert resp_reactivar.json()["puede_evaluar"] is True

    await db_session.refresh(own_patient)
    assert own_patient.estado_beneficio == "ACTIVO"
    assert own_patient.evaluacion_bloqueada_hasta is None

    resp_envio = await client.post("/social-evaluations/me", json=_self_payload_base())
    assert resp_envio.status_code == 201


@pytest.mark.asyncio
async def test_reactivar_requiere_super_admin(client, evaluador_token, db_session):
    """EVALUADOR_SOCIAL no puede reactivar — es exclusivo de SUPER_ADMIN."""
    patient = await _crear_patient(db_session)
    patient.estado_beneficio = "SUSPENDIDO"
    await db_session.commit()

    resp = await client.put(f"/social-evaluations/{patient.id}/reactivate")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_reactivar_paciente_inexistente_retorna_404(client, superuser_token):
    resp = await client.put("/social-evaluations/999999999/reactivate")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_historial_registra_veredictos_pasados(client, superuser_token, db_session):
    """
    GET /{patient_id}/history conserva cada veredicto aunque la evaluación
    "actual" luego se sobreescriba con un reenvío.
    """
    patient = await _crear_patient(db_session)
    resp = await _aprobar_o_rechazar(client, patient, "RECHAZADO", "Fotos ilegibles.")
    assert resp.status_code == 200, resp.text

    resp_hist = await client.get(f"/social-evaluations/{patient.id}/history")
    assert resp_hist.status_code == 200
    hist = resp_hist.json()
    assert len(hist) == 1
    assert hist[0]["accion"] == "RECHAZADO"
    assert hist[0]["payload"]["motivo_rechazo"] == "Fotos ilegibles."
    assert hist[0]["actor_id"] is not None


@pytest.mark.asyncio
async def test_historial_acumula_multiples_veredictos(client, superuser_token, db_session):
    """Varios veredictos consecutivos del mismo paciente se acumulan, más reciente primero."""
    patient = await _crear_patient(db_session)
    r1 = await _aprobar_o_rechazar(client, patient, "RECHAZADO", "Primer rechazo.")
    assert r1.status_code == 200, r1.text
    r2 = await _aprobar_o_rechazar(client, patient, "RECHAZADO_FRAUDE", "Segundo rechazo: fraude.")
    assert r2.status_code == 200, r2.text

    resp_hist = await client.get(f"/social-evaluations/{patient.id}/history")
    hist = resp_hist.json()
    assert len(hist) == 2
    assert hist[0]["accion"] == "RECHAZADO_FRAUDE"
    assert hist[1]["accion"] == "RECHAZADO"


@pytest.mark.asyncio
async def test_historial_requiere_staff(client, patient_token, own_patient):
    resp = await client.get(f"/social-evaluations/{own_patient.id}/history")
    assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
#  SECCIÓN 10: [QA] DELETE /debug-delete/{patient_id} — borrado físico temporal
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_debug_delete_borra_fisicamente_la_evaluacion(client, superuser_token, db_session):
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))

    resp = await client.delete(f"/social-evaluations/debug-delete/{patient.id}")
    assert resp.status_code == 204

    result = await db_session.execute(
        select(models.SocialEvaluation).where(models.SocialEvaluation.patient_id == patient.id)
    )
    assert result.scalars().first() is None

    # El paciente puede volver a llenar el formulario desde cero.
    resp_get = await client.get(f"/social-evaluations/{patient.id}")
    assert resp_get.status_code == 404


@pytest.mark.asyncio
async def test_debug_delete_no_existente_no_falla(client, superuser_token, db_session):
    """Si no hay evaluación para ese paciente, es un no-op (204), no un error."""
    patient = await _crear_patient(db_session)
    resp = await client.delete(f"/social-evaluations/debug-delete/{patient.id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_debug_delete_requiere_super_admin(client, evaluador_token, db_session):
    """EVALUADOR_SOCIAL no puede usar el borrado físico — exclusivo de SUPER_ADMIN."""
    patient = await _crear_patient(db_session)
    resp = await client.delete(f"/social-evaluations/debug-delete/{patient.id}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_debug_delete_no_borra_el_historial(client, superuser_token, db_session):
    """El borrado físico no toca el historial en AuditLog (precedente se conserva)."""
    patient = await _crear_patient(db_session)
    resp_reject = await _aprobar_o_rechazar(client, patient, "RECHAZADO_FRAUDE", "Falsificación detectada.")
    assert resp_reject.status_code == 200, resp_reject.text

    resp_delete = await client.delete(f"/social-evaluations/debug-delete/{patient.id}")
    assert resp_delete.status_code == 204

    resp_hist = await client.get(f"/social-evaluations/{patient.id}/history")
    assert resp_hist.status_code == 200
    assert len(resp_hist.json()) == 1
    assert resp_hist.json()[0]["accion"] == "RECHAZADO_FRAUDE"


# ─────────────────────────────────────────────────────────────────────────────
#  SECCIÓN 11: SERVICIOS DEL HOGAR + CATEGORÍA FINAL ELEGIDA POR EL EVALUADOR
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_servicios_del_hogar_se_guardan(client, superuser_token, db_session):
    patient = await _crear_patient(db_session)
    payload = _payload_base(
        patient.id,
        tiene_agua=True,
        tiene_luz=True,
        tiene_gas_domiciliario=False,
        tiene_internet=True,
    )
    resp = await client.post("/social-evaluations/", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["tiene_agua"] is True
    assert data["tiene_luz"] is True
    assert data["tiene_gas_domiciliario"] is False
    assert data["tiene_internet"] is True


@pytest.mark.asyncio
async def test_servicios_del_hogar_default_false(client, superuser_token, db_session):
    patient = await _crear_patient(db_session)
    resp = await client.post("/social-evaluations/", json=_payload_base(patient.id))
    assert resp.status_code == 201
    data = resp.json()
    assert data["tiene_agua"] is False
    assert data["tiene_luz"] is False
    assert data["tiene_gas_domiciliario"] is False
    assert data["tiene_internet"] is False


@pytest.mark.asyncio
async def test_aprobar_sin_categoria_final_retorna_422(client, superuser_token, db_session):
    """No se puede aprobar sin elegir la categoría final."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "OK"})

    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO"},
    )
    assert resp.status_code == 422
    assert "categoría" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_aprobar_con_categoria_final_invalida_retorna_422(client, superuser_token, db_session):
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "OK"})

    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO", "categoria_final": "EXTREMA"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_categoria_final_puede_diferir_de_la_sugerida(client, superuser_token, db_session):
    """
    El sistema sugiere ALTA (payload base tiene CFNR muy negativo), pero el
    entrevistador, con su criterio, elige MEDIA como categoría final.
    """
    patient = await _crear_patient(db_session)
    resp_create = await client.post("/social-evaluations/", json=_payload_base(patient.id))
    assert resp_create.json()["categoria_asignada"] == "ALTA"
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "OK"})

    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO", "categoria_final": "MEDIA", "monto_comprometido": 150.0},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["categoria_asignada"] == "ALTA"  # la sugerencia del sistema no cambia
    assert data["categoria_final"] == "MEDIA"  # lo que el evaluador decidió


@pytest.mark.asyncio
async def test_aprobacion_alta_exonera_totalmente(client, superuser_token, db_session):
    """ALTA es la única categoría que exonera por completo (no queda monto comprometido)."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "OK"})
    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO", "categoria_final": "ALTA"},
    )
    assert resp.status_code == 200, resp.text

    await db_session.refresh(patient)
    assert patient.exonerado_aporte is True
    assert patient.monto_aporte_comprometido is None


@pytest.mark.asyncio
async def test_aprobacion_baja_no_exonera(client, superuser_token, db_session):
    """BAJA es pudiente y puede pagar: no hay exoneración ni monto fijo, vuelve al aporte normal."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "OK"})
    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO", "categoria_final": "BAJA"},
    )
    assert resp.status_code == 200, resp.text

    await db_session.refresh(patient)
    assert patient.exonerado_aporte is False
    assert patient.monto_aporte_comprometido is None


@pytest.mark.asyncio
async def test_aprobacion_media_requiere_monto_comprometido(client, superuser_token, db_session):
    """MEDIA no exonera del todo: sin monto_comprometido, la aprobación es rechazada con 422."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "OK"})
    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO", "categoria_final": "MEDIA"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_aprobacion_media_fija_monto_y_no_exonera(client, superuser_token, db_session):
    """MEDIA fija el monto reducido que definió el evaluador; no hay exoneración total."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "OK"})
    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO", "categoria_final": "MEDIA", "monto_comprometido": 200.0},
    )
    assert resp.status_code == 200, resp.text

    await db_session.refresh(patient)
    assert patient.exonerado_aporte is False
    assert float(patient.monto_aporte_comprometido) == 200.0


@pytest.mark.asyncio
async def test_exclusion_sugerida_requiere_motivo(client, superuser_token, db_session):
    """Marcar exclusion_sugerida sin motivo_exclusion_sugerida es 422."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "OK"})
    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO", "categoria_final": "BAJA", "exclusion_sugerida": True},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_exclusion_sugerida_solo_aplica_a_baja(client, superuser_token, db_session):
    """exclusion_sugerida con categoria_final distinto de BAJA es 422."""
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "OK"})
    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={
            "decision": "APROBADO",
            "categoria_final": "MEDIA",
            "monto_comprometido": 150.0,
            "exclusion_sugerida": True,
            "motivo_exclusion_sugerida": "Tiene un negocio propio.",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_exclusion_sugerida_se_guarda_con_baja_sin_cambiar_estado(client, superuser_token, db_session):
    """
    BAJA + exclusion_sugerida queda registrada, pero es solo una sugerencia:
    el estado del beneficiario (ACTIVO, sin exoneración) no cambia solo por
    marcarla.
    """
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "OK"})
    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={
            "decision": "APROBADO",
            "categoria_final": "BAJA",
            "exclusion_sugerida": True,
            "motivo_exclusion_sugerida": "Es propietario de un negocio y tiene ingresos estables altos.",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["exclusion_sugerida"] is True
    assert data["motivo_exclusion_sugerida"] == "Es propietario de un negocio y tiene ingresos estables altos."

    await db_session.refresh(patient)
    assert patient.exonerado_aporte is False  # BAJA es pudiente: no se exonera, paga el aporte completo
    assert patient.estado_beneficio == "ACTIVO"  # no se suspende solo por la sugerencia

    resp_hist = await client.get(f"/social-evaluations/{patient.id}/history")
    hist = resp_hist.json()
    assert hist[0]["payload"]["exclusion_sugerida"] is True
    assert hist[0]["payload"]["motivo_exclusion_sugerida"] == "Es propietario de un negocio y tiene ingresos estables altos."


@pytest.mark.asyncio
async def test_categoria_final_no_se_guarda_en_rechazo(client, superuser_token, db_session):
    patient = await _crear_patient(db_session)
    resp = await _aprobar_o_rechazar(client, patient, "RECHAZADO", "No cumple criterios.")
    assert resp.status_code == 200, resp.text
    assert resp.json()["categoria_final"] is None


@pytest.mark.asyncio
async def test_categoria_final_se_archiva_en_historial(client, superuser_token, db_session):
    patient = await _crear_patient(db_session)
    await client.post("/social-evaluations/", json=_payload_base(patient.id))
    await client.put(f"/social-evaluations/{patient.id}/interview", json={"notas": "OK"})
    resp = await client.put(
        f"/social-evaluations/{patient.id}/review",
        json={"decision": "APROBADO", "categoria_final": "BAJA"},
    )
    assert resp.status_code == 200, resp.text

    resp_hist = await client.get(f"/social-evaluations/{patient.id}/history")
    hist = resp_hist.json()
    assert len(hist) == 1
    assert hist[0]["payload"]["categoria_final"] == "BAJA"
    assert hist[0]["payload"]["categoria_asignada"] == "ALTA"
