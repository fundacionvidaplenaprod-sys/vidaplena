"""Almacén: ingreso por el Excel de la donación y reparto consolidado con el motor del reporte.

Cada prueba corre dentro de una transacción que se revierte (los `commit` se vuelven `flush`) y deja fuera del
cálculo todo lo que no sembró (otros pacientes, personas asistidas y lotes de la base de pruebas).
"""
import io
import uuid
from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from openpyxl import Workbook
from sqlalchemy import func, select, update

from app import models
from app.api import deps
from app.api.endpoints import reports as reports_module
from app.api.endpoints import warehouse as warehouse_module
from app.core import equitable_milp
from app.main import app

HEADER = ["CANTIDAD", "PRODUCTO", "TIPO DE INSULINA", "PRESENTACIÓN", "CONCENTRACIÓN", "FECHA VENCIMIENTO", "NRO LOTE"]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FUTURO = datetime.now() + timedelta(days=400)
HAY_OPTIMIZADOR = equitable_milp.HAS_SOLVER  # antes de que la fixture lo apague


@pytest.fixture(autouse=True)
def reparto_aproximado(monkeypatch):
    """Números deterministas, igual con o sin scipy (el almacén y el reporte, con la misma configuración)."""
    monkeypatch.setattr(equitable_milp, "HAS_SOLVER", False)
    monkeypatch.setattr(reports_module, "REQUIRE_OPTIMIZER", False)
    monkeypatch.setattr(warehouse_module, "REQUIRE_OPTIMIZER", False)


@pytest_asyncio.fixture
async def aislado(client, superuser_token, db_session):
    db_session.commit = db_session.flush
    # Ningún lote de otras pruebas entra en el reparto (se revierte al final).
    await db_session.execute(update(models.DonationLot).values(cantidad_disponible=0))
    await db_session.flush()
    yield db_session
    await db_session.rollback()


