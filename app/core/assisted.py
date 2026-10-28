"""Datos del Registro Asistido por Situación Excepcional que usan los cálculos de insulina."""
from __future__ import annotations

from datetime import date
from typing import Optional

# Edad representativa de cada rango, cuando de la persona solo se conoce el rango de edad.
EDAD_DEL_RANGO = {"0-11": 5, "12-17": 15, "18-59": 40, "60+": 65}


def assisted_age(reg) -> Optional[int]:
    """
    Edad de una persona asistida. Sus datos son opcionales, así que se toma la fecha de nacimiento si
    está; si no, la edad aproximada; si tampoco, la de su rango de edad. None si no se sabe nada.
    """
    if getattr(reg, "fecha_nacimiento", None):
        hoy = date.today()
        nac = reg.fecha_nacimiento
        return hoy.year - nac.year - ((hoy.month, hoy.day) < (nac.month, nac.day))
    if getattr(reg, "edad_aproximada", None) is not None:
        return reg.edad_aproximada
    return EDAD_DEL_RANGO.get(getattr(reg, "rango_edad", None))
