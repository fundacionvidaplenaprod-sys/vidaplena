from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app import models, schemas
from app.api import deps
from app.db import get_db

router = APIRouter()


@router.get("/contact", response_model=schemas.SiteContactInfoResponse)
async def get_contact_info(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.SiteContactInfo))
    info = result.scalars().first()
    if not info:
        return schemas.SiteContactInfoResponse()
    return info


@router.put("/contact", response_model=schemas.SiteContactInfoResponse)
async def update_contact_info(
    payload: schemas.SiteContactInfoUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    result = await db.execute(select(models.SiteContactInfo))
    info = result.scalars().first()
    if not info:
        info = models.SiteContactInfo()
        db.add(info)

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(info, field, value)
    info.updated_by = current_user.id

    await db.commit()
    await db.refresh(info)
    return info
