"""Reporte de solicitud de cantidades requeridas de donación.

Responde «¿cuánta insulina hay que pedir para 60 días de tratamiento?» sumando la
dosis diaria de cada beneficiario por tipo de insulina. Cuenta a todos los
beneficiarios registrados (estén o no al día con su aporte y les falten o no
documentos), por eso no filtra por aporte ni por documentos.

Las personas del Registro Asistido por Situación Excepcional también son beneficiarias: las que están
activas suman su insulina, su edad y su tipo de diabetes, igual que las demás. Como sus datos son
opcionales, la edad se toma de la fecha de nacimiento, si no de la edad aproximada y, en último
caso, del rango de edad (con una edad representativa del rango).
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

from app.core.assisted import assisted_age
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

# Viales de 3 ml por concentración: la solicitud indica cuántos se necesitan de cada una. Un vial de 3 ml
# U100 trae 300 UI; U200, 600 UI; U300, 900 UI. El vial de 10 ml solo se calcula en U100 (1.000 UI).
VIAL_ML = 3
CONCENTRACIONES_UI_ML = (100, 200, 300)
VIAL_10ML_ML = 10
CONCENTRACION_10ML_UI_ML = 100


# Presentaciones del reparto por porcentajes y las UI que trae un envase de cada una.
PRESENTACIONES_UI = {"3ml_U100": 300, "3ml_U200": 600, "3ml_U300": 900, "10ml_U100": 1000}
REPARTO_TOLERANCIA = 0.05  # puntos porcentuales: lo que los porcentajes pueden desviarse de 100


def validar_reparto(reparto: dict) -> dict:
    """Valida un reparto por porcentajes (presentación -> %): las cuatro presentaciones, de 0 a 100 y sumando 100."""
    if set(reparto) != set(PRESENTACIONES_UI):
        raise ValueError("El reparto debe indicar el porcentaje de las cuatro presentaciones.")
    for presentacion, pct in reparto.items():
        if not 0 <= pct <= 100:
            raise ValueError(f"El porcentaje de {presentacion} debe estar entre 0 y 100.")
    total = sum(reparto.values())
    if abs(total - 100) > REPARTO_TOLERANCIA:
        raise ValueError(f"Los porcentajes deben sumar 100 % (suman {total:g} %).")
    return {presentacion: float(pct) for presentacion, pct in reparto.items()}


def plan_por_presentacion(ui: float, reparto: dict) -> dict:
    """
    Reparte `ui` entre las presentaciones según los porcentajes y calcula los envases de cada una,
    redondeando hacia arriba (por eso el total pedido puede pasar un poco de las UI requeridas).
    """
    plan = {}
    for presentacion, pct in reparto.items():
        ui_parte = round(ui * pct / 100, 2)
        plan[presentacion] = {
            "pct": pct,
            "ui": ui_parte,
            "envases": math.ceil(ui_parte / PRESENTACIONES_UI[presentacion] - 1e-9),
        }
    return plan


def viales_10ml(ui: float) -> dict:
    """Viales de 10 ml U100 (1.000 UI cada uno) necesarios para `ui` unidades, redondeando hacia arriba."""
    ui = round(ui, 2)
    return {f"U{CONCENTRACION_10ML_UI_ML}": math.ceil(ui / (VIAL_10ML_ML * CONCENTRACION_10ML_UI_ML) - 1e-9)}


def viales_3ml(ui: float) -> dict:
    """Viales de 3 ml necesarios para `ui` unidades, por concentración, redondeando siempre hacia arriba."""
    ui = round(ui, 2)
    return {
        f"U{concentracion}": math.ceil(ui / (VIAL_ML * concentracion) - 1e-9)
        for concentracion in CONCENTRACIONES_UI_ML
    }


def _age(patient) -> Optional[int]:
    return patient.edad_calc if getattr(patient, "fecha_nac", None) else None


def _ordinary_row(patient):
    tipo = patient.medical.tipo_diabetes if patient.medical else None
    tratamientos = [
        (tx.nombre, float(getattr(tx, "dosis_diaria", 0) or 0))
        for tx in patient.treatments
        if getattr(tx, "tipo", "INSULINA") == "INSULINA"
    ]
    return ("P", patient.id), _age(patient), tipo, tratamientos


def _assisted_row(reg):
    tratamientos = [(t.insulina, float(t.dosis_diaria or 0)) for t in reg.treatments]
    return ("A", reg.id), assisted_age(reg), reg.tipo_diabetes, tratamientos


def _pct(count: int, total: int) -> float:
    return round(count * 100 / total, 1) if total else 0.0


def build_donation_request(
    patients: Iterable, days: int = DISTRIBUTION_DAYS, assisted: Iterable = (), reparto: Optional[dict] = None
) -> dict:
    """Cantidades requeridas por tipo de insulina y perfil de los beneficiarios.

    `assisted`: registros ACTIVOS del Registro Asistido por Situación Excepcional.
    `reparto`: porcentajes por presentación (ver `validar_reparto`); si viene, cada insulina trae además su
    `plan` con las UI y los envases de cada presentación.
    """
    reparto = validar_reparto(reparto) if reparto else None
    rows = [_ordinary_row(p) for p in patients] + [_assisted_row(r) for r in assisted]
    total = len(rows)
    asistidos = sum(1 for key, *_ in rows if key[0] == "A")

    ui_per_insulin: dict[str, float] = {}
    patients_per_insulin: dict[str, set] = {}
    sin_insulina = 0
    menores = adultos = mayores = tipo1 = tipo2 = 0

    for key, age, tipo, tratamientos in rows:
        menores += age is not None and age < MINOR_AGE
        adultos += age is not None and MINOR_AGE <= age <= ADULT_MAX_AGE
        mayores += age is not None and age >= OLDER_ADULT_AGE
        tipo1 += is_type1_diabetes(tipo)

        tiene_dosis = False
        for nombre, daily in tratamientos:
            if daily <= 0:
                continue
            tiene_dosis = True
            insulina = normalize_insulin_name(nombre) or SIN_CLASIFICAR
            ui_per_insulin[insulina] = ui_per_insulin.get(insulina, 0.0) + daily * days
            patients_per_insulin.setdefault(insulina, set()).add(key)
        sin_insulina += not tiene_dosis
        # Tipo 2 «insulino requirente»: el que usa insulina (tiene una dosis diaria registrada).
        tipo2 += is_type2_diabetes(tipo) and tiene_dosis

    insulinas = [
        {
            "insulina": nombre,
            "cantidad_ui": round(ui, 2),
            "viales_3ml": viales_3ml(ui),
            "viales_10ml": viales_10ml(ui),
            **({"plan": plan_por_presentacion(ui, reparto)} if reparto else {}),
            "beneficiarios": len(patients_per_insulin[nombre]),
        }
        # Mayor cantidad primero; «sin clasificar» siempre al final.
        for nombre, ui in sorted(ui_per_insulin.items(), key=lambda kv: (kv[0] == SIN_CLASIFICAR, -kv[1], kv[0]))
    ]
    return {
        "dias": days,
        "estados_considerados": list(DONATION_REQUEST_ESTADOS),
        "total_beneficiarios": total,
        # De ese total, las personas del Registro Asistido por Situación Excepcional.
        "asistidos_incluidos": asistidos,
        "sin_insulina_registrada": sin_insulina,
        "reparto": reparto,
        "insulinas": insulinas,
        "menores_18": {"cantidad": menores, "porcentaje": _pct(menores, total)},
        "entre_18_y_60": {"cantidad": adultos, "porcentaje": _pct(adultos, total)},
        "mayores_61": {"cantidad": mayores, "porcentaje": _pct(mayores, total)},
        "diabeticos_tipo_1": {"cantidad": tipo1, "porcentaje": _pct(tipo1, total)},
        "diabeticos_tipo_2": {"cantidad": tipo2, "porcentaje": _pct(tipo2, total)},
    }
