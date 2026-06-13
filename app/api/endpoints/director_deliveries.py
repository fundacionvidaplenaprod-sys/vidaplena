from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app import models, schemas
from app.api.deps import get_db, get_current_user
from app.core.security import hash_password

router = APIRouter()

@router.post("/", response_model=schemas.DirectorDeliveryResponse)
async def create_director_delivery(
    *,
    db: AsyncSession = Depends(get_db),
    delivery_in: schemas.DirectorDeliveryCreate,
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role not in ["SUPER_ADMIN", "REGISTRADOR"]:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    delivery = models.DirectorInsulinDelivery(
        patient_nombres=delivery_in.patient_nombres.strip().upper(),
        patient_ap_paterno=delivery_in.patient_ap_paterno.strip().upper(),
        patient_ap_materno=(delivery_in.patient_ap_materno.strip().upper() if delivery_in.patient_ap_materno else None),
        insulin_type=delivery_in.insulin_type,
        quantity=delivery_in.quantity,
        delivery_date=delivery_in.delivery_date or date.today(),
        recorded_by_id=current_user.id
    )
    db.add(delivery)
    await db.commit()
    await db.refresh(delivery)
    return delivery

@router.get("/search", response_model=Optional[schemas.DirectorDeliveryResponse])
async def search_last_delivery(
    nombres: str = Query(...),
    ap_paterno: str = Query(...),
    ap_materno: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Search for the most recent delivery by patient name
    query = select(models.DirectorInsulinDelivery).filter(
        func.upper(models.DirectorInsulinDelivery.patient_nombres) == nombres.strip().upper(),
        func.upper(models.DirectorInsulinDelivery.patient_ap_paterno) == ap_paterno.strip().upper()
    )
    if ap_materno:
        query = query.filter(func.upper(models.DirectorInsulinDelivery.patient_ap_materno) == ap_materno.strip().upper())

    query = query.order_by(models.DirectorInsulinDelivery.delivery_date.desc(), models.DirectorInsulinDelivery.id.desc())
    result = await db.execute(query)
    last_delivery = result.scalars().first()
    return last_delivery

@router.put("/pin")
async def update_director_pin(
    *,
    db: AsyncSession = Depends(get_db),
    pin_update: schemas.DirectorPinUpdate,
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Only SUPER_ADMIN can update the director PIN")

    if len(pin_update.pin) != 4 or not pin_update.pin.isdigit():
        raise HTTPException(status_code=400, detail="PIN must be exactly 4 digits")

    directora_email = "directora@vidaplena.org"
    query = select(models.User).filter(func.lower(models.User.email) == directora_email.lower())
    result = await db.execute(query)
    user = result.scalars().first()

    if not user:
        user = models.User(
            email=directora_email,
            password_hash=hash_password(pin_update.pin),
            role="REGISTRADOR",
            estado="ACTIVO"
        )
        db.add(user)
    else:
        user.password_hash = hash_password(pin_update.pin)

    await db.commit()
    return {"msg": "PIN updated successfully"}
