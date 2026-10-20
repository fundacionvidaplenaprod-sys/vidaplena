"""
Helper compartido para responder "¿este paciente está al día con su aporte
mensual?". Antes vivía duplicado inline solo en el filtro anti-morosos de
`donations.py::calculate_distribution`; ahora también lo usa el router
`departmental` para mostrar el badge de aporte a los responsables
departamentales/coordinador nacional.
"""
from datetime import date, timedelta
from typing import Optional


def current_periodo(ref_date: Optional[date] = None) -> str:
    """Periodo actual en formato 'YYYY-MM' (el mismo usado en MonthlyContribution.periodo)."""
    d = ref_date or date.today()
    return f"{d.year}-{d.month:02d}"


def normalize_periodo_range(
    periodo: Optional[str] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Rango de periodos (YYYY-MM) a partir de un mes suelto o de un «desde / hasta».

    - `periodo` fija ambos extremos (un solo mes).
    - Si solo viene `desde` o solo `hasta`, el otro extremo queda abierto.
    - Sin ninguno devuelve (None, None): todos los periodos.
    Lanza ValueError si «desde» es posterior a «hasta».
    """
    if periodo:
        return periodo, periodo
    if desde and hasta and desde > hasta:
        raise ValueError("El periodo «desde» no puede ser posterior a «hasta».")
    return desde or None, hasta or None


# Más meses que esto vuelven ilegible la tabla del reporte (una columna por mes).
MAX_MESES_REPORTE = 4


def periodos_en_rango(desde: Optional[str], hasta: Optional[str]) -> list[str]:
    """Los periodos (YYYY-MM) de `desde` a `hasta`, ambos incluidos.

    Lanza ValueError si falta un extremo o si el rango pasa de MAX_MESES_REPORTE meses.
    """
    if not desde or not hasta:
        raise ValueError("Indique los dos extremos del rango: «desde» y «hasta».")
    anio, mes = int(desde[:4]), int(desde[5:7])
    periodos = []
    actual = desde
    while actual <= hasta:
        periodos.append(actual)
        if len(periodos) > MAX_MESES_REPORTE:
            raise ValueError(f"El rango puede abarcar como máximo {MAX_MESES_REPORTE} meses.")
        mes += 1
        if mes > 12:
            anio, mes = anio + 1, 1
        actual = f"{anio}-{mes:02d}"
    return periodos


def periodo_anterior(ref_date: Optional[date] = None) -> str:
    """Periodo del mes anterior a `ref_date` (por defecto hoy), formato 'YYYY-MM'."""
    d = ref_date or date.today()
    ultimo_dia_mes_anterior = d.replace(day=1) - timedelta(days=1)
    return current_periodo(ultimo_dia_mes_anterior)


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
