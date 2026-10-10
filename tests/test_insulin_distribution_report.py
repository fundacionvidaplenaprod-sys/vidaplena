"""Reporte de distribución de insulina desde el Excel de una donación.

Corre dentro de una transacción que se revierte (los `commit` se vuelven `flush`)
y deja fuera todo lo que no sembró, para no depender de lo que haya en la base.
"""
import io
import uuid
from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from openpyxl import Workbook
from sqlalchemy import func, select, update

from app import models

HEADER = ["CANTIDAD", "PRODUCTO", "TIPO DE INSULINA", "PRESENTACIÓN", "CONCENTRACIÓN", "FECHA VENCIMIENTO", "NRO LOTE"]
URL = "/reports/insulin-distribution"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest_asyncio.fixture
async def aislado(client, superuser_token, db_session):
    db_session.commit = db_session.flush
    yield db_session
    await db_session.rollback()


def _excel(rows, header=HEADER):
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _files(content, name="donacion.xlsx"):
    return {"file": (name, content, XLSX)}


async def _paciente(db, *, edad, estado, tipo="Tipo 1", glargina_ui=20.0):
    user = models.User(
        email=f"rep_{uuid.uuid4().hex[:8]}@test.com", password_hash="fakehash", role="PACIENTE", estado="ACTIVO"
    )
    db.add(user)
    await db.flush()
    nac = date.today().replace(year=date.today().year - edad) - timedelta(days=30)
    patient = models.Patient(
        user_id=user.id,
        nombres="Prueba",
        ap_paterno=f"Rep{estado[:3]}{edad}",
        ci=f"CI-{uuid.uuid4().hex[:6]}",
        fecha_nac=nac,
        tipo_sangre="O+",
        estado=estado,
        depto="La Paz",
    )
    db.add(patient)
    await db.flush()
    db.add(models.PatientTreatment(patient_id=patient.id, nombre="Glargina", dosis_diaria=glargina_ui))
    db.add(models.PatientMedical(patient_id=patient.id, tipo_diabetes=tipo))
    await db.flush()
    return patient


async def _solo(db, *patients):
    """Fuera del cálculo todo paciente que no sembró el test (se revierte al final)."""
    ids = [p.id for p in patients]
    await db.execute(update(models.Patient).where(models.Patient.id.notin_(ids)).values(estado="INACTIVO"))
    await db.flush()


def _fila(data, patient_id):
    return next(p for p in data["pacientes"] if p["patient_id"] == patient_id)


@pytest.mark.asyncio
async def test_report_considers_the_three_states_without_requiring_contributions(client, aislado):
    activo = await _paciente(aislado, edad=40, estado="ACTIVO")
    pendiente = await _paciente(aislado, edad=40, estado="PENDIENTE_DOC")
    habilitado = await _paciente(aislado, edad=40, estado="HABILITADO")
    inactivo = await _paciente(aislado, edad=40, estado="INACTIVO")
    await _solo(aislado, activo, pendiente, habilitado, inactivo)  # inactivo se queda INACTIVO

    futuro = datetime.now() + timedelta(days=400)
    content = _excel([[100, "Lantus SoloStar 3 ml", "Glargina", "3 ml", "U100", futuro, "L-1"]])

    res = await client.post(URL, files=_files(content))
    assert res.status_code == 200, res.text
    data = res.json()

    ids = {p["patient_id"] for p in data["pacientes"]}
    assert ids == {activo.id, pendiente.id, habilitado.id}  # el INACTIVO no entra
    assert data["estados_considerados"] == ["ACTIVO", "PENDIENTE_DOC", "HABILITADO"]
    assert data["guardado"] is False and data["dias"] == 60
    assert {_fila(data, activo.id)["estado"], _fila(data, pendiente.id)["estado"]} == {"ACTIVO", "PENDIENTE_DOC"}
    assert data["excluded_patients"] == []  # nadie excluido por falta de aporte
    for pid in ids:
        linea = _fila(data, pid)["insulinas"][0]
        assert linea["necesidad_ui"] == 1200  # 20 UI x 60 días
        assert linea["cobertura_pct"] >= 100


