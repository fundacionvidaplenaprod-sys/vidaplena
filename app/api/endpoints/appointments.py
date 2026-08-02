import hashlib
import io
import uuid
from datetime import date, datetime, time, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app import models, schemas
from app.api import deps
from app.core.config import settings
from app.core.firebase import upload_file_to_firebase
from app.core.ocr import extract_receipt_data
from app.db import get_db

router = APIRouter()

# --- Reglas de negocio (SAPAM) ---
DONATION_AMOUNT = 70.00
VERIFICATION_WINDOW_MINUTES = 8
MIN_BOOKING_DAYS_AHEAD = 1
MAX_BOOKING_DAYS_AHEAD = 15
APPOINTMENT_DURATION_MINUTES = 20
WHATSAPP_CONTACT = "+59172966106"
NO_MATCH_MESSAGE = (
    "No pudimos verificar automáticamente su comprobante de donación. "
    f"Si cree que se trata de un error, comuníquese al WhatsApp {WHATSAPP_CONTACT} "
    "para una verificación manual."
)

MAX_FILE_SIZE_MB = 3
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/jpg"]

# lunes=0 ... domingo=6
BUSINESS_HOURS = {
    0: [(time(8, 30), time(12, 30)), (time(14, 30), time(19, 30))],
    1: [(time(8, 30), time(12, 30)), (time(14, 30), time(19, 30))],
    2: [(time(8, 30), time(12, 30)), (time(14, 30), time(19, 30))],
    3: [(time(8, 30), time(12, 30)), (time(14, 30), time(19, 30))],
    4: [(time(8, 30), time(12, 30)), (time(14, 30), time(19, 30))],
    5: [(time(8, 30), time(13, 30))],
    6: [],
}


def _slots_for_weekday(weekday: int) -> List[time]:
    ranges = BUSINESS_HOURS.get(weekday, [])
    anchor = date(2000, 1, 1)
    slots = []
    for start, end in ranges:
        current = datetime.combine(anchor, start)
        end_dt = datetime.combine(anchor, end)
        while current + timedelta(minutes=APPOINTMENT_DURATION_MINUTES) <= end_dt:
            slots.append(current.time())
            current += timedelta(minutes=APPOINTMENT_DURATION_MINUTES)
    return slots


async def _is_blocked(db: AsyncSession, fecha: date) -> bool:
    result = await db.execute(
        select(models.DoctorBlockedDay).where(models.DoctorBlockedDay.fecha == fecha)
    )
    return result.scalars().first() is not None


async def _validate_bookable_date(db: AsyncSession, fecha: date) -> Optional[str]:
    """Devuelve None si la fecha es agendable, o un motivo textual si no lo es."""
    today = date.today()
    min_date = today + timedelta(days=MIN_BOOKING_DAYS_AHEAD)
    max_date = today + timedelta(days=MAX_BOOKING_DAYS_AHEAD)

    if fecha < min_date or fecha > max_date:
        return (
            f"Solo se puede agendar desde el {min_date.isoformat()} "
            f"hasta el {max_date.isoformat()}."
        )
    if fecha.weekday() == 6:
        return "No hay atención los días domingo."
    if await _is_blocked(db, fecha):
        return "Ese día no está disponible para atención."
    return None


@router.get("/config", response_model=schemas.AppointmentConfigResponse)
async def get_appointment_config():
    return {
        "monto_donacion": DONATION_AMOUNT,
        "duracion_cita_minutos": APPOINTMENT_DURATION_MINUTES,
        "dias_max_anticipacion": MAX_BOOKING_DAYS_AHEAD,
        "whatsapp_contacto": WHATSAPP_CONTACT,
        "horarios": {
            "lunes_a_viernes": "08:30-12:30 y 14:30-19:30",
            "sabado": "08:30-13:30",
            "domingo_y_feriados": "sin atención",
        },
    }


@router.get("/availability", response_model=schemas.AppointmentAvailabilityResponse)
async def get_availability(
    fecha: date = Query(...),
    db: AsyncSession = Depends(get_db),
):
    motivo = await _validate_bookable_date(db, fecha)
    if motivo:
        return {"fecha": fecha, "disponible": False, "motivo": motivo, "slots": []}

    all_slots = _slots_for_weekday(fecha.weekday())

    result = await db.execute(
        select(models.Appointment.hora_cita).where(
            and_(
                models.Appointment.fecha_cita == fecha,
                models.Appointment.estado == "CONFIRMADA",
            )
        )
    )
    taken = {row[0] for row in result.all()}

    slots = [{"hora": s.strftime("%H:%M"), "disponible": s not in taken} for s in all_slots]
    return {"fecha": fecha, "disponible": True, "motivo": None, "slots": slots}


