import asyncio
import io
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from fastapi.responses import StreamingResponse
from PIL import Image as PILImage
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app import models, schemas
from app.api import deps
from app.db import get_db
from app.core.firebase import upload_file_to_firebase
from app.core.ocr import extract_receipt_data

router = APIRouter()

LOGO_PATH = Path(__file__).resolve().parents[2] / "static" / "logo.png"
ESTADO_LABELS = {"DECLARADO": "Declarado", "OBSERVADO": "Observado", "ACEPTADO": "Aceptado"}

# Miniatura de la captura del voucher en el reporte de control (caja
# máxima en puntos PDF; se escala manteniendo proporción, nunca se agranda).
VOUCHER_THUMB_MAX_WIDTH = 55
VOUCHER_THUMB_MAX_HEIGHT = 75
# Resolución objetivo al recomprimir (no solo redibujar) la miniatura. Sin
# esto, reportlab incrusta la foto original completa (varios MB, tomada
# con celular) y solo la escala visualmente — el PDF se vuelve enorme y
# lento con más de un puñado de vouchers.
VOUCHER_THUMB_DPI = 150
VOUCHER_THUMB_JPEG_QUALITY = 70
VOUCHER_FETCH_TIMEOUT = 8.0
VOUCHER_FETCH_CONCURRENCY = 12

# Constantes
MAX_FILE_SIZE_MB = 2
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/jpg"]

# --- FUNCIÓN AUXILIAR (Aquí está la magia que faltaba) ---
async def get_patient_from_user(user_id: int, db: AsyncSession) -> models.Patient:
    """Busca el paciente asociado al usuario de forma explícita."""
    query = select(models.Patient).where(models.Patient.user_id == user_id)
    result = await db.execute(query)
    patient = result.scalars().first()
    return patient