def _excel(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(HEADER)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _files(content, name="donacion.xlsx"):
    return {"file": (name, content, XLSX)}


def _donacion(lantus=4, abasaglar=10, levemir=10):
    tag = uuid.uuid4().hex[:6]  # cada prueba sube un archivo distinto
    return _excel(
        [
            [lantus, "Lantus SoloStar 3 ml", "Glargina", "3 ml", "U100", FUTURO, f"LAN-{tag}"],
            [abasaglar, "Abasaglar KwikPen 3 ml", "Glargina", "3 ml", "U100", FUTURO, f"ABA-{tag}"],
            [levemir, "Levemir FlexPen 3 ml", "Detemir", "3 ml", "U100", FUTURO, f"LEV-{tag}"],
        ]
    )


async def _paciente(db, *, edad, insulina="Glargina", dosis=20.0, tipo="Tipo 2", estado="ACTIVO"):
    user = models.User(email=f"alm_{uuid.uuid4().hex[:8]}@test.com", password_hash="fakehash", role="PACIENTE", estado="ACTIVO")
    db.add(user)
    await db.flush()
    patient = models.Patient(
        user_id=user.id, nombres="Prueba", ap_paterno=f"Alm{insulina[:3]}{edad}", ci=f"CI-{uuid.uuid4().hex[:6]}",
        fecha_nac=date.today().replace(year=date.today().year - edad) - timedelta(days=30), tipo_sangre="O+",
        estado=estado, depto="La Paz",
    )
    db.add(patient)
    await db.flush()
    db.add(models.PatientTreatment(patient_id=patient.id, nombre=insulina, dosis_diaria=dosis))
    db.add(models.PatientMedical(patient_id=patient.id, tipo_diabetes=tipo))
    await db.flush()
    return patient


async def _asistido(db, *, insulina="Glargina", dosis=20.0, edad=50):
    reg = models.AssistedRegistration(estado="ACTIVO", nombre="Asistida", tipo_diabetes="Tipo 2", edad_aproximada=edad, depto="Oruro")
    reg.treatments = [models.AssistedTreatment(insulina=insulina, dosis_diaria=dosis)]
    db.add(reg)
    await db.flush()
    reg.codigo = f"RA-{reg.id:05d}"
    await db.flush()
    return reg


async def _solo(db, *patients, asistidos=()):
    await db.execute(update(models.Patient).where(models.Patient.id.notin_([p.id for p in patients])).values(estado="INACTIVO"))
    await db.execute(
        update(models.AssistedRegistration)
        .where(models.AssistedRegistration.id.notin_([a.id for a in asistidos]))
        .values(estado="CESADO")
    )
    await db.flush()


async def _escenario(client, db, **stock):
    menor = await _paciente(db, edad=10, tipo="Tipo 1")
    adulto = await _paciente(db, edad=40)
    detemir = await _paciente(db, edad=45, insulina="Detemir")
    await _solo(db, menor, adulto, detemir)
    res = await client.post("/donations/intake", files=_files(_donacion(**stock)))
    assert res.status_code == 200, res.text
    return menor, adulto, detemir


def _fila(data, pid):
    return next(p for p in data["resultado"]["pacientes"] if p["patient_id"] == pid)


def _lineas(data, pid):
    """(producto, envases) que recibe un beneficiario en su primer tratamiento."""
    return {(l["producto"], l["unidades"]) for l in _fila(data, pid)["insulinas"][0]["lotes"]}


def _lot_id(data, producto):
    return next(s["lot_id"] for s in data["resultado"]["stock"] if s["producto"] == producto)


# ------------------------------------------------------------------------------------------------ ingreso
@pytest.mark.asyncio
async def test_intake_requires_lote_and_expiry_and_rejects_expired_rows(client, aislado):
    content = _excel(
        [
            [5, "Lantus SoloStar 3 ml", "Glargina", "3 ml", "U100", FUTURO, None],
            [5, "Abasaglar KwikPen 3 ml", "Glargina", "3 ml", "U100", None, "L-2"],
            [5, "Levemir FlexPen 3 ml", "Detemir", "3 ml", "U100", datetime.now() - timedelta(days=3), "L-3"],
            [5, "Humulin N 10 ml", "NPH", "10 ml", "U100", FUTURO, "L-4"],
        ]
    )
    preview = await client.post("/donations/intake/preview", files=_files(content))
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["puede_ingresar"] is False
    mensajes = {e["fila"]: e["mensaje"] for e in data["errores"]}
    assert "NRO LOTE es obligatorio" in mensajes[2]
    assert "FECHA VENCIMIENTO es obligatoria" in mensajes[3]
    assert "vencido" in mensajes[4]
    assert 5 not in mensajes and len(data["filas"]) == 4

    antes = (await aislado.execute(select(func.count(models.DonationLot.id)))).scalar()
    res = await client.post("/donations/intake", files=_files(content))
    assert res.status_code == 400 and "No se ingresó nada" in res.json()["detail"]
    assert (await aislado.execute(select(func.count(models.DonationLot.id)))).scalar() == antes  # todo o nada


@pytest.mark.asyncio
async def test_intake_creates_products_lots_and_entries_and_the_same_file_cannot_enter_twice(client, aislado):
    content = _excel(
        [
            [4, "Toujeo SoloStar 1,5 ml", "Glargina", "1,5 ml", "U300", FUTURO, f"TOU-{uuid.uuid4().hex[:6]}"],
            [2, "Humulin N 10 ml", "NPH", "10 ml", "U100", FUTURO, f"NPH-{uuid.uuid4().hex[:6]}"],
        ]
    )
    res = await client.post("/donations/intake", files=_files(content, "packing_list.xlsx"))
    assert res.status_code == 200, res.text
    ingreso = res.json()
    assert ingreso["lotes_creados"] == 2 and ingreso["envases"] == 6 and ingreso["ui_total"] == 4 * 450 + 2 * 1000

    lotes = (
        await aislado.execute(select(models.DonationLot).where(models.DonationLot.intake_id == ingreso["id"]))
    ).scalars().all()
    assert sorted(l.cantidad_disponible for l in lotes) == [2, 4]
    for lot in lotes:
        donation = await aislado.get(models.Donation, lot.donation_id)
        assert donation.factor_conversion == donation.presentacion_ml * donation.concentracion_ui_ml
        movimientos = (
            await aislado.execute(select(models.StockMovement).where(models.StockMovement.lot_id == lot.id))
        ).scalars().all()
        assert [(m.tipo, m.cantidad, m.referencia) for m in movimientos] == [("ENTRADA", lot.cantidad_total, f"INGRESO:{ingreso['id']}")]

    stock = (await client.get("/donations/stock", params={"solo_disponibles": True})).json()
    toujeo = next(s for s in stock if s["producto"] == "Toujeo SoloStar 1,5 ml")
    assert toujeo["ui_por_envase"] == 450 and toujeo["concentracion_ui_ml"] == 300 and toujeo["ingreso_archivo"] == "packing_list.xlsx"

    again = await client.post("/donations/intake", files=_files(content, "otro_nombre.xlsx"))
    assert again.status_code == 409 and "ya se ingresó" in again.json()["detail"]
    preview = (await client.post("/donations/intake/preview", files=_files(content))).json()
    assert preview["puede_ingresar"] is False and preview["ingreso_previo"]["id"] == ingreso["id"]


# ------------------------------------------------------------------------------------------------ reparto
@pytest.mark.asyncio
@pytest.mark.parametrize("exacto", [False, True], ids=["aproximado", "optimizador"])
async def test_warehouse_distribution_is_exactly_the_report_distribution(client, aislado, monkeypatch, exacto):
    if exacto:
        if not HAY_OPTIMIZADOR:
            pytest.skip("scipy no está instalado: no hay optimizador")
        monkeypatch.setattr(equitable_milp, "HAS_SOLVER", True)
        monkeypatch.setattr(reports_module, "REQUIRE_OPTIMIZER", True)
        monkeypatch.setattr(warehouse_module, "REQUIRE_OPTIMIZER", True)
    menor = await _paciente(aislado, edad=10, tipo="Tipo 1")
    adulto = await _paciente(aislado, edad=40)
    detemir = await _paciente(aislado, edad=45, insulina="Detemir")
    pendiente = await _paciente(aislado, edad=50, estado="PENDIENTE_DOC")  # sin aporte y con documentos pendientes
    asistido = await _asistido(aislado)
    await _solo(aislado, menor, adulto, detemir, pendiente, asistidos=[asistido])
    content = _donacion(lantus=4, abasaglar=6, levemir=3)

    reporte = (await client.post("/reports/insulin-distribution", files=_files(content))).json()
    assert (await client.post("/donations/intake", files=_files(content))).status_code == 200
    res = await client.post("/donations/distributions")
    assert res.status_code == 200, res.text
    data = res.json()
    almacen = data["resultado"]

    assert data["estado"] == "BORRADOR" and almacen["guardado"] is True
    assert almacen["estados_considerados"] == reporte["estados_considerados"] == ["ACTIVO", "PENDIENTE_DOC", "HABILITADO"]
    assert almacen["asistidos_incluidos"] == 1
    for campo in ("stock_total_ui", "reserva_ui", "asignado_ui", "reserva_pct", "dias"):
        assert almacen[campo] == reporte[campo], campo

    def resumen(result):
        out = {}
        for p in result["pacientes"]:
            for i in p["insulinas"]:
                out[(p["patient_id"], i["insulina"])] = (
                    i["entregado_ui"], i["cobertura_pct"], i["sustituto"], sorted(i["notas"]),
                    sorted((l["producto"], l["unidades"]) for l in i["lotes"]),
                )
        return out

    assert resumen(almacen) == resumen(reporte)  # mismo motor, mismas reglas, mismo resultado
    # La persona del Registro Asistido queda en las líneas del reparto con su registro.
    items = (
        await aislado.execute(select(models.InsulinDistributionItem).where(models.InsulinDistributionItem.distribution_id == data["id"]))
    ).scalars().all()
    assert {i.assisted_registration_id for i in items if i.beneficiario_id < 0} == {asistido.id}
    assert all(i.patient_id == i.beneficiario_id for i in items if i.beneficiario_id > 0)
    assert sum(s["asignados"] for s in almacen["stock"]) == sum(i.envases for i in items) == data["envases"]


@pytest.mark.asyncio
async def test_a_new_calculation_discards_the_previous_draft(client, aislado):
    await _escenario(client, aislado)
    primero = (await client.post("/donations/distributions")).json()
    segundo = (await client.post("/donations/distributions")).json()
    assert segundo["id"] != primero["id"] and segundo["estado"] == "BORRADOR"
    assert (await client.get(f"/donations/distributions/{primero['id']}")).json()["estado"] == "DESCARTADO"
    historial = (await client.get("/donations/distributions")).json()
    estados = {h["id"]: h["estado"] for h in historial}
    assert estados[primero["id"]] == "DESCARTADO" and estados[segundo["id"]] == "BORRADOR"
    fila = next(h for h in historial if h["id"] == segundo["id"])
    assert fila["beneficiarios"] == 3 and fila["envases"] == segundo["envases"] > 0


@pytest.mark.asyncio
async def test_equivalent_swap_changes_the_envases_but_not_the_coverage(client, aislado):
    menor, adulto, detemir = await _escenario(client, aislado)
    data = (await client.post("/donations/distributions")).json()
    aba, lev, lan = (_lot_id(data, p) for p in ("Abasaglar KwikPen 3 ml", "Levemir FlexPen 3 ml", "Lantus SoloStar 3 ml"))
    assert ("Lantus SoloStar 3 ml", 4) in _lineas(data, menor.id)  # la Lantus va al menor
    antes_adulto, antes_detemir = _fila(data, adulto.id)["insulinas"][0], _fila(data, detemir.id)["insulinas"][0]

    opciones = (
        await client.get(
            f"/donations/distributions/{data['id']}/swap-options",
            params={"beneficiario_id": adulto.id, "insulina": "Glargina", "lot_id": aba, "envases": 1},
        )
    ).json()
    pares = {(o["beneficiario_id"], o["lot_id"], o["envases"]) for o in opciones["opciones"]}
    assert (detemir.id, lev, 1) in pares
    assert not any(o["beneficiario_id"] == menor.id for o in opciones["opciones"])  # el menor conserva la Lantus

    res = await client.post(
        f"/donations/distributions/{data['id']}/swaps",
        json={"beneficiario_id": adulto.id, "insulina": "Glargina", "lot_id": aba, "envases": 1,
              "con_beneficiario_id": detemir.id, "con_insulina": "Detemir", "con_lot_id": lev, "con_envases": 1},
    )
    assert res.status_code == 200, res.text
    nuevo = res.json()
    a, d = _fila(nuevo, adulto.id)["insulinas"][0], _fila(nuevo, detemir.id)["insulinas"][0]
    assert a["entregado_ui"] == antes_adulto["entregado_ui"] and a["cobertura_pct"] == antes_adulto["cobertura_pct"]
    assert d["entregado_ui"] == antes_detemir["entregado_ui"] and d["cobertura_pct"] == antes_detemir["cobertura_pct"]
    assert a["sustituto"] == "Detemir" and "SUSTITUCION" in a["notas"]
    assert d["sustituto"] == "Glargina"
    assert ("Levemir FlexPen 3 ml", 1) in _lineas(nuevo, adulto.id)
    assert nuevo["intercambios"] == 1 and nuevo["intercambios_detalle"][0]["producto_a"] == "Abasaglar KwikPen 3 ml"
    assert [s["asignados"] for s in nuevo["resultado"]["stock"]] == [s["asignados"] for s in data["resultado"]["stock"]]
    assert nuevo["propuesta"] == data["propuesta"]  # la propuesta del motor se conserva

    # Restablecer vuelve a la propuesta y borra los intercambios.
    reset = (await client.post(f"/donations/distributions/{data['id']}/reset")).json()
    assert reset["intercambios"] == 0 and _lineas(reset, adulto.id) == _lineas(data, adulto.id)
    assert _fila(reset, adulto.id)["insulinas"][0]["sustituto"] is None
    del lan


@pytest.mark.asyncio
async def test_swaps_that_change_the_distribution_or_break_rules_are_rejected(client, aislado):
    menor, adulto, detemir = await _escenario(client, aislado)
    data = (await client.post("/donations/distributions")).json()
    aba, lev, lan = (_lot_id(data, p) for p in ("Abasaglar KwikPen 3 ml", "Levemir FlexPen 3 ml", "Lantus SoloStar 3 ml"))
    url = f"/donations/distributions/{data['id']}/swaps"

    def swap(a, ia, la, na, b, ib, lb, nb):
        return client.post(url, json={"beneficiario_id": a, "insulina": ia, "lot_id": la, "envases": na,
                                      "con_beneficiario_id": b, "con_insulina": ib, "con_lot_id": lb, "con_envases": nb})

    no_equivalente = await swap(adulto.id, "Glargina", aba, 2, detemir.id, "Detemir", lev, 1)
    assert no_equivalente.status_code == 400 and "No es equivalente" in no_equivalente.json()["detail"]
    menor_pierde_lantus = await swap(menor.id, "Glargina", lan, 1, adulto.id, "Glargina", aba, 1)
    assert menor_pierde_lantus.status_code == 400 and "Lantus" in menor_pierde_lantus.json()["detail"]
    detalle = (await client.get(f"/donations/distributions/{data['id']}")).json()
    assert detalle["intercambios"] == 0 and _lineas(detalle, adulto.id) == _lineas(data, adulto.id)  # nada cambió


@pytest.mark.asyncio
async def test_consolidate_discounts_only_what_was_assigned_and_freezes_the_distribution(client, aislado):
    await _escenario(client, aislado)
    data = (await client.post("/donations/distributions")).json()
    disponibles_antes = {s["lot_id"]: s["disponibles"] for s in data["resultado"]["stock"]}

    res = await client.post(f"/donations/distributions/{data['id']}/consolidate")
    assert res.status_code == 200, res.text
    cons = res.json()
    assert cons["estado"] == "CONSOLIDADO" and cons["consolidated_at"] and cons["consolidado_por"]
    for s in data["resultado"]["stock"]:
        lot = await aislado.get(models.DonationLot, s["lot_id"])
        await aislado.refresh(lot)
        # Sale lo asignado; la reserva y el sobrante quedan en el almacén.
        assert lot.cantidad_disponible == disponibles_antes[s["lot_id"]] - s["asignados"] == s["reserva"] + s["sobrante"]
        salidas = (
            await aislado.execute(
                select(models.StockMovement).where(models.StockMovement.lot_id == s["lot_id"], models.StockMovement.tipo == "SALIDA")
            )
        ).scalars().all()
        assert [(m.cantidad, m.referencia) for m in salidas] == ([(s["asignados"], f"REPARTO:{data['id']}")] if s["asignados"] else [])
        # Lo mismo en la pestaña Stock: la entrada del ingreso y la salida del reparto.
        movimientos = (await client.get(f"/donations/lots/{s['lot_id']}/movements")).json()
        assert [m["tipo"] for m in movimientos] == (["ENTRADA", "SALIDA"] if s["asignados"] else ["ENTRADA"])
        assert movimientos[0]["referencia"].startswith("INGRESO:")

    # Consolidado ya no se modifica, pero se puede volver a ver tal cual.
    assert (await client.post(f"/donations/distributions/{data['id']}/consolidate")).status_code == 409
    assert (await client.post(f"/donations/distributions/{data['id']}/reset")).status_code == 409
    assert (await client.post(f"/donations/distributions/{data['id']}/discard")).status_code == 409
    visto = (await client.get(f"/donations/distributions/{data['id']}")).json()
    assert visto["resultado"]["pacientes"] == cons["resultado"]["pacientes"] and visto["estado"] == "CONSOLIDADO"

    # Un reparto nuevo parte del stock que quedó (la reserva y el sobrante).
    siguiente = (await client.post("/donations/distributions")).json()
    assert siguiente["resultado"]["stock_total_ui"] < data["resultado"]["stock_total_ui"]


@pytest.mark.asyncio
async def test_consolidate_requires_the_stock_the_distribution_was_calculated_with(client, aislado):
    await _escenario(client, aislado)
    data = (await client.post("/donations/distributions")).json()
    # Otro ingreso después del cálculo: el reparto ya no corresponde al stock.
    otro = _excel([[3, "Basaglar KwikPen 3 ml", "Glargina", "3 ml", "U100", FUTURO, f"BAS-{uuid.uuid4().hex[:6]}"]])
    assert (await client.post("/donations/intake", files=_files(otro))).status_code == 200

    detalle = (await client.get(f"/donations/distributions/{data['id']}")).json()
    assert detalle["stock_vigente"] is False and any("ingresó después" in c for c in detalle["stock_cambios"])
    res = await client.post(f"/donations/distributions/{data['id']}/consolidate")
    assert res.status_code == 409 and "vuelva a calcularlo" in res.json()["detail"]
    lot = await aislado.get(models.DonationLot, data["resultado"]["stock"][0]["lot_id"])
    await aislado.refresh(lot)
    assert lot.cantidad_disponible == data["resultado"]["stock"][0]["disponibles"]  # no se descontó nada


@pytest.mark.asyncio
async def test_discard_keeps_the_draft_in_the_history(client, aislado):
    await _escenario(client, aislado)
    data = (await client.post("/donations/distributions")).json()
    res = await client.post(f"/donations/distributions/{data['id']}/discard")
    assert res.status_code == 200 and res.json()["estado"] == "DESCARTADO" and res.json()["discarded_at"]
    assert (await client.post(f"/donations/distributions/{data['id']}/consolidate")).status_code == 409


# ------------------------------------------------------------------------------------------------ historial
async def _lote_sin_ingreso(db, *, cantidad=3):
    """Un lote cargado antes del ingreso por Excel: no viene de ningún packing list."""
    donation = models.Donation(
        tipo="INSULINA", nombre_generico="NPH", nombre_comercial="Humulin N 10 ml", presentacion="10 ml U100",
        factor_conversion=1000, presentacion_ml=10, concentracion_ui_ml=100,
    )
    db.add(donation)
    await db.flush()
    lot = models.DonationLot(
        donation_id=donation.id, lote=f"OLD-{uuid.uuid4().hex[:6]}", fecha_venc=date.today() + timedelta(days=300),
        cantidad_total=cantidad, cantidad_disponible=cantidad,
    )
    db.add(lot)
    await db.flush()
    return lot


async def _origen_esperado(db, data):
    """{ingreso_id: envases asignados} calculado lote por lote desde el stock guardado del reparto."""
    esperado = {}
    for s in data["resultado"]["stock"]:
        if s["asignados"]:
            lot = await db.get(models.DonationLot, s["lot_id"])
            esperado[lot.intake_id] = esperado.get(lot.intake_id, 0) + s["asignados"]
    return esperado


@pytest.mark.asyncio
async def test_each_distribution_shows_the_packing_lists_it_came_from(client, aislado):
    menor = await _paciente(aislado, edad=10, tipo="Tipo 1")
    adulto = await _paciente(aislado, edad=40)
    nph = await _paciente(aislado, edad=60, insulina="NPH")
    await _solo(aislado, menor, adulto, nph)
    viejo = await _lote_sin_ingreso(aislado)  # la NPH solo está en un lote sin packing list
    primero = (await client.post("/donations/intake", files=_files(_donacion(), "packing_octubre.xlsx"))).json()

    data = (await client.post("/donations/distributions")).json()
    ingresos = {o["ingreso_id"]: o for o in data["ingresos"]}
    assert {k: o["envases"] for k, o in ingresos.items()} == await _origen_esperado(aislado, data)
    assert ingresos[primero["id"]]["archivo"] == "packing_octubre.xlsx" and ingresos[primero["id"]]["ingresado_at"]
    assert ingresos[None]["archivo"] is None and ingresos[None]["lotes"] == 1  # el lote viejo de NPH
    assert sum(o["envases"] for o in data["ingresos"]) == data["envases"]
    assert sum(o["ui"] for o in data["ingresos"]) == pytest.approx(data["resultado"]["asignado_ui"])
    assert [o["ingreso_id"] for o in data["ingresos"]][-1] is None  # los lotes sin packing list, al final
    del viejo

    # El historial muestra lo mismo; un reparto posterior parte de lo que quedó y del packing list nuevo.
    assert (await client.post(f"/donations/distributions/{data['id']}/consolidate")).status_code == 200
    segundo = (await client.post("/donations/intake", files=_files(_donacion(lantus=2, abasaglar=4, levemir=2), "packing_noviembre.xlsx"))).json()
    otro = (await client.post("/donations/distributions")).json()
    assert {o["ingreso_id"]: o["envases"] for o in otro["ingresos"]} == await _origen_esperado(aislado, otro)
    historial = {h["id"]: h for h in (await client.get("/donations/distributions")).json()}
    assert historial[data["id"]]["ingresos"] == data["ingresos"]
    assert historial[otro["id"]]["ingresos"] == otro["ingresos"]
    assert {o["archivo"] for o in otro["ingresos"]} <= {"packing_octubre.xlsx", "packing_noviembre.xlsx", None}
    del segundo


@pytest.mark.asyncio
async def test_a_beneficiary_can_be_searched_across_all_saved_distributions(client, aislado):
    menor, adulto, detemir = await _escenario(client, aislado)
    adulto.nombres, adulto.ap_paterno = "Martín", "Ñúñez"
    asistido = await _asistido(aislado)
    await _solo(aislado, menor, adulto, detemir, asistidos=[asistido])

    consolidado = (await client.post("/donations/distributions")).json()
    aba, lev = (_lot_id(consolidado, p) for p in ("Abasaglar KwikPen 3 ml", "Levemir FlexPen 3 ml"))
    res = await client.post(
        f"/donations/distributions/{consolidado['id']}/swaps",
        json={"beneficiario_id": adulto.id, "insulina": "Glargina", "lot_id": aba, "envases": 1,
              "con_beneficiario_id": detemir.id, "con_insulina": "Detemir", "con_lot_id": lev, "con_envases": 1},
    )
    assert res.status_code == 200, res.text
    res = await client.post(f"/donations/distributions/{consolidado['id']}/consolidate")
    assert res.status_code == 200, res.text
    consolidado = res.json()
    otro = _excel([[6, "Basaglar KwikPen 3 ml", "Glargina", "3 ml", "U100", FUTURO, f"BAS-{uuid.uuid4().hex[:6]}"]])
    assert (await client.post("/donations/intake", files=_files(otro))).status_code == 200
    descartado = (await client.post("/donations/distributions")).json()
    borrador = (await client.post("/donations/distributions")).json()  # descarta el anterior

    # Sin tildes ni mayúsculas, por nombre y apellido, o por C.I.
    for q in ("martin nunez", "ÑÚÑEZ", adulto.ci.lower()):
        res = await client.get("/donations/distributions/beneficiarios", params={"q": q})
        assert res.status_code == 200, res.text
        assert [(m["beneficiario_id"], m["repartos"]) for m in res.json()] == [(adulto.id, 2)], q
    match = (await client.get("/donations/distributions/beneficiarios", params={"q": "martin"})).json()[0]
    assert match["nombre_completo"].startswith("Martín") and match["ci"] == adulto.ci and match["registro_asistido"] is False
    con_descartados = (
        await client.get("/donations/distributions/beneficiarios", params={"q": "martin", "incluir_descartados": True})
    ).json()
    assert con_descartados[0]["repartos"] == 3
    asistidos = (await client.get("/donations/distributions/beneficiarios", params={"q": "asistida"})).json()
    assert [(m["beneficiario_id"], m["registro_asistido"]) for m in asistidos] == [(-asistido.id, True)]
    assert (await client.get("/donations/distributions/beneficiarios", params={"q": "m"})).status_code == 422

    # Lo que recibió en cada reparto, tal como quedó guardado (con el intercambio del consolidado).
    hist = (await client.get(f"/donations/distributions/beneficiarios/{adulto.id}")).json()
    assert hist["beneficiario_id"] == adulto.id and hist["ci"] == adulto.ci
    assert [r["distribution_id"] for r in hist["repartos"]] == [borrador["id"], consolidado["id"]]  # más reciente primero
    assert [r["estado"] for r in hist["repartos"]] == ["BORRADOR", "CONSOLIDADO"]
    for entrega, data in zip(hist["repartos"], (borrador, consolidado)):
        fila = _fila(data, adulto.id)
        assert entrega["paciente"] == fila  # tal como quedó guardado
        assert entrega["envases"] == sum(l["unidades"] for i in fila["insulinas"] for l in i["lotes"])
        assert entrega["ui"] == pytest.approx(sum(i["entregado_ui"] for i in fila["insulinas"]))
    assert [r["intercambios"] for r in hist["repartos"]] == [0, 1]
    assert ("Levemir FlexPen 3 ml", 1) in {
        (l["producto"], l["unidades"]) for l in hist["repartos"][1]["paciente"]["insulinas"][0]["lotes"]
    }
    con_descartados = (
        await client.get(f"/donations/distributions/beneficiarios/{adulto.id}", params={"incluir_descartados": True})
    ).json()
    assert [r["distribution_id"] for r in con_descartados["repartos"]] == [borrador["id"], descartado["id"], consolidado["id"]]
    assert (await client.get(f"/donations/distributions/beneficiarios/{-asistido.id}")).status_code == 200
    assert (await client.get("/donations/distributions/beneficiarios/999999999")).status_code == 404


# ------------------------------------------------------------------------------------------------ aviso en el portal
def _como(user):
    """Las rutas del beneficiario (usuario activo) responden como `user`; las del almacén siguen como SUPER_ADMIN."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: user


@pytest.mark.asyncio
async def test_consolidating_notifies_each_beneficiary_in_their_portal(client, aislado):
    menor, adulto, detemir = await _escenario(client, aislado)
    asistido = await _asistido(aislado)
    await _solo(aislado, menor, adulto, detemir, asistidos=[asistido])
    detemir.user_id = None  # ficha sin usuario: no puede entrar al portal
    await aislado.flush()

    data = (await client.post("/donations/distributions")).json()
    assert data["avisos"] == [] and (await aislado.execute(select(func.count(models.InsulinDistributionNotice.id)))).scalar() == 0
    assert (await client.get("/donations/insulin-notices/me")).status_code == 403  # el personal no tiene avisos

    desde, hasta = date.today() + timedelta(days=7), date.today() + timedelta(days=16)
    res = await client.post(
        f"/donations/distributions/{data['id']}/consolidate",
        json={"mensaje": "  Llevar su carnet de identidad  ", "entrega_desde": desde.isoformat(), "entrega_hasta": hasta.isoformat()},
    )
    assert res.status_code == 200, res.text
    cons = res.json()
    assert cons["aviso_mensaje"] == "Llevar su carnet de identidad"
    assert (cons["entrega_desde"], cons["entrega_hasta"]) == (desde.isoformat(), hasta.isoformat())
    estados = {a["beneficiario_id"]: a["estado"] for a in cons["avisos"]}
    assert estados == {menor.id: "PENDIENTE", adulto.id: "PENDIENTE", detemir.id: "SIN_CUENTA", -asistido.id: "SIN_PORTAL"}

    # El beneficiario ve en su portal lo que le corresponde, tal como quedó consolidado.
    usuario = await aislado.get(models.User, adulto.user_id)
    _como(usuario)
    avisos = (await client.get("/donations/insulin-notices/me")).json()
    assert len(avisos) == 1
    aviso, fila = avisos[0], _fila(cons, adulto.id)["insulinas"][0]
    assert aviso["distribution_id"] == cons["id"] and aviso["dias"] == cons["dias"] and aviso["visto_at"] is None
    assert aviso["mensaje"] == "Llevar su carnet de identidad"
    assert (aviso["entrega_desde"], aviso["entrega_hasta"]) == (desde.isoformat(), hasta.isoformat())
    t = aviso["tratamientos"][0]
    assert t["insulina"] == "Glargina" and t["dosis_diaria"] == 20
    assert t["envases"] == aviso["envases"] == sum(l["unidades"] for l in fila["lotes"]) > 0
    assert t["ui"] == pytest.approx(fila["entregado_ui"])
    assert t["dias_cubiertos"] == int(fila["cobertura_pct"] * cons["dias"] / 100 + 0.5)
    assert [(p["producto"], p["envases"], p["lote"]) for p in t["productos"]] == [
        (l["producto"], l["unidades"], l["lote"]) for l in fila["lotes"]
    ]
    assert all(p["lote"] and p["fecha_venc"] for p in t["productos"])  # el número de lote siempre llega al aviso

    # «Entendido»: queda la fecha en que lo vio (la primera) y el personal lo ve.
    visto = await client.post(f"/donations/insulin-notices/me/{aviso['id']}/visto")
    assert visto.status_code == 200 and visto.json()["visto_at"]
    otra_vez = (await client.post(f"/donations/insulin-notices/me/{aviso['id']}/visto")).json()
    assert otra_vez["visto_at"] == visto.json()["visto_at"]
    detalle = (await client.get(f"/donations/distributions/{cons['id']}")).json()
    assert {a["beneficiario_id"]: a["estado"] for a in detalle["avisos"]}[adulto.id] == "VISTO"

    # Nadie ve ni marca el aviso de otro.
    _como(await aislado.get(models.User, menor.user_id))
    assert (await client.post(f"/donations/insulin-notices/me/{aviso['id']}/visto")).status_code == 404
    del_menor = (await client.get("/donations/insulin-notices/me")).json()
    assert [a["id"] for a in del_menor] != [aviso["id"]] and len(del_menor) == 1

    # Un reparto consolidado después queda primero. Sin fechas, la entrega es del 1 al 10 del mes siguiente.
    _como(usuario)
    segundo = (await client.post("/donations/distributions")).json()
    assert (await client.post(f"/donations/distributions/{segundo['id']}/consolidate")).status_code == 200
    avisos = (await client.get("/donations/insulin-notices/me")).json()
    assert [a["distribution_id"] for a in avisos] == [segundo["id"], cons["id"]]
    assert avisos[0]["visto_at"] is None and avisos[0]["mensaje"] is None and avisos[1]["visto_at"]
    hoy = date.today()
    anio, mes = (hoy.year + 1, 1) if hoy.month == 12 else (hoy.year, hoy.month + 1)
    assert (avisos[0]["entrega_desde"], avisos[0]["entrega_hasta"]) == (
        date(anio, mes, 1).isoformat(), date(anio, mes, 10).isoformat()
    )


@pytest.mark.asyncio
async def test_the_beneficiary_uploads_the_photos_of_used_insulin_and_hba1c(client, aislado, monkeypatch):
    from app.api.endpoints import patients as patients_module

    subidas, borradas = [], []

    def _subir(content, path, content_type):
        subidas.append((path, content_type))
        return f"https://storage.test/{path}"

    monkeypatch.setattr(warehouse_module, "upload_file_to_firebase", _subir)
    monkeypatch.setattr(warehouse_module, "delete_file_from_firebase_by_url", borradas.append)
    menor, adulto, detemir = await _escenario(client, aislado)
    await _solo(aislado, menor, adulto, detemir)
    data = (await client.post("/donations/distributions")).json()
    cons = (await client.post(f"/donations/distributions/{data['id']}/consolidate")).json()
    jpg = {"foto": ("plumas.jpg", b"\xff\xd8\xff jpeg", "image/jpeg")}
    assert (await client.post("/donations/insulin-notices/me/1/fotos/envases", files=jpg)).status_code == 403  # personal

    _como(await aislado.get(models.User, adulto.user_id))
    aviso = (await client.get("/donations/insulin-notices/me")).json()[0]
    assert aviso["foto_envases"] is None and aviso["foto_hba1c"] is None
    url = f"/donations/insulin-notices/me/{aviso['id']}/fotos"

    res = await client.post(f"{url}/envases", files=jpg)
    assert res.status_code == 200, res.text
    primera = res.json()["url"]
    assert primera.startswith(f"https://storage.test/pacientes/{adulto.id}/repartos/{cons['id']}/insulinas_usadas_")
    assert primera.endswith(".jpg") and res.json()["subida_at"] and res.json()["estado"] == "PENDIENTE"

    # El resultado de laboratorio puede venir en PDF; las insulinas usadas, solo en foto.
    pdf = {"foto": ("hba1c.pdf", b"%PDF-1.4", "application/pdf")}
    assert (await client.post(f"{url}/envases", files=pdf)).status_code == 400
    hba1c = await client.post(f"{url}/hba1c", files=pdf)
    assert hba1c.status_code == 200 and "/hemoglobina_glucosilada_" in hba1c.json()["url"]

    # Otra foto reemplaza a la anterior, que se borra del almacenamiento.
    otra = (await client.post(f"{url}/envases", files={"foto": ("plumas.png", b"\x89PNG", "image/png")})).json()
    assert otra["url"] != primera and otra["url"].endswith(".png")
    assert borradas == [primera]

    # Vacía, demasiado grande o de un tipo que no existe: no se sube nada.
    assert (await client.post(f"{url}/envases", files={"foto": ("vacia.jpg", b"", "image/jpeg")})).status_code == 400
    grande = {"foto": ("grande.jpg", b"\xff" * (warehouse_module.NOTICE_PHOTO_MAX_BYTES + 1), "image/jpeg")}
    assert (await client.post(f"{url}/envases", files=grande)).status_code == 413
    assert (await client.post(f"{url}/receta", files=jpg)).status_code == 422
    assert len(subidas) == 3

    # Lo ve en su aviso, y nadie sube fotos al aviso de otro.
    aviso = (await client.get("/donations/insulin-notices/me")).json()[0]
    assert (aviso["foto_envases"]["url"], aviso["foto_hba1c"]["url"]) == (otra["url"], hba1c.json()["url"])
    _como(await aislado.get(models.User, menor.user_id))
    assert (await client.post(f"{url}/envases", files=jpg)).status_code == 404

    # El personal las ve en el reparto consolidado, con el aviso para revisarlas.
    detalle = (await client.get(f"/donations/distributions/{cons['id']}")).json()
    avisos = {a["beneficiario_id"]: a for a in detalle["avisos"]}
    assert avisos[adulto.id]["notice_id"] == aviso["id"]
    assert avisos[adulto.id]["foto_envases"]["url"] == otra["url"] and avisos[adulto.id]["foto_hba1c"]["estado"] == "PENDIENTE"
    assert avisos[menor.id]["foto_envases"] is None

    # Si se borra al beneficiario, sus fotos se borran con sus demás documentos.
    urls = await patients_module._collect_patient_document_urls(aislado, adulto)
    assert {otra["url"], hba1c.json()["url"]} <= set(urls)


@pytest.mark.asyncio
async def test_the_super_admin_approves_or_observes_each_photo(client, aislado, monkeypatch):
    monkeypatch.setattr(warehouse_module, "upload_file_to_firebase", lambda content, path, ct: f"https://storage.test/{path}")
    monkeypatch.setattr(warehouse_module, "delete_file_from_firebase_by_url", lambda u: None)
    menor, adulto, detemir = await _escenario(client, aislado)
    await _solo(aislado, menor, adulto, detemir)
    data = (await client.post("/donations/distributions")).json()
    cons = (await client.post(f"/donations/distributions/{data['id']}/consolidate")).json()
    usuario = await aislado.get(models.User, adulto.user_id)
    _como(usuario)
    aviso = (await client.get("/donations/insulin-notices/me")).json()[0]
    subir = lambda tipo, nombre="foto.jpg": client.post(  # noqa: E731
        f"/donations/insulin-notices/me/{aviso['id']}/fotos/{tipo}", files={"foto": (nombre, b"\xff\xd8\xff", "image/jpeg")}
    )
    revision = f"/donations/insulin-notices/{aviso['id']}/fotos"

    # Lo que todavía no subió no se puede revisar.
    assert (await client.post(f"{revision}/envases/revision", json={"estado": "APROBADA"})).status_code == 404
    assert (await subir("envases")).status_code == 200 and (await subir("hba1c")).status_code == 200

    # Observar exige decir qué corregir.
    sin_motivo = await client.post(f"{revision}/hba1c/revision", json={"estado": "OBSERVADA", "observacion": "  "})
    assert sin_motivo.status_code == 422
    obs = await client.post(
        f"{revision}/hba1c/revision", json={"estado": "OBSERVADA", "observacion": "  No se lee el resultado  "}
    )
    assert obs.status_code == 200, obs.text
    assert obs.json()["estado"] == "OBSERVADA" and obs.json()["observacion"] == "No se lee el resultado"
    assert obs.json()["revisada_por"] and obs.json()["revisada_at"]
    apr = await client.post(f"{revision}/envases/revision", json={"estado": "APROBADA", "observacion": "ignorada"})
    assert apr.status_code == 200 and apr.json()["estado"] == "APROBADA" and apr.json()["observacion"] is None

    # El beneficiario ve la revisión (sin saber quién la hizo).
    mio = (await client.get("/donations/insulin-notices/me")).json()[0]
    assert mio["foto_envases"]["estado"] == "APROBADA" and mio["foto_envases"]["revisada_por"] is None
    assert (mio["foto_hba1c"]["estado"], mio["foto_hba1c"]["observacion"]) == ("OBSERVADA", "No se lee el resultado")

    # La aprobada ya no se cambia; la observada se reemplaza y vuelve a quedar por revisar.
    assert (await subir("envases")).status_code == 409
    nueva = (await subir("hba1c", "hba1c_nitida.jpg")).json()
    assert nueva["estado"] == "PENDIENTE" and nueva["observacion"] is None and nueva["revisada_at"] is None

    # El personal ve el estado de cada foto y quién la revisó; cada revisión queda en la auditoría.
    detalle = (await client.get(f"/donations/distributions/{cons['id']}")).json()
    fila = {a["beneficiario_id"]: a for a in detalle["avisos"]}[adulto.id]
    assert fila["foto_envases"]["estado"] == "APROBADA" and fila["foto_envases"]["revisada_por"]
    assert fila["foto_hba1c"]["estado"] == "PENDIENTE"
    revisiones = (
        await aislado.execute(
            select(models.AuditLog.payload).where(models.AuditLog.accion == "REVIEW_INSULIN_NOTICE_PHOTO")
            .order_by(models.AuditLog.id)
        )
    ).scalars().all()
    assert [(r["tipo"], r["estado"]) for r in revisiones[-2:]] == [("hba1c", "OBSERVADA"), ("envases", "APROBADA")]
    assert (await client.post(f"{revision}/receta/revision", json={"estado": "APROBADA"})).status_code == 422


@pytest.mark.asyncio
async def test_the_delivery_window_must_be_complete_and_not_already_over(client, aislado):
    menor, adulto, detemir = await _escenario(client, aislado)
    await _solo(aislado, menor, adulto, detemir)
    data = (await client.post("/donations/distributions")).json()
    url = f"/donations/distributions/{data['id']}/consolidate"
    hoy = date.today()

    solo_desde = await client.post(url, json={"entrega_desde": hoy.isoformat()})
    al_reves = await client.post(url, json={"entrega_desde": (hoy + timedelta(days=5)).isoformat(), "entrega_hasta": hoy.isoformat()})
    ya_paso = await client.post(
        url, json={"entrega_desde": (hoy - timedelta(days=10)).isoformat(), "entrega_hasta": (hoy - timedelta(days=1)).isoformat()}
    )
    assert solo_desde.status_code == al_reves.status_code == 422
    assert ya_paso.status_code == 400 and "antes de hoy" in ya_paso.json()["detail"]
    assert (await client.get(f"/donations/distributions/{data['id']}")).json()["estado"] == "BORRADOR"  # nada se consolidó

    hoy_mismo = await client.post(url, json={"entrega_desde": hoy.isoformat(), "entrega_hasta": hoy.isoformat()})
    assert hoy_mismo.status_code == 200 and hoy_mismo.json()["entrega_hasta"] == hoy.isoformat()


@pytest.mark.asyncio
async def test_warehouse_refuses_an_approximate_split(client, aislado, monkeypatch):
    monkeypatch.setattr(warehouse_module, "REQUIRE_OPTIMIZER", True)
    await _escenario(client, aislado)
    res = await client.post("/donations/distributions")
    assert res.status_code == 503 and "scipy" in res.json()["detail"]
    assert (await aislado.execute(select(func.count(models.InsulinDistribution.id)))).scalar() == 0


@pytest.mark.asyncio
async def test_without_stock_there_is_nothing_to_distribute(client, aislado):
    res = await client.post("/donations/distributions")
    assert res.status_code == 400 and "No hay stock" in res.json()["detail"]


@pytest.mark.asyncio
async def test_only_super_admin_uses_the_warehouse(client, patient_token):
    for method, url in (
        ("get", "/donations/stock"),
        ("get", "/donations/intakes"),
        ("get", "/donations/distributions"),
        ("post", "/donations/distributions"),
        ("post", "/donations/distributions/1/consolidate"),
        ("post", "/donations/insulin-notices/1/fotos/envases/revision"),
    ):
        res = await getattr(client, method)(url)
        assert res.status_code in (401, 403), (url, res.status_code)