@router.post("/book", response_model=schemas.AppointmentBookingResponse, status_code=status.HTTP_201_CREATED)
async def book_appointment(
    nombres: str = Form(...),
    ap_paterno: str = Form(...),
    ap_materno: Optional[str] = Form(None),
    ci: str = Form(...),
    fecha_nac: date = Form(...),
    fecha_cita: date = Form(...),
    hora_cita: str = Form(...),
    comprobante: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    # 1. Revalidar fecha/hora en servidor (nunca confiar solo en el frontend)
    motivo_fecha = await _validate_bookable_date(db, fecha_cita)
    if motivo_fecha:
        raise HTTPException(status_code=400, detail=motivo_fecha)

    try:
        hora_obj = datetime.strptime(hora_cita, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de hora inválido.")

    if hora_obj not in _slots_for_weekday(fecha_cita.weekday()):
        raise HTTPException(status_code=400, detail="Ese horario no es válido para el día seleccionado.")

    existing_q = await db.execute(
        select(models.Appointment).where(
            and_(
                models.Appointment.fecha_cita == fecha_cita,
                models.Appointment.hora_cita == hora_obj,
                models.Appointment.estado == "CONFIRMADA",
            )
        )
    )
    if existing_q.scalars().first():
        raise HTTPException(status_code=409, detail="Ese horario ya fue tomado, por favor elija otro.")

    # 2. Validar y subir el comprobante
    if comprobante.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido (use imagen o PDF).")

    file_content = await comprobante.read()
    if len(file_content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail=f"Archivo demasiado grande. Máximo {MAX_FILE_SIZE_MB}MB.")

    ext = (comprobante.filename or "comprobante").split(".")[-1]
    firebase_path = f"citas/{fecha_cita.isoformat()}/{uuid.uuid4().hex[:10]}.{ext}"
    try:
        public_url = upload_file_to_firebase(file_content, firebase_path, comprobante.content_type)
    except Exception as e:
        print(f"Error Firebase (citas): {e}")
        raise HTTPException(status_code=500, detail="Error al subir el comprobante.")

    # 3. OCR y verificación
    ocr_monto = ocr_fecha = ocr_hora = None
    motivo_rechazo = None
    user_message = None
    verificado = False
    contact_suffix = f"Si crees que esto es un error, comunícate al WhatsApp {WHATSAPP_CONTACT}."

    try:
        ocr_result = extract_receipt_data(file_content, comprobante.content_type)
        ocr_monto = ocr_result.get("monto")
        ocr_fecha = ocr_result.get("fecha")
        ocr_hora = ocr_result.get("hora")
        raw_text = (ocr_result.get("raw_text") or "").strip()

        if not raw_text:
            motivo_rechazo = "OCR no detectó texto en la imagen."
            user_message = (
                "No pudimos leer texto en tu comprobante. Asegúrate de que la foto o captura esté "
                f"clara y completa, e inténtalo de nuevo. {contact_suffix}"
            )
        else:
            now = datetime.now()
            problems = []

            if ocr_monto is None:
                problems.append("no detectamos el monto")
            elif abs(ocr_monto - DONATION_AMOUNT) > 0.01:
                problems.append(
                    f"el monto detectado (Bs. {ocr_monto:.2f}) no coincide con el esperado (Bs. {DONATION_AMOUNT:.2f})"
                )

            if ocr_fecha is None:
                problems.append("no detectamos la fecha")
            elif ocr_fecha != now.date():
                problems.append(f"la fecha detectada ({ocr_fecha.strftime('%d/%m/%Y')}) no es la de hoy")

            if ocr_hora is None:
                problems.append("no detectamos la hora")
            else:
                receipt_dt = datetime.combine(ocr_fecha or now.date(), ocr_hora)
                window_start = now - timedelta(minutes=VERIFICATION_WINDOW_MINUTES)
                if not (window_start <= receipt_dt <= now):
                    problems.append(
                        f"la hora detectada ({ocr_hora.strftime('%H:%M')}) es de hace más de "
                        f"{VERIFICATION_WINDOW_MINUTES} minutos"
                    )

            if problems:
                motivo_rechazo = "; ".join(problems).capitalize() + "."
                user_message = f"No pudimos verificar tu comprobante: {'; '.join(problems)}. {contact_suffix}"
            else:
                verificado = True
    except Exception as e:
        print(f"Error OCR (citas): {e}")
        motivo_rechazo = f"Error técnico de OCR: {e}"
        user_message = (
            "Tuvimos un problema técnico al procesar tu comprobante (no relacionado a tus datos). "
            f"Intenta nuevamente en unos minutos. {contact_suffix}"
        )

    # 4. Guardar el intento (confirmado o rechazado)
    appointment = models.Appointment(
        nombres=nombres,
        ap_paterno=ap_paterno,
        ap_materno=ap_materno,
        ci=ci,
        fecha_nac=fecha_nac,
        fecha_cita=fecha_cita,
        hora_cita=hora_obj,
        estado="CONFIRMADA" if verificado else "RECHAZADA",
        url_comprobante=public_url,
        ocr_monto_detectado=ocr_monto,
        ocr_fecha_detectada=ocr_fecha,
        ocr_hora_detectada=ocr_hora,
        motivo_rechazo=motivo_rechazo,
    )
    db.add(appointment)

    if not verificado:
        await db.commit()
        raise HTTPException(status_code=400, detail=user_message or NO_MATCH_MESSAGE)

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Ese horario ya fue tomado, por favor elija otro.")

    raw_str = f"CITA-{appointment.id}-{settings.SECRET_KEY}"
    appointment.security_code = hashlib.sha256(raw_str.encode()).hexdigest()[:10].upper()

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Ese horario ya fue tomado, por favor elija otro.")

    full_name = f"{nombres} {ap_paterno} {ap_materno or ''}".strip()
    return {
        "id": appointment.id,
        "security_code": appointment.security_code,
        "fecha_cita": fecha_cita,
        "hora_cita": hora_obj,
        "nombre_completo": full_name,
    }


@router.get("/{appointment_id}/ficha.pdf")
async def download_ficha(
    appointment_id: int,
    code: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    appointment = await db.get(models.Appointment, appointment_id)
    if not appointment or appointment.estado != "CONFIRMADA" or appointment.security_code != code:
        raise HTTPException(status_code=404, detail="Ficha no encontrada.")

    full_name = f"{appointment.nombres} {appointment.ap_paterno} {appointment.ap_materno or ''}".strip().title()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=72, leftMargin=72, topMargin=52, bottomMargin=52,
    )
    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "TitleStyle", parent=styles["Normal"], fontSize=14,
        leading=18, alignment=TA_CENTER, spaceAfter=20, fontName="Helvetica-Bold",
    )
    style_body = ParagraphStyle(
        "BodyStyle", parent=styles["Normal"], fontSize=11, leading=18, alignment=TA_LEFT,
    )
    style_code = ParagraphStyle(
        "CodeStyle", parent=styles["Normal"], fontSize=10, alignment=TA_LEFT, fontName="Helvetica-Bold",
    )

    story = [
        Paragraph("FICHA DE ATENCIÓN MÉDICA — Fundación V.I.D.A. Plena", style_title),
        Paragraph(f"CÓDIGO: {appointment.security_code}", style_code),
        Spacer(1, 16),
        Paragraph(f"<b>Paciente:</b> {full_name}", style_body),
        Paragraph(f"<b>C.I.:</b> {appointment.ci}", style_body),
        Paragraph(f"<b>Fecha de nacimiento:</b> {appointment.fecha_nac.strftime('%d/%m/%Y')}", style_body),
        Paragraph(f"<b>Fecha de la cita:</b> {appointment.fecha_cita.strftime('%d/%m/%Y')}", style_body),
        Paragraph(f"<b>Hora de la cita:</b> {appointment.hora_cita.strftime('%H:%M')}", style_body),
        Spacer(1, 10),
        Paragraph(
            "Presentarse en Calle Juan Capriles N°346 entre Santa Cruz y Villarroel, "
            "zona Norte, Cochabamba.",
            style_body,
        ),
    ]

    doc.build(story)
    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Ficha_{appointment.security_code}.pdf"'},
    )


