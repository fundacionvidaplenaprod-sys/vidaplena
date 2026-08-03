import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app import models, schemas
from app.api import deps
from app.core.firebase import delete_file_from_firebase, upload_file_to_firebase
from app.db import get_db

router = APIRouter()

MAX_FILE_SIZE_MB = 5
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_TYPES = ["image/jpeg", "image/png", "image/jpg", "image/webp"]


@router.get("/", response_model=List[schemas.GalleryPhotoResponse])
async def list_gallery_photos(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.GalleryPhoto).order_by(models.GalleryPhoto.orden, models.GalleryPhoto.created_at)
    )
    return result.scalars().all()


@router.post("/", response_model=schemas.GalleryPhotoResponse, status_code=status.HTTP_201_CREATED)
async def create_gallery_photo(
    foto: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    orden: int = Form(0),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    if foto.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido (use imagen JPG, PNG o WEBP).")

    content = await foto.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail=f"Archivo demasiado grande. Máximo {MAX_FILE_SIZE_MB}MB.")

    ext = (foto.filename or "foto").split(".")[-1]
    storage_path = f"galeria/{uuid.uuid4().hex[:12]}.{ext}"
    try:
        public_url = upload_file_to_firebase(content, storage_path, foto.content_type)
    except Exception as e:
        print(f"Error Firebase (galeria): {e}")
        raise HTTPException(status_code=500, detail="Error al subir la foto.")

    photo = models.GalleryPhoto(
        url=public_url,
        storage_path=storage_path,
        caption=(caption or "").strip() or None,
        orden=orden,
        created_by=current_user.id,
    )
    db.add(photo)
    await db.commit()
    await db.refresh(photo)
    return photo


@router.put("/{photo_id}", response_model=schemas.GalleryPhotoResponse)
async def update_gallery_photo(
    photo_id: int,
    payload: schemas.GalleryPhotoUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    photo = await db.get(models.GalleryPhoto, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Foto no encontrada.")

    if payload.caption is not None:
        photo.caption = payload.caption.strip() or None
    if payload.orden is not None:
        photo.orden = payload.orden

    await db.commit()
    await db.refresh(photo)
    return photo


@router.delete("/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gallery_photo(
    photo_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    photo = await db.get(models.GalleryPhoto, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Foto no encontrada.")

    storage_path = photo.storage_path
    await db.delete(photo)
    await db.commit()

    try:
        delete_file_from_firebase(storage_path)
    except Exception as e:
        print(f"Error al borrar archivo de Firebase (galeria): {e}")
