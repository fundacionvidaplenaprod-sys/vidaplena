"""
Corrección del aporte mensual comprometido (PUT /patients/{id}/commitment-amount).

Caso real: el informe de la evaluación socioeconómica fijó un aporte reducido de Bs. 25, pero el
beneficiario quedó comprometido con Bs. 100 y nadie podía corregirlo.
"""
import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app import models


async def _beneficiario(db_session, *, monto, estado="ACTIVO", media=False, exonerado=False, user_id=None):
    sufijo = uuid.uuid4().hex[:8]
    patient = models.Patient(
        user_id=user_id,
        nombres="Monto",
        ap_paterno=f"Aporte{sufijo}",
        ci=f"MA{sufijo}",
        fecha_nac=date(2014, 3, 11),
        depto="Cochabamba",
        estado=estado,
        monto_aporte_comprometido=monto,
        url_declaracion_aporte="https://storage.example/compromiso_firmado.pdf",
        exonerado_aporte=exonerado,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    if media or exonerado:
        db_session.add(
            models.SocialEvaluation(
                patient_id=patient.id,
                departamento="Cochabamba",
                integrantes_hogar=5,
                dependientes=3,
                tipo_vivienda="Alquilada",
                monto_alquiler=900.0,
                tiene_seguro=False,
                ingreso_titular=0.0,
                ingreso_conyuge=2000.0,
                ingreso_per_capita=400.0,
                categoria_asignada="ALTA",
                estado_alerta="NORMAL",
                habeas_data_accepted=True,
                imagen_consent_accepted=True,
                estado_revision="APROBADO",
                categoria_final="MEDIA" if media else "ALTA",
            )
        )
        await db_session.commit()
    # Los tests comparten sesión con la app: sin esto la ficha recién sembrada queda en memoria sin
    # sus relaciones y no se serializa (en producción cada petición la carga desde cero).
    db_session.expunge_all()
    return patient


async def _recargar(db_session, patient_id):
    db_session.expire_all()
    return (await db_session.execute(select(models.Patient).where(models.Patient.id == patient_id))).scalars().one()


@pytest.mark.asyncio
async def test_corrige_el_monto_anula_el_compromiso_firmado_y_reabre_el_expediente(client, superuser_token, db_session):
    patient = await _beneficiario(db_session, monto=100, media=True)

    resp = await client.put(
        f"/patients/{patient.id}/commitment-amount",
        json={"monto": 25, "motivo": "El informe indica un aporte de Bs. 25."},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["monto_aporte_comprometido"] == 25.0
    assert resp.json()["estado"] == "PENDIENTE_DOC"

    guardado = await _recargar(db_session, patient.id)
    assert float(guardado.monto_aporte_comprometido) == 25.0
    assert guardado.url_declaracion_aporte is None  # el compromiso con Bs. 100 ya no vale
    assert guardado.estado == "PENDIENTE_DOC"

    evento = (
        await db_session.execute(
            select(models.PatientStatusEvent)
            .where(models.PatientStatusEvent.patient_id == patient.id)
            .order_by(models.PatientStatusEvent.id.desc())
        )
    ).scalars().first()
    assert (evento.old_state, evento.new_state) == ("ACTIVO", "PENDIENTE_DOC")
    assert evento.payload == {"commitment_amount_changed": True, "old_amount": 100.0, "new_amount": 25.0}
    auditoria = (
        await db_session.execute(
            select(models.AuditLog).where(
                models.AuditLog.entidad_id == patient.id, models.AuditLog.accion == "UPDATE_COMMITMENT_AMOUNT"
            )
        )
    ).scalars().one()
    assert auditoria.payload["old_amount"] == 100.0 and auditoria.payload["new_amount"] == 25.0
    assert "Bs. 25" in auditoria.payload["motivo"]


@pytest.mark.asyncio
async def test_sin_evaluacion_de_aporte_reducido_rige_el_minimo_de_100(client, superuser_token, db_session):
    patient = await _beneficiario(db_session, monto=100)

    por_debajo = await client.put(
        f"/patients/{patient.id}/commitment-amount", json={"monto": 25, "motivo": "Prueba de mínimo"}
    )
    assert por_debajo.status_code == 400
    assert "100" in por_debajo.json()["detail"]
    assert float((await _recargar(db_session, patient.id)).monto_aporte_comprometido) == 100.0  # no cambió

    mayor = await client.put(
        f"/patients/{patient.id}/commitment-amount", json={"monto": 150, "motivo": "El beneficiario quiere aportar más"}
    )
    assert mayor.status_code == 200
    assert float((await _recargar(db_session, patient.id)).monto_aporte_comprometido) == 150.0


@pytest.mark.asyncio
async def test_un_exonerado_no_tiene_monto_que_corregir_y_el_motivo_es_obligatorio(client, superuser_token, db_session):
    exonerado = await _beneficiario(db_session, monto=None, exonerado=True)
    resp = await client.put(f"/patients/{exonerado.id}/commitment-amount", json={"monto": 25, "motivo": "Prueba exonerado"})
    assert resp.status_code == 400
    assert "exonerado" in resp.json()["detail"].lower()

    normal = await _beneficiario(db_session, monto=100, media=True)
    sin_motivo = await client.put(f"/patients/{normal.id}/commitment-amount", json={"monto": 25, "motivo": ""})
    assert sin_motivo.status_code == 422
    monto_cero = await client.put(f"/patients/{normal.id}/commitment-amount", json={"monto": 0, "motivo": "Monto cero"})
    assert monto_cero.status_code == 422
    inexistente = await client.put("/patients/99999999/commitment-amount", json={"monto": 25, "motivo": "No existe"})
    assert inexistente.status_code == 404


@pytest.mark.asyncio
async def test_solo_el_super_admin_corrige_el_monto(client, patient_token, db_session):
    patient = await _beneficiario(db_session, monto=100, media=True)
    resp = await client.put(f"/patients/{patient.id}/commitment-amount", json={"monto": 25, "motivo": "Intento de paciente"})
    assert resp.status_code == 403
    assert float((await _recargar(db_session, patient.id)).monto_aporte_comprometido) == 100.0


@pytest.mark.asyncio
async def test_reabrir_el_compromiso_conserva_el_aporte_reducido_de_la_evaluacion(client, superuser_token, db_session):
    reducido = await _beneficiario(db_session, monto=25, media=True)
    estandar = await _beneficiario(db_session, monto=150)

    r1 = await client.post(f"/patients/{reducido.id}/reset-commitment", json={"observacion_admin": "Reapertura"})
    r2 = await client.post(f"/patients/{estandar.id}/reset-commitment", json={"observacion_admin": "Reapertura"})
    assert r1.status_code == 200 and r2.status_code == 200

    reducido = await _recargar(db_session, reducido.id)
    assert (reducido.estado, float(reducido.monto_aporte_comprometido), reducido.url_declaracion_aporte) == ("PENDIENTE_DOC", 25.0, None)
    # sin evaluación de aporte reducido el beneficiario vuelve a elegir su monto
    estandar = await _recargar(db_session, estandar.id)
    assert (estandar.estado, estandar.monto_aporte_comprometido) == ("PENDIENTE_DOC", None)


@pytest.mark.asyncio
async def test_el_beneficiario_descarga_el_compromiso_con_el_monto_corregido(client, patient_token, db_session):
    patient = await _beneficiario(db_session, monto=25, estado="PENDIENTE_DOC", media=True, user_id=patient_token.id)

    corregido = await client.get("/patients/me/commitment-template", params={"monto_compromiso": 25})
    assert corregido.status_code == 200, corregido.text
    assert corregido.headers["content-type"].startswith("application/pdf")
    # no puede bajar uno con otro monto: el fijado manda
    otro = await client.get("/patients/me/commitment-template", params={"monto_compromiso": 100})
    assert otro.status_code == 400
    assert "25.00" in otro.json()["detail"]
    assert patient.id