# 0. PACIENTE: Leer comprobante con OCR (solo lectura, no crea el aporte)
@router.post("/ocr-preview", response_model=schemas.ContributionOcrPreviewResponse)
async def preview_contribution_ocr(
    comprobante: UploadFile = File(...),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Extrae monto/fecha/hora del comprobante con el mismo motor OCR usado para
    las citas médicas, para precargar el registro de aporte solidario. A
    diferencia de las citas, el monto no se valida contra ningún valor fijo:
    el paciente confirma/edita el monto detectado.
    """
    if comprobante.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de archivo inválido.")

    content = await comprobante.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="El archivo excede los 2MB.")

    try:
        result = extract_receipt_data(content, comprobante.content_type)
    except Exception as e:
        print(f"Error OCR (aportes): {e}")
        raise HTTPException(status_code=500, detail="No se pudo leer el comprobante. Ingrese el monto manualmente.")

    return {"monto": result.get("monto"), "fecha": result.get("fecha"), "hora": result.get("hora")}


# 1. PACIENTE: Subir aporte (Estado: DECLARADO)
@router.post("/me", response_model=schemas.ContributionResponse, status_code=status.HTTP_201_CREATED)
async def create_my_contribution(
    monto: float = Form(..., gt=0),
    periodo: str = Form(..., regex=r"^\d{4}-\d{2}$"),
    fecha_pago: date = Form(...),
    # NOTA: Se eliminó 'observacion' porque no existe en la BD
    comprobante: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    # Usamos la función auxiliar definida arriba
    patient = await get_patient_from_user(current_user.id, db)
    
    if not patient:
        raise HTTPException(status_code=400, detail="Usuario sin ficha de paciente asociada.")
    
    patient_id = patient.id
    if patient.monto_aporte_comprometido is not None:
        committed_amount = float(patient.monto_aporte_comprometido)
        if round(monto, 2) != round(committed_amount, 2):
            raise HTTPException(
                status_code=400,
                detail=f"El voucher debe coincidir con su aporte comprometido de Bs. {committed_amount:.2f}.",
            )

    existing_query = select(models.MonthlyContribution).where(
        models.MonthlyContribution.patient_id == patient_id,
        models.MonthlyContribution.periodo == periodo,
    )
    existing_contribution = (await db.execute(existing_query)).scalars().first()
    if existing_contribution and existing_contribution.estado == "ACEPTADO":
        raise HTTPException(status_code=400, detail=f"El aporte del periodo {periodo} ya fue validado y no se puede reemplazar.")

    # --- Lógica de Archivos ---
    if comprobante.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de archivo inválido.")
    
    content = await comprobante.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="El archivo excede los 2MB.")
    
    await comprobante.seek(0)
    
    ext = comprobante.filename.split(".")[-1]
    unique_name = f"pacientes/{patient_id}/aportes/{periodo}/voucher_{uuid.uuid4().hex[:8]}.{ext}"
    
    try:
        public_url = upload_file_to_firebase(content, unique_name, comprobante.content_type)
    except Exception as e:
        print(f"Error Firebase: {e}") 
        raise HTTPException(status_code=500, detail="Error al subir el voucher.")

    # Si ya existe para el periodo (DECLARADO/OBSERVADO), se reemplaza voucher y vuelve a DECLARADO.
    if existing_contribution:
        existing_contribution.fecha_pago = fecha_pago
        existing_contribution.monto = monto
        existing_contribution.url_comprobante = public_url
        existing_contribution.estado = "DECLARADO"
        existing_contribution.observacion_admin = None
        db.add(existing_contribution)
        await db.commit()
        await db.refresh(existing_contribution)
        return existing_contribution

    new_contribution = models.MonthlyContribution(
        patient_id=patient_id,
        periodo=periodo,
        fecha_pago=fecha_pago,
        monto=monto,
        url_comprobante=public_url,
        estado="DECLARADO"
    )
    db.add(new_contribution)
    await db.commit()
    await db.refresh(new_contribution)
    return new_contribution

# 1.b ADMIN: Registrar un aporte que el beneficiario pagó pero nunca declaró
# en la app. Dos casos:
#   - VOUCHER: pagó por QR/transferencia y trae un comprobante físico/digital
#     que el staff sube en su nombre.
#   - EFECTIVO: gente del área rural que paga en efectivo directamente a la
#     doctora en campo — no existe ningún voucher que subir.
# Queda directamente ACEPTADO porque el propio SUPER_ADMIN lo está
# verificando al registrarlo — no pasa de nuevo por el flujo de revisión.
@router.post(
    "/{patient_id}",
    response_model=schemas.ContributionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contribution_admin(
    patient_id: int,
    monto: float = Form(..., gt=0),
    periodo: str = Form(..., regex=r"^\d{4}-\d{2}$"),
    fecha_pago: date = Form(...),
    metodo_pago: Literal["VOUCHER", "EFECTIVO"] = Form("VOUCHER"),
    comprobante: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_super_user),
):
    patient = await db.get(models.Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado.")

    if metodo_pago == "VOUCHER" and comprobante is None:
        raise HTTPException(status_code=400, detail="Debe adjuntar el comprobante para un aporte por voucher/QR.")

    if patient.monto_aporte_comprometido is not None:
        committed_amount = float(patient.monto_aporte_comprometido)
        if round(monto, 2) != round(committed_amount, 2):
            raise HTTPException(
                status_code=400,
                detail=f"El voucher debe coincidir con su aporte comprometido de Bs. {committed_amount:.2f}.",
            )

    existing_query = select(models.MonthlyContribution).where(
        models.MonthlyContribution.patient_id == patient_id,
        models.MonthlyContribution.periodo == periodo,
    )
    existing_contribution = (await db.execute(existing_query)).scalars().first()
    if existing_contribution and existing_contribution.estado == "ACEPTADO":
        raise HTTPException(status_code=400, detail=f"El aporte del periodo {periodo} ya fue validado y no se puede reemplazar.")

    public_url = None
    if metodo_pago == "VOUCHER":
        if comprobante.content_type not in ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail="Tipo de archivo inválido.")

        content = await comprobante.read()
        if len(content) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=400, detail="El archivo excede los 2MB.")

        ext = comprobante.filename.split(".")[-1]
        unique_name = f"pacientes/{patient_id}/aportes/{periodo}/voucher_{uuid.uuid4().hex[:8]}.{ext}"

        try:
            public_url = upload_file_to_firebase(content, unique_name, comprobante.content_type)
        except Exception as e:
            print(f"Error Firebase: {e}")
            raise HTTPException(status_code=500, detail="Error al subir el voucher.")

    nota = (
        f"Aporte en efectivo registrado manualmente por {current_user.email} "
        "(pagado en campo, sin comprobante digital)."
        if metodo_pago == "EFECTIVO"
        else f"Registrado manualmente por {current_user.email} (beneficiario no lo declaró en la app)."
    )

    if existing_contribution:
        existing_contribution.fecha_pago = fecha_pago
        existing_contribution.monto = monto
        existing_contribution.url_comprobante = public_url
        existing_contribution.metodo_pago = metodo_pago
        existing_contribution.estado = "ACEPTADO"
        existing_contribution.observacion_admin = nota
        db.add(existing_contribution)
        await db.commit()
        await db.refresh(existing_contribution)
        return existing_contribution

    new_contribution = models.MonthlyContribution(
        patient_id=patient_id,
        periodo=periodo,
        fecha_pago=fecha_pago,
        monto=monto,
        url_comprobante=public_url,
        metodo_pago=metodo_pago,
        estado="ACEPTADO",
        observacion_admin=nota,
    )
    db.add(new_contribution)
    await db.commit()
    await db.refresh(new_contribution)
    return new_contribution


# 2. VER HISTORIAL
@router.get("/me", response_model=List[schemas.ContributionResponse])
async def read_my_contributions(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    patient = await get_patient_from_user(current_user.id, db)

    if not patient: 
        raise HTTPException(status_code=400, detail="Sin ficha de paciente.")
    
    query = select(models.MonthlyContribution).where(
        models.MonthlyContribution.patient_id == patient.id
    ).order_by(desc(models.MonthlyContribution.periodo))
    
    result = await db.execute(query)
    return result.scalars().all()

async def _fetch_contributions_for_review(
    db: AsyncSession, estado: Optional[str], patient_id: Optional[int] = None, periodo: Optional[str] = None
) -> List[schemas.ContributionReviewResponse]:
    query = (
        select(models.MonthlyContribution, models.Patient)
        .join(models.Patient, models.Patient.id == models.MonthlyContribution.patient_id)
        .order_by(
            desc(models.MonthlyContribution.created_at),
            desc(models.MonthlyContribution.periodo),
        )
    )
    if estado:
        query = query.where(models.MonthlyContribution.estado == estado)
    if patient_id:
        query = query.where(models.MonthlyContribution.patient_id == patient_id)
    if periodo:
        query = query.where(models.MonthlyContribution.periodo == periodo)

    result = await db.execute(query)
    rows = result.all()
    return [
        schemas.ContributionReviewResponse(
            id=contrib.id,
            patient_id=patient.id,
            patient_nombre=f"{patient.nombres} {patient.ap_paterno} {patient.ap_materno or ''}".strip(),
            patient_ci=patient.ci,
            periodo=contrib.periodo,
            fecha_pago=contrib.fecha_pago,
            monto=float(contrib.monto),
            estado=contrib.estado,
            metodo_pago=contrib.metodo_pago,
            observacion_admin=contrib.observacion_admin,
            url_comprobante=contrib.url_comprobante,
            created_at=contrib.created_at,
            updated_at=contrib.updated_at,
        )
        for contrib, patient in rows
    ]


@router.get("/review", response_model=List[schemas.ContributionReviewResponse])
async def read_contributions_for_review(
    estado: Optional[Literal["DECLARADO", "OBSERVADO", "ACEPTADO"]] = None,
    periodo: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    if current_user.role not in ["SUPER_ADMIN", "REGISTRADOR"]:
        raise HTTPException(status_code=403, detail="No tiene permisos para revisar aportes.")

    return await _fetch_contributions_for_review(db, estado, periodo=periodo)


@router.get("/patient/{patient_id}", response_model=List[schemas.ContributionReviewResponse])
async def read_contributions_for_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Historial completo de aportes de un beneficiario específico (todos los
    periodos y estados), para cuando hay que verificar/certificar si
    realmente subió su voucher de un mes puntual — sin tener que buscarlo
    en la lista general de revisión.
    """
    if current_user.role not in ["SUPER_ADMIN", "REGISTRADOR"]:
        raise HTTPException(status_code=403, detail="No tiene permisos para revisar aportes.")

    patient = await db.get(models.Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado.")

    return await _fetch_contributions_for_review(db, estado=None, patient_id=patient_id)


@router.get("/review/export.pdf")
async def export_contributions_report_pdf(
    estado: Optional[Literal["DECLARADO", "OBSERVADO", "ACEPTADO"]] = None,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """Reporte membretado (logo + nombre de la Fundación) de vouchers de aporte,
    con nombre del beneficiario, fecha de pago y estado, respetando el mismo
    filtro por estado que la vista de revisión."""
    if current_user.role not in ["SUPER_ADMIN", "REGISTRADOR"]:
        raise HTTPException(status_code=403, detail="No tiene permisos para revisar aportes.")

    items = await _fetch_contributions_for_review(db, estado)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=48, leftMargin=48, topMargin=48, bottomMargin=48,
    )
    styles = getSampleStyleSheet()
    style_org = ParagraphStyle(
        "OrgStyle", parent=styles["Normal"], fontSize=15,
        leading=18, fontName="Helvetica-Bold", textColor=colors.HexColor("#0F3D1E"),
    )
    style_subtitle = ParagraphStyle(
        "SubtitleStyle", parent=styles["Normal"], fontSize=9,
        leading=12, textColor=colors.HexColor("#6B7280"),
    )
    style_title = ParagraphStyle(
        "TitleStyle", parent=styles["Normal"], fontSize=13,
        leading=16, alignment=TA_CENTER, spaceAfter=4, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0F3D1E"),
    )
    style_meta = ParagraphStyle(
        "MetaStyle", parent=styles["Normal"], fontSize=9,
        leading=12, alignment=TA_CENTER, textColor=colors.HexColor("#6B7280"), spaceAfter=16,
    )

    header_cells = [
        [
            Image(str(LOGO_PATH), width=46, height=46) if LOGO_PATH.exists() else "",
            [
                Paragraph("Fundación V.I.D.A. Plena", style_org),
                Paragraph("Comprometidos con la salud y el bienestar.", style_subtitle),
            ],
        ]
    ]
    header_table = Table(header_cells, colWidths=[54, 420])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
    ]))

    estado_label = ESTADO_LABELS.get(estado, "Todos los estados")
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")

    METODO_LABELS = {"VOUCHER": "Voucher/QR", "EFECTIVO": "Efectivo"}
    table_data = [["Nombre del beneficiario", "C.I.", "Periodo", "Fecha de pago", "Monto (Bs.)", "Método", "Estado"]]
    for item in items:
        table_data.append([
            Paragraph(item.patient_nombre, styles["Normal"]),
            item.patient_ci or "Sin CI",
            item.periodo,
            item.fecha_pago.strftime("%d/%m/%Y"),
            f"{item.monto:.2f}",
            METODO_LABELS.get(item.metodo_pago, item.metodo_pago),
            ESTADO_LABELS.get(item.estado, item.estado),
        ])

    report_table = Table(
        table_data,
        colWidths=[130, 60, 50, 70, 55, 60, 55],
        repeatRows=1,
    )
    report_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F3D1E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#E9F5EC")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    story = [
        header_table,
        Spacer(1, 14),
        Paragraph("Reporte de Vouchers de Aporte", style_title),
        Paragraph(f"Filtro: {estado_label} &nbsp;|&nbsp; Generado: {generated_at} &nbsp;|&nbsp; Total: {len(items)}", style_meta),
        report_table if items else Paragraph("No hay vouchers para el filtro seleccionado.", styles["Normal"]),
    ]

    doc.build(story)
    buffer.seek(0)
    filename = f"Reporte_Vouchers_{(estado or 'TODOS')}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        buffer, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _fetch_voucher_thumbnail(http_client: httpx.AsyncClient, semaphore: asyncio.Semaphore, url: Optional[str]):
    """
    Descarga la captura de un comprobante y la prepara como miniatura para
    el reporte. Devuelve None si no hay URL, si es un PDF (no es una imagen
    que se pueda incrustar como miniatura), o si falla la descarga/lectura
    — en cualquiera de esos casos el reporte cae a un texto de reemplazo en
    vez de romper la generación completa del PDF.
    """
    if not url:
        return None
    async with semaphore:
        try:
            resp = await http_client.get(url, timeout=VOUCHER_FETCH_TIMEOUT)
            resp.raise_for_status()
        except Exception:
            return None

    content_type = resp.headers.get("content-type", "")
    if "pdf" in content_type.lower():
        return None

    try:
        pil_img = PILImage.open(io.BytesIO(resp.content))
        pil_img.load()
        width, height = pil_img.size
        if not width or not height:
            return None
        scale = min(VOUCHER_THUMB_MAX_WIDTH / width, VOUCHER_THUMB_MAX_HEIGHT / height, 1.0)
        draw_width, draw_height = width * scale, height * scale

        # Reescalar y RECOMPRIMIR de verdad a la resolución de impresión
        # objetivo — pasarle a reportlab el ancho/alto de dibujo NO reduce
        # el peso incrustado: la foto original (a veces varios MB, tomada
        # con celular) quedaría intacta dentro del PDF, solo escalada
        # visualmente. Con decenas de vouchers eso vuelve el PDF enorme.
        if pil_img.mode not in ("RGB", "L"):
            pil_img = pil_img.convert("RGB")
        target_px = (
            max(round(draw_width * VOUCHER_THUMB_DPI / 72), 1),
            max(round(draw_height * VOUCHER_THUMB_DPI / 72), 1),
        )
        pil_img.thumbnail(target_px, PILImage.LANCZOS)

        recompressed = io.BytesIO()
        pil_img.save(recompressed, format="JPEG", quality=VOUCHER_THUMB_JPEG_QUALITY)
        recompressed.seek(0)

        # reportlab's Image acepta un objeto tipo-archivo (con .read()) — un
        # ImageReader ya "consumido" no sirve como filename posicional aquí.
        return Image(recompressed, width=draw_width, height=draw_height)
    except Exception:
        return None


