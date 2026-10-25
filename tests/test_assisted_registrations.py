"""
Registro Asistido por Situación Excepcional (reglamento especial).

Lo que el reglamento obliga y estas pruebas protegen:
- ningún dato es obligatorio: se registra a una persona sin llenar nada y recibe su Código Interno;
- no se exige ninguna constancia para entregar insumos;
- acceso restringido al Evaluador Social, la Coordinación y la Dirección Ejecutiva;
- gratuidad: las personas asistidas no entran en los reportes de aportes ni de morosos;
- revisión de vigencia semestral, cese solo por las causas del Art. 23 y denegación motivada.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import models
from app.api import deps
from app.main import app

URL = "/assisted-registrations"


async def _usuario(db_session, role):
    user = models.User(
        email=f"asistido_{role.lower()}_{uuid.uuid4().hex[:8]}@test.com",
        password_hash="fakehash",
        role=role,
        estado="ACTIVO",
        depto_asignado="La Paz" if role == "RESPONSABLE_DEPARTAMENTAL" else None,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _como(db_session, role):
    """Cambia el usuario autenticado de la prueba a uno con otro rol."""
    user = await _usuario(db_session, role)

    async def override():
        return user

    app.dependency_overrides[deps.get_current_active_user] = override
    app.dependency_overrides[deps.get_current_user] = override
    return user


@pytest.mark.asyncio
async def test_se_registra_sin_ningun_dato_y_recibe_su_codigo_interno(client, superuser_token):
    resp = await client.post(f"{URL}/", json={})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["codigo"] == f"RA-{body['id']:05d}"
    assert body["estado"] == "ACTIVO"
    assert body["nombre"] is None and body["entidad_nombre"] is None and body["treatments"] == []
    assert body["revision_vencida"] is False

    otra = await client.post(f"{URL}/", json={})
    assert otra.json()["codigo"] != body["codigo"]  # el código es único


@pytest.mark.asyncio
async def test_registro_completo_con_entidad_referente_y_tratamiento(client, superuser_token):
    resp = await client.post(
        f"{URL}/",
        json={
            "nombre": "  Iniciales J.P.  ",
            "rango_edad": "12-17",
            "depto": "Cochabamba",
            "ciudad_localidad": "Quillacollo",
            "entidad_nombre": "Hogar Esperanza",
            "entidad_tipo": "CENTRO_ACOGIDA",
            "referente_nombre": "Lic. Rosa",
            "referente_vinculo": "TRABAJADOR_SOCIAL",
            "referente_contacto": "70000000",
            "insumos_requeridos": "Jeringas y tiras reactivas",
            "urgente": True,
            "buen_uso_comunicado": True,
            "treatments": [{"insulina": "Glargina", "dosis_diaria": 20}, {"insulina": "Lispro"}],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["nombre"] == "Iniciales J.P."  # sin espacios sobrantes
    assert (body["entidad_tipo"], body["urgente"]) == ("CENTRO_ACOGIDA", True)
    assert body["buen_uso_comunicado_at"] is not None
    assert [(t["insulina"], t["dosis_diaria"]) for t in body["treatments"]] == [("Glargina", 20.0), ("Lispro", None)]


@pytest.mark.asyncio
async def test_los_campos_en_blanco_cuentan_como_sin_dato_y_los_valores_invalidos_se_rechazan(client, superuser_token):
    en_blanco = await client.post(f"{URL}/", json={"nombre": "   ", "entidad_tipo": "", "depto": ""})
    assert en_blanco.status_code == 201
    assert en_blanco.json()["nombre"] is None and en_blanco.json()["entidad_tipo"] is None

    mala = await client.post(f"{URL}/", json={"entidad_tipo": "CARCEL_DE_MAXIMA"})
    assert mala.status_code == 422
    edad = await client.post(f"{URL}/", json={"edad_aproximada": 300})
    assert edad.status_code == 422


@pytest.mark.asyncio
async def test_se_puede_completar_el_registro_despues(client, superuser_token):
    creado = (await client.post(f"{URL}/", json={"urgente": True})).json()

    resp = await client.put(
        f"{URL}/{creado['id']}",
        json={
            "nombre": "Apodo Beto",
            "entidad_nombre": "Albergue Central",
            "urgente": False,
            "treatments": [{"insulina": "NPH", "dosis_diaria": 12}],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["nombre"], body["entidad_nombre"], body["urgente"]) == ("Apodo Beto", "Albergue Central", False)
    assert [t["insulina"] for t in body["treatments"]] == ["NPH"]

    # lo omitido queda igual; la cadena vacía borra el dato
    resp = await client.put(f"{URL}/{creado['id']}", json={"nombre": ""})
    assert resp.json()["nombre"] is None
    assert resp.json()["entidad_nombre"] == "Albergue Central"
    assert [t["insulina"] for t in resp.json()["treatments"]] == ["NPH"]


@pytest.mark.asyncio
async def test_la_entrega_no_exige_constancia_ni_ningun_dato_del_receptor(client, superuser_token):
    reg = (await client.post(f"{URL}/", json={})).json()

    resp = await client.post(f"{URL}/{reg['id']}/entregas", json={"insumo": "Insulina Glargina", "cantidad": "2 frascos"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["total_entregas"] == 1 and body["ultima_entrega"] == date.today().isoformat()
    [entrega] = body["deliveries"]
    assert (entrega["insumo"], entrega["cantidad"], entrega["constancia_tipo"]) == ("Insulina Glargina", "2 frascos", None)
    assert entrega["entregado_por"].endswith("@test.com")

    con_constancia = await client.post(
        f"{URL}/{reg['id']}/entregas",
        json={"insumo": "Jeringas", "cantidad": "30", "receptor_tipo": "PERSONAL_SALUD", "constancia_tipo": "TESTIMONIO_PERSONAL"},
    )
    assert con_constancia.status_code == 201
    futura = await client.post(
        f"{URL}/{reg['id']}/entregas",
        json={"insumo": "Jeringas", "cantidad": "1", "fecha": (date.today() + timedelta(days=2)).isoformat()},
    )
    assert futura.status_code == 400


@pytest.mark.asyncio
async def test_la_revision_semestral_marca_los_registros_vencidos(client, superuser_token, db_session):
    reg = (await client.post(f"{URL}/", json={"nombre": "Revisión"})).json()
    assert reg["revision_vencida"] is False

    # siete meses sin revisar
    fila = (await db_session.execute(select(models.AssistedRegistration).where(models.AssistedRegistration.id == reg["id"]))).scalars().one()
    fila.created_at = datetime.now(timezone.utc) - timedelta(days=210)
    await db_session.commit()

    vencidos = await client.get(f"{URL}/", params={"revision_vencida": "true"})
    assert reg["id"] in [r["id"] for r in vencidos.json()]
    detalle = (await client.get(f"{URL}/{reg['id']}")).json()
    assert detalle["revision_vencida"] is True

    resp = await client.post(f"{URL}/{reg['id']}/revision")
    assert resp.status_code == 200
    assert resp.json()["revision_vencida"] is False
    assert resp.json()["ultima_revision_at"] is not None
    vencidos = await client.get(f"{URL}/", params={"revision_vencida": "true"})
    assert reg["id"] not in [r["id"] for r in vencidos.json()]


@pytest.mark.asyncio
async def test_el_cese_solo_admite_las_causas_del_reglamento_y_cierra_el_registro(client, superuser_token):
    reg = (await client.post(f"{URL}/", json={})).json()

    # la pérdida de contacto no es causal de cese
    perdida = await client.post(f"{URL}/{reg['id']}/cese", json={"causa": "PERDIDA_DE_CONTACTO"})
    assert perdida.status_code == 422
    # una falta grave exige detalle
    sin_detalle = await client.post(f"{URL}/{reg['id']}/cese", json={"causa": "FALTA_GRAVE"})
    assert sin_detalle.status_code == 422

    resp = await client.post(f"{URL}/{reg['id']}/cese", json={"causa": "SIN_NECESIDAD", "detalle": "Ya no usa insulina"})
    assert resp.status_code == 200, resp.text
    assert (resp.json()["estado"], resp.json()["cese_causa"]) == ("CESADO", "SIN_NECESIDAD")
    assert resp.json()["revision_vencida"] is False  # un registro cesado no se revisa

    # cesado: ya no admite entregas ni cambios
    assert (await client.post(f"{URL}/{reg['id']}/entregas", json={"insumo": "X", "cantidad": "1"})).status_code == 400
    assert (await client.put(f"{URL}/{reg['id']}", json={"nombre": "Otro"})).status_code == 400


@pytest.mark.asyncio
async def test_el_traslado_al_registro_ordinario_puede_enlazar_la_ficha(client, superuser_token, db_session):
    paciente = models.Patient(
        nombres="Transito", ap_paterno=f"Ordinario{uuid.uuid4().hex[:6]}", ci=f"TR{uuid.uuid4().hex[:8]}",
        fecha_nac=date(2000, 1, 1), estado="HABILITADO",
    )
    db_session.add(paciente)
    await db_session.commit()
    await db_session.refresh(paciente)

    reg = (await client.post(f"{URL}/", json={})).json()
    otra_causa = await client.post(f"{URL}/{reg['id']}/cese", json={"causa": "RENUNCIA", "patient_id": paciente.id})
    assert otra_causa.status_code == 422
    inexistente = await client.post(f"{URL}/{reg['id']}/cese", json={"causa": "TRASLADO_REGIMEN_ORDINARIO", "patient_id": 99999999})
    assert inexistente.status_code == 404

    resp = await client.post(f"{URL}/{reg['id']}/cese", json={"causa": "TRASLADO_REGIMEN_ORDINARIO", "patient_id": paciente.id})
    assert resp.status_code == 200
    assert resp.json()["patient_id"] == paciente.id


@pytest.mark.asyncio
async def test_la_denegacion_es_motivada_y_solo_antes_de_entregar(client, superuser_token):
    sin_entregas = (await client.post(f"{URL}/", json={})).json()
    corta = await client.post(f"{URL}/{sin_entregas['id']}/denegar", json={"motivo": "no"})
    assert corta.status_code == 422
    resp = await client.post(
        f"{URL}/{sin_entregas['id']}/denegar", json={"motivo": "Manifiesta ausencia de necesidad de insulina."}
    )
    assert resp.status_code == 200
    assert (resp.json()["estado"], resp.json()["motivo_denegacion"]) == ("DENEGADO", "Manifiesta ausencia de necesidad de insulina.")

    con_entregas = (await client.post(f"{URL}/", json={})).json()
    await client.post(f"{URL}/{con_entregas['id']}/entregas", json={"insumo": "Insulina", "cantidad": "1"})
    rechazada = await client.post(f"{URL}/{con_entregas['id']}/denegar", json={"motivo": "Ya no la necesita, según se informó."})
    assert rechazada.status_code == 400  # corresponde el cese


@pytest.mark.asyncio
async def test_busqueda_por_codigo_nombre_o_entidad_sin_tildes(client, superuser_token):
    marca = uuid.uuid4().hex[:6]
    reg = (
        await client.post(f"{URL}/", json={"nombre": f"José {marca}", "entidad_nombre": "Hogar Niño Jesús", "depto": "Oruro"})
    ).json()

    for texto in (reg["codigo"], f"jose {marca}", "nino jesus", marca.upper()):
        ids = [r["id"] for r in (await client.get(f"{URL}/", params={"q": texto})).json()]
        assert reg["id"] in ids, texto
    por_estado = await client.get(f"{URL}/", params={"estado": "CESADO", "q": marca})
    assert por_estado.json() == []
    por_depto = await client.get(f"{URL}/", params={"depto": "oruro", "q": marca})
    assert [r["id"] for r in por_depto.json()] == [reg["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", ["EVALUADOR_SOCIAL", "COORDINADOR_NACIONAL"])
async def test_evaluador_y_coordinacion_acceden(client, superuser_token, db_session, rol):
    await _como(db_session, rol)
    assert (await client.post(f"{URL}/", json={})).status_code == 201
    assert (await client.get(f"{URL}/")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", ["REGISTRADOR", "RESPONSABLE_DEPARTAMENTAL", "PACIENTE"])
async def test_los_demas_roles_no_ven_nada_del_modulo(client, superuser_token, db_session, rol):
    reg = (await client.post(f"{URL}/", json={})).json()  # lo crea el admin de la fixture
    await _como(db_session, rol)
    assert (await client.get(f"{URL}/")).status_code == 403
    assert (await client.get(f"{URL}/{reg['id']}")).status_code == 403
    assert (await client.post(f"{URL}/", json={})).status_code == 403
    assert (await client.post(f"{URL}/{reg['id']}/entregas", json={"insumo": "X", "cantidad": "1"})).status_code == 403


@pytest.mark.asyncio
async def test_solo_el_evaluador_social_o_la_direccion_deniegan_la_admision(client, superuser_token, db_session):
    reg = (await client.post(f"{URL}/", json={})).json()
    await _como(db_session, "COORDINADOR_NACIONAL")
    resp = await client.post(f"{URL}/{reg['id']}/denegar", json={"motivo": "Manifiesta ausencia de necesidad."})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_las_personas_asistidas_no_entran_en_los_reportes_de_aportes(client, superuser_token, db_session):
    antes = (await client.get("/reports/population")).json()
    await client.post(f"{URL}/", json={"nombre": "Sin aporte", "treatments": [{"insulina": "Glargina", "dosis_diaria": 20}]})
    despues = (await client.get("/reports/population")).json()
    assert despues["total_beneficiarios"] == antes["total_beneficiarios"]
    assert despues["morosos"] == antes["morosos"]


@pytest.mark.asyncio
async def test_la_bitacora_no_guarda_datos_personales(client, superuser_token, db_session):
    reg = (await client.post(f"{URL}/", json={"nombre": "Nombre Secreto", "referente_contacto": "77777777"})).json()
    logs = (
        await db_session.execute(
            select(models.AuditLog).where(
                models.AuditLog.entidad == "assisted_registration", models.AuditLog.entidad_id == reg["id"]
            )
        )
    ).scalars().all()
    assert [l.accion for l in logs] == ["CREATE"]
    assert "Secreto" not in str(logs[0].payload) and "7777" not in str(logs[0].payload)
