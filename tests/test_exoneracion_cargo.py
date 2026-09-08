"""
Exoneración del aporte mensual por cargo (Responsable Departamental).

Por normativa interna, un SUPER_ADMIN puede exonerar del aporte mensual a un
responsable departamental que además sea beneficiario, porque el cargo no es
remunerado. La exoneración es independiente de la que otorga la evaluación
socioeconómica y se revoca sola cuando la persona deja el cargo.
"""
import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app import models
from app.core.contributions import current_periodo, is_patient_current_on_contribution


MOTIVO = "Responsable departamental sin remuneracion, segun normativa interna."


@pytest_asyncio.fixture(autouse=True)
async def _limpiar_rastros(db_session):
    """
    Borra lo que crea cada test. A diferencia del resto de la suite, acá la
    limpieza no es opcional: `exonerado_por_cargo` es una bandera con carga
    semántica —un exonerado aparece como "al día" en el panel departamental
    sin haber aportado—, y dejar fichas de prueba marcadas ensucia una vista
    que el personal usa para decidir entregas de insulina.
    """
    yield

    creados = (
        await db_session.execute(
            select(models.Patient).where(models.Patient.ci.like("EXO-%"))
        )
    ).scalars().all()
    ids = [p.id for p in creados]

    if ids:
        await db_session.execute(
            delete(models.AuditLog).where(
                models.AuditLog.entidad == "patient",
                models.AuditLog.entidad_id.in_(ids),
            )
        )
        await db_session.execute(
            delete(models.Patient).where(models.Patient.id.in_(ids))
        )

    # audit_logs.actor_id referencia users sin ON DELETE, así que las filas de
    # auditoría del super admin de prueba deben irse antes que su cuenta.
    usuarios = (
        await db_session.execute(
            select(models.User.id).where(
                models.User.email.like("resp_exo_%@test.com")
            )
        )
    ).scalars().all()
    if usuarios:
        await db_session.execute(
            delete(models.AuditLog).where(models.AuditLog.actor_id.in_(usuarios))
        )
        await db_session.execute(
            delete(models.User).where(models.User.id.in_(usuarios))
        )

    await db_session.commit()


