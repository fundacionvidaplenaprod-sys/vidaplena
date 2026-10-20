"""
Reportes de aportes: columna Departamento y rango de periodos (desde / hasta).

- GET /reports/contributions  (Historial de Aportes): una fila por voucher con su
  periodo y departamento; admite un mes, un rango y un departamento.
- GET /contributions/review   (base de Control de Vouchers): devuelve `depto` y
  admite el mismo rango y departamento.
- GET /contributions/vouchers/export.pdf y /review/export.pdf: el PDF lleva las
  columnas Departamento y Periodo.

Se usan periodos de años lejanos propios de cada test: la BD compartida no se limpia
entre ejecuciones y reutilizar un periodo contaminaría los conteos.
"""
import base64
import re
import uuid
import zlib
from datetime import date

import pytest

from app import models


def pdf_text(data: bytes) -> str:
    """Texto dibujado en un PDF de ReportLab (streams ASCII85 + Flate), sin librerías extra."""
    partes = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = m.group(1).strip()
        try:
            if raw.endswith(b"~>"):
                raw = raw[:-2]
            partes.append(zlib.decompress(base64.a85decode(raw)).decode("latin-1"))
        except Exception:
            continue
    return " ".join(re.findall(r"\(([^)]*)\) Tj", "\n".join(partes)))


