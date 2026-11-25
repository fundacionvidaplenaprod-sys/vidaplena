"""Fotos de control del beneficiario (sus insulinas ya usadas y su hemoglobina glucosilada).

Cuenta la más reciente de cada tipo: es la que ve el beneficiario en su portal y la que ve el personal en cada
reparto. Las rutas están en `api/endpoints/insulin_photos.py`.
"""
from collections import defaultdict
from typing import Dict, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas


def photo_out(foto: models.InsulinControlPhoto, *, personal: bool) -> schemas.InsulinControlPhoto:
    """Quién la revisó solo lo ve el personal."""
    return schemas.InsulinControlPhoto(
        id=foto.id, tipo=foto.tipo, url=foto.url, subida_at=foto.subida_at, estado=foto.estado,
        observacion=foto.observacion, revisada_at=foto.revisada_at,
        revisada_por=foto.revisada_por.email if personal and foto.revisada_por else None,
    )


def photos_fields(fotos: Dict[str, models.InsulinControlPhoto], *, personal: bool) -> dict:
    """`{"foto_envases": ..., "foto_hba1c": ...}` para `schemas.InsulinControlPhotos` y los que heredan de él."""
    return {f"foto_{tipo}": photo_out(f, personal=personal) for tipo, f in fotos.items()}


async def latest_photos(db: AsyncSession, patient_ids: Iterable[int]) -> Dict[int, Dict[str, models.InsulinControlPhoto]]:
    """Por beneficiario, la foto más reciente de cada tipo (los del Registro Asistido, con id negativo, no tienen)."""
    ids = sorted({pid for pid in patient_ids if pid > 0})
    if not ids:
        return {}
    P = models.InsulinControlPhoto
    fotos = (
        await db.execute(
            select(P)
            .where(P.patient_id.in_(ids))
            .distinct(P.patient_id, P.tipo)
            .order_by(P.patient_id, P.tipo, P.subida_at.desc(), P.id.desc())
        )
    ).scalars().all()
    out: Dict[int, Dict[str, models.InsulinControlPhoto]] = defaultdict(dict)
    for f in fotos:
        out[f.patient_id][f.tipo] = f
    return out
