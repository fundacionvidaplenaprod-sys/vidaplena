"""
Registro Asistido por Situación Excepcional (reglamento especial).

Lo que se protege:
- los datos de la persona asistida son opcionales: se registra con solo su persona referente y el
  vínculo, y recibe un Código Interno;
- la persona referente SÍ es obligatoria (nombre completo, C.I., teléfono y foto personal) y una misma
  persona puede serlo de varios beneficiarios; el vínculo no admite «no se sabe»;
- no se exige constancia para entregar insumos;
- acceso restringido al Evaluador Social, la Coordinación y la Dirección Ejecutiva;
- gratuidad: las personas asistidas no entran en los reportes de aportes ni de morosos;
- revisión de vigencia semestral, cese solo por las causas del Art. 23 y denegación motivada.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app import models
from app.api import deps
from app.api.endpoints import assisted_registrations as assisted_module
from app.main import app

URL = "/assisted-registrations"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def _firebase_falso(monkeypatch):
    """Las fotos no se suben a Firebase en las pruebas."""
    monkeypatch.setattr(
        assisted_module, "upload_file_to_firebase", lambda content, path, content_type: f"https://storage.test/{path}"
    )


async def _crear_referente(client, *, nombre="Rosa Quispe Mamani", ci=None, telefono="70123456", foto=("foto.png", PNG, "image/png")):
    ci = ci or f"RF{uuid.uuid4().hex[:8]}"
    files = {"foto": foto} if foto else None
    return await client.post(
        f"{URL}/referentes",
        data={"nombre_completo": nombre, "ci": ci, "telefono": telefono},
        files=files,
    )


@pytest_asyncio.fixture
async def ref(client, superuser_token):
    resp = await _crear_referente(client)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _datos(ref, **extra):
    """Cuerpo mínimo de un registro: persona referente y vínculo; el resto es opcional."""
    return {"referente_id": ref["id"], "referente_vinculo": "FAMILIAR", **extra}


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


# --- Persona referente -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_la_persona_referente_exige_nombre_ci_telefono_y_foto(client, superuser_token):
    ok = await _crear_referente(client)
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert body["foto_url"].startswith("https://storage.test/registro_asistido/referentes/")
    assert body["registros_activos"] == 0

    sin_foto = await _crear_referente(client, foto=None)
    assert sin_foto.status_code == 422
    sin_nombre = await _crear_referente(client, nombre="  ")
    assert sin_nombre.status_code == 422
    sin_ci = await _crear_referente(client, ci=" ")
    assert sin_ci.status_code == 422
    # el C.I. en blanco se reemplaza por uno generado: usamos un valor vacío explícito
    resp = await client.post(
        f"{URL}/referentes",
        data={"nombre_completo": "Juan Pérez", "ci": "", "telefono": "70123456"},
        files={"foto": ("f.png", PNG, "image/png")},
    )
    assert resp.status_code == 422
    sin_tel = await _crear_referente(client, telefono="abc")
    assert sin_tel.status_code == 422


@pytest.mark.asyncio
async def test_la_foto_debe_ser_una_imagen_de_hasta_2_mb(client, superuser_token):
    pdf = await _crear_referente(client, foto=("doc.pdf", b"%PDF-1.4 x", "application/pdf"))
    assert pdf.status_code == 400
    grande = await _crear_referente(client, foto=("grande.png", PNG + b"0" * (2 * 1024 * 1024), "image/png"))
    assert grande.status_code == 413
    vacia = await _crear_referente(client, foto=("vacia.png", b"", "image/png"))
    assert vacia.status_code == 400


@pytest.mark.asyncio
async def test_el_mismo_ci_no_se_registra_dos_veces_como_persona_referente(client, superuser_token):
    ci = f"DUP{uuid.uuid4().hex[:6]}"
    primera = await _crear_referente(client, ci=ci)
    assert primera.status_code == 201
    segunda = await _crear_referente(client, ci=ci.lower(), nombre="Otra Persona")
    assert segunda.status_code == 409
    assert "Rosa Quispe" in segunda.json()["detail"]  # indica a quién pertenece


@pytest.mark.asyncio
async def test_una_misma_persona_referente_puede_serlo_de_varios_beneficiarios(client, superuser_token, ref):
    a = (await client.post(f"{URL}/", json=_datos(ref))).json()
    b = (await client.post(f"{URL}/", json=_datos(ref, referente_vinculo="AMISTAD"))).json()

    detalle = (await client.get(f"{URL}/{a['id']}")).json()
    assert detalle["referente"]["registros_activos"] == 2
    assert detalle["referente_vinculo"] == "FAMILIAR" and b["referente_vinculo"] == "AMISTAD"  # el vínculo es por beneficiario

    ficha = (await client.get(f"{URL}/referentes/{ref['id']}")).json()
    assert ficha["codigos"] == [a["codigo"], b["codigo"]]

    # al cesar uno, deja de contar entre sus registros activos
    await client.post(f"{URL}/{b['id']}/cese", json={"causa": "RENUNCIA"})
    assert (await client.get(f"{URL}/referentes/{ref['id']}")).json()["codigos"] == [a["codigo"]]


@pytest.mark.asyncio
async def test_busca_personas_referentes_por_nombre_o_ci_sin_tildes(client, superuser_token):
    marca = uuid.uuid4().hex[:6]
    creada = (await _crear_referente(client, nombre=f"María Pérez {marca}", ci=f"CI{marca}")).json()
    for texto in (f"maria perez {marca}", f"ci{marca}", marca.upper()):
        ids = [r["id"] for r in (await client.get(f"{URL}/referentes", params={"q": texto})).json()]
        assert creada["id"] in ids, texto
    assert (await client.get(f"{URL}/referentes", params={"q": f"zzz{marca}"})).json() == []


@pytest.mark.asyncio
async def test_se_puede_corregir_la_persona_referente_y_cambiar_su_foto(client, superuser_token, ref):
    resp = await client.put(
        f"{URL}/referentes/{ref['id']}",
        data={"telefono": "76543210"},
        files={"foto": ("nueva.jpg", PNG, "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["telefono"] == "76543210"
    assert resp.json()["foto_url"].endswith("foto.jpg")
    assert resp.json()["nombre_completo"] == ref["nombre_completo"]  # lo omitido queda igual


@pytest.mark.asyncio
async def test_una_persona_referente_anterior_sin_ci_ni_foto_se_completa_con_los_dos(client, superuser_token, db_session):
    legado = models.AssistedReferent(nombre_completo="Legado Sin Datos", telefono="7000000")
    db_session.add(legado)
    await db_session.commit()
    await db_session.refresh(legado)

    sin_foto = await client.put(f"{URL}/referentes/{legado.id}", data={"ci": "LEG123"})
    assert sin_foto.status_code == 422
    assert "foto" in sin_foto.json()["detail"].lower()
    completo = await client.put(
        f"{URL}/referentes/{legado.id}", data={"ci": f"LEG{uuid.uuid4().hex[:5]}"}, files={"foto": ("f.png", PNG, "image/png")}
    )
    assert completo.status_code == 200 and completo.json()["foto_url"]


# --- Registro ----------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_se_registra_con_solo_la_persona_referente_y_recibe_su_codigo_interno(client, superuser_token, ref):
    resp = await client.post(f"{URL}/", json=_datos(ref))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["codigo"] == f"RA-{body['id']:05d}"
    assert body["estado"] == "ACTIVO"
    assert body["nombre"] is None and body["ci"] is None and body["treatments"] == []
    assert body["referente"]["nombre_completo"] == ref["nombre_completo"]
    assert body["referente_pendiente"] is False
    otra = await client.post(f"{URL}/", json=_datos(ref))
    assert otra.json()["codigo"] != body["codigo"]  # el código es único


@pytest.mark.asyncio
async def test_sin_persona_referente_o_sin_vinculo_no_se_registra(client, superuser_token, ref):
    sin_nada = await client.post(f"{URL}/", json={})
    assert sin_nada.status_code == 422
    sin_referente = await client.post(f"{URL}/", json={"referente_vinculo": "FAMILIAR"})
    assert sin_referente.status_code == 422
    sin_vinculo = await client.post(f"{URL}/", json={"referente_id": ref["id"]})
    assert sin_vinculo.status_code == 422
    inexistente = await client.post(f"{URL}/", json={"referente_id": 99999999, "referente_vinculo": "FAMILIAR"})
    assert inexistente.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("vinculo", ["NO_SE_SABE", "", "PERSONAL_SALUD", "OTRO"])
async def test_el_vinculo_solo_admite_familiar_conocido_referido_o_amistad(client, superuser_token, ref, vinculo):
    resp = await client.post(f"{URL}/", json={"referente_id": ref["id"], "referente_vinculo": vinculo})
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("vinculo", ["FAMILIAR", "CONOCIDO", "REFERIDO_POR_TERCEROS", "AMISTAD"])
async def test_los_cuatro_vinculos_validos(client, superuser_token, ref, vinculo):
    resp = await client.post(f"{URL}/", json=_datos(ref, referente_vinculo=vinculo))
    assert resp.status_code == 201
    assert resp.json()["referente_vinculo"] == vinculo


@pytest.mark.asyncio
async def test_registro_completo_con_los_datos_complementarios(client, superuser_token, ref):
    resp = await client.post(
        f"{URL}/",
        json=_datos(
            ref,
            nombre="  Iniciales J.P.  ",
            ci="9876543",
            fecha_nacimiento="1990-05-17",
            rango_edad="18-59",
            depto="Cochabamba",
            municipio="Quillacollo",
            ciudad_localidad="Vinto",
            tipo_diabetes="Tipo 1",
            anios_diabetes=8,
            complicaciones_otras="Hipertensión, neuropatía",
            entidad_nombre="Recinto San Sebastián",
            entidad_tipo="RECINTO_PENITENCIARIO",
            insumos_requeridos="Jeringas y tiras reactivas",
            urgente=True,
            buen_uso_comunicado=True,
            treatments=[{"insulina": "Glargina", "dosis_diaria": 20}, {"insulina": "Lispro"}],
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["nombre"] == "Iniciales J.P."  # sin espacios sobrantes
    assert (body["ci"], body["fecha_nacimiento"]) == ("9876543", "1990-05-17")
    assert (body["depto"], body["municipio"]) == ("Cochabamba", "Quillacollo")
    assert (body["tipo_diabetes"], body["anios_diabetes"]) == ("Tipo 1", 8)
    assert body["complicaciones_otras"] == "Hipertensión, neuropatía"
    assert (body["entidad_tipo"], body["urgente"]) == ("RECINTO_PENITENCIARIO", True)
    assert body["buen_uso_comunicado_at"] is not None
    assert [(t["insulina"], t["dosis_diaria"]) for t in body["treatments"]] == [("Glargina", 20.0), ("Lispro", None)]


@pytest.mark.asyncio
async def test_los_campos_en_blanco_cuentan_como_sin_dato_y_los_valores_invalidos_se_rechazan(client, superuser_token, ref):
    en_blanco = await client.post(
        f"{URL}/", json=_datos(ref, nombre="   ", entidad_tipo="", depto="", ci="", fecha_nacimiento="", tipo_diabetes="")
    )
    assert en_blanco.status_code == 201, en_blanco.text
    body = en_blanco.json()
    assert body["nombre"] is None and body["entidad_tipo"] is None and body["ci"] is None
    assert body["fecha_nacimiento"] is None and body["tipo_diabetes"] is None

    for mala in (
        {"entidad_tipo": "CARCEL_DE_MAXIMA"},
        {"edad_aproximada": 300},
        {"tipo_diabetes": "Tipo 9"},
        {"anios_diabetes": 150},
        {"fecha_nacimiento": (date.today() + timedelta(days=1)).isoformat()},
        {"fecha_nacimiento": "1850-01-01"},
    ):
        assert (await client.post(f"{URL}/", json=_datos(ref, **mala))).status_code == 422, mala


@pytest.mark.asyncio
async def test_se_puede_completar_el_registro_despues_y_cambiar_de_persona_referente(client, superuser_token, ref):
    creado = (await client.post(f"{URL}/", json=_datos(ref, urgente=True))).json()
    otra_ref = (await _crear_referente(client, nombre="Pedro Condori")).json()

    resp = await client.put(
        f"{URL}/{creado['id']}",
        json={
            "nombre": "Apodo Beto",
            "municipio": "Sacaba",
            "tipo_diabetes": "Tipo 2",
            "urgente": False,
            "referente_id": otra_ref["id"],
            "referente_vinculo": "CONOCIDO",
            "treatments": [{"insulina": "NPH", "dosis_diaria": 12}],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["nombre"], body["municipio"], body["tipo_diabetes"], body["urgente"]) == ("Apodo Beto", "Sacaba", "Tipo 2", False)
    assert (body["referente"]["id"], body["referente_vinculo"]) == (otra_ref["id"], "CONOCIDO")
    assert [t["insulina"] for t in body["treatments"]] == ["NPH"]

    # lo omitido queda igual; la cadena vacía borra un dato de la persona, pero nunca el vínculo
    resp = await client.put(f"{URL}/{creado['id']}", json={"nombre": ""})
    assert resp.json()["nombre"] is None and resp.json()["municipio"] == "Sacaba"
    assert resp.json()["referente"]["id"] == otra_ref["id"]
    assert (await client.put(f"{URL}/{creado['id']}", json={"referente_vinculo": ""})).status_code == 422
    assert (await client.put(f"{URL}/{creado['id']}", json={"referente_id": 99999999})).status_code == 404


@pytest.mark.asyncio
async def test_un_registro_anterior_sin_persona_referente_queda_marcado_como_pendiente(client, superuser_token, db_session):
    legado = models.AssistedRegistration(estado="ACTIVO", nombre="Registro anterior")
    db_session.add(legado)
    await db_session.flush()
    legado.codigo = f"RA-{legado.id:05d}"
    await db_session.commit()

    detalle = (await client.get(f"{URL}/{legado.id}")).json()
    assert detalle["referente_pendiente"] is True and detalle["referente"] is None


@pytest.mark.asyncio
async def test_la_entrega_no_exige_constancia_ni_ningun_dato_del_receptor(client, superuser_token, ref):
    reg = (await client.post(f"{URL}/", json=_datos(ref))).json()

    resp = await client.post(f"{URL}/{reg['id']}/entregas", json={"insumo": "Insulina Glargina", "cantidad": "2 frascos"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["total_entregas"] == 1 and body["ultima_entrega"] == date.today().isoformat()
    [entrega] = body["deliveries"]
    assert (entrega["insumo"], entrega["cantidad"], entrega["constancia_tipo"]) == ("Insulina Glargina", "2 frascos", None)
    assert entrega["entregado_por"].endswith("@test.com")

    con_constancia = await client.post(
        f"{URL}/{reg['id']}/entregas",
        json={"insumo": "Jeringas", "cantidad": "30", "receptor_tipo": "PERSONA_REFERENTE", "constancia_tipo": "TESTIMONIO_PERSONAL"},
    )
    assert con_constancia.status_code == 201
    futura = await client.post(
        f"{URL}/{reg['id']}/entregas",
        json={"insumo": "Jeringas", "cantidad": "1", "fecha": (date.today() + timedelta(days=2)).isoformat()},
    )
    assert futura.status_code == 400


@pytest.mark.asyncio
async def test_la_revision_semestral_marca_los_registros_vencidos(client, superuser_token, db_session, ref):
    reg = (await client.post(f"{URL}/", json=_datos(ref, nombre="Revisión"))).json()
    assert reg["revision_vencida"] is False

    # siete meses sin revisar
    fila = (await db_session.execute(select(models.AssistedRegistration).where(models.AssistedRegistration.id == reg["id"]))).scalars().one()
    fila.created_at = datetime.now(timezone.utc) - timedelta(days=210)
    await db_session.commit()

    vencidos = await client.get(f"{URL}/", params={"revision_vencida": "true"})
    assert reg["id"] in [r["id"] for r in vencidos.json()]
    assert (await client.get(f"{URL}/{reg['id']}")).json()["revision_vencida"] is True

    resp = await client.post(f"{URL}/{reg['id']}/revision")
    assert resp.status_code == 200
    assert resp.json()["revision_vencida"] is False and resp.json()["ultima_revision_at"] is not None
    vencidos = await client.get(f"{URL}/", params={"revision_vencida": "true"})
    assert reg["id"] not in [r["id"] for r in vencidos.json()]


@pytest.mark.asyncio
async def test_el_cese_solo_admite_las_causas_del_reglamento_y_cierra_el_registro(client, superuser_token, ref):
    reg = (await client.post(f"{URL}/", json=_datos(ref))).json()

    # la pérdida de contacto no es causal de cese
    assert (await client.post(f"{URL}/{reg['id']}/cese", json={"causa": "PERDIDA_DE_CONTACTO"})).status_code == 422
    # una falta grave exige detalle
    assert (await client.post(f"{URL}/{reg['id']}/cese", json={"causa": "FALTA_GRAVE"})).status_code == 422

    resp = await client.post(f"{URL}/{reg['id']}/cese", json={"causa": "SIN_NECESIDAD", "detalle": "Ya no usa insulina"})
    assert resp.status_code == 200, resp.text
    assert (resp.json()["estado"], resp.json()["cese_causa"]) == ("CESADO", "SIN_NECESIDAD")
    assert resp.json()["revision_vencida"] is False  # un registro cesado no se revisa

    # cesado: ya no admite entregas ni cambios
    assert (await client.post(f"{URL}/{reg['id']}/entregas", json={"insumo": "X", "cantidad": "1"})).status_code == 400
    assert (await client.put(f"{URL}/{reg['id']}", json={"nombre": "Otro"})).status_code == 400


@pytest.mark.asyncio
async def test_el_traslado_al_registro_ordinario_puede_enlazar_la_ficha(client, superuser_token, db_session, ref):
    paciente = models.Patient(
        nombres="Transito", ap_paterno=f"Ordinario{uuid.uuid4().hex[:6]}", ci=f"TR{uuid.uuid4().hex[:8]}",
        fecha_nac=date(2000, 1, 1), estado="HABILITADO",
    )
    db_session.add(paciente)
    await db_session.commit()
    await db_session.refresh(paciente)

    reg = (await client.post(f"{URL}/", json=_datos(ref))).json()
    assert (await client.post(f"{URL}/{reg['id']}/cese", json={"causa": "RENUNCIA", "patient_id": paciente.id})).status_code == 422
    inexistente = await client.post(f"{URL}/{reg['id']}/cese", json={"causa": "TRASLADO_REGIMEN_ORDINARIO", "patient_id": 99999999})
    assert inexistente.status_code == 404

    resp = await client.post(f"{URL}/{reg['id']}/cese", json={"causa": "TRASLADO_REGIMEN_ORDINARIO", "patient_id": paciente.id})
    assert resp.status_code == 200 and resp.json()["patient_id"] == paciente.id


@pytest.mark.asyncio
async def test_la_denegacion_es_motivada_y_solo_antes_de_entregar(client, superuser_token, ref):
    sin_entregas = (await client.post(f"{URL}/", json=_datos(ref))).json()
    assert (await client.post(f"{URL}/{sin_entregas['id']}/denegar", json={"motivo": "no"})).status_code == 422
    resp = await client.post(
        f"{URL}/{sin_entregas['id']}/denegar", json={"motivo": "Manifiesta ausencia de necesidad de insulina."}
    )
    assert resp.status_code == 200
    assert (resp.json()["estado"], resp.json()["motivo_denegacion"]) == ("DENEGADO", "Manifiesta ausencia de necesidad de insulina.")

    con_entregas = (await client.post(f"{URL}/", json=_datos(ref))).json()
    await client.post(f"{URL}/{con_entregas['id']}/entregas", json={"insumo": "Insulina", "cantidad": "1"})
    rechazada = await client.post(f"{URL}/{con_entregas['id']}/denegar", json={"motivo": "Ya no la necesita, según se informó."})
    assert rechazada.status_code == 400  # corresponde el cese


@pytest.mark.asyncio
async def test_busqueda_por_codigo_nombre_ci_entidad_o_persona_referente_sin_tildes(client, superuser_token):
    marca = uuid.uuid4().hex[:6]
    persona = (await _crear_referente(client, nombre=f"Lucía Ñandú {marca}", ci=f"RC{marca}")).json()
    reg = (
        await client.post(
            f"{URL}/",
            json=_datos(persona, nombre=f"José {marca}", ci=f"BEN{marca}", entidad_nombre="Hogar Niño Jesús", depto="Oruro"),
        )
    ).json()

    for texto in (reg["codigo"], f"jose {marca}", "nino jesus", marca.upper(), f"BEN{marca}", f"lucia nandu {marca}", f"RC{marca}"):
        ids = [r["id"] for r in (await client.get(f"{URL}/", params={"q": texto})).json()]
        assert reg["id"] in ids, texto
    assert (await client.get(f"{URL}/", params={"estado": "CESADO", "q": marca})).json() == []
    por_depto = await client.get(f"{URL}/", params={"depto": "oruro", "q": marca})
    assert [r["id"] for r in por_depto.json()] == [reg["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", ["EVALUADOR_SOCIAL", "COORDINADOR_NACIONAL"])
async def test_evaluador_y_coordinacion_acceden(client, superuser_token, db_session, ref, rol):
    await _como(db_session, rol)
    assert (await client.post(f"{URL}/", json=_datos(ref))).status_code == 201
    assert (await client.get(f"{URL}/")).status_code == 200
    assert (await client.get(f"{URL}/referentes")).status_code == 200
    assert (await _crear_referente(client)).status_code == 201


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", ["REGISTRADOR", "RESPONSABLE_DEPARTAMENTAL", "PACIENTE"])
async def test_los_demas_roles_no_ven_nada_del_modulo(client, superuser_token, db_session, ref, rol):
    reg = (await client.post(f"{URL}/", json=_datos(ref))).json()  # lo crea el admin de la fixture
    await _como(db_session, rol)
    assert (await client.get(f"{URL}/")).status_code == 403
    assert (await client.get(f"{URL}/{reg['id']}")).status_code == 403
    assert (await client.post(f"{URL}/", json=_datos(ref))).status_code == 403
    assert (await client.post(f"{URL}/{reg['id']}/entregas", json={"insumo": "X", "cantidad": "1"})).status_code == 403
    # ni la foto ni los datos de la persona referente
    assert (await client.get(f"{URL}/referentes")).status_code == 403
    assert (await client.get(f"{URL}/referentes/{ref['id']}")).status_code == 403
    assert (await _crear_referente(client)).status_code == 403


@pytest.mark.asyncio
async def test_solo_el_evaluador_social_o_la_direccion_deniegan_la_admision(client, superuser_token, db_session, ref):
    reg = (await client.post(f"{URL}/", json=_datos(ref))).json()
    await _como(db_session, "COORDINADOR_NACIONAL")
    resp = await client.post(f"{URL}/{reg['id']}/denegar", json={"motivo": "Manifiesta ausencia de necesidad."})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_las_personas_asistidas_suman_al_total_de_beneficiarios_pero_no_a_aportes_ni_morosos(client, superuser_token, ref):
    antes = (await client.get("/reports/population")).json()
    await client.post(f"{URL}/", json=_datos(ref, nombre="Sin aporte", treatments=[{"insulina": "Glargina", "dosis_diaria": 20}]))
    cesado = (await client.post(f"{URL}/", json=_datos(ref))).json()
    await client.post(f"{URL}/{cesado['id']}/cese", json={"causa": "RENUNCIA"})  # un cesado no cuenta
    despues = (await client.get("/reports/population")).json()

    assert despues["asistidos"] == antes["asistidos"] + 1
    assert despues["total_beneficiarios"] == antes["total_beneficiarios"] + 1
    # no tienen aporte: no son morosos ni cambian los estados de los beneficiarios ordinarios
    assert despues["morosos"] == antes["morosos"]
    for estado in ("activos", "pendientes_validacion", "inactivos", "otros_estados"):
        assert despues[estado] == antes[estado]


@pytest.mark.asyncio
async def test_la_bitacora_no_guarda_datos_personales(client, superuser_token, db_session):
    persona = (await _crear_referente(client, nombre="Nombre Referente Secreto", ci=f"CISECRETO{uuid.uuid4().hex[:6]}", telefono="77777777")).json()
    reg = (await client.post(f"{URL}/", json=_datos(persona, nombre="Nombre Secreto", ci="55555555"))).json()
    logs = (
        await db_session.execute(
            select(models.AuditLog).where(
                models.AuditLog.entidad.in_(["assisted_registration", "assisted_referent"]),
                models.AuditLog.entidad_id.in_([reg["id"], persona["id"]]),
            )
        )
    ).scalars().all()
    assert {l.accion for l in logs} == {"CREATE"}
    texto = " ".join(str(l.payload) for l in logs)
    for secreto in ("Secreto", "7777", "5555", "CISECRETO"):
        assert secreto not in texto
