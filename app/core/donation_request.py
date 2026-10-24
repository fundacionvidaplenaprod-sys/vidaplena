"""Reporte de solicitud de cantidades requeridas de donación.

Responde «¿cuánta insulina hay que pedir para 60 días de tratamiento?» sumando la
dosis diaria de cada beneficiario por tipo de insulina. Cuenta a todos los
beneficiarios registrados (estén o no al día con su aporte y les falten o no
documentos), por eso no filtra por aporte ni por documentos.
"""
from __future__ import annotations

from typing import Iterable, Optional

from app.core.insulin_catalog import normalize_insulin_name
from app.core.insulin_distribution import (
    DISTRIBUTION_DAYS,
    MINOR_AGE,
    is_type1_diabetes,
    is_type2_diabetes,
)

# Se cuentan los mismos estados que el reporte de distribución de insulina.
DONATION_REQUEST_ESTADOS = ("ACTIVO", "PENDIENTE_DOC", "HABILITADO")
# Rangos de edad del reporte: menores de 18, de 18 a 60 y de 61 en adelante.
ADULT_MAX_AGE = 60
OLDER_ADULT_AGE = ADULT_MAX_AGE + 1
SIN_CLASIFICAR = "Otras (sin clasificar)"


def _age(patient) -> Optional[int]:
    return patient.edad_calc if getattr(patient, "fecha_nac", None) else None


def _pct(count: int, total: int) -> float:
    return round(count * 100 / total, 1) if total else 0.0


def build_donation_request(patients: Iterable, days: int = DISTRIBUTION_DAYS) -> dict:
    """Cantidades requeridas por tipo de insulina y perfil de los beneficiarios."""
    patients = list(patients)
    total = len(patients)

    ui_per_insulin: dict[str, float] = {}
    patients_per_insulin: dict[str, set] = {}
    sin_insulina = 0
    menores = adultos = mayores = tipo1 = tipo2 = 0

    for patient in patients:
        age = _age(patient)
        tipo = patient.medical.tipo_diabetes if patient.medical else None
        menores += age is not None and age < MINOR_AGE
        adultos += age is not None and MINOR_AGE <= age <= ADULT_MAX_AGE
        mayores += age is not None and age >= OLDER_ADULT_AGE
        tipo1 += is_type1_diabetes(tipo)

        tiene_dosis = False
        for tx in patient.treatments:
            if getattr(tx, "tipo", "INSULINA") != "INSULINA":
                continue
            daily = float(getattr(tx, "dosis_diaria", 0) or 0)
            if daily <= 0:
                continue
            tiene_dosis = True
            insulina = normalize_insulin_name(tx.nombre) or SIN_CLASIFICAR
            ui_per_insulin[insulina] = ui_per_insulin.get(insulina, 0.0) + daily * days
            patients_per_insulin.setdefault(insulina, set()).add(patient.id)
        sin_insulina += not tiene_dosis
        # Tipo 2 «insulino requirente»: el que usa insulina (tiene una dosis diaria registrada).
        tipo2 += is_type2_diabetes(tipo) and tiene_dosis

    insulinas = [
        {
            "insulina": nombre,
            "cantidad_ui": round(ui, 2),
            "beneficiarios": len(patients_per_insulin[nombre]),
        }
        # Mayor cantidad primero; «sin clasificar» siempre al final.
        for nombre, ui in sorted(ui_per_insulin.items(), key=lambda kv: (kv[0] == SIN_CLASIFICAR, -kv[1], kv[0]))
    ]
    return {
        "dias": days,
        "estados_considerados": list(DONATION_REQUEST_ESTADOS),
        "total_beneficiarios": total,
        "sin_insulina_registrada": sin_insulina,
        "insulinas": insulinas,
        "menores_18": {"cantidad": menores, "porcentaje": _pct(menores, total)},
        "entre_18_y_60": {"cantidad": adultos, "porcentaje": _pct(adultos, total)},
        "mayores_61": {"cantidad": mayores, "porcentaje": _pct(mayores, total)},
        "diabeticos_tipo_1": {"cantidad": tipo1, "porcentaje": _pct(tipo1, total)},
        "diabeticos_tipo_2": {"cantidad": tipo2, "porcentaje": _pct(tipo2, total)},
    }
