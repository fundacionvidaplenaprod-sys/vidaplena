from datetime import date
from typing import Any, List
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, desc, and_, or_
from sqlalchemy.orm import aliased

from app import models, schemas
from app.db import get_db
from app.api import deps
from app.core.config import settings
from app.core.contributions import periodo_anterior
from app.core.text_normalize import normalize_name
from app.core import distribution_service as dist
from app.core.donation_excel import DonationExcelError, parse_donation_excel
from app.core.insulin_catalog import normalize_insulin_name
from app.core.insulin_distribution import (
    DISTRIBUTION_DAYS,
    PRIORITY_MAX_COVERAGE,
    LotInput as InsulinLotInput,
    plan_distribution as plan_insulin_distribution,
)

router = APIRouter()

# --- MOROSOS ---
async def calcular_morosos(db: AsyncSession, periodo: str, depto: str | None = None) -> list[dict]:
    """
    Beneficiarios ACTIVOS que no tienen un aporte ACEPTADO en `periodo`.

    Es la definición única de "moroso": la usan tanto la tarjeta del resumen
    operativo como el listado, para que nunca discrepen. Los exonerados del
    aporte (por vulnerabilidad o por cargo, ver `esta_exonerado` en
    core/contributions.py) no deben el aporte y quedan fuera. Un aporte
    DECLARADO u OBSERVADO sigue contando como no pagado hasta que se acepte,
    pero se informa el motivo para distinguir "no pagó" de "pagó y falta
    revisarlo".

    Nadie debe un periodo anterior a su ingreso: quien es activado en octubre
    paga desde octubre y no es moroso de septiembre. El ingreso es el primer
    momento en que el beneficiario estuvo ACTIVO, que es cuando se aprueban sus
    documentos y se le concede el beneficio. Se toma de `patient_status_events`
    (el primer evento que muestra al beneficiario ya activo, sea porque pasó a
    ACTIVO o porque salió de ACTIVO); así, reabrirlo y volver a activarlo no
    reinicia lo que debe. Para quienes no tienen ese evento (antiguos) se usa,
    en orden, la creación de su usuario y la de su ficha. Ni `created_at` de la
    ficha ni el usuario sirven como regla principal: la ficha de un
    beneficiario precargado desde el padrón existe meses antes de registrarse,
    y el usuario se genera antes de que se aprueben los documentos.

    El mes se toma en hora de Bolivia, para que una activación el 30 a las
    22:00 no pase al mes siguiente por la zona horaria del servidor.
    """
    aporte = aliased(models.MonthlyContribution)
    evento = models.PatientStatusEvent
    primera_vez_activo = (
        select(func.min(evento.created_at))
        .where(
            evento.patient_id == models.Patient.id,
            or_(evento.new_state == "ACTIVO", evento.old_state == "ACTIVO"),
        )
        .correlate(models.Patient)
        .scalar_subquery()
    )
    fecha_ingreso = func.coalesce(
        primera_vez_activo, models.User.created_at, models.Patient.created_at
    )
    mes_ingreso = func.to_char(func.timezone("America/La_Paz", fecha_ingreso), "YYYY-MM")
    query = (
        select(models.Patient, aporte.estado)
        .outerjoin(models.User, models.User.id == models.Patient.user_id)
        .outerjoin(
            aporte,
            and_(aporte.patient_id == models.Patient.id, aporte.periodo == periodo),
        )
        .where(
            models.Patient.estado == "ACTIVO",
            mes_ingreso <= periodo,
            models.Patient.exonerado_aporte.is_(False),
            models.Patient.exonerado_por_cargo.is_(False),
            or_(aporte.estado.is_(None), aporte.estado != "ACEPTADO"),
        )
        .order_by(models.Patient.nombres, models.Patient.ap_paterno)
    )
    rows = (await db.execute(query)).all()

    motivos = {None: "SIN_APORTE", "DECLARADO": "DECLARADO", "OBSERVADO": "OBSERVADO"}
    items = []
    for patient, estado_aporte in rows:
        # `depto` es texto libre en Patient, por eso se compara normalizado.
        if depto and normalize_name(patient.depto) != normalize_name(depto):
            continue
        items.append({
            "patient_id": patient.id,
            "patient_nombre": f"{patient.nombres} {patient.ap_paterno or ''} {patient.ap_materno or ''}".strip(),
            "patient_ci": patient.ci,
            "depto": patient.depto,
            "tel_contacto": patient.tel_contacto,
            "motivo": motivos.get(estado_aporte, estado_aporte),
        })
    return items


