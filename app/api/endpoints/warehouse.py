"""Almacén de insulina: ingreso por el Excel de la donación y reparto consolidado.

Flujo:
  1. Ingreso: el mismo Excel (packing list) que recibe el reporte de distribución, con el mismo lector. En el
     almacén el NRO LOTE y la FECHA VENCIMIENTO son obligatorios (trazabilidad, reglamento art. 17 c) y no entra
     nada vencido. Se revisa con una vista previa y se ingresa todo o nada.
  2. Calcular: el mismo motor y las mismas reglas del reporte (`distribution_service.run_equitable_plan`), sobre
     los mismos beneficiarios, con el stock disponible del almacén. Queda guardado en BORRADOR; un cálculo nuevo
     descarta el borrador anterior.
  3. Ajustar: solo intercambios equivalentes entre dos beneficiarios (`core/warehouse_distribution.py`).
  4. Consolidar: congela el reparto y descuenta del stock lo asignado (la reserva y el sobrante quedan en el
     almacén). Exige que el stock siga siendo el del cálculo.
  5. Historial: cada reparto se puede volver a ver tal como quedó, con los packing lists de los que salió, y se
     puede buscar a un beneficiario en todos los repartos guardados.
  6. Aviso: al consolidar, cada beneficiario con ficha ve en su portal cuánta insulina le corresponde para el
     periodo, con el número de lote y la ventana de entrega «del … al …» (el día y la hora los coordina con el(la)
     responsable de su departamento) (`/insulin-notices/me`); el personal ve quién lo vio. En el aviso, el
     beneficiario sube una foto de sus insulinas ya usadas y otra de su hemoglobina glucosilada, que el
     SUPER_ADMIN aprueba u observa (`/insulin-notices/{id}/fotos/{tipo}/revision`).
"""
from __future__ import annotations

import copy
import hashlib
import math
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Integer, column, func, or_, select, true, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app import models, schemas
from app.api import deps
from app.core import distribution_service as dist
from app.core import warehouse_distribution as wd
from app.core.donation_excel import DonationExcelError, parse_donation_excel
from app.core.equitable_distribution import OptimizerUnavailable
from app.core.firebase import delete_file_from_firebase_by_url, upload_file_to_firebase
from app.core.insulin_catalog import normalize_insulin_name
from app.core.insulin_distribution import PRIORITY_NAMES, LotInput
from app.core.text_normalize import fold_sql, normalize_name
from app.db import get_db

router = APIRouter()

# El reparto del almacén exige el reparto exacto (optimizador), igual que el reporte. Las pruebas lo apagan.
REQUIRE_OPTIMIZER = True
INTAKE_MAX_BYTES = 5 * 1024 * 1024

# Fotos del beneficiario en el aviso: tipo -> (nombre del archivo, formatos). La HbA1c admite el PDF del
# laboratorio. El portal achica las fotos antes de subirlas; el tope es para las que no pudo achicar.
NOTICE_PHOTO_MAX_BYTES = 5 * 1024 * 1024
_IMAGENES = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp"}
NOTICE_PHOTOS = {
    "envases": ("insulinas_usadas", _IMAGENES),
    "hba1c": ("hemoglobina_glucosilada", {**_IMAGENES, "application/pdf": "pdf"}),
}


def _audit(db: AsyncSession, actor_id: Optional[int], entidad: str, entidad_id: int, accion: str, payload: dict) -> None:
    db.add(models.AuditLog(actor_id=actor_id, entidad=entidad, entidad_id=entidad_id, accion=accion, payload=payload))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _producto(donation: models.Donation) -> str:
    """Nombre del producto tal como vino en el Excel (incluye la marca: el motor reconoce Lantus por el nombre)."""
    return (
        donation.nombre_comercial
        or " ".join(p for p in (donation.marca, donation.presentacion) if p)
        or donation.nombre_generico
        or f"Producto {donation.id}"
    )


# =============================================================================================== ingreso
async def _read_excel(file: UploadFile) -> Tuple[str, bytes]:
    filename = (file.filename or "").strip()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if not filename.lower().endswith(".xlsx") or content[:2] != b"PK":
        raise HTTPException(status_code=400, detail="Sube el Excel de la donación en formato .xlsx.")
    if len(content) > INTAKE_MAX_BYTES:
        raise HTTPException(status_code=400, detail="El archivo excede el máximo de 5 MB.")
    return filename[:255], content


async def _intake_preview(db: AsyncSession, filename: str, content: bytes) -> Tuple[schemas.WarehouseIntakePreview, list, str]:
    try:
        parsed = await run_in_threadpool(parse_donation_excel, content, normalize_insulin_name)
    except DonationExcelError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    today = date.today()
    errores = [
        schemas.DonationExcelRowError(fila=e.row_number, producto=e.producto, mensaje=e.message) for e in parsed.errors
    ]
    filas: List[schemas.DonationExcelLine] = []
    for row in parsed.rows:
        problemas = []
        if not row.lote:
            problemas.append("NRO LOTE es obligatorio en el almacén")
        elif len(row.lote) > 80:
            problemas.append("NRO LOTE supera los 80 caracteres")
        if not row.fecha_venc:
            problemas.append("FECHA VENCIMIENTO es obligatoria en el almacén")
        elif row.fecha_venc < today:
            problemas.append(f"vencido el {row.fecha_venc.isoformat()}: no se ingresa")
        if len(row.producto) > 160:
            problemas.append("PRODUCTO supera los 160 caracteres")
        if problemas:
            errores.append(schemas.DonationExcelRowError(fila=row.row_number, producto=row.producto, mensaje="; ".join(problemas)))
        filas.append(
            schemas.DonationExcelLine(
                fila=row.row_number,
                producto=row.producto,
                insulina=row.insulina,
                cantidad=row.cantidad,
                presentacion_ml=row.presentacion_ml,
                concentracion_ui_ml=row.concentracion_ui_ml,
                ui_por_envase=row.ui_per_unit,
                ui_total=row.ui_per_unit * row.cantidad,
                lote=row.lote,
                fecha_venc=row.fecha_venc,
            )
        )
    errores.sort(key=lambda e: e.fila)

    sha = hashlib.sha256(content).hexdigest()
    previo = (
        await db.execute(
            select(models.DonationIntake).options(selectinload(models.DonationIntake.created_by)).where(
                models.DonationIntake.sha256 == sha
            )
        )
    ).scalars().first()
    preview = schemas.WarehouseIntakePreview(
        archivo=filename,
        filas_leidas=parsed.total_rows,
        filas=filas,
        errores=errores,
        envases=sum(f.cantidad for f in filas),
        ui_total=sum(f.ui_total for f in filas),
        puede_ingresar=bool(filas) and not errores and previo is None,
        ingreso_previo=_intake_summary(previo) if previo else None,
    )
    return preview, parsed.rows, sha


def _intake_summary(intake: models.DonationIntake) -> schemas.WarehouseIntakeSummary:
    return schemas.WarehouseIntakeSummary(
        id=intake.id,
        archivo=intake.archivo,
        filas=intake.filas,
        envases=intake.envases,
        ui_total=intake.ui_total,
        created_at=intake.created_at,
        autor=intake.created_by.email if intake.created_by else None,
    )