async def _paciente(db_session, nombre: str, depto: str = "La Paz") -> models.Patient:
    suffix = uuid.uuid4().hex[:8]
    user = models.User(
        email=f"rango_aportes_{suffix}@test.com", password_hash="fakehash", role="PACIENTE", estado="ACTIVO"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    patient = models.Patient(
        user_id=user.id,
        nombres=nombre,
        ap_paterno=f"Rango{suffix}",
        ci=f"CI-{suffix}",
        fecha_nac=date(1990, 1, 1),
        depto=depto,
        estado="ACTIVO",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


async def _aporte(db_session, patient, periodo, estado="ACEPTADO") -> models.MonthlyContribution:
    contrib = models.MonthlyContribution(
        patient_id=patient.id,
        periodo=periodo,
        fecha_pago=date.today(),
        monto=70.0,
        url_comprobante=None,
        metodo_pago="EFECTIVO",
        estado=estado,
    )
    db_session.add(contrib)
    await db_session.commit()
    await db_session.refresh(contrib)
    return contrib


@pytest.mark.asyncio
async def test_historial_con_rango_trae_una_fila_por_voucher_con_periodo_y_departamento(client, superuser_token, db_session):
    ana = await _paciente(db_session, "Ana", "La Paz")
    beto = await _paciente(db_session, "Beto", "Cochabamba")
    await _aporte(db_session, ana, "2043-04")
    await _aporte(db_session, ana, "2043-05")
    await _aporte(db_session, ana, "2043-06")  # fuera del rango
    await _aporte(db_session, beto, "2043-05", estado="DECLARADO")

    resp = await client.get("/reports/contributions", params={"periodo_desde": "2043-04", "periodo_hasta": "2043-05"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["periodo_desde"], body["periodo_hasta"]) == ("2043-04", "2043-05")
    assert body["periodo"] is None  # no es un solo mes

    filas_ana = [(i["periodo"], i["depto"]) for i in body["items"] if i["patient_id"] == ana.id]
    assert filas_ana == [("2043-04", "La Paz"), ("2043-05", "La Paz")]  # ordenadas por periodo; sin 2043-06
    filas_beto = [(i["periodo"], i["depto"], i["estado"]) for i in body["items"] if i["patient_id"] == beto.id]
    assert filas_beto == [("2043-05", "Cochabamba", "DECLARADO")]
    assert all("id" in i for i in body["items"])  # una fila por voucher: ya no basta patient_id como llave
    assert body["total_aceptados"] >= 2 and body["total_declarados"] >= 1
    assert body["total_beneficiarios"] >= 2


@pytest.mark.asyncio
async def test_historial_un_solo_mes_sigue_funcionando(client, superuser_token, db_session):
    paciente = await _paciente(db_session, "Carla")
    await _aporte(db_session, paciente, "2043-07")
    resp = await client.get("/reports/contributions", params={"periodo": "2043-07"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["periodo"] == "2043-07" and body["periodo_desde"] == body["periodo_hasta"] == "2043-07"
    assert [i["periodo"] for i in body["items"] if i["patient_id"] == paciente.id] == ["2043-07"]


@pytest.mark.asyncio
async def test_historial_filtra_por_departamento_sin_importar_mayusculas(client, superuser_token, db_session):
    paz = await _paciente(db_session, "Dora", "La Paz")
    cbba = await _paciente(db_session, "Elio", "Cochabamba")
    await _aporte(db_session, paz, "2043-08")
    await _aporte(db_session, cbba, "2043-08")

    resp = await client.get("/reports/contributions", params={"periodo": "2043-08", "depto": "cochabamba"})
    assert resp.status_code == 200, resp.text
    ids = {i["patient_id"] for i in resp.json()["items"]}
    assert cbba.id in ids and paz.id not in ids
    assert {i["depto"] for i in resp.json()["items"]} == {"Cochabamba"}


@pytest.mark.asyncio
async def test_historial_valida_el_rango(client, superuser_token):
    al_reves = await client.get("/reports/contributions", params={"periodo_desde": "2043-10", "periodo_hasta": "2043-04"})
    assert al_reves.status_code == 400
    assert "posterior" in al_reves.json()["detail"]
    solo_un_extremo = await client.get("/reports/contributions", params={"periodo_desde": "2043-04"})
    assert solo_un_extremo.status_code == 400
    mal_formato = await client.get("/reports/contributions", params={"periodo_desde": "abril-2043"})
    assert mal_formato.status_code == 422
    mes_13 = await client.get("/reports/contributions", params={"periodo": "2043-13"})
    assert mes_13.status_code == 422


@pytest.mark.asyncio
async def test_review_devuelve_departamento_y_filtra_por_rango_y_depto(client, superuser_token, db_session):
    paz = await _paciente(db_session, "Fanny", "La Paz")
    tja = await _paciente(db_session, "Gael", "Tarija")
    await _aporte(db_session, paz, "2044-02")
    await _aporte(db_session, tja, "2044-03")
    await _aporte(db_session, tja, "2044-09")

    resp = await client.get("/contributions/review", params={"periodo_desde": "2044-02", "periodo_hasta": "2044-04"})
    assert resp.status_code == 200, resp.text
    por_pac = {(i["patient_id"], i["periodo"]): i["depto"] for i in resp.json()}
    assert por_pac[(paz.id, "2044-02")] == "La Paz"
    assert por_pac[(tja.id, "2044-03")] == "Tarija"
    assert (tja.id, "2044-09") not in por_pac

    solo_tja = await client.get("/contributions/review", params={"periodo_desde": "2044-02", "periodo_hasta": "2044-12", "depto": "TARIJA"})
    assert {i["depto"] for i in solo_tja.json()} == {"Tarija"}
    assert {i["periodo"] for i in solo_tja.json() if i["patient_id"] == tja.id} == {"2044-03", "2044-09"}

    al_reves = await client.get("/contributions/review", params={"periodo_desde": "2044-09", "periodo_hasta": "2044-02"})
    assert al_reves.status_code == 400


@pytest.mark.asyncio
async def test_pdf_control_de_vouchers_lleva_departamento_y_periodo_y_acepta_rango(client, superuser_token, db_session):
    paciente = await _paciente(db_session, "Hilda", "Santa Cruz")
    await _aporte(db_session, paciente, "2045-04")
    await _aporte(db_session, paciente, "2045-05")
    await _aporte(db_session, paciente, "2045-11")  # fuera del rango

    resp = await client.get(
        "/contributions/vouchers/export.pdf", params={"periodo_desde": "2045-04", "periodo_hasta": "2045-06"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert "2045-04_a_2045-06" in resp.headers["content-disposition"]
    texto = pdf_text(resp.content)
    for esperado in ("Departamento", "Periodo", "Santa Cruz", "2045-04", "2045-05"):
        assert esperado in texto, esperado
    assert "2045-11" not in texto
    assert "2045-04 a 2045-06" in texto  # el encabezado indica el rango

    con_depto = await client.get(
        "/contributions/vouchers/export.pdf", params={"periodo": "2045-04", "depto": "Oruro"}
    )
    assert con_depto.status_code == 200
    assert "Santa Cruz" not in pdf_text(con_depto.content)
    assert "Departamento: Oruro" in pdf_text(con_depto.content)

    al_reves = await client.get(
        "/contributions/vouchers/export.pdf", params={"periodo_desde": "2045-09", "periodo_hasta": "2045-01"}
    )
    assert al_reves.status_code == 400


@pytest.mark.asyncio
async def test_pdf_de_revision_de_aportes_lleva_departamento(client, superuser_token, db_session):
    paciente = await _paciente(db_session, "Ines", "Potosí")
    await _aporte(db_session, paciente, "2046-01")
    resp = await client.get("/contributions/review/export.pdf")
    assert resp.status_code == 200, resp.text
    texto = pdf_text(resp.content)
    assert "Departamento" in texto and "Potos" in texto


@pytest.mark.asyncio
async def test_historial_con_periodos_arma_una_columna_por_mes_con_el_estado_del_aporte(client, superuser_token, db_session):
    ana = await _paciente(db_session, "Ana", "La Paz")
    beto = await _paciente(db_session, "Beto", "La Paz")
    carla = await _paciente(db_session, "Carla", "La Paz")
    await _aporte(db_session, ana, "2044-08", estado="ACEPTADO")
    await _aporte(db_session, ana, "2044-09", estado="DECLARADO")
    await _aporte(db_session, beto, "2044-09", estado="OBSERVADO")
    # Carla es ACTIVA y no pagó ningún mes: debe salir con «No registrado» en los dos.
    # Beto tiene un voucher OBSERVADO en septiembre: el estado se informa tal cual.

    resp = await client.get(
        "/reports/contributions",
        params={"periodo_desde": "2044-08", "periodo_hasta": "2044-09", "depto": "La Paz"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meses"] == ["2044-08", "2044-09"]
    por_id = {b["patient_id"]: b for b in body["beneficiarios"]}
    assert por_id[ana.id]["meses"] == {"2044-08": "ACEPTADO", "2044-09": "DECLARADO"}
    assert por_id[beto.id]["meses"] == {"2044-08": "NO_REGISTRADO", "2044-09": "OBSERVADO"}
    assert por_id[carla.id]["meses"] == {"2044-08": "NO_REGISTRADO", "2044-09": "NO_REGISTRADO"}
    # monto / fecha / método: los del voucher más reciente del rango
    assert (por_id[ana.id]["monto"], por_id[ana.id]["metodo_pago"]) == (70.0, "EFECTIVO")
    assert por_id[carla.id]["monto"] is None and por_id[carla.id]["fecha_pago"] is None
    # una fila por beneficiario, ordenados por nombre
    nombres = [b["patient_nombre"] for b in body["beneficiarios"]]
    assert nombres == sorted(nombres, key=str.lower)


@pytest.mark.asyncio
async def test_los_exonerados_aparecen_y_sin_voucher_figuran_como_exonerado(client, superuser_token, db_session):
    por_cargo = await _paciente(db_session, "Elena", "Oruro")
    por_cargo.exonerado_por_cargo = True
    por_vulnerabilidad = await _paciente(db_session, "Fabio", "Oruro")
    por_vulnerabilidad.exonerado_aporte = True
    db_session.add_all([por_cargo, por_vulnerabilidad])
    await db_session.commit()
    # Elena aportó de forma voluntaria solo en octubre; Fabio no aportó
    await _aporte(db_session, por_cargo, "2044-10")

    resp = await client.get(
        "/reports/contributions", params={"periodo_desde": "2044-10", "periodo_hasta": "2044-11", "depto": "Oruro"}
    )
    assert resp.status_code == 200
    por_id = {b["patient_id"]: b for b in resp.json()["beneficiarios"]}
    assert por_id[por_cargo.id]["exonerado"] is True
    assert por_id[por_cargo.id]["meses"] == {"2044-10": "ACEPTADO", "2044-11": "EXONERADO"}
    assert por_id[por_vulnerabilidad.id]["meses"] == {"2044-10": "EXONERADO", "2044-11": "EXONERADO"}
    # su voucher voluntario también cuenta en la lista por voucher
    plano = await client.get("/reports/contributions", params={"depto": "Oruro"})
    assert any(i["patient_id"] == por_cargo.id for i in plano.json()["items"])


@pytest.mark.asyncio
async def test_el_rango_de_periodos_no_puede_pasar_de_cuatro_meses(client, superuser_token):
    cuatro = await client.get("/reports/contributions", params={"periodo_desde": "2044-08", "periodo_hasta": "2044-11"})
    assert cuatro.status_code == 200
    assert cuatro.json()["meses"] == ["2044-08", "2044-09", "2044-10", "2044-11"]
    cinco = await client.get("/reports/contributions", params={"periodo_desde": "2044-08", "periodo_hasta": "2044-12"})
    assert cinco.status_code == 400
    assert "4 meses" in cinco.json()["detail"]
    # cruza el cambio de año
    anio = await client.get("/reports/contributions", params={"periodo_desde": "2044-11", "periodo_hasta": "2045-02"})
    assert anio.json()["meses"] == ["2044-11", "2044-12", "2045-01", "2045-02"]


@pytest.mark.asyncio
async def test_sin_periodo_devuelve_todo_el_historial_plano_sin_columnas_por_mes(client, superuser_token, db_session):
    ana = await _paciente(db_session, "Ana", "Pando")
    await _aporte(db_session, ana, "2044-01")
    await _aporte(db_session, ana, "2044-07")

    resp = await client.get("/reports/contributions", params={"depto": "Pando"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meses"] == [] and body["beneficiarios"] == []
    assert [(i["periodo"]) for i in body["items"] if i["patient_id"] == ana.id] == ["2044-01", "2044-07"]