# --- A. REPORTE DE POBLACIÓN (Beneficiarios) ---
@router.get("/population", summary="Estadísticas de Beneficiarios")
async def get_population_stats(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Cuántos beneficiarios hay por estado y cuántos son morosos del mes anterior.

    `morosos` NO sale de restar estados: cuenta a los activos sin aporte
    aceptado en `periodo_morosos` (el mes anterior, para no marcar como
    deudor a todo el mundo en los primeros días del mes). Es el mismo
    cálculo del listado `/reports/morosos`.
    """
    por_estado = dict(
        (await db.execute(select(models.Patient.estado, func.count(models.Patient.id)).group_by(models.Patient.estado))).all()
    )
    total = sum(por_estado.values())
    activos = por_estado.get("ACTIVO", 0)
    pendientes = por_estado.get("PENDIENTE_DOC", 0)
    inactivos = por_estado.get("INACTIVO", 0)

    periodo = periodo_anterior()
    morosos = await calcular_morosos(db, periodo)

    return {
        "total_beneficiarios": total,
        "activos": activos,
        "pendientes_validacion": pendientes,
        "inactivos": inactivos,
        # HABILITADO, PENDIENTE_APORTE y NO_REGISTRADO.
        "otros_estados": total - activos - pendientes - inactivos,
        "morosos": len(morosos),
        "periodo_morosos": periodo,
    }


@router.get("/morosos", summary="Beneficiarios activos sin aporte aceptado en un periodo")
async def get_morosos_report(
    periodo: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM; por defecto, el mes anterior"),
    depto: str | None = Query(None, description="Filtra por departamento"),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    periodo = periodo or periodo_anterior()
    items = await calcular_morosos(db, periodo, depto)
    return {
        "periodo": periodo,
        "total": len(items),
        "sin_aporte": sum(1 for i in items if i["motivo"] == "SIN_APORTE"),
        "declarados": sum(1 for i in items if i["motivo"] == "DECLARADO"),
        "observados": sum(1 for i in items if i["motivo"] == "OBSERVADO"),
        "items": items,
    }

# --- B. REPORTE DE INVENTARIO (Stock Crítico) ---
@router.get("/inventory", summary="Estado del Stock de Donaciones")
async def get_inventory_stats(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Responde: ¿Qué medicamentos se están acabando?
    """
    # Agrupamos por producto y sumamos el stock disponible de sus lotes
    # Nota: Esta es una query simplificada. En producción SQL puro es más rápido, 
    # pero aquí usamos ORM para mantener consistencia.
    
    products = await db.execute(select(models.Donation))
    products_list = products.scalars().all()
    
    report = []
    for prod in products_list:
        # Sumar lotes de este producto
        sum_query = select(func.sum(models.DonationLot.cantidad_disponible)).where(models.DonationLot.donation_id == prod.id)
        total_stock = (await db.execute(sum_query)).scalar() or 0
        
        # Alerta visual
        estado_stock = "OK"
        if total_stock == 0:
            estado_stock = "CRÍTICO (0)"
        elif total_stock < settings.INVENTORY_LOW_STOCK_THRESHOLD:
            estado_stock = "BAJO"

        report.append({
            "producto": prod.nombre_generico,
            "presentacion": prod.presentacion,
            "stock_total": total_stock,
            "estado": estado_stock
        })
    
    return report

# --- C. AUDITORÍA (El Ojo que todo lo ve) ---
@router.get("/audit-logs", summary="Bitácora de Movimientos")
async def get_audit_logs(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Muestra quién hizo qué y cuándo.
    Solo para Super Admins.
    """
    if current_user.role != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Acceso denegado")

    query = (
        select(models.AuditLog)
        .order_by(desc(models.AuditLog.created_at))
        .limit(limit)
    )
    result = await db.execute(query)
    logs = result.scalars().all()
    
    # Mapeo manual simple para devolver JSON
    return [
        {
            "fecha": log.created_at,
            "usuario_id": log.actor_id,
            "accion": log.accion, # Ej: "CREAR_PACIENTE", "VALIDAR_APORTE"
            "detalle": log.payload,
        }
        for log in logs
    ]

# --- D. HISTORIAL DE APORTES SOLIDARIOS POR PERIODO ---
@router.get("/contributions", summary="Historial de aportes solidarios de un periodo (mes) elegido")
async def get_contributions_report(
    periodo: str = Query(..., pattern=r"^\d{4}-\d{2}$", description="Periodo en formato YYYY-MM"),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    """
    Responde: ¿quién hizo su aporte solidario en tal mes, y cuántos van?
    `total_aceptados` es el número principal para control (aportes ya
    validados); `total_declarados`/`total_observados` dan contexto de lo
    que aún está pendiente de revisión o fue rechazado ese mismo periodo.
    """
    query = (
        select(models.MonthlyContribution, models.Patient)
        .join(models.Patient, models.Patient.id == models.MonthlyContribution.patient_id)
        .where(models.MonthlyContribution.periodo == periodo)
        .order_by(models.Patient.nombres, models.Patient.ap_paterno)
    )
    rows = (await db.execute(query)).all()

    items = []
    counts = {"ACEPTADO": 0, "DECLARADO": 0, "OBSERVADO": 0}
    for contrib, patient in rows:
        counts[contrib.estado] = counts.get(contrib.estado, 0) + 1
        items.append({
            "patient_id": patient.id,
            "patient_nombre": f"{patient.nombres} {patient.ap_paterno} {patient.ap_materno or ''}".strip(),
            "patient_ci": patient.ci,
            "depto": patient.depto,
            "monto": float(contrib.monto),
            "fecha_pago": contrib.fecha_pago,
            "metodo_pago": contrib.metodo_pago,
            "estado": contrib.estado,
        })

    return {
        "periodo": periodo,
        "total_aceptados": counts.get("ACEPTADO", 0),
        "total_declarados": counts.get("DECLARADO", 0),
        "total_observados": counts.get("OBSERVADO", 0),
        "items": items,
    }


# --- Distribución de insulina a partir del Excel de una donación ---------------
# Reporte de planificación: no toca lotes ni asignaciones de la base, no descuenta
# stock y no filtra por aporte al día (a diferencia del reparto guardado).
INSULIN_REPORT_ESTADOS = ("ACTIVO", "PENDIENTE_DOC", "HABILITADO")
INSULIN_REPORT_MAX_BYTES = 5 * 1024 * 1024


@router.post(
    "/insulin-distribution",
    response_model=schemas.DistributionReportResult,
    summary="Distribución de insulina calculada a partir del Excel de una donación",
)
async def insulin_distribution_report(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    """Recibe el Excel de la donación y calcula el reparto con las reglas definidas.

    Considera a los beneficiarios ACTIVO, PENDIENTE_DOC y HABILITADO con insulina
    cargada, sin exigir aporte. No guarda nada.
    """
    filename = (file.filename or "").strip()
    content = await file.read()
    if not filename.lower().endswith(".xlsx") or content[:2] != b"PK":
        raise HTTPException(status_code=400, detail="Sube el Excel de la donación en formato .xlsx.")
    if not content:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(content) > INSULIN_REPORT_MAX_BYTES:
        raise HTTPException(status_code=400, detail="El archivo excede el máximo de 5 MB.")

    try:
        parsed = await run_in_threadpool(parse_donation_excel, content, normalize_insulin_name)
    except DonationExcelError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not parsed.rows:
        detalle = "; ".join(f"fila {e.row_number}: {e.message}" for e in parsed.errors[:5])
        raise HTTPException(
            status_code=400,
            detail="El Excel no tiene ninguna fila válida." + (f" {detalle}" if detalle else ""),
        )

    today = date.today()
    lot_inputs: List[InsulinLotInput] = []
    lot_meta: dict = {}
    errors = [
        schemas.DonationExcelRowError(fila=e.row_number, producto=e.producto, mensaje=e.message)
        for e in parsed.errors
    ]
    vencidos = 0
    for row in parsed.rows:
        if row.fecha_venc and row.fecha_venc < today:
            vencidos += 1
            errors.append(
                schemas.DonationExcelRowError(
                    fila=row.row_number,
                    producto=row.producto,
                    mensaje=f"Vencido el {row.fecha_venc.isoformat()}: no se reparte",
                )
            )
            continue
        lot_inputs.append(
            InsulinLotInput(
                lot_id=row.row_number,
                ingredient=row.insulina,
                label=row.producto,
                ui_per_unit=row.ui_per_unit,
                units=row.cantidad,
                expiry=row.fecha_venc,
            )
        )
        lot_meta[row.row_number] = (row.producto, row.lote, row.fecha_venc)
    errors.sort(key=lambda e: e.fila)

    patient_inputs, info, excluded = await dist.load_distribution_patients(
        db, estados=INSULIN_REPORT_ESTADOS, require_current_contribution=False
    )
    plan = plan_insulin_distribution(lot_inputs, patient_inputs, days=DISTRIBUTION_DAYS)
    grouped = dist.group_assignments(plan)
    pacientes = dist.plan_patient_items(plan, patient_inputs, info, lot_meta)
    sobre_tope = sum(
        1
        for p in pacientes
        if p.es_menor or p.es_tipo1
        for i in p.insulinas
        if i.cobertura_pct > PRIORITY_MAX_COVERAGE * 100 + 0.05
    )

    return schemas.DistributionReportResult(
        guardado=False,
        dias=plan.days,
        reserva_pct=plan.reserve_pct,
        stock_total_ui=plan.total_stock_ui,
        reserva_objetivo_ui=plan.reserve_target_ui,
        reserva_ui=plan.reserve_ui,
        asignado_ui=plan.allocated_ui,
        lotes_considerados=len(lot_inputs),
        lotes_excluidos_consolidados=0,
        lotes_vencidos=vencidos,
        lotes_sin_catalogo=0,
        asignaciones_generadas=len(grouped),
        insulinas=dist.plan_ingredient_items(plan),
        reserva=dist.plan_reserve_items(plan, lot_meta),
        pacientes=pacientes,
        prioritarios_sobre_120=sobre_tope,
        excluded_patients=excluded,
        registros_por_corregir=dist.group_choice_issues(plan, info),
        archivo=filename,
        filas_leidas=parsed.total_rows,
        filas_con_error=errors,
        donacion=[
            schemas.DonationExcelLine(
                fila=r.row_number,
                producto=r.producto,
                insulina=r.insulina,
                cantidad=r.cantidad,
                presentacion_ml=r.presentacion_ml,
                concentracion_ui_ml=r.concentracion_ui_ml,
                ui_por_envase=r.ui_per_unit,
                ui_total=r.ui_per_unit * r.cantidad,
                lote=r.lote,
                fecha_venc=r.fecha_venc,
            )
            for r in parsed.rows
        ],
        estados_considerados=list(INSULIN_REPORT_ESTADOS),
    )