@router.get("/vouchers/export.pdf")
async def export_vouchers_control_report_pdf(
    periodo: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Reporte general de control de vouchers (Reportes > Control de Vouchers):
    a diferencia del historial de un beneficiario puntual (en su ficha) o
    del reporte de vouchers sin imagen (/review/export.pdf, usado en
    Revisión de Aportes), este incrusta la captura de cada comprobante
    junto al nombre del beneficiario y la fecha de pago, para TODOS los
    beneficiarios. `periodo` (YYYY-MM) es opcional — sin él trae todos los
    periodos, lo que puede ser un PDF grande/lento si hay muchos vouchers.
    """
    if current_user.role not in ["SUPER_ADMIN", "REGISTRADOR"]:
        raise HTTPException(status_code=403, detail="No tiene permisos para ver este reporte.")

    items = await _fetch_contributions_for_review(db, estado=None, periodo=periodo)

    semaphore = asyncio.Semaphore(VOUCHER_FETCH_CONCURRENCY)
    async with httpx.AsyncClient() as http_client:
        thumbnails = await asyncio.gather(*[
            _fetch_voucher_thumbnail(http_client, semaphore, item.url_comprobante) for item in items
        ])

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=48, leftMargin=48, topMargin=48, bottomMargin=48,
    )
    styles = getSampleStyleSheet()
    style_org = ParagraphStyle(
        "OrgStyle", parent=styles["Normal"], fontSize=15,
        leading=18, fontName="Helvetica-Bold", textColor=colors.HexColor("#0F3D1E"),
    )
    style_subtitle = ParagraphStyle(
        "SubtitleStyle", parent=styles["Normal"], fontSize=9,
        leading=12, textColor=colors.HexColor("#6B7280"),
    )
    style_title = ParagraphStyle(
        "TitleStyle", parent=styles["Normal"], fontSize=13,
        leading=16, alignment=TA_CENTER, spaceAfter=4, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0F3D1E"),
    )
    style_meta = ParagraphStyle(
        "MetaStyle", parent=styles["Normal"], fontSize=9,
        leading=12, alignment=TA_CENTER, textColor=colors.HexColor("#6B7280"), spaceAfter=16,
    )
    style_cell = ParagraphStyle("CellStyle", parent=styles["Normal"], fontSize=9, leading=11)
    style_link = ParagraphStyle(
        "LinkStyle", parent=styles["Normal"], fontSize=8,
        leading=10, textColor=colors.HexColor("#0F3D1E"),
    )

    header_cells = [
        [
            Image(str(LOGO_PATH), width=46, height=46) if LOGO_PATH.exists() else "",
            [
                Paragraph("Fundación V.I.D.A. Plena", style_org),
                Paragraph("Comprometidos con la salud y el bienestar.", style_subtitle),
            ],
        ]
    ]
    header_table = Table(header_cells, colWidths=[54, 420])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
    ]))

    periodo_label = periodo or "Todos los periodos"
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")

    table_data = [["Captura", "Beneficiario", "C.I.", "Fecha de pago"]]
    for item, thumb in zip(items, thumbnails):
        if thumb is not None:
            captura_cell = thumb
        elif item.url_comprobante:
            captura_cell = Paragraph(f'<link href="{item.url_comprobante}">Ver comprobante (PDF)</link>', style_link)
        else:
            captura_cell = Paragraph("Sin comprobante", style_link)
        table_data.append([
            captura_cell,
            Paragraph(item.patient_nombre, style_cell),
            item.patient_ci or "Sin CI",
            item.fecha_pago.strftime("%d/%m/%Y"),
        ])

    report_table = Table(
        table_data,
        colWidths=[65, 200, 65, 80],
        repeatRows=1,
    )
    report_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F3D1E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#E9F5EC")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    story = [
        header_table,
        Spacer(1, 14),
        Paragraph("Control de Vouchers", style_title),
        Paragraph(f"Periodo: {periodo_label} &nbsp;|&nbsp; Generado: {generated_at} &nbsp;|&nbsp; Total: {len(items)}", style_meta),
        report_table if items else Paragraph("No hay vouchers para el filtro seleccionado.", styles["Normal"]),
    ]

    doc.build(story)
    buffer.seek(0)
    filename = f"Control_Vouchers_{(periodo or 'TODOS')}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        buffer, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

# 3. ADMIN VALIDAR
class ContributionValidationSchema(schemas.BaseModel):
    estado: Literal["ACEPTADO", "OBSERVADO"] 
    observacion_admin: Optional[str] = None

@router.put("/{contribution_id}/validate", response_model=schemas.ContributionResponse)
async def validate_contribution(
    contribution_id: int,
    validation_in: ContributionValidationSchema,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    if current_user.role not in ["SUPER_ADMIN", "REGISTRADOR"]:
        raise HTTPException(status_code=403, detail="No tiene permisos para validar aportes.")

    contribution = await db.get(models.MonthlyContribution, contribution_id)
    if not contribution: 
        raise HTTPException(status_code=404, detail="Aporte no encontrado")

    if validation_in.estado == "OBSERVADO":
        if not (validation_in.observacion_admin or "").strip():
            raise HTTPException(status_code=400, detail="Debe registrar un motivo al observar el aporte.")
        contribution.observacion_admin = validation_in.observacion_admin.strip()
    else:
        contribution.observacion_admin = None

    contribution.estado = validation_in.estado
            
    await db.commit()
    await db.refresh(contribution)
    return contribution