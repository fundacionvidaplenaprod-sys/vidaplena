import uuid
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app import models, schemas
from app.api import deps
from app.core.firebase import delete_file_from_firebase, upload_file_to_firebase
from app.db import get_db

router = APIRouter()

ALLOWED_KEYS = {"qr_donaciones", "qr_compromisos", "qr_consultas"}
ALLOWED_TYPES = ["image/jpeg", "image/png", "image/jpg", "image/webp"]
MAX_FILE_SIZE_MB = 5
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


@router.get("/", response_model=List[schemas.SiteAssetResponse])
async def list_site_assets(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.SiteAsset))
    return result.scalars().all()


@router.put("/{key}", response_model=schemas.SiteAssetResponse)
async def upsert_site_asset(
    key: str,
    foto: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    if key not in ALLOWED_KEYS:
        raise HTTPException(status_code=400, detail="Clave de recurso no reconocida.")

    if foto.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido (use imagen JPG, PNG o WEBP).")

    content = await foto.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail=f"Archivo demasiado grande. Máximo {MAX_FILE_SIZE_MB}MB.")

    ext = (foto.filename or "qr").split(".")[-1]
    storage_path = f"site-assets/{key}/{uuid.uuid4().hex[:12]}.{ext}"
    try:
        public_url = upload_file_to_firebase(content, storage_path, foto.content_type)
    except Exception as e:
        print(f"Error Firebase (site-assets): {e}")
        raise HTTPException(status_code=500, detail="Error al subir la imagen.")

    result = await db.execute(select(models.SiteAsset).where(models.SiteAsset.key == key))
    asset = result.scalars().first()
    old_storage_path = asset.storage_path if asset else None

    if asset:
        asset.url = public_url
        asset.storage_path = storage_path
        asset.updated_by = current_user.id
    else:
        asset = models.SiteAsset(key=key, url=public_url, storage_path=storage_path, updated_by=current_user.id)
        db.add(asset)

    await db.commit()
    await db.refresh(asset)

    if old_storage_path:
        try:
            delete_file_from_firebase(old_storage_path)
        except Exception as e:
            print(f"Error al borrar QR anterior de Firebase: {e}")

    return asset