# ==========================================
#   PANEL DOCTORA (SOLO SUPER_ADMIN)
# ==========================================

@router.post("/{appointment_id}/approve", response_model=schemas.AppointmentHistoryItem)
async def approve_appointment_manually(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    Aprueba manualmente una cita que el OCR rechazó, para el caso en que el
    paciente se comunicó (WhatsApp) y se verificó que su comprobante sí era
    válido. Genera el código de seguridad para poder emitir la ficha.
    """
    appointment = await db.get(models.Appointment, appointment_id)
    if not appointment:
        raise HTTPException(status_code=404, detail="Cita no encontrada.")
    if appointment.estado == "CONFIRMADA":
        raise HTTPException(status_code=400, detail="Esta cita ya está confirmada.")
    if appointment.estado != "RECHAZADA":
        raise HTTPException(status_code=400, detail="Solo se pueden aprobar citas rechazadas.")

    conflict_q = await db.execute(
        select(models.Appointment).where(
            and_(
                models.Appointment.fecha_cita == appointment.fecha_cita,
                models.Appointment.hora_cita == appointment.hora_cita,
                models.Appointment.estado == "CONFIRMADA",
                models.Appointment.id != appointment.id,
            )
        )
    )
    if conflict_q.scalars().first():
        raise HTTPException(
            status_code=409,
            detail="Ese horario ya fue tomado por otra cita confirmada. Coordine una nueva fecha/hora con el paciente.",
        )

    appointment.estado = "CONFIRMADA"
    appointment.revisado_manualmente_por = current_user.id
    appointment.revisado_manualmente_at = datetime.now()
    raw_str = f"CITA-{appointment.id}-{settings.SECRET_KEY}"
    appointment.security_code = hashlib.sha256(raw_str.encode()).hexdigest()[:10].upper()

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Ese horario ya fue tomado, por favor elija otro.")

    await db.refresh(appointment)
    return appointment


@router.post("/{appointment_id}/approve-social-case", response_model=schemas.AppointmentHistoryItem)
async def approve_appointment_social_case(
    appointment_id: int,
    payload: schemas.SocialCaseApproval,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    """
    Confirma una cita sin exigir voucher de donación, para pacientes en
    situación de vulnerabilidad ("Caso Social") detectada en evaluación
    presencial o reportada por WhatsApp. Deja registro de quién autorizó
    la exención.
    """
    appointment = await db.get(models.Appointment, appointment_id)
    if not appointment:
        raise HTTPException(status_code=404, detail="Cita no encontrada.")
    if appointment.estado == "CONFIRMADA":
        raise HTTPException(status_code=400, detail="Esta cita ya está confirmada.")

    conflict_q = await db.execute(
        select(models.Appointment).where(
            and_(
                models.Appointment.fecha_cita == appointment.fecha_cita,
                models.Appointment.hora_cita == appointment.hora_cita,
                models.Appointment.estado == "CONFIRMADA",
                models.Appointment.id != appointment.id,
            )
        )
    )
    if conflict_q.scalars().first():
        raise HTTPException(
            status_code=409,
            detail="Ese horario ya fue tomado por otra cita confirmada. Coordine una nueva fecha/hora con el paciente.",
        )

    appointment.estado = "CONFIRMADA"
    appointment.eximido_por = current_user.id
    appointment.eximido_at = datetime.now()
    appointment.motivo_exencion = (payload.motivo or "").strip() or "Caso Social"
    raw_str = f"CITA-{appointment.id}-{settings.SECRET_KEY}"
    appointment.security_code = hashlib.sha256(raw_str.encode()).hexdigest()[:10].upper()

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Ese horario ya fue tomado, por favor elija otro.")

    await db.refresh(appointment)
    return appointment


@router.get("/blocked-days", response_model=List[schemas.BlockedDayResponse])
async def list_blocked_days(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    result = await db.execute(
        select(models.DoctorBlockedDay).order_by(models.DoctorBlockedDay.fecha)
    )
    return result.scalars().all()


@router.post("/blocked-days", response_model=schemas.BlockedDayResponse, status_code=status.HTTP_201_CREATED)
async def create_blocked_day(
    payload: schemas.BlockedDayCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    blocked = models.DoctorBlockedDay(
        fecha=payload.fecha, motivo=payload.motivo, created_by=current_user.id
    )
    db.add(blocked)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Ese día ya está bloqueado.")
    await db.refresh(blocked)
    return blocked


@router.delete("/blocked-days/{fecha}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blocked_day(
    fecha: date,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    result = await db.execute(
        select(models.DoctorBlockedDay).where(models.DoctorBlockedDay.fecha == fecha)
    )
    blocked = result.scalars().first()
    if not blocked:
        raise HTTPException(status_code=404, detail="No existe un bloqueo para esa fecha.")
    await db.delete(blocked)
    await db.commit()


@router.get("/agenda", response_model=List[schemas.AppointmentAgendaItem])
async def get_agenda(
    fecha: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    result = await db.execute(
        select(models.Appointment)
        .where(
            and_(
                models.Appointment.fecha_cita == fecha,
                models.Appointment.estado == "CONFIRMADA",
            )
        )
        .order_by(models.Appointment.hora_cita)
    )
    return result.scalars().all()


@router.put("/{appointment_id}/clinical-note", response_model=schemas.AppointmentAgendaItem)
async def update_clinical_note(
    appointment_id: int,
    payload: schemas.ClinicalNoteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_staff_user),
):
    appointment = await db.get(models.Appointment, appointment_id)
    if not appointment or appointment.estado != "CONFIRMADA":
        raise HTTPException(status_code=404, detail="Cita no encontrada.")

    appointment.nota_consulta = payload.nota
    appointment.nota_consulta_at = datetime.now()
    appointment.nota_consulta_by = current_user.id
    await db.commit()
    await db.refresh(appointment)
    return appointment


@router.get("/history", response_model=List[schemas.AppointmentHistoryItem])
async def get_history_by_ci(
    ci: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    result = await db.execute(
        select(models.Appointment)
        .where(models.Appointment.ci == ci)
        .order_by(models.Appointment.fecha_cita.desc())
    )
    return result.scalars().all()
