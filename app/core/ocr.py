import os
import re
from datetime import date, time
from typing import Optional

from google.cloud import vision
from google.oauth2 import service_account

CREDENTIALS_FILE = "firebase_key.json"

_vision_client: Optional[vision.ImageAnnotatorClient] = None


def _get_vision_client() -> vision.ImageAnnotatorClient:
    """
    Reutiliza las mismas credenciales de la cuenta de servicio de Firebase
    (firebase_key.json) para autenticar contra Cloud Vision API. Requiere que
    la API "Cloud Vision API" esté habilitada en ese mismo proyecto de GCP.
    """
    global _vision_client
    if _vision_client is None:
        if not os.path.exists(CREDENTIALS_FILE):
            raise RuntimeError(f"No se encontró {CREDENTIALS_FILE} para autenticar con Cloud Vision API.")
        credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE)
        _vision_client = vision.ImageAnnotatorClient(credentials=credentials)
    return _vision_client


# --- Patrones heurísticos (v1) para comprobantes bancarios bolivianos ---
# NOTA: sin capturas reales de los comprobantes que suben los donantes, estos
# patrones son un punto de partida y probablemente necesiten ajuste una vez
# se observen casos reales en producción.
_MONTO_PATTERNS = [
    re.compile(r"Bs\.?\s*([0-9]{1,3}(?:[.,][0-9]{2})?)", re.IGNORECASE),
    re.compile(r"\b([0-9]{1,3}[.,][0-9]{2})\b"),
    re.compile(r"\bMonto[:\s]+([0-9]{1,3}(?:[.,][0-9]{2})?)", re.IGNORECASE),
]

_FECHA_PATTERNS = [
    re.compile(r"\b(\d{2})[/\-](\d{2})[/\-](\d{4})\b"),  # dd/mm/aaaa
    re.compile(r"\b(\d{4})[/\-](\d{2})[/\-](\d{2})\b"),  # aaaa-mm-dd
]

_HORA_PATTERNS = [
    re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?\s*(AM|PM|am|pm)?\b"),
]


def _parse_monto(text: str) -> Optional[float]:
    for pattern in _MONTO_PATTERNS:
        match = pattern.search(text)
        if match:
            raw = match.group(1).replace(",", ".")
            try:
                return float(raw)
            except ValueError:
                continue
    return None


def _parse_fecha(text: str) -> Optional[date]:
    for pattern in _FECHA_PATTERNS:
        match = pattern.search(text)
        if match:
            groups = match.groups()
            try:
                if len(groups[0]) == 4:  # aaaa-mm-dd
                    return date(int(groups[0]), int(groups[1]), int(groups[2]))
                else:  # dd/mm/aaaa
                    return date(int(groups[2]), int(groups[1]), int(groups[0]))
            except ValueError:
                continue
    return None


def _parse_hora(text: str) -> Optional[time]:
    for pattern in _HORA_PATTERNS:
        for match in pattern.finditer(text):
            hour = int(match.group(1))
            minute = int(match.group(2))
            meridiem = (match.group(3) or "").upper()
            if meridiem == "PM" and hour != 12:
                hour += 12
            elif meridiem == "AM" and hour == 12:
                hour = 0
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return time(hour, minute)
    return None


def _detect_text(file_bytes: bytes, content_type: str) -> str:
    client = _get_vision_client()

    if content_type == "application/pdf":
        # text_detection no acepta PDF; se usa batch_annotate_files (soporta
        # PDF/TIFF inline, hasta 5 páginas por request síncrono).
        input_config = vision.InputConfig(content=file_bytes, mime_type="application/pdf")
        feature = vision.Feature(type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION)
        request = vision.AnnotateFileRequest(
            input_config=input_config, features=[feature], pages=[1]
        )
        response = client.batch_annotate_files(requests=[request])
        file_response = response.responses[0]
        if not file_response.responses:
            return ""
        page_response = file_response.responses[0]
        if page_response.error.message:
            raise RuntimeError(f"Error de Cloud Vision API: {page_response.error.message}")
        return page_response.full_text_annotation.text if page_response.full_text_annotation else ""

    image = vision.Image(content=file_bytes)
    response = client.text_detection(image=image)
    if response.error.message:
        raise RuntimeError(f"Error de Cloud Vision API: {response.error.message}")
    return response.full_text_annotation.text if response.full_text_annotation else ""


def extract_receipt_data(file_bytes: bytes, content_type: str = "image/jpeg") -> dict:
    """
    Ejecuta OCR sobre la imagen/PDF del comprobante de donación y extrae
    monto/fecha/hora mediante heurísticas de texto. Devuelve también el
    texto crudo detectado para depuración.
    """
    raw_text = _detect_text(file_bytes, content_type)

    return {
        "monto": _parse_monto(raw_text),
        "fecha": _parse_fecha(raw_text),
        "hora": _parse_hora(raw_text),
        "raw_text": raw_text,
    }
