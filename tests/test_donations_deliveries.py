import uuid
import pytest
from datetime import date, timedelta
from app import models


async def _seed_test_patient(db_session):
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
        nombres="Juan",
        ap_paterno="Perez",
        ci=f"CI-{uuid.uuid4().hex[:6]}",
        fecha_nac=date(1990, 1, 1),
        tipo_sangre="O+",
        estado="ACTIVO",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


async def _seed_lot(db_session):
    donation = models.Donation(
        tipo="INSULINA",
        nombre_generico="Insulina Lispro",
        marca="TestMarca",
        nombre_comercial="TestComercial",
        presentacion="Frasco",
        factor_conversion=100.0,
    )
    db_session.add(donation)
    await db_session.commit()
    await db_session.refresh(donation)

    lot = models.DonationLot(
        donation_id=donation.id,
        lote=f"L-{uuid.uuid4().hex[:6]}",
        fecha_venc=date.today() + timedelta(days=365),
        cantidad_total=5000,
        cantidad_disponible=5000,
    )
    db_session.add(lot)
    await db_session.commit()
    await db_session.refresh(lot)
    return lot


@pytest.mark.asyncio
async def test_donation_product_and_lot_creation(client, superuser_token):
    # 1. Crear producto de donación (Insulina)
    prod_payload = {
        "tipo": "INSULINA",
        "nombre_generico": "Insulina Lispro Test",
        "marca": "Humalog",
        "nombre_comercial": "Humalog 100 UI Test",
        "presentacion": "Frasco 10ml",
        "factor_conversion": 1000.0,
    }
    res_prod = await client.post("/donations/products/", json=prod_payload)
    assert res_prod.status_code == 200, res_prod.text
    prod_data = res_prod.json()
    assert prod_data["nombre_generico"] == "Lispro"
    donation_id = prod_data["id"]

    # 2. Crear lote de donación
    lot_payload = {
        "donation_id": donation_id,
        "lote": f"LOTE-{uuid.uuid4().hex[:6]}",
        "fecha_venc": (date.today() + timedelta(days=365)).isoformat(),
        "cantidad_total": 50,
    }
    res_lot = await client.post("/donations/lots/", json=lot_payload)
    assert res_lot.status_code == 200, res_lot.text
    lot_data = res_lot.json()
    assert lot_data["cantidad_disponible"] == 50
    assert lot_data["donation_id"] == donation_id


@pytest.mark.asyncio
async def test_delivery_fails_if_allocation_not_consolidated(client, superuser_token, db_session):
    patient = await _seed_test_patient(db_session)
    lot = await _seed_lot(db_session)

    # Crear una asignación en estado BORRADOR
    alloc = models.DonationAllocation(
        lot_id=lot.id,
        patient_id=patient.id,
        cantidad_sugerida=3,
        cantidad_ajustada=3,
        estado="BORRADOR",
    )
    db_session.add(alloc)
    await db_session.commit()
    await db_session.refresh(alloc)

    payload = {
        "allocation_id": alloc.id,
        "fecha_entrega": date.today().isoformat(),
        "cantidad_entregada": 2,
    }
    res = await client.post("/donations/deliveries/", json=payload)
    assert res.status_code == 400
    assert "consolidada" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delivery_success_for_consolidated_allocation_and_no_duplicates(
    client, superuser_token, db_session
):
    patient = await _seed_test_patient(db_session)
    lot = await _seed_lot(db_session)

    # Crear una asignación en estado CONSOLIDADO
    alloc = models.DonationAllocation(
        lot_id=lot.id,
        patient_id=patient.id,
        cantidad_sugerida=4,
        cantidad_ajustada=4,
        estado="CONSOLIDADO",
    )
    db_session.add(alloc)
    await db_session.commit()
    await db_session.refresh(alloc)

    # 1. Crear entrega con éxito
    payload = {
        "allocation_id": alloc.id,
        "fecha_entrega": date.today().isoformat(),
        "cantidad_entregada": 4,
    }
    res = await client.post("/donations/deliveries/", json=payload)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["cantidad_entregada"] == 4
    assert data["estado"] == "PENDIENTE_CARGA"
    assert "id" in data

    # 2. Verificar que intentar crear otra entrega para la misma asignación sea rechazado
    res_dup = await client.post("/donations/deliveries/", json=payload)
    assert res_dup.status_code == 400
    assert "ya tiene una entrega registrada" in res_dup.json()["detail"].lower()

    # 3. Consultar entrega por asignación (GET /donations/deliveries/by-allocation/{id})
    res_get = await client.get(f"/donations/deliveries/by-allocation/{alloc.id}")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == data["id"]


