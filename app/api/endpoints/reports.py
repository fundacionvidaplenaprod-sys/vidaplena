from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, desc

from app import models, schemas
from app.db import get_db
from app.api import deps
from app.core.config import settings

router = APIRouter()

# --- A. REPORTE DE POBLACIÓN (Beneficiarios) ---
@router.get("/population", summary="Estadísticas de Beneficiarios")
async def get_population_stats(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Responde: ¿Cuántos activos tenemos? ¿Cuántos inactivos/morosos?
    """
    # Contar total
    total_query = select(func.count(models.Patient.id))
    total = (await db.execute(total_query)).scalar()

    # Contar activos
    active_query = select(func.count(models.Patient.id)).where(models.Patient.estado == "ACTIVO")
    active = (await db.execute(active_query)).scalar()

    # Contar pendientes de documento
    pending_query = select(func.count(models.Patient.id)).where(models.Patient.estado == "PENDIENTE_DOC")
    pending = (await db.execute(pending_query)).scalar()

    return {
        "total_beneficiarios": total,
        "activos": active,
        "inactivos_morosos": total - active - pending,
        "pendientes_validacion": pending
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