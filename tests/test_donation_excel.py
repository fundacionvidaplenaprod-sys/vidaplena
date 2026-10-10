"""Lectura del Excel de la donación (pura, sin base de datos)."""
import io
from datetime import date, datetime

import pytest
from openpyxl import Workbook

from app.core.donation_excel import DonationExcelError, parse_donation_excel

HEADER = [
    "CANTIDAD",
    "PRODUCTO",
    "TIPO DE INSULINA",
    "PRESENTACIÓN",
    "CONCENTRACIÓN",
    "FECHA VENCIMIENTO",
    "NRO LOTE",
]


def _norm(tipo):
    """Catálogo mínimo para las pruebas (el real vive en endpoints/donations.py)."""
    t = (tipo or "").lower()
    for nombre, claves in {
        "Glargina": ("glargina", "lantus"),
        "Aspart": ("aspart", "novorapid"),
        "Lispro": ("lispro", "humalog"),
    }.items():
        if any(c in t for c in claves):
            return nombre
    return None


def _xlsx(rows, header=HEADER):
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_reads_valid_rows_and_computes_ui_per_package():
    content = _xlsx(
        [
            [10, "Lantus SoloStar 3 ml", "Glargina", "3 ml", "U100", datetime(2027, 1, 1), "L1"],
            [4, "Toujeo SoloStar 1.5 ml", "Glargina", "1.5 ml", "U300", date(2027, 6, 30), "L2"],
            [5, "NovoRapid Dstfl 10 ml", "Aspart", "10 ml", "U100", "2028-02-01", None],
        ]
    )
    parsed = parse_donation_excel(content, _norm)
    assert parsed.errors == [] and parsed.total_rows == 3
    lantus, toujeo, vial = parsed.rows
    assert lantus.ui_per_unit == 300 and lantus.fecha_venc == date(2027, 1, 1) and lantus.lote == "L1"
    assert toujeo.ui_per_unit == 450 and toujeo.insulina == "Glargina"
    assert vial.ui_per_unit == 1000 and vial.lote is None and vial.fecha_venc == date(2028, 2, 1)
    assert lantus.row_number == 2


def test_header_ignores_case_accents_and_extra_columns():
    content = _xlsx(
        [[3, "Humalog", "Lispro", "3 ml", "U100", "x"]],
        header=["cantidad", "Producto", "tipo de insulina", "presentacion", "concentracion", "OBSERVACIONES"],
    )
    parsed = parse_donation_excel(content, _norm)
    assert len(parsed.rows) == 1 and parsed.rows[0].fecha_venc is None and parsed.rows[0].lote is None


def test_optional_columns_may_be_missing():
    content = _xlsx(
        [[3, "Humalog", "Lispro", "3 ml", "U100"]],
        header=["CANTIDAD", "PRODUCTO", "TIPO DE INSULINA", "PRESENTACIÓN", "CONCENTRACIÓN"],
    )
    assert len(parse_donation_excel(content, _norm).rows) == 1


def test_a_bad_row_is_reported_but_does_not_stop_the_others():
    content = _xlsx(
        [
            [10, "Lantus", "Glargina", "3 ml", "U100", None, None],  # ok
            [0, "Lantus", "Glargina", "3 ml", "U100", None, None],  # cantidad 0
            [2.5, "Lantus", "Glargina", "3 ml", "U100", None, None],  # no entera
            [3, "Producto raro", "Zumo", "3 ml", "U100", None, None],  # no está en el catálogo
            [3, "Lantus", "Glargina", "tres", "U100", None, None],  # sin ml
            [3, "Lantus", "Glargina", "3 ml", "alta", None, None],  # concentración inválida
            [3, "Lantus", "Glargina", "3 ml", "U100", "mañana", None],  # fecha inválida
            [None, None, None, None, None, None, None],  # fila vacía: se ignora
        ]
    )
    parsed = parse_donation_excel(content, _norm)
    assert len(parsed.rows) == 1
    assert [e.row_number for e in parsed.errors] == [3, 4, 5, 6, 7, 8]
    assert parsed.total_rows == 7  # la vacía no cuenta
    assert "catálogo" in parsed.errors[2].message


def test_insulin_falls_back_to_the_product_name():
    content = _xlsx([[3, "Humalog KwikPen", "", "3 ml", "U100", None, None]])
    assert parse_donation_excel(content, _norm).rows[0].insulina == "Lispro"


def test_missing_required_columns_is_an_error():
    content = _xlsx([[3, "Humalog"]], header=["CANTIDAD", "PRODUCTO"])
    with pytest.raises(DonationExcelError, match="TIPO"):
        parse_donation_excel(content, _norm)


def test_a_file_that_is_not_excel_is_an_error():
    with pytest.raises(DonationExcelError, match="Excel"):
        parse_donation_excel(b"esto no es un xlsx", _norm)


def test_missing_openpyxl_gives_a_clear_error_instead_of_breaking(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "openpyxl", None)  # simula que el servidor no la tiene
    with pytest.raises(DonationExcelError, match="openpyxl"):
        parse_donation_excel(b"PK\x03\x04", _norm)
