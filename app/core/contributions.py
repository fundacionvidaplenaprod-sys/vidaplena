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

    `include_exonerados`: si True, un paciente exonerado cuenta como al día
    aunque no tenga ninguna contribución registrada ese mes (usado en la
    vista departamental: un exonerado igual debe recibir su insulina). El
    filtro anti-morosos de `donations.py` NO usa esto — mantiene su
    comportamiento histórico sin cambios.

    Cuentan las dos exoneraciones, que tienen causas distintas y conviven:
    `exonerado_aporte` (vulnerabilidad, la decide la evaluación
    socioeconómica) y `exonerado_por_cargo` (incentivo al responsable
    departamental, la autoriza un SUPER_ADMIN). Ver `esta_exonerado`.
    """
    if include_exonerados and esta_exonerado(patient):
        return True

    periodo = periodo or current_periodo()
    for aporte in (patient.contributions or []):
        if aporte.periodo == periodo and aporte.estado == "ACEPTADO":
            return True
    return False


def esta_exonerado(patient) -> bool:
    """
    True si el paciente está exonerado del aporte mensual por cualquiera de
    las dos vías. Punto único de lectura: quien necesite distinguir el motivo
    debe mirar las banderas por separado (los reportes lo hacen, porque la
    fundación necesita justificar ambas poblaciones aparte).
    """
    return bool(
        getattr(patient, "exonerado_aporte", False)
        or getattr(patient, "exonerado_por_cargo", False)
    )
