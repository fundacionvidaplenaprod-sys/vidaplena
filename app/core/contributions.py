"""
Helper compartido para responder "¿este paciente está al día con su aporte
mensual?". Antes vivía duplicado inline solo en el filtro anti-morosos de
`donations.py::calculate_distribution`; ahora también lo usa el router
`departmental` para mostrar el badge de aporte a los responsables
departamentales/coordinador nacional.
"""
from datetime import date
from typing import Optional


def current_periodo(ref_date: Optional[date] = None) -> str:
    """Periodo actual en formato 'YYYY-MM' (el mismo usado en MonthlyContribution.periodo)."""
    d = ref_date or date.today()
    return f"{d.year}-{d.month:02d}"


def is_patient_current_on_contribution(
    patient, periodo: Optional[str] = None, include_exonerados: bool = False
) -> bool:
    """
    True si el paciente tiene un MonthlyContribution ACEPTADO para el
    periodo dado (por defecto, el mes actual).

    `include_exonerados`: si True, un paciente con `exonerado_aporte=True`
    cuenta como al día aunque no tenga ninguna contribución registrada ese
    mes (usado en la vista departamental: un exonerado igual debe recibir
    su insulina). El filtro anti-morosos de `donations.py` NO usa esto —
    mantiene su comportamiento histórico sin cambios.
    """
    if include_exonerados and getattr(patient, "exonerado_aporte", False):
        return True

    periodo = periodo or current_periodo()
    for aporte in (patient.contributions or []):
        if aporte.periodo == periodo and aporte.estado == "ACEPTADO":
            return True
    return False