@pytest.mark.asyncio
async def test_delivery_fails_if_quantity_exceeds_allocated(client, superuser_token, db_session):
    patient = await _seed_test_patient(db_session)
    lot = await _seed_lot(db_session)

    alloc = models.DonationAllocation(
        lot_id=lot.id,
        patient_id=patient.id,
        cantidad_sugerida=2,
        cantidad_ajustada=2,
        estado="CONSOLIDADO",
    )
    db_session.add(alloc)
    await db_session.commit()
    await db_session.refresh(alloc)

    payload = {
        "allocation_id": alloc.id,
        "fecha_entrega": date.today().isoformat(),
        "cantidad_entregada": 5,  # Excede la cantidad asignada (2)
    }
    res = await client.post("/donations/deliveries/", json=payload)
    assert res.status_code == 400
    assert "fuera de rango" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_calculate_distribution_success_with_active_contribution(client, superuser_token, db_session):
    patient = await _seed_test_patient(db_session)
    lot = await _seed_lot(db_session)

    # 1. Aporte al día para el periodo actual
    periodo_actual = f"{date.today().year}-{date.today().month:02d}"
    contrib = models.MonthlyContribution(
        patient_id=patient.id,
        periodo=periodo_actual,
        fecha_pago=date.today(),
        monto=10.0,
        url_comprobante="http://test.com/comprobante.pdf",
        estado="ACEPTADO",
    )
    db_session.add(contrib)

    # 2. Tratamiento compatible con la insulina del lote (20 UI/d * 30 días = 600 UI / factor 100 = 6 frascos)
    tx = models.PatientTreatment(
        patient_id=patient.id,
        nombre="Insulina Lispro",
        dosis_diaria=20.0,
    )
    db_session.add(tx)
    await db_session.commit()

    res = await client.post(f"/donations/calculate-distribution/{lot.id}")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total_pacientes_compatibles"] >= 1
    # Verifica que se generaron frascos sugeridos para el paciente
    allocs = [a for a in data["allocations"] if a["patient_id"] == patient.id]
    assert len(allocs) == 1
    assert allocs[0]["cantidad_sugerida"] == 18
    assert allocs[0]["estado"] == "BORRADOR"


@pytest.mark.asyncio
async def test_calculate_distribution_excludes_patient_without_contribution(client, superuser_token, db_session):
    patient = await _seed_test_patient(db_session)
    lot = await _seed_lot(db_session)

    # Paciente CON tratamiento pero SIN aporte para el periodo
    tx = models.PatientTreatment(
        patient_id=patient.id,
        nombre="Insulina Lispro",
        dosis_diaria=10.0,
    )
    db_session.add(tx)
    await db_session.commit()

    res = await client.post(f"/donations/calculate-distribution/{lot.id}")
    assert res.status_code == 200, res.text
    data = res.json()
    excluded = [e for e in data["excluded_patients"] if e["patient_id"] == patient.id]
    assert len(excluded) == 1
    assert "falta aporte" in excluded[0]["motivo"].lower()


@pytest.mark.asyncio
async def test_calculate_distribution_applies_solidarity_when_shortage(client, superuser_token, db_session):
    # Lote con stock suficiente para 1 por paciente pero inferior al requerimiento total (escasez)
    lot = await _seed_lot(db_session)
    lot.cantidad_disponible = 10
    await db_session.commit()

    patient = await _seed_test_patient(db_session)
    periodo_actual = f"{date.today().year}-{date.today().month:02d}"
    contrib = models.MonthlyContribution(
        patient_id=patient.id,
        periodo=periodo_actual,
        fecha_pago=date.today(),
        monto=10.0,
        url_comprobante="http://test.com/comprobante.pdf",
        estado="ACEPTADO",
    )
    db_session.add(contrib)
    tx = models.PatientTreatment(
        patient_id=patient.id,
        nombre="Insulina Lispro",
        dosis_diaria=30.0,
    )
    db_session.add(tx)
    await db_session.commit()

    res = await client.post(f"/donations/calculate-distribution/{lot.id}")
    assert res.status_code == 200, res.text
    data = res.json()
    allocs = [a for a in data["allocations"] if a["patient_id"] == patient.id]
    assert len(allocs) == 1
    # Por regla de solidaridad en escasez, se reduce a 1 envase
    assert allocs[0]["cantidad_sugerida"] == 1
