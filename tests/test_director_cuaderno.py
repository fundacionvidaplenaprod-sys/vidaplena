"""
Cuaderno de la Directora: registro estructurado y reporte.

- GET  /api/director-deliveries/beneficiaries  busca al beneficiario y trae sus insulinas anotadas.
- POST /api/director-deliveries/batch          registra la visita (varias insulinas) con presentación y marca.
- GET  /api/director-deliveries/               reporte de lo registrado (fechas, búsqueda).

Los textos de búsqueda llevan un sufijo único por test: la BD compartida conserva las filas de
corridas anteriores.
"""
import uuid
from datetime import date, timedelta

import pytest

from app import models

URL = "/api/director-deliveries"


async def _beneficiario(db_session, *, nombre="Mariela", depto="La Paz", insulinas=(("Lantus", 24.0), ("Humalog", 12.0))):
    sufijo = uuid.uuid4().hex[:8]
    user = models.User(
        email=f"cuaderno_{sufijo}@test.com", password_hash="fakehash", role="PACIENTE", estado="ACTIVO"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    patient = models.Patient(
        user_id=user.id,
        nombres=nombre,
        ap_paterno=f"Cuaderno{sufijo}",
        ap_materno="Quispe",
        ci=f"CQ{sufijo}",
        fecha_nac=date(1985, 5, 5),
        depto=depto,
        estado="ACTIVO",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    for nombre_ins, dosis in insulinas:
        db_session.add(models.PatientTreatment(patient_id=patient.id, nombre=nombre_ins, dosis_diaria=dosis))
    await db_session.commit()
    return patient, sufijo


@pytest.mark.asyncio
async def test_busca_al_beneficiario_y_trae_sus_insulinas_anotadas(client, superuser_token, db_session):
    patient, sufijo = await _beneficiario(db_session)

    por_apellido = await client.get(f"{URL}/beneficiaries", params={"q": f"Cuaderno{sufijo}"})
    assert por_apellido.status_code == 200, por_apellido.text
    [item] = por_apellido.json()
    assert item["id"] == patient.id
    assert (item["ci"], item["depto"], item["estado"]) == (f"CQ{sufijo}", "La Paz", "ACTIVO")
    assert [(t["nombre"], t["insulina"], t["dosis_diaria"]) for t in item["tratamientos"]] == [
        ("Lantus", "Glargina", 24.0),
        ("Humalog", "Lispro", 12.0),
    ]
    assert item["ultima_entrega"] is None

    por_ci = await client.get(f"{URL}/beneficiaries", params={"q": f"cq{sufijo}"})
    assert [i["id"] for i in por_ci.json()] == [patient.id]
    por_varias_palabras = await client.get(f"{URL}/beneficiaries", params={"q": f"mariela quispe cuaderno{sufijo}"})
    assert [i["id"] for i in por_varias_palabras.json()] == [patient.id]


@pytest.mark.asyncio
async def test_la_busqueda_pide_al_menos_dos_letras_y_no_es_para_pacientes(client, superuser_token, patient_token):
    corta = await client.get(f"{URL}/beneficiaries", params={"q": "a"})
    assert corta.status_code == 422


@pytest.mark.asyncio
async def test_un_paciente_no_puede_usar_el_cuaderno(client, patient_token):
    assert (await client.get(f"{URL}/beneficiaries", params={"q": "juan"})).status_code == 403
    assert (await client.get(f"{URL}/")).status_code == 403
    assert (await client.get(f"{URL}/search", params={"nombres": "a", "ap_paterno": "b"})).status_code == 403
    visita = {"patient_nombres": "A", "patient_ap_paterno": "B", "items": [{"insulin_type": "Glargina", "quantity": "1"}]}
    assert (await client.post(f"{URL}/batch", json=visita)).status_code == 403


@pytest.mark.asyncio
async def test_registra_la_visita_con_varias_insulinas_presentacion_y_marca(client, superuser_token, db_session):
    patient, sufijo = await _beneficiario(db_session)
    payload = {
        "patient_id": patient.id,
        "delivery_date": date.today().isoformat(),
        "items": [
            {"insulin_type": "Glargina", "presentacion": "Pen 3ml", "marca": "Lantus", "quantity": "4 pens"},
            {"insulin_type": "Lispro", "presentacion": "Frasco 10ml", "marca": "Humalog", "quantity": "1 frasco"},
        ],
    }
    res = await client.post(f"{URL}/batch", json=payload)
    assert res.status_code == 200, res.text
    filas = res.json()
    assert len(filas) == 2
    assert {f["patient_id"] for f in filas} == {patient.id}
    # los nombres salen de la ficha, en mayúsculas
    assert {(f["patient_nombres"], f["patient_ap_paterno"], f["patient_ap_materno"]) for f in filas} == {
        ("MARIELA", f"CUADERNO{sufijo}".upper(), "QUISPE")
    }
    assert [(f["insulin_type"], f["presentacion"], f["marca"], f["quantity"]) for f in filas] == [
        ("Glargina", "Pen 3ml", "Lantus", "4 pens"),
        ("Lispro", "Frasco 10ml", "Humalog", "1 frasco"),
    ]

    # y la próxima búsqueda avisa de la última entrega
    buscado = await client.get(f"{URL}/beneficiaries", params={"q": f"Cuaderno{sufijo}"})
    ultima = buscado.json()[0]["ultima_entrega"]
    assert ultima["delivery_date"] == date.today().isoformat()
    assert ultima["marca"] in ("Lantus", "Humalog")


@pytest.mark.asyncio
async def test_la_visita_se_registra_completa_o_no_se_registra(client, superuser_token, db_session):
    patient, sufijo = await _beneficiario(db_session)
    mala = {
        "patient_id": patient.id,
        "items": [
            {"insulin_type": "Glargina", "presentacion": "Pen 3ml", "quantity": "2"},
            {"insulin_type": "Lispro", "presentacion": "Jeringa", "quantity": "1"},  # presentación inválida
        ],
    }
    assert (await client.post(f"{URL}/batch", json=mala)).status_code == 422
    reporte = await client.get(f"{URL}/", params={"q": f"Cuaderno{sufijo}"})
    assert reporte.json()["total"] == 0  # la primera insulina tampoco quedó guardada


@pytest.mark.asyncio
async def test_persona_fuera_del_padron_se_registra_con_sus_nombres(client, superuser_token):
    sufijo = uuid.uuid4().hex[:6]
    sin_nombre = {"items": [{"insulin_type": "NPH", "quantity": "1 frasco"}]}
    assert (await client.post(f"{URL}/batch", json=sin_nombre)).status_code == 422
    inexistente = {"patient_id": 99999999, "items": [{"insulin_type": "NPH", "quantity": "1"}]}
    assert (await client.post(f"{URL}/batch", json=inexistente)).status_code == 404

    res = await client.post(
        f"{URL}/batch",
        json={
            "patient_nombres": " juana ",
            "patient_ap_paterno": f"visita{sufijo}",
            "items": [{"insulin_type": "NPH", "quantity": "1 frasco"}],
        },
    )
    assert res.status_code == 200, res.text
    [fila] = res.json()
    assert (fila["patient_id"], fila["patient_nombres"], fila["presentacion"], fila["marca"]) == (None, "JUANA", None, None)


@pytest.mark.asyncio
async def test_el_registro_individual_acepta_los_campos_nuevos(client, superuser_token, db_session):
    patient, _ = await _beneficiario(db_session)
    res = await client.post(
        f"{URL}/",
        json={
            "patient_nombres": "ignorado",
            "patient_ap_paterno": "ignorado",
            "insulin_type": "Glargina",
            "quantity": "2",
            "patient_id": patient.id,
            "presentacion": "Cartucho 3ml",
            "marca": "Toujeo",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert (data["patient_id"], data["presentacion"], data["marca"]) == (patient.id, "Cartucho 3ml", "Toujeo")
    assert data["patient_nombres"] == "MARIELA"  # prevalece la ficha


@pytest.mark.asyncio
async def test_reporte_del_cuaderno_filtra_por_fechas_y_por_texto(client, superuser_token, db_session):
    patient, sufijo = await _beneficiario(db_session, depto="Cochabamba")
    hoy, hace_dos_meses = date.today(), date.today() - timedelta(days=60)
    for fecha, marca in ((hoy, "Lantus"), (hace_dos_meses, "Toujeo")):
        res = await client.post(
            f"{URL}/batch",
            json={
                "patient_id": patient.id,
                "delivery_date": fecha.isoformat(),
                "items": [{"insulin_type": "Glargina", "presentacion": "Pen 3ml", "marca": marca, "quantity": "3 pens"}],
            },
        )
        assert res.status_code == 200, res.text

    todo = await client.get(f"{URL}/", params={"q": f"Cuaderno{sufijo}"})
    assert todo.status_code == 200, todo.text
    cuerpo = todo.json()
    assert cuerpo["total"] == 2
    assert [i["marca"] for i in cuerpo["items"]] == ["Lantus", "Toujeo"]  # más reciente primero
    primera = cuerpo["items"][0]
    assert primera["patient_ci"] == f"CQ{sufijo}" and primera["patient_depto"] == "Cochabamba"
    assert primera["registrado_por"]  # quién lo anotó

    ultimo_mes = await client.get(
        f"{URL}/", params={"q": f"Cuaderno{sufijo}", "desde": (hoy - timedelta(days=30)).isoformat(), "hasta": hoy.isoformat()}
    )
    assert [i["marca"] for i in ultimo_mes.json()["items"]] == ["Lantus"]

    por_marca = await client.get(f"{URL}/", params={"q": f"Cuaderno{sufijo} toujeo"})
    assert [i["marca"] for i in por_marca.json()["items"]] == ["Toujeo"]

    por_ci = await client.get(f"{URL}/", params={"q": f"CQ{sufijo}"})
    assert por_ci.json()["total"] == 2

    al_reves = await client.get(f"{URL}/", params={"desde": hoy.isoformat(), "hasta": hace_dos_meses.isoformat()})
    assert al_reves.status_code == 400


@pytest.mark.asyncio
async def test_las_entregas_anteriores_sin_vinculo_siguen_apareciendo_en_el_reporte_y_la_alerta(client, superuser_token):
    sufijo = uuid.uuid4().hex[:6]
    res = await client.post(
        f"{URL}/",
        json={
            "patient_nombres": "Rufina",
            "patient_ap_paterno": f"Antigua{sufijo}",
            "insulin_type": "TOUJEO LYUMJEV",
            "quantity": "3 TOUJEO 1LYUMJEV",
        },
    )
    assert res.status_code == 200, res.text
    reporte = await client.get(f"{URL}/", params={"q": f"Antigua{sufijo}"})
    [fila] = reporte.json()["items"]
    assert (fila["patient_id"], fila["presentacion"], fila["marca"], fila["patient_ci"]) == (None, None, None, None)
    assert fila["insulin_type"] == "TOUJEO LYUMJEV"
