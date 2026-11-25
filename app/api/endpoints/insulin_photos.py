"""Fotos de control del beneficiario: sus insulinas ya usadas y su hemoglobina glucosilada.

- El beneficiario las sube desde su portal cuando quiera, aunque todavía no tenga un reparto: `envases`, los envases
  vacíos de su entrega anterior (reglamento, art. 17 b; solo imagen), y `hba1c`, su último resultado de
  laboratorio (art. 8, cada 3 meses; imagen o PDF).
- Cuenta la más reciente de cada tipo. Mientras está por revisar u observada, una nueva la reemplaza (y la anterior
  se borra del almacenamiento); una aprobada queda en el historial y la siguiente es otra.
- El SUPER_ADMIN las revisa (pestaña «Fotos» del almacén y tabla de avisos de cada reparto): las aprueba o las
  observa con el motivo, que el beneficiario lee en su portal para subir otra. Cada revisión queda en la auditoría.
- Subirlas no es condición para recibir la insulina (art. 19).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.api import deps
from app.core.firebase import delete_file_from_firebase_by_url, upload_file_to_firebase
from app.core.insulin_photos import latest_photos, photo_out, photos_fields
from app.core.text_normalize import fold_sql, normalize_name
from app.db import get_db

router = APIRouter()

# El portal achica las fotos antes de subirlas; el tope es para las que no pudo achicar.
PHOTO_MAX_BYTES = 5 * 1024 * 1024
_IMAGENES = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp"}
# tipo -> (nombre del archivo, formatos). La HbA1c admite el PDF del laboratorio.
PHOTO_TIPOS = {
    "envases": ("insulinas_usadas", _IMAGENES),
    "hba1c": ("hemoglobina_glucosilada", {**_IMAGENES, "application/pdf": "pdf"}),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================================== beneficiario
@router.get("/insulin-photos/me", response_model=schemas.InsulinControlPhotos, summary="Mis fotos de control")
async def my_insulin_photos(
    db: AsyncSession = Depends(get_db),
    patient_id: int = Depends(deps.get_current_patient_id),
) -> Any:
    """La más reciente de cada tipo, con su revisión."""
    fotos = (await latest_photos(db, [patient_id])).get(patient_id, {})
    return schemas.InsulinControlPhotos(**photos_fields(fotos, personal=False))


@router.post(
    "/insulin-photos/me/{tipo}",
    response_model=schemas.InsulinControlPhoto,
    summary="El beneficiario sube la foto de sus insulinas ya usadas o de su hemoglobina glucosilada",
)
async def upload_my_insulin_photo(
    tipo: Literal["envases", "hba1c"],
    foto: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    patient_id: int = Depends(deps.get_current_patient_id),
) -> Any:
    """Queda por revisar. Reemplaza a la más reciente si todavía está por revisar u observada; si estaba aprobada
    (o no había), es una foto nueva y la aprobada queda en el historial."""
    nombre, formatos = PHOTO_TIPOS[tipo]
    extension = formatos.get(foto.content_type or "")
    if extension is None:
        raise HTTPException(
            status_code=400,
            detail="Suba una foto JPG, PNG o WEBP" + (" o el PDF del laboratorio." if tipo == "hba1c" else "."),
        )
    content = await foto.read()
    if not content:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(content) > PHOTO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el máximo de 5 MB.")

    P = models.InsulinControlPhoto
    actual = (
        await db.execute(
            select(P).where(P.patient_id == patient_id, P.tipo == tipo)
            .order_by(P.subida_at.desc(), P.id.desc()).limit(1).with_for_update()
        )
    ).scalars().first()
    # La URL es pública y es un dato de salud: el nombre lleva un código imposible de adivinar.
    path = f"pacientes/{patient_id}/fotos_control/{nombre}_{uuid.uuid4().hex}.{extension}"
    try:
        url = await run_in_threadpool(upload_file_to_firebase, content, path, foto.content_type)
    except Exception:
        raise HTTPException(status_code=502, detail="No se pudo subir el archivo; intente de nuevo en unos minutos.")

    N = models.InsulinDistributionNotice
    aviso_id = (await db.execute(select(func.max(N.id)).where(N.patient_id == patient_id))).scalar()  # su aviso vigente

    anterior = None
    if actual is not None and actual.estado != "APROBADA":
        anterior = actual.url
    else:
        actual = models.InsulinControlPhoto(patient_id=patient_id, tipo=tipo, url=url)
        db.add(actual)
    actual.notice_id = aviso_id
    actual.url, actual.subida_at, actual.estado = url, _now(), "PENDIENTE"
    actual.observacion = actual.revisada_at = actual.revisada_por_id = None
    await db.commit()
    if anterior:  # después del commit: si la base fallara, la foto anterior sigue sirviendo
        try:
            await run_in_threadpool(delete_file_from_firebase_by_url, anterior)
        except Exception:
            pass  # mejor esfuerzo: un archivo huérfano no afecta al beneficiario
    await db.refresh(actual, ["revisada_por"])
    return photo_out(actual, personal=False)


# ============================================================================================== SUPER_ADMIN
@router.get(
    "/insulin-photos",
    response_model=List[schemas.InsulinControlPhotoListItem],
    summary="Fotos de control de los beneficiarios, para revisarlas",
)
async def list_insulin_photos(
    estado: Optional[Literal["PENDIENTE", "APROBADA", "OBSERVADA"]] = Query(None, description="Sin estado: todas."),
    q: Optional[str] = Query(None, max_length=80, description="Nombre o C.I. del beneficiario"),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    """Las por revisar, de la más antigua a la más nueva (en el orden en que conviene revisarlas); las demás, de la
    más nueva a la más antigua. Hasta 500."""
    P, Pa = models.InsulinControlPhoto, models.Patient
    nombre = func.concat_ws(" ", Pa.nombres, Pa.ap_paterno, Pa.ap_materno)
    query = select(P, Pa.id, nombre, Pa.ci).join(Pa, Pa.id == P.patient_id)
    if estado:
        query = query.where(P.estado == estado)
    for token in normalize_name(q or "").split():
        query = query.where(
            or_(fold_sql(nombre).contains(token, autoescape=True), func.coalesce(Pa.ci, "").icontains(token, autoescape=True))
        )
    orden = (P.subida_at.asc(), P.id.asc()) if estado == "PENDIENTE" else (P.subida_at.desc(), P.id.desc())
    filas = (await db.execute(query.order_by(*orden).limit(500))).all()
    return [
        schemas.InsulinControlPhotoListItem(
            **photo_out(foto, personal=True).model_dump(), beneficiario_id=pid, nombre_completo=nombre_completo, ci=ci,
        )
        for foto, pid, nombre_completo, ci in filas
    ]


@router.post(
    "/insulin-photos/{photo_id}/revision",
    response_model=schemas.InsulinControlPhoto,
    summary="El SUPER_ADMIN aprueba u observa una foto de control",
)
async def review_insulin_photo(
    photo_id: int,
    payload: schemas.InsulinControlPhotoReview,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
) -> Any:
    """APROBADA: queda firme (la próxima que suba el beneficiario es otra). OBSERVADA: el beneficiario ve el motivo y
    sube otra, que la reemplaza y vuelve a quedar por revisar. Se puede cambiar la decisión."""
    P = models.InsulinControlPhoto
    foto = (await db.execute(select(P).where(P.id == photo_id).with_for_update())).scalars().first()
    if foto is None:
        raise HTTPException(status_code=404, detail="Foto no encontrada.")
    foto.estado, foto.observacion = payload.estado, payload.observacion
    foto.revisada_at, foto.revisada_por_id = _now(), current_user.id
    db.add(
        models.AuditLog(
            actor_id=current_user.id, entidad="insulin_control_photo", entidad_id=foto.id,
            accion="REVIEW_INSULIN_CONTROL_PHOTO",
            payload={"patient_id": foto.patient_id, "tipo": foto.tipo, "estado": foto.estado, "observacion": foto.observacion},
        )
    )
    await db.commit()
    await db.refresh(foto, ["revisada_por"])
    return photo_out(foto, personal=True)