@pytest.mark.asyncio
async def test_report_applies_the_distribution_rules_and_shows_lots(client, aislado):
    menor = await _paciente(aislado, edad=10, estado="PENDIENTE_DOC")
    adulto = await _paciente(aislado, edad=40, estado="HABILITADO", tipo="Tipo 2")
    await _solo(aislado, menor, adulto)

    futuro = datetime.now() + timedelta(days=400)
    content = _excel(
        [
            [100, "Lantus SoloStar 3 ml", "Glargina", "3 ml", "U100", futuro, "LOTE-LANTUS"],
            [100, "ABASAGLAR KwikPen 3", "Glargina", "3 ml", "U100", futuro + timedelta(days=200), "LOTE-ABA"],
        ]
    )
    data = (await client.post(URL, files=_files(content))).json()

    m = _fila(data, menor.id)
    a = _fila(data, adulto.id)
    assert m["es_menor"] is True and a["es_menor"] is False
    assert [l["lote"] for l in m["insulinas"][0]["lotes"]] == ["LOTE-LANTUS"]  # Lantus para menores
    assert [l["lote"] for l in a["insulinas"][0]["lotes"]] == ["LOTE-ABA"]
    assert m["insulinas"][0]["lotes"][0]["unidades"] == 4  # 1.200 UI = 4 envases de 300
    assert m["insulinas"][0]["lotes"][0]["fecha_venc"] is not None
    # Reserva del 10 % y orden de prioridad (menor primero)
    assert data["reserva_ui"] >= data["reserva_objetivo_ui"] - 1e-6 > 0
    assert [p["patient_id"] for p in data["pacientes"]] == [menor.id, adulto.id]


@pytest.mark.asyncio
async def test_report_lists_bad_and_expired_rows_without_stopping(client, aislado):
    p = await _paciente(aislado, edad=40, estado="ACTIVO")
    await _solo(aislado, p)
    futuro = datetime.now() + timedelta(days=400)
    ayer = datetime.now() - timedelta(days=1)
    content = _excel(
        [
            [100, "Lantus", "Glargina", "3 ml", "U100", futuro, "OK"],
            [50, "Lantus viejo", "Glargina", "3 ml", "U100", ayer, "VENCIDO"],
            [0, "Cantidad cero", "Glargina", "3 ml", "U100", futuro, "X"],
            [5, "Producto raro", "Zumo", "3 ml", "U100", futuro, "Y"],
        ]
    )
    data = (await client.post(URL, files=_files(content))).json()

    assert data["filas_leidas"] == 4
    assert data["lotes_considerados"] == 1 and data["lotes_vencidos"] == 1
    msgs = {e["fila"]: e["mensaje"] for e in data["filas_con_error"]}
    assert set(msgs) == {3, 4, 5}
    assert "Vencido" in msgs[3] and "mayor a 0" in msgs[4] and "catálogo" in msgs[5]
    assert [l["producto"] for l in data["donacion"]] == ["Lantus", "Lantus viejo"]
    assert data["donacion"][0]["ui_total"] == 100 * 300


@pytest.mark.asyncio
async def test_report_does_not_write_anything(client, aislado):
    p = await _paciente(aislado, edad=40, estado="ACTIVO")
    await _solo(aislado, p)

    async def conteos():
        out = []
        for model in (models.Donation, models.DonationLot, models.DonationAllocation, models.StockMovement):
            out.append((await aislado.execute(select(func.count()).select_from(model))).scalar())
        return out

    antes = await conteos()
    futuro = datetime.now() + timedelta(days=400)
    res = await client.post(URL, files=_files(_excel([[100, "Lantus", "Glargina", "3 ml", "U100", futuro, "A"]])))
    assert res.status_code == 200
    assert await conteos() == antes


@pytest.mark.asyncio
async def test_report_rejects_bad_uploads(client, aislado):
    sin_xlsx = await client.post(URL, files={"file": ("lista.csv", b"a,b", "text/csv")})
    assert sin_xlsx.status_code == 400

    falso = await client.post(URL, files=_files(b"no soy un excel"))
    assert falso.status_code == 400

    sin_filas = await client.post(
        URL, files=_files(_excel([[0, "Lantus", "Glargina", "3 ml", "U100", None, None]]))
    )
    assert sin_filas.status_code == 400 and "ninguna fila válida" in sin_filas.json()["detail"]

    sin_columnas = await client.post(URL, files=_files(_excel([[1, "x"]], header=["CANTIDAD", "PRODUCTO"])))
    assert sin_columnas.status_code == 400 and "columnas" in sin_columnas.json()["detail"].lower()