async def _seed_responsable(db_session, depto="La Paz"):
    user = models.User(
        email=f"resp_exo_{uuid.uuid4().hex[:8]}@test.com",
        password_hash="fakehash",
        role="RESPONSABLE_DEPARTAMENTAL",
        estado="ACTIVO",
        depto_asignado=depto,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_patient(db_session):
    patient = models.Patient(
        nombres="Elena",
        ap_paterno="Quispe",
        ci=f"EXO-{uuid.uuid4().hex[:8]}",
        fecha_nac=date(1985, 5, 5),
        estado="ACTIVO",
        depto="La Paz",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


async def _refetch(db_session, patient_id):
    """
    Relee la ficha desde la base saltando la identity map (el endpoint la
    modificó en otra sesión). `populate_existing` refresca solo este objeto:
    un `expire_all()` expiraría también los User del test y leer `resp.id`
    dispararía IO perezoso fuera del contexto async. `contributions` se carga
    de forma anticipada porque el helper de aportes la recorre.
    """
    res = await db_session.execute(
        select(models.Patient)
        .where(models.Patient.id == patient_id)
        .options(selectinload(models.Patient.contributions))
        .execution_options(populate_existing=True)
    )
    return res.scalars().first()


@pytest.mark.asyncio
async def test_exonerar_vincula_beneficiario_y_registra_auditoria(
    client, superuser_token, db_session
):
    resp = await _seed_responsable(db_session)
    patient = await _seed_patient(db_session)

    res = await client.post(
        f"/users/{resp.id}/exoneracion-cargo",
        json={"ci": patient.ci, "motivo": MOTIVO},
    )
    assert res.status_code == 200, res.text

    body = res.json()
    assert body["patient_id"] == patient.id
    assert body["beneficiario_ci"] == patient.ci
    assert body["motivo"] == MOTIVO
    assert body["exonerado_at"] is not None

    actualizado = await _refetch(db_session, patient.id)
    assert actualizado.exonerado_por_cargo is True
    assert actualizado.exonerado_cargo_user_id == resp.id
    assert actualizado.exonerado_cargo_por is not None
    # La exoneración por vulnerabilidad queda intacta: son causas distintas.
    assert actualizado.exonerado_aporte is False


@pytest.mark.asyncio
async def test_exoneracion_no_la_pisa_una_evaluacion_social(
    client, superuser_token, db_session
):
    """
    El motivo de tener columnas separadas: la evaluación socioeconómica
    reescribe `exonerado_aporte` en cada revisión, incluido ponerla en False.
    Eso no debe tocar la exoneración por cargo.
    """
    resp = await _seed_responsable(db_session)
    patient = await _seed_patient(db_session)
    await client.post(
        f"/users/{resp.id}/exoneracion-cargo",
        json={"ci": patient.ci, "motivo": MOTIVO},
    )

    # Simula el efecto de una revisión con categoría BAJA sobre la ficha.
    fresco = await _refetch(db_session, patient.id)
    fresco.exonerado_aporte = False
    db_session.add(fresco)
    await db_session.commit()

    final = await _refetch(db_session, patient.id)
    assert final.exonerado_por_cargo is True
    assert is_patient_current_on_contribution(
        final, current_periodo(), include_exonerados=True
    ) is True


@pytest.mark.asyncio
async def test_exonerado_por_cargo_cuenta_como_al_dia(
    client, superuser_token, db_session
):
    resp = await _seed_responsable(db_session)
    patient = await _seed_patient(db_session)

    sin_exonerar = await _refetch(db_session, patient.id)
    assert is_patient_current_on_contribution(
        sin_exonerar, current_periodo(), include_exonerados=True
    ) is False

    await client.post(
        f"/users/{resp.id}/exoneracion-cargo",
        json={"ci": patient.ci, "motivo": MOTIVO},
    )

    exonerado = await _refetch(db_session, patient.id)
    assert is_patient_current_on_contribution(
        exonerado, current_periodo(), include_exonerados=True
    ) is True
    # El filtro anti-morosos del reparto automático NO cambia de comportamiento.
    assert is_patient_current_on_contribution(exonerado, current_periodo()) is False


@pytest.mark.asyncio
async def test_solo_aplica_a_responsable_departamental(
    client, superuser_token, db_session
):
    otro = models.User(
        email=f"registrador_{uuid.uuid4().hex[:8]}@test.com",
        password_hash="fakehash",
        role="REGISTRADOR",
        estado="ACTIVO",
    )
    db_session.add(otro)
    await db_session.commit()
    await db_session.refresh(otro)
    patient = await _seed_patient(db_session)

    res = await client.post(
        f"/users/{otro.id}/exoneracion-cargo",
        json={"ci": patient.ci, "motivo": MOTIVO},
    )
    assert res.status_code == 400
    assert "RESPONSABLE_DEPARTAMENTAL" in res.json()["detail"]


@pytest.mark.asyncio
async def test_ci_inexistente_devuelve_404(client, superuser_token, db_session):
    resp = await _seed_responsable(db_session)
    res = await client.post(
        f"/users/{resp.id}/exoneracion-cargo",
        json={"ci": "NO-EXISTE-9999", "motivo": MOTIVO},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_un_responsable_no_puede_exonerar_dos_fichas(
    client, superuser_token, db_session
):
    resp = await _seed_responsable(db_session)
    primero = await _seed_patient(db_session)
    segundo = await _seed_patient(db_session)

    await client.post(
        f"/users/{resp.id}/exoneracion-cargo",
        json={"ci": primero.ci, "motivo": MOTIVO},
    )
    res = await client.post(
        f"/users/{resp.id}/exoneracion-cargo",
        json={"ci": segundo.ci, "motivo": MOTIVO},
    )
    assert res.status_code == 400
    assert "vigente" in res.json()["detail"]


@pytest.mark.asyncio
async def test_cambio_de_rol_revoca_la_exoneracion(
    client, superuser_token, db_session
):
    resp = await _seed_responsable(db_session)
    patient = await _seed_patient(db_session)
    await client.post(
        f"/users/{resp.id}/exoneracion-cargo",
        json={"ci": patient.ci, "motivo": MOTIVO},
    )

    res = await client.put(f"/users/{resp.id}", json={"role": "REGISTRADOR"})
    assert res.status_code == 200, res.text

    final = await _refetch(db_session, patient.id)
    assert final.exonerado_por_cargo is False
    assert final.exonerado_cargo_user_id is None
    assert final.exonerado_cargo_motivo is None


@pytest.mark.asyncio
async def test_baja_de_cuenta_revoca_la_exoneracion(
    client, superuser_token, db_session
):
    resp = await _seed_responsable(db_session)
    patient = await _seed_patient(db_session)
    await client.post(
        f"/users/{resp.id}/exoneracion-cargo",
        json={"ci": patient.ci, "motivo": MOTIVO},
    )

    res = await client.put(f"/users/{resp.id}/toggle-status")
    assert res.status_code == 200, res.text
    assert res.json()["estado"] == "INACTIVO"

    final = await _refetch(db_session, patient.id)
    assert final.exonerado_por_cargo is False


@pytest.mark.asyncio
async def test_editar_responsable_sin_cambiar_rol_conserva_exoneracion(
    client, superuser_token, db_session
):
    resp = await _seed_responsable(db_session, depto="La Paz")
    patient = await _seed_patient(db_session)
    await client.post(
        f"/users/{resp.id}/exoneracion-cargo",
        json={"ci": patient.ci, "motivo": MOTIVO},
    )

    res = await client.put(
        f"/users/{resp.id}",
        json={"role": "RESPONSABLE_DEPARTAMENTAL", "depto_asignado": "Cochabamba"},
    )
    assert res.status_code == 200, res.text

    final = await _refetch(db_session, patient.id)
    assert final.exonerado_por_cargo is True


@pytest.mark.asyncio
async def test_retiro_manual_de_la_exoneracion(client, superuser_token, db_session):
    resp = await _seed_responsable(db_session)
    patient = await _seed_patient(db_session)
    await client.post(
        f"/users/{resp.id}/exoneracion-cargo",
        json={"ci": patient.ci, "motivo": MOTIVO},
    )

    res = await client.delete(f"/users/{resp.id}/exoneracion-cargo")
    assert res.status_code == 204, res.text

    final = await _refetch(db_session, patient.id)
    assert final.exonerado_por_cargo is False

    # Retirar dos veces no es idempotente por diseño: avisa que no hay nada.
    repetido = await client.delete(f"/users/{resp.id}/exoneracion-cargo")
    assert repetido.status_code == 404


@pytest.mark.asyncio
async def test_listado_expone_la_exoneracion_del_responsable(
    client, superuser_token, db_session
):
    resp = await _seed_responsable(db_session)
    patient = await _seed_patient(db_session)
    await client.post(
        f"/users/{resp.id}/exoneracion-cargo",
        json={"ci": patient.ci, "motivo": MOTIVO},
    )

    res = await client.get("/users/", params={"search": resp.email})
    assert res.status_code == 200, res.text
    item = res.json()["items"][0]
    assert item["exoneracion_cargo"] is not None
    assert item["exoneracion_cargo"]["beneficiario_ci"] == patient.ci
    assert item["exoneracion_cargo"]["motivo"] == MOTIVO
    assert item["exoneracion_cargo"]["autorizado_por"] is not None


@pytest.mark.asyncio
async def test_usuario_sin_exoneracion_no_trae_el_bloque(
    client, superuser_token, db_session
):
    resp = await _seed_responsable(db_session)
    res = await client.get("/users/", params={"search": resp.email})
    assert res.status_code == 200, res.text
    assert res.json()["items"][0]["exoneracion_cargo"] is None


@pytest.mark.asyncio
async def test_exonerar_requiere_super_admin(client, db_session):
    resp = await _seed_responsable(db_session)
    patient = await _seed_patient(db_session)
    res = await client.post(
        f"/users/{resp.id}/exoneracion-cargo",
        json={"ci": patient.ci, "motivo": MOTIVO},
    )
    assert res.status_code == 401
