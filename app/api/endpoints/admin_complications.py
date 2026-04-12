from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError

from app import models, schemas
from app.db import get_db

router = APIRouter()

# --- Endpoints para ComplicationType ---

@router.post("/", response_model=schemas.ComplicationTypeResponse, status_code=status.HTTP_201_CREATED)
async def create_complication_type(
    comp_type: schemas.ComplicationTypeCreate, db: AsyncSession = Depends(get_db)
):
    # Verificar si el código ya existe
    query = select(models.ComplicationType).where(models.ComplicationType.code == comp_type.code)
    result = await db.execute(query)
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="El código de complicación ya existe")

    db_comp_type = models.ComplicationType(**comp_type.model_dump())
    db.add(db_comp_type)
    try:
        await db.commit()
        await db.refresh(db_comp_type)
        return db_comp_type
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Error al crear tipo de complicación")

@router.get("/", response_model=List[schemas.ComplicationTypeResponse])
async def get_complication_types(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.ComplicationType))
    return result.scalars().all()

@router.get("/{code}", response_model=schemas.ComplicationTypeResponse)
async def get_complication_type_by_code(code: str, db: AsyncSession = Depends(get_db)):
    query = select(models.ComplicationType).where(models.ComplicationType.code == code)
    result = await db.execute(query)
    db_comp_type = result.scalars().first()
    
    if db_comp_type is None:
        raise HTTPException(status_code=404, detail="Tipo de complicación no encontrado")
    return db_comp_type

@router.put("/{code}", response_model=schemas.ComplicationTypeResponse)
async def update_complication_type(
    code: str, comp_type_update: schemas.ComplicationTypeUpdate, db: AsyncSession = Depends(get_db)
):
    query = select(models.ComplicationType).where(models.ComplicationType.code == code)
    result = await db.execute(query)
    db_comp_type = result.scalars().first()
    
    if db_comp_type is None:
        raise HTTPException(status_code=404, detail="Tipo de complicación no encontrado")

    if comp_type_update.code is not None and comp_type_update.code != code:
        # Si el código se está actualizando, verificar unicidad
        q_check = select(models.ComplicationType).where(models.ComplicationType.code == comp_type_update.code)
        res_check = await db.execute(q_check)
        if res_check.scalars().first():
            raise HTTPException(status_code=400, detail="El nuevo código de complicación ya existe")
        db_comp_type.code = comp_type_update.code
    
    # Actualizar descripción u otros campos si los hubiera
    if comp_type_update.description is not None:
         db_comp_type.description = comp_type_update.description

    try:
        await db.commit()
        await db.refresh(db_comp_type)
        return db_comp_type
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Error al actualizar tipo de complicación")

@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_complication_type(code: str, db: AsyncSession = Depends(get_db)):
    query = select(models.ComplicationType).where(models.ComplicationType.code == code)
    result = await db.execute(query)
    db_comp_type = result.scalars().first()
    
    if db_comp_type is None:
        raise HTTPException(status_code=404, detail="Tipo de complicación no encontrado")
    
    try:
        await db.delete(db_comp_type)
        await db.commit()
        return {"ok": True}
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="No se puede eliminar el tipo de complicación, está en uso por registros de pacientes")
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Error al eliminar tipo de complicación")