@pytest.mark.asyncio
async def test_only_super_admin_can_generate_the_report(client, patient_token):
    res = await client.post(URL, files=_files(_excel([[1, "Lantus", "Glargina", "3 ml", "U100", None, None]])))
    assert res.status_code in (401, 403)


@pytest.mark.asyncio
async def test_report_caps_minors_dose_and_reports_priority_coverage(client, aislado):
    menor = await _paciente(aislado, edad=10, estado="ACTIVO", glargina_ui=48.0)
    adulto_t1 = await _paciente(aislado, edad=40, estado="HABILITADO", tipo="TIPO 1", glargina_ui=48.0)
    pen_corto = await _paciente(aislado, edad=9, estado="PENDIENTE_DOC", glargina_ui=6.0)  # 360 UI en 60 días
    await _solo(aislado, menor, adulto_t1, pen_corto)

    futuro = datetime.now() + timedelta(days=400)
    content = _excel([[200, "Lantus SoloStar 3 ml", "Glargina", "3 ml", "U100", futuro, "L-1"]])
    data = (await client.post(URL, files=_files(content))).json()

    m = _fila(data, menor.id)["insulinas"][0]
    assert (m["dosis_diaria_registrada"], m["dosis_diaria_aplicada"], m["dosis_limitada"]) == (48.0, 30.0, True)
    assert m["necesidad_ui"] == 1800 and m["cobertura_pct"] == 100.0  # 30 UI x 60 días, 6 pens exactos

    a = _fila(data, adulto_t1.id)["insulinas"][0]
    assert a["dosis_limitada"] is False and a["necesidad_ui"] == 2880  # el adulto no tiene tope
    assert 100.0 <= a["cobertura_pct"] <= 120.0

    # 360 UI con pens de 300: 2 pens = 166 %; se garantiza el 100 % y se informa
    c = _fila(data, pen_corto.id)["insulinas"][0]
    assert c["cobertura_pct"] > 120
    assert data["prioritarios_sobre_120"] == 1


