"""Boletas de las entregas registradas con el almacén anterior: el beneficiario las sigue viendo y descargando en su
portal aunque ese almacén se haya reemplazado (sus entregas y asignaciones se conservan en la base)."""
import uuid
from datetime import date, timedelta

import pytest

from app import models
from app.api import deps
from app.main import app


async def _paciente_con_cuenta(db_session, nombres="Juan"):
    user = models.User(email=f"patient_{uuid.uuid4().hex[:8]}@test.com", password_hash="fakehash", role="PACIENTE", estado="ACTIVO")
    db_session.add(user)
    await db_session.flush()
    patient = models.Patient(
        user_id=user.id, nombres=nombres, ap_paterno="Perez", ci=f"CI-{uuid.uuid4().hex[:6]}", fecha_nac=date(1990, 1, 1),
        tipo_sangre="O+", estado="ACTIVO",
    )
    db_session.add(patient)
    await db_session.flush()
    return user, patient


async def _entrega_anterior(db_session, patient, *, cantidad=4, dias_atras=10):
    """Una entrega como las que registraba el almacén anterior: producto, lote, asignación consolidada y entrega."""
    donation = models.Donation(
        tipo="INSULINA", nombre_generico="Lispro", marca="Humalog", nombre_comercial="Humalog KwikPen", presentacion="3 ml",
        factor_conversion=300.0,
    )
    db_session.add(donation)
    await db_session.flush()
    lot = models.DonationLot(
        donation_id=donation.id, lote=f"L-{uuid.uuid4().hex[:6]}", fecha_venc=date.today() + timedelta(days=365),
        cantidad_total=50, cantidad_disponible=50 - cantidad,
    )
    db_session.add(lot)
    await db_session.flush()
    allocation = models.DonationAllocation(
        lot_id=lot.id, patient_id=patient.id, cantidad_sugerida=cantidad, cantidad_ajustada=cantidad, estado="CONSOLIDADO",
    )
    db_session.add(allocation)
    await db_session.flush()
    delivery = models.Delivery(
        allocation_id=allocation.id, patient_id=patient.id, fecha_entrega=date.today() - timedelta(days=dias_atras),
        cantidad_entregada=cantidad, estado="PENDIENTE_CARGA",
    )
    db_session.add(delivery)
    await db_session.flush()
    return delivery


@pytest.mark.asyncio
async def test_the_beneficiary_still_sees_and_downloads_their_previous_delivery_receipts(client, db_session):
    user, patient = await _paciente_con_cuenta(db_session)
    _, otro = await _paciente_con_cuenta(db_session, nombres="Otro")
    reciente = await _entrega_anterior(db_session, patient, dias_atras=5)
    antigua = await _entrega_anterior(db_session, patient, cantidad=2, dias_atras=40)
    ajena = await _entrega_anterior(db_session, otro)

    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    try:
        res = await client.get("/donations/deliveries/me")
        assert res.status_code == 200, res.text
        assert [(d["id"], d["cantidad_entregada"]) for d in res.json()] == [(reciente.id, 4), (antigua.id, 2)]

        boleta = await client.get(f"/donations/deliveries/me/{reciente.id}/receipt")
        assert boleta.status_code == 200
        assert boleta.headers["content-type"] == "application/pdf" and boleta.content.startswith(b"%PDF")
        assert (await client.get(f"/donations/deliveries/me/{ajena.id}/receipt")).status_code == 404  # la de otro, no
    finally:
        app.dependency_overrides.pop(deps.get_current_active_user, None)


@pytest.mark.asyncio
async def test_only_beneficiaries_have_delivery_receipts(client, superuser_token):
    assert (await client.get("/donations/deliveries/me")).status_code == 403
