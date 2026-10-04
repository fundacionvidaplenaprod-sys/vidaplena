"""
Morosos: beneficiarios ACTIVOS sin aporte ACEPTADO en el mes anterior.

Antes la tarjeta "Inactivos / morosos" del resumen mostraba
`total - activos - pendientes`, un resto aritmético que no miraba aportes: un
activo que no pagó no contaba como moroso. Ahora hay una sola definición
(`calcular_morosos`) usada por la tarjeta y por el listado.

La suite corre contra una base compartida con datos de otros tests, así que
las aserciones se hacen sobre los beneficiarios sembrados aquí y sobre
invariantes (tarjeta == listado), no sobre totales absolutos.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app import models
from app.core.contributions import periodo_anterior


# Hora de Bolivia (UTC-4, sin horario de verano).
LA_PAZ = timezone(timedelta(hours=-4))
# Ingreso anterior a cualquier periodo evaluado en estos tests.
INGRESO_ANTIGUO = datetime(2026, 1, 15, tzinfo=LA_PAZ)


async def _paciente(db_session, estado="ACTIVO", depto="La Paz", **extra):
    suffix = uuid.uuid4().hex[:8]
    extra.setdefault("created_at", INGRESO_ANTIGUO)
    patient = models.Patient(
        nombres=f"Moroso{suffix}",
        ap_paterno="Prueba",
        ci=f"MOR-{suffix}",
        fecha_nac=date(1990, 1, 1),
        estado=estado,
        depto=depto,
        tel_contacto="70000000",
        **extra,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


async def _aporte(db_session, patient, periodo, estado):
    db_session.add(models.MonthlyContribution(
        patient_id=patient.id, periodo=periodo, fecha_pago=date.today(),
        monto=100.0, url_comprobante="https://fake.test/v.jpg", estado=estado,
    ))
    await db_session.commit()


async def _morosos(client, **params):
    resp = await client.get("/reports/morosos", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ids(body):
    return {i["patient_id"]: i for i in body["items"]}


def test_periodo_anterior_cruza_el_cambio_de_anio():
    assert periodo_anterior(date(2026, 1, 15)) == "2025-12"
    assert periodo_anterior(date(2026, 10, 4)) == "2026-09"
    assert periodo_anterior(date(2026, 3, 31)) == "2026-02"


@pytest.mark.asyncio
async def test_por_defecto_evalua_el_mes_anterior(client, superuser_token):
    body = await _morosos(client)
    assert body["periodo"] == periodo_anterior()


@pytest.mark.asyncio
async def test_activo_sin_aporte_es_moroso(client, superuser_token, db_session):
    p = await _paciente(db_session)
    item = _ids(await _morosos(client, periodo="2026-09"))[p.id]
    assert item["motivo"] == "SIN_APORTE"
    assert item["patient_ci"] == p.ci
    assert item["tel_contacto"] == "70000000"


@pytest.mark.asyncio
async def test_activo_con_aporte_aceptado_no_es_moroso(client, superuser_token, db_session):
    p = await _paciente(db_session)
    await _aporte(db_session, p, "2026-09", "ACEPTADO")
    assert p.id not in _ids(await _morosos(client, periodo="2026-09"))


@pytest.mark.asyncio
@pytest.mark.parametrize("estado", ["DECLARADO", "OBSERVADO"])
async def test_aporte_no_aceptado_sigue_siendo_moroso_con_su_motivo(client, superuser_token, db_session, estado):
    p = await _paciente(db_session)
    await _aporte(db_session, p, "2026-09", estado)
    assert _ids(await _morosos(client, periodo="2026-09"))[p.id]["motivo"] == estado


@pytest.mark.asyncio
async def test_aporte_aceptado_de_otro_mes_no_salva_del_periodo_evaluado(client, superuser_token, db_session):
    p = await _paciente(db_session)
    await _aporte(db_session, p, "2026-10", "ACEPTADO")
    assert p.id in _ids(await _morosos(client, periodo="2026-09"))


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{"exonerado_aporte": True}, {"exonerado_por_cargo": True}])
async def test_los_exonerados_no_son_morosos(client, superuser_token, db_session, extra):
    p = await _paciente(db_session, **extra)
    assert p.id not in _ids(await _morosos(client, periodo="2026-09"))


@pytest.mark.asyncio
@pytest.mark.parametrize("estado", ["PENDIENTE_DOC", "NO_REGISTRADO", "INACTIVO", "HABILITADO"])
async def test_solo_los_activos_pueden_ser_morosos(client, superuser_token, db_session, estado):
    p = await _paciente(db_session, estado=estado)
    assert p.id not in _ids(await _morosos(client, periodo="2026-09"))


@pytest.mark.asyncio
async def test_filtro_por_departamento_tolera_mayusculas_y_tildes(client, superuser_token, db_session):
    lp = await _paciente(db_session, depto="La Paz")
    pt = await _paciente(db_session, depto="Potosí")
    ids = _ids(await _morosos(client, periodo="2026-09", depto="potosi"))
    assert pt.id in ids
    assert lp.id not in ids


@pytest.mark.asyncio
async def test_contadores_por_motivo_suman_el_total(client, superuser_token, db_session):
    body = await _morosos(client, periodo="2026-09")
    assert body["total"] == len(body["items"])
    assert body["total"] == body["sin_aporte"] + body["declarados"] + body["observados"]


@pytest.mark.asyncio
async def test_tarjeta_del_resumen_coincide_con_el_listado(client, superuser_token, db_session):
    """La tarjeta y el listado usan la misma función: no pueden discrepar."""
    await _paciente(db_session)
    pop = (await client.get("/reports/population")).json()
    listado = await _morosos(client, periodo=pop["periodo_morosos"])
    assert pop["periodo_morosos"] == periodo_anterior()
    assert pop["morosos"] == listado["total"]


@pytest.mark.asyncio
async def test_resumen_reparte_todos_los_estados_sin_perder_ninguno(client, superuser_token):
    pop = (await client.get("/reports/population")).json()
    suma = pop["activos"] + pop["pendientes_validacion"] + pop["inactivos"] + pop["otros_estados"]
    assert suma == pop["total_beneficiarios"]
    # La clave engañosa anterior ya no existe.
    assert "inactivos_morosos" not in pop


@pytest.mark.asyncio
async def test_periodo_invalido_es_422(client, superuser_token):
    resp = await client.get("/reports/morosos", params={"periodo": "2026-13"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_el_listado_exige_personal_autorizado(client, patient_token):
    resp = await client.get("/reports/morosos")
    assert resp.status_code in (401, 403)


# ─────────────────────────────────────────────────────────────────────────
#  NADIE DEBE UN PERIODO ANTERIOR A SU INGRESO
# ─────────────────────────────────────────────────────────────────────────

async def _usuario_creado_el(db_session, fecha):
    user = models.User(
        email=f"mor_{uuid.uuid4().hex[:8]}@test.com", password_hash="fakehash",
        role="PACIENTE", estado="ACTIVO", created_at=fecha,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_registrado_en_octubre_no_es_moroso_de_septiembre(client, superuser_token, db_session):
    p = await _paciente(db_session, created_at=datetime(2026, 10, 3, 10, 0, tzinfo=LA_PAZ))
    assert p.id not in _ids(await _morosos(client, periodo="2026-09"))


@pytest.mark.asyncio
async def test_registrado_en_octubre_si_debe_octubre(client, superuser_token, db_session):
    p = await _paciente(db_session, created_at=datetime(2026, 10, 3, 10, 0, tzinfo=LA_PAZ))
    assert p.id in _ids(await _morosos(client, periodo="2026-10"))


@pytest.mark.asyncio
async def test_precargado_del_padron_cuenta_desde_que_se_le_genero_el_usuario(client, superuser_token, db_session):
    """Ficha precargada en julio, registrada de verdad en octubre: no debe septiembre."""
    usuario = await _usuario_creado_el(db_session, datetime(2026, 10, 2, 9, 0, tzinfo=LA_PAZ))
    p = await _paciente(db_session, user_id=usuario.id, created_at=datetime(2026, 7, 10, tzinfo=LA_PAZ))
    assert p.id not in _ids(await _morosos(client, periodo="2026-09"))
    assert p.id in _ids(await _morosos(client, periodo="2026-10"))


@pytest.mark.asyncio
async def test_usuario_anterior_al_periodo_si_debe_ese_periodo(client, superuser_token, db_session):
    usuario = await _usuario_creado_el(db_session, datetime(2026, 8, 20, tzinfo=LA_PAZ))
    p = await _paciente(db_session, user_id=usuario.id, created_at=datetime(2026, 7, 10, tzinfo=LA_PAZ))
    assert p.id in _ids(await _morosos(client, periodo="2026-09"))


@pytest.mark.asyncio
async def test_el_mes_de_ingreso_se_toma_en_hora_de_bolivia(client, superuser_token, db_session):
    """30 de septiembre 22:00 en Bolivia es el 1 de octubre en UTC: sigue siendo septiembre."""
    p = await _paciente(db_session, created_at=datetime(2026, 9, 30, 22, 0, tzinfo=LA_PAZ))
    assert p.id in _ids(await _morosos(client, periodo="2026-09"))


# ─────────────────────────────────────────────────────────────────────────
#  EL INGRESO ES LA ACTIVACIÓN (aprobación de documentos)
# ─────────────────────────────────────────────────────────────────────────

async def _evento(db_session, patient, old, new, fecha):
    revisor = await _usuario_creado_el(db_session, INGRESO_ANTIGUO)
    db_session.add(models.PatientStatusEvent(
        patient_id=patient.id, user_id=revisor.id,
        old_state=old, new_state=new, created_at=fecha,
    ))
    await db_session.commit()


@pytest.mark.asyncio
async def test_activado_en_octubre_no_es_moroso_de_septiembre_aunque_su_usuario_sea_anterior(
    client, superuser_token, db_session
):
    """
    Usuario generado en agosto, pero los documentos se aprobaron en octubre:
    el compromiso empieza en octubre, no cuando se creó la cuenta.
    """
    usuario = await _usuario_creado_el(db_session, datetime(2026, 8, 20, tzinfo=LA_PAZ))
    p = await _paciente(db_session, user_id=usuario.id)
    await _evento(db_session, p, "HABILITADO", "ACTIVO", datetime(2026, 10, 3, 11, 0, tzinfo=LA_PAZ))

    assert p.id not in _ids(await _morosos(client, periodo="2026-09"))
    assert p.id in _ids(await _morosos(client, periodo="2026-10"))


@pytest.mark.asyncio
async def test_activado_en_agosto_si_debe_septiembre(client, superuser_token, db_session):
    p = await _paciente(db_session)
    await _evento(db_session, p, "HABILITADO", "ACTIVO", datetime(2026, 8, 12, tzinfo=LA_PAZ))
    assert p.id in _ids(await _morosos(client, periodo="2026-09"))


@pytest.mark.asyncio
async def test_reabrir_y_reactivar_no_reinicia_la_deuda(client, superuser_token, db_session):
    p = await _paciente(db_session)
    await _evento(db_session, p, "HABILITADO", "ACTIVO", datetime(2026, 8, 12, tzinfo=LA_PAZ))
    await _evento(db_session, p, "ACTIVO", "PENDIENTE_DOC", datetime(2026, 9, 10, tzinfo=LA_PAZ))
    await _evento(db_session, p, "PENDIENTE_DOC", "ACTIVO", datetime(2026, 10, 2, tzinfo=LA_PAZ))
    assert p.id in _ids(await _morosos(client, periodo="2026-09"))


@pytest.mark.asyncio
async def test_evento_de_salida_de_activo_tambien_prueba_que_ya_estaba_activo(client, superuser_token, db_session):
    """Sin el evento de entrada (antiguo), una salida de ACTIVO acota desde cuándo lo era."""
    p = await _paciente(db_session)
    await _evento(db_session, p, "ACTIVO", "PENDIENTE_DOC", datetime(2026, 8, 25, tzinfo=LA_PAZ))
    assert p.id in _ids(await _morosos(client, periodo="2026-09"))


@pytest.mark.asyncio
async def test_sin_evento_se_usa_el_respaldo_del_usuario(client, superuser_token, db_session):
    usuario = await _usuario_creado_el(db_session, datetime(2026, 10, 2, tzinfo=LA_PAZ))
    p = await _paciente(db_session, user_id=usuario.id)
    assert p.id not in _ids(await _morosos(client, periodo="2026-09"))


@pytest.mark.asyncio
async def test_el_mes_de_activacion_se_toma_en_hora_de_bolivia(client, superuser_token, db_session):
    """Activado el 30 de septiembre 22:00 (Bolivia) = 1 de octubre en UTC: sigue siendo septiembre."""
    p = await _paciente(db_session)
    await _evento(db_session, p, "HABILITADO", "ACTIVO", datetime(2026, 9, 30, 22, 0, tzinfo=LA_PAZ))
    assert p.id in _ids(await _morosos(client, periodo="2026-09"))