@pytest.mark.asyncio
async def test_report_uses_one_insulin_per_group_and_flags_the_record(client, aislado):
    # A (menor): glargina + lispro + aspart -> las dos rápidas están en conflicto.
    a = await _paciente(aislado, edad=11, estado="ACTIVO", glargina_ui=20.0)
    aislado.add(models.PatientTreatment(patient_id=a.id, nombre="Lispro", dosis_diaria=28.0))
    aislado.add(models.PatientTreatment(patient_id=a.id, nombre="Aspart", dosis_diaria=28.0))
    # B: degludec + NPH -> conflicto en el grupo basal.
    b = await _paciente(aislado, edad=30, estado="HABILITADO", glargina_ui=0.0)
    await aislado.execute(
        update(models.PatientTreatment)
        .where(models.PatientTreatment.patient_id == b.id)
        .values(nombre="Degludec", dosis_diaria=10.0)
    )
    aislado.add(models.PatientTreatment(patient_id=b.id, nombre="NPH", dosis_diaria=40.0))
    # C: una de cada grupo, sin problema.
    c = await _paciente(aislado, edad=30, estado="ACTIVO", glargina_ui=15.0)
    aislado.add(models.PatientTreatment(patient_id=c.id, nombre="Aspart", dosis_diaria=12.0))
    await aislado.flush()
    await _solo(aislado, a, b, c)

    futuro = datetime.now() + timedelta(days=400)
    content = _excel(
        [
            [100, "Lantus SoloStar 3 ml", "Glargina", "3 ml", "U100", futuro, "L1"],
            [10, "NovoRapid Penfill 3 ml", "Aspart", "3 ml", "U100", futuro, "L2"],
            [200, "Humalog KwikPen 3 ml", "Lispro", "3 ml", "U100", futuro, "L3"],
            [100, "Tresiba Penfill 3 ml", "Degludec", "3 ml", "U100", futuro, "L4"],
            [2, "Insulatard Penfill 3 ml", "Humana isófana (NPH)", "3 ml", "U100", futuro, "L5"],
        ]
    )
    data = (await client.post(URL, files=_files(content))).json()

    # Todos reciben reparto, y cada uno con UNA sola insulina por grupo
    assert {p["patient_id"] for p in data["pacientes"]} == {a.id, b.id, c.id}
    assert {i["insulina"] for i in _fila(data, a.id)["insulinas"]} == {"Glargina", "Lispro"}
    assert {i["insulina"] for i in _fila(data, b.id)["insulinas"]} == {"Degludec"}
    assert {i["insulina"] for i in _fila(data, c.id)["insulinas"]} == {"Glargina", "Aspart"}
    # A (menor) usa la dosis de la elegida, con el tope de 30 UI/día
    lispro = next(i for i in _fila(data, a.id)["insulinas"] if i["insulina"] == "Lispro")
    assert lispro["dosis_diaria_aplicada"] == 28.0 and lispro["necesidad_ui"] == 28 * 60
    # Nadie recibe el producto de la insulina descartada
    productos = {l["producto"] for p in data["pacientes"] for i in p["insulinas"] for l in i["lotes"]}
    assert "Insulatard Penfill 3 ml" not in productos

    avisos = {(r["patient_id"], r["grupo"]): r for r in data["registros_por_corregir"]}
    assert set(avisos) == {(a.id, "RAPIDA"), (b.id, "BASAL")}
    ra = avisos[(a.id, "RAPIDA")]
    assert ra["insulina_usada"] == "Lispro" and ra["motivo"] == "STOCK" and ra["es_menor"] is True
    assert {i["insulina"]: i["dosis_diaria"] for i in ra["insulinas"]} == {"Lispro": 28.0, "Aspart": 28.0}
    assert "Se calculó con Lispro" in ra["mensaje"] and "corrige la ficha" in ra["mensaje"].lower()
    rb = avisos[(b.id, "BASAL")]
    assert rb["insulina_usada"] == "Degludec" and rb["estado"] == "HABILITADO"
    assert {i["insulina"] for i in rb["insulinas"]} == {"Degludec", "NPH"}


@pytest.mark.asyncio
async def test_report_never_uses_a_premix_in_place_of_a_basal(client, aislado):
    # Glargina + premezcla (Mix): la premezcla tiene todo el stock, la glargina casi nada.
    p = await _paciente(aislado, edad=40, estado="ACTIVO", glargina_ui=20.0)
    aislado.add(models.PatientTreatment(patient_id=p.id, nombre="Protamina", dosis_diaria=18.0))
    await aislado.flush()
    await _solo(aislado, p)

    futuro = datetime.now() + timedelta(days=400)
    content = _excel(
        [
            [1, "Lantus SoloStar 3 ml", "Glargina", "3 ml", "U100", futuro, "L1"],
            [500, "Humalog Mix 25 KwikPen", "Lispro bifásica (25 % lispro / 75 % lispro protamina)", "3 ml", "U100", futuro, "L2"],
        ]
    )
    data = (await client.post(URL, files=_files(content))).json()

    fila = _fila(data, p.id)
    assert [i["insulina"] for i in fila["insulinas"]] == ["Glargina"]
    productos = {l["producto"] for i in fila["insulinas"] for l in i["lotes"]}
    assert "Humalog Mix 25 KwikPen" not in productos
    aviso = data["registros_por_corregir"][0]
    assert aviso["insulina_usada"] == "Glargina" and aviso["premezcla_descartada"] is True
    assert "premezcla no puede sustituir a una basal" in aviso["mensaje"]


def test_report_endpoint_does_not_depend_on_the_warehouse_module():
    """El reporte se despliega solo: no debe importar el módulo de donaciones del almacén."""
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "app" / "api" / "endpoints" / "reports.py"
    text = source.read_text(encoding="utf-8")
    assert "endpoints import donations" not in text and "endpoints.donations" not in text