@router.post("/intake/preview", response_model=schemas.WarehouseIntakePreview, summary="Vista previa del ingreso de un Excel")
async def preview_intake(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    """Lee el Excel de la donación y muestra lo que se ingresaría, con los errores por fila. No guarda nada."""
    filename, content = await _read_excel(file)
    preview, _, _ = await _intake_preview(db, filename, content)
    return preview


@router.post("/intake", response_model=schemas.WarehouseIntakeResult, summary="Ingresa al almacén el Excel de una donación")
async def create_intake(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    """Ingresa todas las filas del Excel como lotes (con su entrada de stock) o ninguna si alguna tiene un error."""
    filename, content = await _read_excel(file)
    preview, rows, sha = await _intake_preview(db, filename, content)
    if preview.ingreso_previo:
        fecha = preview.ingreso_previo.created_at.strftime("%d/%m/%Y")
        raise HTTPException(status_code=409, detail=f"Este archivo ya se ingresó el {fecha} (ingreso #{preview.ingreso_previo.id}).")
    if not rows:
        raise HTTPException(status_code=400, detail="El Excel no tiene ninguna fila válida.")
    if preview.errores:
        detalle = "; ".join(f"fila {e.fila}: {e.mensaje}" for e in preview.errores[:5])
        raise HTTPException(
            status_code=400,
            detail=f"No se ingresó nada: {len(preview.errores)} fila(s) con error. Corrija el Excel y vuelva a subirlo. {detalle}",
        )

    intake = models.DonationIntake(
        archivo=filename, sha256=sha, filas=len(rows), envases=preview.envases, ui_total=preview.ui_total,
        created_by_id=current_user.id,
    )
    db.add(intake)
    await db.flush()

    productos: Dict[tuple, models.Donation] = {}
    nuevos = 0
    for row in rows:
        key = (row.insulina, row.producto, float(row.presentacion_ml), int(row.concentracion_ui_ml))
        donation = productos.get(key)
        if donation is None:
            donation = (
                await db.execute(
                    select(models.Donation).where(
                        models.Donation.tipo == "INSULINA",
                        models.Donation.nombre_generico == row.insulina,
                        models.Donation.nombre_comercial == row.producto,
                        models.Donation.presentacion_ml == float(row.presentacion_ml),
                        models.Donation.concentracion_ui_ml == int(row.concentracion_ui_ml),
                    ).order_by(models.Donation.id)
                )
            ).scalars().first()
            if donation is None:
                donation = models.Donation(
                    tipo="INSULINA",
                    nombre_generico=row.insulina,
                    nombre_comercial=row.producto,
                    presentacion=f"{row.presentacion_ml:g} ml U{row.concentracion_ui_ml}",
                    factor_conversion=row.ui_per_unit,
                    presentacion_ml=float(row.presentacion_ml),
                    concentracion_ui_ml=int(row.concentracion_ui_ml),
                )
                db.add(donation)
                await db.flush()
                nuevos += 1
            productos[key] = donation
        lot = models.DonationLot(
            donation_id=donation.id,
            intake_id=intake.id,
            lote=row.lote,
            fecha_venc=row.fecha_venc,
            cantidad_total=row.cantidad,
            cantidad_disponible=row.cantidad,
        )
        db.add(lot)
        await db.flush()
        db.add(models.StockMovement(lot_id=lot.id, tipo="ENTRADA", cantidad=row.cantidad, referencia=f"INGRESO:{intake.id}"))

    _audit(
        db, current_user.id, "donation_intake", intake.id, "CREATE_DONATION_INTAKE",
        {"archivo": filename, "filas": len(rows), "envases": preview.envases, "ui_total": preview.ui_total},
    )
    await db.commit()
    await db.refresh(intake)
    return schemas.WarehouseIntakeResult(
        id=intake.id, archivo=intake.archivo, filas=intake.filas, envases=intake.envases, ui_total=intake.ui_total,
        created_at=intake.created_at, autor=current_user.email, lotes_creados=len(rows), productos_nuevos=nuevos,
    )


@router.get("/intakes", response_model=List[schemas.WarehouseIntakeSummary], summary="Ingresos al almacén")
async def list_intakes(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    result = await db.execute(
        select(models.DonationIntake)
        .options(selectinload(models.DonationIntake.created_by))
        .order_by(models.DonationIntake.created_at.desc(), models.DonationIntake.id.desc())
    )
    return [_intake_summary(i) for i in result.scalars().all()]


# =============================================================================================== stock
async def _insulin_lots(db: AsyncSession, *, only_available: bool) -> List[models.DonationLot]:
    query = (
        select(models.DonationLot)
        .join(models.Donation, models.Donation.id == models.DonationLot.donation_id)
        .options(selectinload(models.DonationLot.donation), selectinload(models.DonationLot.intake))
        .where(models.Donation.tipo == "INSULINA")
        .order_by(models.Donation.nombre_generico, models.Donation.nombre_comercial, models.DonationLot.fecha_venc, models.DonationLot.id)
    )
    if only_available:
        query = query.where(models.DonationLot.cantidad_disponible > 0)
    return list((await db.execute(query)).scalars().all())


@router.get("/stock", response_model=List[schemas.WarehouseStockLot], summary="Stock de insulina del almacén por lote")
async def list_stock(
    solo_disponibles: bool = Query(False, description="Solo los lotes con envases disponibles"),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    today = date.today()
    out = []
    for lot in await _insulin_lots(db, only_available=solo_disponibles):
        d = lot.donation
        out.append(
            schemas.WarehouseStockLot(
                lot_id=lot.id,
                donation_id=d.id,
                producto=_producto(d),
                insulina=normalize_insulin_name(d.nombre_generico),
                presentacion_ml=d.presentacion_ml,
                concentracion_ui_ml=d.concentracion_ui_ml,
                ui_por_envase=float(d.factor_conversion or 0),
                lote=lot.lote,
                fecha_venc=lot.fecha_venc,
                cantidad_total=lot.cantidad_total,
                disponibles=lot.cantidad_disponible,
                vencido=bool(lot.fecha_venc and lot.fecha_venc < today),
                ingreso_id=lot.intake_id,
                ingreso_archivo=lot.intake.archivo if lot.intake else None,
            )
        )
    return out


@router.get("/lots/{lot_id}/movements", response_model=List[schemas.StockMovementResponse], summary="Movimientos de un lote")
async def list_lot_movements(
    lot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    """Entradas (`INGRESO:{id}`) y salidas (`REPARTO:{id}`) del lote, de la más antigua a la más reciente."""
    if not (await db.execute(select(models.DonationLot.id).where(models.DonationLot.id == lot_id))).scalar():
        raise HTTPException(status_code=404, detail="Lote no encontrado")
    result = await db.execute(
        select(models.StockMovement)
        .where(models.StockMovement.lot_id == lot_id)
        .order_by(models.StockMovement.created_at.asc(), models.StockMovement.id.asc())
    )
    return result.scalars().all()


def _eligible(lots: List[models.DonationLot], today: date) -> Tuple[List[models.DonationLot], int, int]:
    """Lotes que entran en el reparto: con envases, sin vencer, con insulina del catálogo y UI por envase."""
    ok, vencidos, sin_catalogo = [], 0, 0
    for lot in lots:
        if lot.cantidad_disponible <= 0:
            continue
        if lot.fecha_venc and lot.fecha_venc < today:
            vencidos += 1
            continue
        if not normalize_insulin_name(lot.donation.nombre_generico) or float(lot.donation.factor_conversion or 0) <= 0:
            sin_catalogo += 1
            continue
        ok.append(lot)
    return ok, vencidos, sin_catalogo


# =============================================================================================== reparto
def _lots_info(resultado: dict) -> Dict[int, wd.LotInfo]:
    return {
        int(s["lot_id"]): wd.LotInfo(
            lot_id=int(s["lot_id"]),
            donation_id=int(s["donation_id"]),
            insulina=s["insulina"],
            producto=s["producto"],
            ui_por_envase=float(s["ui_por_envase"]),
            lote=s.get("lote"),
            fecha_venc=date.fromisoformat(s["fecha_venc"]) if s.get("fecha_venc") else None,
        )
        for s in resultado.get("stock", [])
    }


def _holders(resultado: dict) -> Tuple[Dict[Tuple[int, str], wd.Holder], Dict[int, dict]]:
    holders, people = {}, {}
    for p in resultado.get("pacientes", []):
        people[p["patient_id"]] = p
        for i in p["insulinas"]:
            holders[(p["patient_id"], i["insulina"])] = wd.Holder(p["patient_id"], i["insulina"], p["grupo_prioridad"])
    return holders, people


def _summary(d: models.InsulinDistribution, *, envases: int, intercambios: int, ingresos: list) -> dict:
    return dict(
        id=d.id,
        estado=d.estado,
        dias=d.dias,
        created_at=d.created_at,
        autor=d.created_by.email if d.created_by else None,
        consolidated_at=d.consolidated_at,
        consolidado_por=d.consolidated_by.email if d.consolidated_by else None,
        discarded_at=d.discarded_at,
        beneficiarios=len(d.resultado.get("pacientes", [])),
        envases=envases,
        asignado_ui=float(d.resultado.get("asignado_ui") or 0),
        intercambios=intercambios,
        ingresos=ingresos,
    )


async def _origins(
    db: AsyncSession, distribution_ids: Optional[List[int]] = None
) -> Dict[int, List[schemas.WarehouseDistributionOrigin]]:
    """Por reparto, de qué packing lists salen los envases asignados (los intercambios no cambian lo que sale de
    cada lote, así que tampoco de cada packing list)."""
    I, L, K = models.InsulinDistributionItem, models.DonationLot, models.DonationIntake
    query = (
        select(
            I.distribution_id, L.intake_id, K.archivo, K.created_at,
            func.count(func.distinct(L.id)), func.sum(I.envases), func.sum(I.ui),
        )
        .join(L, L.id == I.lot_id)
        .outerjoin(K, K.id == L.intake_id)
        .group_by(I.distribution_id, L.intake_id, K.archivo, K.created_at)
    )
    if distribution_ids is not None:
        query = query.where(I.distribution_id.in_(distribution_ids))
    out: Dict[int, List[schemas.WarehouseDistributionOrigin]] = defaultdict(list)
    for dist_id, intake_id, archivo, ingresado_at, lotes, envases, ui in (await db.execute(query)).all():
        out[dist_id].append(
            schemas.WarehouseDistributionOrigin(
                ingreso_id=intake_id, archivo=archivo, ingresado_at=ingresado_at,
                lotes=int(lotes), envases=int(envases or 0), ui=float(ui or 0),
            )
        )
    for origins in out.values():
        # Primero los packing lists, del más antiguo al más reciente; al final los lotes sin packing list.
        origins.sort(key=lambda o: (o.ingreso_id is None, o.ingreso_id or 0))
    return out


async def _stock_changes(db: AsyncSession, d: models.InsulinDistribution, *, lock: bool = False) -> List[str]:
    """Diferencias entre el stock con que se calculó el reparto y el stock que entra hoy en un reparto."""
    query = (
        select(models.DonationLot)
        .join(models.Donation, models.Donation.id == models.DonationLot.donation_id)
        .options(selectinload(models.DonationLot.donation))
        .where(models.Donation.tipo == "INSULINA")
    )
    if lock:
        query = query.with_for_update(of=models.DonationLot)
    lots = list((await db.execute(query)).scalars().all())
    current = {lot.id: lot for lot in _eligible(lots, date.today())[0]}
    before = {int(k): int(v) for k, v in d.stock_calculado.items()}
    names = {int(s["lot_id"]): f"{s['producto']} (lote {s.get('lote') or '-'})" for s in d.resultado.get("stock", [])}
    cambios = []
    for lot_id, units in sorted(before.items()):
        now = current.get(lot_id)
        name = names.get(lot_id, f"lote {lot_id}")
        if now is None:
            cambios.append(f"{name}: ya no está disponible (sin envases o vencido)")
        elif now.cantidad_disponible != units:
            cambios.append(f"{name}: tenía {units} envases y ahora tiene {now.cantidad_disponible}")
    for lot_id, lot in sorted(current.items()):
        if lot_id not in before:
            cambios.append(f"{_producto(lot.donation)} (lote {lot.lote or '-'}): ingresó después del cálculo ({lot.cantidad_disponible} envases)")
    return cambios


async def _load(db: AsyncSession, distribution_id: int, *, lock: bool = False) -> models.InsulinDistribution:
    # populate_existing: relee el reparto y sus líneas aunque ya estén en la sesión (tras un intercambio o un reset).
    query = (
        select(models.InsulinDistribution)
        .execution_options(populate_existing=True)
        .options(
            selectinload(models.InsulinDistribution.items),
            selectinload(models.InsulinDistribution.swaps).selectinload(models.InsulinDistributionSwap.created_by),
            selectinload(models.InsulinDistribution.created_by),
            selectinload(models.InsulinDistribution.consolidated_by),
        )
        .where(models.InsulinDistribution.id == distribution_id)
    )
    if lock:
        query = query.with_for_update(of=models.InsulinDistribution)
    d = (await db.execute(query)).scalars().first()
    if d is None:
        raise HTTPException(status_code=404, detail="Reparto no encontrado")
    return d


async def _detail(db: AsyncSession, distribution_id: int) -> schemas.WarehouseDistributionDetail:
    d = await _load(db, distribution_id)
    lots = _lots_info(d.resultado)
    _, people = _holders(d.resultado)

    def nombre(bid: int) -> str:
        return people.get(bid, {}).get("nombre_completo") or f"Beneficiario {bid}"

    def producto(lot_id: int) -> str:
        return lots[lot_id].producto if lot_id in lots else f"Lote {lot_id}"

    swaps = [
        schemas.WarehouseSwapResponse(
            id=s.id, created_at=s.created_at, autor=s.created_by.email if s.created_by else None,
            beneficiario_a=s.beneficiario_a, nombre_a=nombre(s.beneficiario_a), insulina_a=s.insulina_a,
            lot_a_id=s.lot_a_id, producto_a=producto(s.lot_a_id), envases_a=s.envases_a,
            beneficiario_b=s.beneficiario_b, nombre_b=nombre(s.beneficiario_b), insulina_b=s.insulina_b,
            lot_b_id=s.lot_b_id, producto_b=producto(s.lot_b_id), envases_b=s.envases_b, ui=s.ui,
        )
        for s in d.swaps
    ]
    cambios = await _stock_changes(db, d) if d.estado == "BORRADOR" else []
    ingresos = (await _origins(db, [d.id])).get(d.id, [])
    return schemas.WarehouseDistributionDetail(
        **_summary(d, envases=sum(i.envases for i in d.items), intercambios=len(d.swaps), ingresos=ingresos),
        resultado=d.resultado,
        propuesta=d.propuesta,
        intercambios_detalle=swaps,
        stock_vigente=not cambios,
        stock_cambios=cambios,
        entrega_desde=d.entrega_desde,
        entrega_hasta=d.entrega_hasta,
        aviso_mensaje=d.aviso_mensaje,
        avisos=await _notice_statuses(db, d) if d.estado == "CONSOLIDADO" else [],
    )


def _foto_out(foto: models.InsulinNoticePhoto, *, personal: bool) -> schemas.InsulinNoticePhoto:
    """Quién la revisó solo lo ve el personal."""
    return schemas.InsulinNoticePhoto(
        tipo=foto.tipo, url=foto.url, subida_at=foto.subida_at, estado=foto.estado, observacion=foto.observacion,
        revisada_at=foto.revisada_at,
        revisada_por=foto.revisada_por.email if personal and foto.revisada_por else None,
    )


def _fotos(notice: Optional[models.InsulinDistributionNotice], *, personal: bool) -> dict:
    """Las fotos que subió el beneficiario para el reparto (vacío si no tiene aviso)."""
    if notice is None:
        return {}
    return {f"foto_{f.tipo}": _foto_out(f, personal=personal) for f in notice.fotos}


async def _notice_statuses(db: AsyncSession, d: models.InsulinDistribution) -> List[schemas.WarehouseNoticeStatus]:
    """Por beneficiario del reparto (en el orden del reparto): si vio el aviso en su portal y qué fotos subió."""
    N = models.InsulinDistributionNotice
    rows = (
        await db.execute(
            select(N, models.Patient.user_id)
            .join(models.Patient, models.Patient.id == N.patient_id)
            .where(N.distribution_id == d.id)
        )
    ).all()
    avisos = {notice.patient_id: (notice, user_id) for notice, user_id in rows}
    out = []
    for p in d.resultado.get("pacientes", []):
        bid = p["patient_id"]
        notice, user_id = avisos.get(bid, (None, None))
        visto_at = notice.visto_at if notice else None
        if bid < 0:
            estado = "SIN_PORTAL"
        elif visto_at:
            estado = "VISTO"
        else:
            estado = "PENDIENTE" if user_id else "SIN_CUENTA"
        out.append(
            schemas.WarehouseNoticeStatus(
                notice_id=notice.id if notice else None, beneficiario_id=bid, nombre_completo=p["nombre_completo"],
                ci=p.get("ci"), estado=estado, visto_at=visto_at, **_fotos(notice, personal=True),
            )
        )
    return out


def _distribution_lot(lot: models.DonationLot, *, asignados: int, reserva: int) -> dict:
    d = lot.donation
    return schemas.WarehouseDistributionLot(
        lot_id=lot.id,
        donation_id=d.id,
        producto=_producto(d),
        insulina=normalize_insulin_name(d.nombre_generico),
        presentacion_ml=d.presentacion_ml,
        concentracion_ui_ml=d.concentracion_ui_ml,
        ui_por_envase=float(d.factor_conversion),
        lote=lot.lote,
        fecha_venc=lot.fecha_venc,
        disponibles=lot.cantidad_disponible,
        asignados=asignados,
        reserva=reserva,
        sobrante=lot.cantidad_disponible - asignados - reserva,
    ).model_dump(mode="json")


@router.post("/distributions", response_model=schemas.WarehouseDistributionDetail, summary="Calcula el reparto con el stock del almacén")
async def calculate_distribution(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    """Calcula el reparto con el motor y las reglas del reporte de distribución sobre el stock disponible del
    almacén y lo guarda en BORRADOR. Si ya había un borrador, queda DESCARTADO."""
    today = date.today()
    lots, vencidos, sin_catalogo = _eligible(await _insulin_lots(db, only_available=True), today)
    if not lots:
        raise HTTPException(status_code=400, detail="No hay stock de insulina disponible para repartir.")

    lot_inputs, lot_meta = [], {}
    for lot in lots:
        producto = _producto(lot.donation)
        lot_inputs.append(
            LotInput(
                lot_id=lot.id,
                ingredient=normalize_insulin_name(lot.donation.nombre_generico),
                label=producto,
                ui_per_unit=float(lot.donation.factor_conversion),
                units=int(lot.cantidad_disponible),
                expiry=lot.fecha_venc,
            )
        )
        lot_meta[lot.id] = (producto, lot.lote, lot.fecha_venc)

    patient_inputs, info, excluded = await dist.load_distribution_patients(
        db, estados=dist.DISTRIBUTION_ESTADOS, require_current_contribution=False, include_assisted=True
    )
    try:
        plan = await run_in_threadpool(
            dist.run_equitable_plan, lot_inputs, patient_inputs, require_optimizer=REQUIRE_OPTIMIZER
        )
    except OptimizerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"{exc} {dist.OPTIMIZER_UNAVAILABLE_HINT}")

    lines: Dict[Tuple[int, str, int], int] = defaultdict(int)
    for a in plan.assignments:
        lines[(a.patient_id, a.for_ingredient, a.lot_id)] += a.units
    assigned_by_lot: Dict[int, int] = defaultdict(int)
    for (_, _, lot_id), n in lines.items():
        assigned_by_lot[lot_id] += n
    reserve_by_lot = {r.lot_id: r.units for r in plan.reserve_lots}

    resultado = schemas.WarehouseDistributionResult(
        guardado=True,
        lotes_considerados=len(lot_inputs),
        lotes_excluidos_consolidados=0,
        lotes_vencidos=vencidos,
        lotes_sin_catalogo=sin_catalogo,
        **dist.plan_report_fields(plan, patient_inputs, info, excluded, lot_meta),
        stock=[
            _distribution_lot(lot, asignados=assigned_by_lot.get(lot.id, 0), reserva=reserve_by_lot.get(lot.id, 0))
            for lot in lots
        ],
    ).model_dump(mode="json")

    # Un solo borrador a la vez: el anterior queda descartado (se conserva en el historial).
    drafts = (
        await db.execute(
            select(models.InsulinDistribution)
            .where(models.InsulinDistribution.estado == "BORRADOR")
            .with_for_update()
        )
    ).scalars().all()
    for old in drafts:
        old.estado = "DESCARTADO"
        old.discarded_at = _now()

    propuesta = [
        {"beneficiario_id": bid, "insulina": ing, "lot_id": lot_id, "envases": n}
        for (bid, ing, lot_id), n in sorted(lines.items())
        if n > 0
    ]
    distribution = models.InsulinDistribution(
        estado="BORRADOR",
        dias=plan.days,
        resultado=resultado,
        propuesta=propuesta,
        stock_calculado={str(lot.id): int(lot.cantidad_disponible) for lot in lots},
        created_by_id=current_user.id,
    )
    db.add(distribution)
    await db.flush()
    ui_by_lot = {lot.id: float(lot.donation.factor_conversion) for lot in lots}
    for line in propuesta:
        db.add(_item(distribution.id, line["beneficiario_id"], line["insulina"], line["lot_id"], line["envases"], ui_by_lot))
    _audit(
        db, current_user.id, "insulin_distribution", distribution.id, "CALCULATE_INSULIN_DISTRIBUTION",
        {
            "lotes": len(lot_inputs),
            "beneficiarios": len(resultado["pacientes"]),
            "asignado_ui": plan.allocated_ui,
            "reserva_ui": plan.reserve_ui,
            "descartados": [old.id for old in drafts],
            "optimizador_usado": plan.optimizer_used,
        },
    )
    await db.commit()
    return await _detail(db, distribution.id)


def _item(distribution_id: int, bid: int, insulina: str, lot_id: int, envases: int, ui_by_lot: Dict[int, float]):
    return models.InsulinDistributionItem(
        distribution_id=distribution_id,
        beneficiario_id=bid,
        patient_id=bid if bid > 0 else None,
        assisted_registration_id=-bid if bid < 0 else None,
        insulina=insulina,
        lot_id=lot_id,
        envases=envases,
        ui=envases * ui_by_lot[lot_id],
    )


@router.get("/distributions", response_model=List[schemas.WarehouseDistributionSummary], summary="Historial de repartos")
async def list_distributions(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    D = models.InsulinDistribution
    envases = (
        select(func.coalesce(func.sum(models.InsulinDistributionItem.envases), 0))
        .where(models.InsulinDistributionItem.distribution_id == D.id)
        .correlate(D)
        .scalar_subquery()
    )
    swaps = (
        select(func.count(models.InsulinDistributionSwap.id))
        .where(models.InsulinDistributionSwap.distribution_id == D.id)
        .correlate(D)
        .scalar_subquery()
    )
    pacientes = func.jsonb_array_length(D.resultado["pacientes"])
    asignado = D.resultado["asignado_ui"].as_float()
    result = await db.execute(
        select(D.id, D.estado, D.dias, D.created_at, D.consolidated_at, D.discarded_at, pacientes, asignado, envases, swaps, D.created_by_id, D.consolidated_by_id)
        .order_by(D.created_at.desc(), D.id.desc())
    )
    rows = result.all()
    user_ids = {r.created_by_id for r in rows} | {r.consolidated_by_id for r in rows}
    users = {}
    if user_ids - {None}:
        users = dict((await db.execute(select(models.User.id, models.User.email).where(models.User.id.in_(user_ids - {None})))).all())
    origins = await _origins(db)
    return [
        schemas.WarehouseDistributionSummary(
            id=r.id, estado=r.estado, dias=r.dias, created_at=r.created_at, autor=users.get(r.created_by_id),
            consolidated_at=r.consolidated_at, consolidado_por=users.get(r.consolidated_by_id), discarded_at=r.discarded_at,
            beneficiarios=r[6] or 0, asignado_ui=float(r[7] or 0), envases=int(r[8] or 0), intercambios=int(r[9] or 0),
            ingresos=origins.get(r.id, []),
        )
        for r in rows
    ]


# ----------------------------------------------------------------------------------- beneficiario en el historial
def _snapshot_patients():
    """Cada beneficiario guardado en `resultado.pacientes` de cada reparto, como una fila (JOIN LATERAL)."""
    D = models.InsulinDistribution
    p = func.jsonb_array_elements(D.resultado["pacientes"]).table_valued(column("value", JSONB)).lateral("p")
    return D, p, p.c.value


@router.get(
    "/distributions/beneficiarios",
    response_model=List[schemas.WarehouseBeneficiaryMatch],
    summary="Busca un beneficiario en todos los repartos guardados",
)
async def search_distribution_beneficiaries(
    q: str = Query(..., min_length=2, max_length=80, description="Nombre o C.I."),
    incluir_descartados: bool = Query(False, description="También los borradores descartados"),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    """Busca por nombre o C.I. en lo guardado en cada reparto (el nombre de entonces, aunque después se corrija la ficha)."""
    tokens = normalize_name(q).split()
    if not tokens:
        return []
    D, p, val = _snapshot_patients()
    nombre, ci = val["nombre_completo"].astext, val["ci"].astext
    query = select(
        val["patient_id"].astext.cast(Integer), nombre, ci, val["registro_asistido"].astext,
        D.id, func.coalesce(D.consolidated_at, D.created_at),
    ).select_from(D).join(p, true())
    for token in tokens:
        query = query.where(fold_sql(nombre).contains(token, autoescape=True) | func.coalesce(ci, "").icontains(token, autoescape=True))
    if not incluir_descartados:
        query = query.where(D.estado != "DESCARTADO")

    people: Dict[int, dict] = {}
    # Los repartos se calculan uno tras otro (un solo borrador a la vez): el id más alto es el más reciente.
    for bid, name, ci_value, asistido, dist_id, fecha in (await db.execute(query)).all():
        person = people.setdefault(bid, {"repartos": set(), "ultimo": 0})
        person["repartos"].add(dist_id)
        if dist_id > person["ultimo"]:  # nombre y CI del reparto más reciente
            person.update(ultimo=dist_id, fecha=fecha, nombre=name, ci=ci_value, asistido=asistido)
    matches = [
        schemas.WarehouseBeneficiaryMatch(
            beneficiario_id=bid, nombre_completo=x["nombre"], ci=x["ci"], registro_asistido=x["asistido"] == "true",
            repartos=len(x["repartos"]), ultimo_reparto=x["fecha"],
        )
        for bid, x in people.items()
    ]
    matches.sort(key=lambda m: (normalize_name(m.nombre_completo), m.beneficiario_id))
    return matches[:30]


@router.get(
    "/distributions/beneficiarios/{beneficiario_id}",
    response_model=schemas.WarehouseBeneficiaryHistory,
    summary="Lo que recibió un beneficiario en cada reparto guardado",
)
async def beneficiary_distributions(
    beneficiario_id: int,
    incluir_descartados: bool = Query(False, description="También los borradores descartados"),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    """Cada reparto en que aparece el beneficiario, del más reciente al más antiguo, con lo que recibió tal como quedó
    guardado (lotes, vencimientos, cobertura y sustitutos, ya con los intercambios)."""
    D, p, val = _snapshot_patients()
    query = (
        select(D.id, D.estado, D.dias, D.created_at, D.consolidated_at, val)
        .select_from(D)
        .join(p, true())
        .where(val["patient_id"].astext.cast(Integer) == beneficiario_id)
        .order_by(D.id.desc())  # uno tras otro: el id más alto es el más reciente
    )
    if not incluir_descartados:
        query = query.where(D.estado != "DESCARTADO")
    rows = (await db.execute(query)).all()
    if not rows:
        raise HTTPException(status_code=404, detail="Ese beneficiario no aparece en ningún reparto guardado.")

    ids = [r[0] for r in rows]
    I, S = models.InsulinDistributionItem, models.InsulinDistributionSwap
    items = {
        dist_id: (int(envases or 0), float(ui or 0))
        for dist_id, envases, ui in (
            await db.execute(
                select(I.distribution_id, func.sum(I.envases), func.sum(I.ui))
                .where(I.beneficiario_id == beneficiario_id, I.distribution_id.in_(ids))
                .group_by(I.distribution_id)
            )
        ).all()
    }
    swaps = dict(
        (
            await db.execute(
                select(S.distribution_id, func.count(S.id))
                .where(S.distribution_id.in_(ids), or_(S.beneficiario_a == beneficiario_id, S.beneficiario_b == beneficiario_id))
                .group_by(S.distribution_id)
            )
        ).all()
    )
    entregas = [
        schemas.WarehouseBeneficiaryDelivery(
            distribution_id=dist_id, estado=estado, dias=dias, created_at=created_at, consolidated_at=consolidated_at,
            envases=items.get(dist_id, (0, 0.0))[0], ui=items.get(dist_id, (0, 0.0))[1],
            intercambios=int(swaps.get(dist_id, 0)), paciente=paciente,
        )
        for dist_id, estado, dias, created_at, consolidated_at, paciente in rows
    ]
    ultimo = entregas[0].paciente
    return schemas.WarehouseBeneficiaryHistory(
        beneficiario_id=beneficiario_id, nombre_completo=ultimo.nombre_completo, ci=ultimo.ci,
        registro_asistido=ultimo.registro_asistido, repartos=entregas,
    )


@router.get("/distributions/{distribution_id}", response_model=schemas.WarehouseDistributionDetail, summary="Un reparto tal como quedó")
async def get_distribution(
    distribution_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    return await _detail(db, distribution_id)


def _require_draft(d: models.InsulinDistribution) -> None:
    if d.estado != "BORRADOR":
        estado = "consolidado" if d.estado == "CONSOLIDADO" else "descartado"
        raise HTTPException(status_code=409, detail=f"El reparto #{d.id} está {estado}: ya no se puede modificar.")


@router.get(
    "/distributions/{distribution_id}/swap-options",
    response_model=schemas.WarehouseSwapOptions,
    summary="Con quién se pueden intercambiar unos envases sin cambiar el reparto",
)
async def get_swap_options(
    distribution_id: int,
    beneficiario_id: int = Query(...),
    insulina: str = Query(..., max_length=40),
    lot_id: int = Query(...),
    envases: int = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    d = await _load(db, distribution_id)
    _require_draft(d)
    lots = _lots_info(d.resultado)
    holders, people = _holders(d.resultado)
    a = holders.get((beneficiario_id, insulina))
    if a is None or lot_id not in lots:
        raise HTTPException(status_code=404, detail="Ese tratamiento o lote no está en el reparto.")
    lines = wd.lines_from_rows(d.items)
    if lines.get((beneficiario_id, insulina, lot_id), 0) < envases:
        raise HTTPException(status_code=400, detail="El beneficiario no tiene esa cantidad de envases de ese lote.")
    opciones = []
    for o in wd.swap_options(lines, lots, holders, a, lot_id, envases):
        p, lot = people[o["beneficiario_id"]], lots[o["lot_id"]]
        opciones.append(
            schemas.WarehouseSwapOption(
                beneficiario_id=o["beneficiario_id"], nombre_completo=p["nombre_completo"], ci=p.get("ci"),
                grupo_prioridad=p["grupo_prioridad"], grupo_prioridad_nombre=p.get("grupo_prioridad_nombre") or PRIORITY_NAMES.get(p["grupo_prioridad"], ""),
                es_menor=bool(p.get("es_menor")), insulina=o["insulina"], lot_id=o["lot_id"], producto=lot.producto,
                lote=lot.lote, fecha_venc=lot.fecha_venc, envases=o["envases"], ui=o["ui"], misma_insulina=o["misma_insulina"],
            )
        )
    opciones.sort(key=lambda o: (not o.misma_insulina, o.producto, o.nombre_completo))
    return schemas.WarehouseSwapOptions(
        beneficiario_id=beneficiario_id, insulina=insulina, lot_id=lot_id, producto=lots[lot_id].producto,
        envases=envases, ui=envases * lots[lot_id].ui_por_envase, opciones=opciones,
    )


async def _save_lines(db: AsyncSession, d: models.InsulinDistribution, lines: Dict[Tuple[int, str, int], int]) -> None:
    """Deja las líneas del reparto (tabla y resultado guardado) como `lines`."""
    ui_by_lot = {int(s["lot_id"]): float(s["ui_por_envase"]) for s in d.resultado.get("stock", [])}
    existing = {(i.beneficiario_id, i.insulina, i.lot_id): i for i in d.items}
    for key, item in existing.items():
        n = lines.get(key, 0)
        if n <= 0:
            await db.delete(item)
        elif item.envases != n:
            item.envases = n
            item.ui = n * ui_by_lot[key[2]]
    await db.flush()
    for key, n in lines.items():
        if key not in existing and n > 0:
            db.add(_item(d.id, key[0], key[1], key[2], n, ui_by_lot))
    # Copia profunda: si se modificara el JSON en su lugar, SQLAlchemy lo vería igual al guardado y no lo escribiría.
    d.resultado = wd.rebuild_result(copy.deepcopy(d.resultado), lines, _lots_info(d.resultado))
    flag_modified(d, "resultado")
    d.updated_at = _now()


@router.post("/distributions/{distribution_id}/swaps", response_model=schemas.WarehouseDistributionDetail, summary="Intercambio equivalente entre dos beneficiarios")
async def create_swap(
    distribution_id: int,
    payload: schemas.WarehouseSwapCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    d = await _load(db, distribution_id, lock=True)
    _require_draft(d)
    lots = _lots_info(d.resultado)
    holders, people = _holders(d.resultado)
    a = holders.get((payload.beneficiario_id, payload.insulina))
    b = holders.get((payload.con_beneficiario_id, payload.con_insulina))
    if a is None or b is None:
        raise HTTPException(status_code=404, detail="Ese tratamiento no está en el reparto.")
    lines = wd.lines_from_rows(d.items)
    nombres = {bid: p["nombre_completo"] for bid, p in people.items()}
    try:
        ui = wd.validate_swap(lines, lots, a, payload.lot_id, payload.envases, b, payload.con_lot_id, payload.con_envases, nombres)
        wd.apply_swap(lines, a, payload.lot_id, payload.envases, b, payload.con_lot_id, payload.con_envases)
    except wd.SwapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await _save_lines(db, d, lines)
    db.add(
        models.InsulinDistributionSwap(
            distribution_id=d.id,
            beneficiario_a=a.beneficiario_id, insulina_a=a.insulina, lot_a_id=payload.lot_id, envases_a=payload.envases,
            beneficiario_b=b.beneficiario_id, insulina_b=b.insulina, lot_b_id=payload.con_lot_id, envases_b=payload.con_envases,
            ui=ui, created_by_id=current_user.id,
        )
    )
    _audit(db, current_user.id, "insulin_distribution", d.id, "SWAP_INSULIN_DISTRIBUTION", payload.model_dump())
    await db.commit()
    return await _detail(db, d.id)


@router.post("/distributions/{distribution_id}/reset", response_model=schemas.WarehouseDistributionDetail, summary="Deshace todos los intercambios")
async def reset_distribution(
    distribution_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    """Vuelve a la propuesta del motor: deshace todos los intercambios del borrador."""
    d = await _load(db, distribution_id, lock=True)
    _require_draft(d)
    deshechos = len(d.swaps)
    await _save_lines(db, d, wd.lines_from_rows(d.propuesta))
    for s in list(d.swaps):
        await db.delete(s)
    _audit(db, current_user.id, "insulin_distribution", d.id, "RESET_INSULIN_DISTRIBUTION", {"intercambios_deshechos": deshechos})
    await db.commit()
    return await _detail(db, d.id)


@router.post("/distributions/{distribution_id}/discard", response_model=schemas.WarehouseDistributionDetail, summary="Descarta un borrador")
async def discard_distribution(
    distribution_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    d = await _load(db, distribution_id, lock=True)
    _require_draft(d)
    d.estado = "DESCARTADO"
    d.discarded_at = _now()
    _audit(db, current_user.id, "insulin_distribution", d.id, "DISCARD_INSULIN_DISTRIBUTION", {})
    await db.commit()
    return await _detail(db, d.id)


@router.post("/distributions/{distribution_id}/consolidate", response_model=schemas.WarehouseDistributionDetail, summary="Consolida el reparto y descuenta el stock")
async def consolidate_distribution(
    distribution_id: int,
    payload: Optional[schemas.WarehouseConsolidate] = Body(None),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    """Congela el reparto y descuenta del stock los envases asignados (una salida por lote). La reserva y el sobrante
    quedan en el almacén. Si el stock cambió desde el cálculo, hay que volver a calcular.

    Cada beneficiario con ficha recibe en su portal el aviso de cuánta insulina le corresponde, con la ventana de
    entrega (`entrega_desde`/`entrega_hasta`; sin fechas, del 1 al 10 del mes siguiente) y las indicaciones
    opcionales (`mensaje`)."""
    hoy = date.today()
    if payload and payload.entrega_desde:
        desde, hasta = payload.entrega_desde, payload.entrega_hasta
    else:
        desde, hasta = _ventana_por_defecto(hoy)
    if hasta < hoy:
        raise HTTPException(status_code=400, detail="La entrega no puede terminar antes de hoy: revise las fechas.")
    d = await _load(db, distribution_id, lock=True)
    _require_draft(d)
    cambios = await _stock_changes(db, d, lock=True)
    if cambios:
        raise HTTPException(
            status_code=409,
            detail="El stock cambió desde que se calculó este reparto; vuelva a calcularlo antes de consolidar. "
            + "; ".join(cambios[:5]),
        )
    por_lote: Dict[int, int] = defaultdict(int)
    for item in d.items:
        por_lote[item.lot_id] += item.envases
    lots = {
        lot.id: lot
        for lot in (await db.execute(select(models.DonationLot).where(models.DonationLot.id.in_(list(por_lote))))).scalars().all()
    }
    for lot_id, n in sorted(por_lote.items()):
        lot = lots[lot_id]
        if n > lot.cantidad_disponible:  # no debería pasar: el stock es el del cálculo
            raise HTTPException(status_code=409, detail=f"El lote {lot.lote or lot_id} no tiene {n} envases disponibles.")
        lot.cantidad_disponible -= n
        db.add(models.StockMovement(lot_id=lot_id, tipo="SALIDA", cantidad=n, referencia=f"REPARTO:{d.id}"))
    d.estado = "CONSOLIDADO"
    d.consolidated_by_id = current_user.id
    d.consolidated_at = _now()
    d.aviso_mensaje = ((payload.mensaje if payload else None) or "").strip() or None
    d.entrega_desde, d.entrega_hasta = desde, hasta

    # Aviso en el portal: uno por beneficiario con ficha que sigue existiendo (el Registro Asistido no tiene portal).
    con_ficha = [p["patient_id"] for p in d.resultado.get("pacientes", []) if p["patient_id"] > 0]
    existentes = set(
        (await db.execute(select(models.Patient.id).where(models.Patient.id.in_(con_ficha)))).scalars().all()
    ) if con_ficha else set()
    for patient_id in con_ficha:
        if patient_id in existentes:
            db.add(models.InsulinDistributionNotice(distribution_id=d.id, patient_id=patient_id))
    _audit(
        db, current_user.id, "insulin_distribution", d.id, "CONSOLIDATE_INSULIN_DISTRIBUTION",
        {
            "lotes": len(por_lote), "envases": sum(por_lote.values()), "intercambios": len(d.swaps),
            "avisos_portal": len(existentes), "aviso_mensaje": d.aviso_mensaje,
            "entrega_desde": desde.isoformat(), "entrega_hasta": hasta.isoformat(),
        },
    )
    await db.commit()
    return await _detail(db, d.id)


# =============================================================================================== aviso en el portal
def _ventana_por_defecto(hoy: date) -> Tuple[date, date]:
    """Del 1 al 10 del mes siguiente al de la consolidación."""
    anio, mes = (hoy.year + 1, 1) if hoy.month == 12 else (hoy.year, hoy.month + 1)
    return date(anio, mes, 1), date(anio, mes, 10)


async def _my_patient_id(db: AsyncSession, user: models.User) -> int:
    if user.role != "PACIENTE":
        raise HTTPException(status_code=403, detail="Solo los beneficiarios pueden ver sus avisos.")
    patient_id = (await db.execute(select(models.Patient.id).where(models.Patient.user_id == user.id))).scalar()
    if not patient_id:
        raise HTTPException(status_code=404, detail="No se encontró la ficha del beneficiario.")
    return patient_id


def _notice_out(
    notice: models.InsulinDistributionNotice, dias, consolidated_at, entrega_desde, entrega_hasta, mensaje, paciente: dict
) -> schemas.InsulinNoticeOut:
    """Lo guardado del beneficiario en el reparto, en términos para él: qué envases recibe y cuántos días cubren."""
    tratamientos = []
    for i in paciente.get("insulinas", []):
        productos = [
            schemas.InsulinNoticeProduct(
                producto=l["producto"], envases=l["unidades"], ui=l["ui"], lote=l.get("lote"), fecha_venc=l.get("fecha_venc"),
            )
            for l in i.get("lotes", [])
        ]
        tratamientos.append(
            schemas.InsulinNoticeTreatment(
                insulina=i["insulina"],
                dosis_diaria=i.get("dosis_diaria_aplicada") or 0,
                dosis_registrada=i.get("dosis_diaria_registrada") or 0,
                dosis_limitada=bool(i.get("dosis_limitada")),
                sustituto=i.get("sustituto"),
                envases=sum(p.envases for p in productos),
                ui=float(i.get("entregado_ui") or 0),
                # Igual que en pantalla (cobertura × días del reparto), redondeando .5 hacia arriba.
                dias_cubiertos=math.floor(float(i.get("cobertura_pct") or 0) * dias / 100 + 0.5),
                productos=productos,
            )
        )
    return schemas.InsulinNoticeOut(
        id=notice.id, distribution_id=notice.distribution_id, consolidated_at=consolidated_at, dias=dias,
        entrega_desde=entrega_desde, entrega_hasta=entrega_hasta, mensaje=mensaje, visto_at=notice.visto_at,
        envases=sum(t.envases for t in tratamientos), ui=sum(t.ui for t in tratamientos), tratamientos=tratamientos,
        **_fotos(notice, personal=False),
    )


@router.get(
    "/insulin-notices/me",
    response_model=List[schemas.InsulinNoticeOut],
    summary="Avisos del beneficiario: la insulina que le corresponde en cada reparto consolidado",
)
async def list_my_insulin_notices(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """Del más reciente al más antiguo, con lo que quedó guardado al consolidar (ya con los intercambios)."""
    patient_id = await _my_patient_id(db, current_user)
    D, p, val = _snapshot_patients()
    N = models.InsulinDistributionNotice
    rows = (
        await db.execute(
            select(N, D.dias, D.consolidated_at, D.entrega_desde, D.entrega_hasta, D.aviso_mensaje, val)
            .select_from(N)
            .join(D, D.id == N.distribution_id)
            .join(p, true())
            .where(N.patient_id == patient_id, val["patient_id"].astext.cast(Integer) == patient_id)
            .order_by(D.id.desc())
        )
    ).all()
    return [_notice_out(*row) for row in rows]


@router.post(
    "/insulin-notices/me/{notice_id}/visto",
    response_model=schemas.InsulinNoticeSeen,
    summary="El beneficiario confirma que vio el aviso",
)
async def mark_my_insulin_notice_seen(
    notice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    patient_id = await _my_patient_id(db, current_user)
    N = models.InsulinDistributionNotice
    notice = (await db.execute(select(N).where(N.id == notice_id, N.patient_id == patient_id))).scalars().first()
    if notice is None:
        raise HTTPException(status_code=404, detail="Aviso no encontrado.")
    if notice.visto_at is None:  # la primera vez cuenta
        notice.visto_at = _now()
        await db.commit()
    return schemas.InsulinNoticeSeen(id=notice.id, visto_at=notice.visto_at)


@router.post(
    "/insulin-notices/me/{notice_id}/fotos/{tipo}",
    response_model=schemas.InsulinNoticePhoto,
    summary="El beneficiario sube la foto de sus insulinas ya usadas o de su hemoglobina glucosilada",
)
async def upload_my_insulin_notice_photo(
    notice_id: int,
    tipo: Literal["envases", "hba1c"],
    foto: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """Una foto de cada tipo por reparto: `envases` (sus insulinas ya usadas, imagen) o `hba1c` (su último resultado
    de hemoglobina glucosilada, imagen o PDF). Queda por revisar; si sube otra, reemplaza a la anterior (que se
    borra del almacenamiento). Una foto aprobada ya no se cambia."""
    patient_id = await _my_patient_id(db, current_user)
    N = models.InsulinDistributionNotice
    notice = (await db.execute(select(N).where(N.id == notice_id, N.patient_id == patient_id))).scalars().first()
    if notice is None:
        raise HTTPException(status_code=404, detail="Aviso no encontrado.")
    actual = next((f for f in notice.fotos if f.tipo == tipo), None)
    if actual is not None and actual.estado == "APROBADA":
        raise HTTPException(status_code=409, detail="Esta foto ya fue aprobada por la Fundación; no hace falta cambiarla.")
    nombre, formatos = NOTICE_PHOTOS[tipo]
    extension = formatos.get(foto.content_type or "")
    if extension is None:
        raise HTTPException(
            status_code=400,
            detail="Suba una foto JPG, PNG o WEBP" + (" o el PDF del laboratorio." if tipo == "hba1c" else "."),
        )
    content = await foto.read()
    if not content:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(content) > NOTICE_PHOTO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el máximo de 5 MB.")
    # La URL es pública y es un dato de salud: el nombre lleva un código imposible de adivinar.
    path = f"pacientes/{patient_id}/repartos/{notice.distribution_id}/{nombre}_{uuid.uuid4().hex}.{extension}"
    try:
        url = await run_in_threadpool(upload_file_to_firebase, content, path, foto.content_type)
    except Exception:
        raise HTTPException(status_code=502, detail="No se pudo subir el archivo; intente de nuevo en unos minutos.")
    anterior = actual.url if actual else None
    if actual is None:
        actual = models.InsulinNoticePhoto(tipo=tipo)
        notice.fotos.append(actual)
    actual.url, actual.subida_at, actual.estado = url, _now(), "PENDIENTE"
    actual.observacion = actual.revisada_at = actual.revisada_por_id = None
    await db.commit()
    if anterior:  # después del commit: si la base fallara, la foto anterior sigue sirviendo
        try:
            await run_in_threadpool(delete_file_from_firebase_by_url, anterior)
        except Exception:
            pass  # mejor esfuerzo: un archivo huérfano no afecta al beneficiario
    return _foto_out(actual, personal=False)


@router.post(
    "/insulin-notices/{notice_id}/fotos/{tipo}/revision",
    response_model=schemas.InsulinNoticePhoto,
    summary="El SUPER_ADMIN aprueba u observa una foto del aviso",
)
async def review_insulin_notice_photo(
    notice_id: int,
    tipo: Literal["envases", "hba1c"],
    payload: schemas.InsulinNoticePhotoReview,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    """APROBADA: la foto queda firme (el beneficiario ya no la cambia). OBSERVADA: el beneficiario ve el motivo y
    sube otra, que vuelve a quedar por revisar. Se puede cambiar la decisión; cada revisión queda en la auditoría."""
    P = models.InsulinNoticePhoto
    foto = (
        await db.execute(select(P).where(P.notice_id == notice_id, P.tipo == tipo).with_for_update())
    ).scalars().first()
    if foto is None:
        raise HTTPException(status_code=404, detail="El beneficiario todavía no subió esta foto.")
    foto.estado, foto.observacion = payload.estado, payload.observacion
    foto.revisada_at, foto.revisada_por_id = _now(), current_user.id
    _audit(
        db, current_user.id, "insulin_notice_photo", foto.id, "REVIEW_INSULIN_NOTICE_PHOTO",
        {"notice_id": notice_id, "tipo": tipo, "estado": foto.estado, "observacion": foto.observacion},
    )
    await db.commit()
    await db.refresh(foto, ["revisada_por"])
    return _foto_out(foto, personal=True)
