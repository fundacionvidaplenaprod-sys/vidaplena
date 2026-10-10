"""Datos y armado de respuestas del reparto de insulina.

Funciones compartidas por el reporte de distribución (`/reports/insulin-distribution`) y por el
reparto global del almacén. Traducen entre la base de datos / los esquemas de la API y el motor
puro de `app/core/insulin_distribution.py`.
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app import models, schemas
from app.core.contributions import current_periodo, is_patient_current_on_contribution
from app.core.insulin_catalog import normalize_insulin_name
from app.core.insulin_distribution import (
    GROUP_LABELS,
    MINOR_AGE,
    PatientInput as InsulinPatientInput,
    is_type1_diabetes,
)


def treatment_daily_units(treatment: models.PatientTreatment) -> float:
    return float(getattr(treatment, "dosis_diaria", 0) or 0)


async def load_distribution_patients(
    db: AsyncSession,
    *,
    estados: Sequence[str],
    require_current_contribution: bool,
) -> Tuple[List[InsulinPatientInput], dict, List[dict]]:
    """Pacientes con insulina en los estados dados, listos para el motor de reparto.

    Devuelve (entradas del motor, datos de cada paciente por id, excluidos con motivo).
    Las dosis van tal como están en la ficha: si trae dos insulinas del mismo grupo, el
    motor decide cuál usar (`resolve_group_choices`) y `group_choice_issues` lo informa.
    Con `require_current_contribution` aplica el filtro de aporte del periodo en curso.
    """
    options = [selectinload(models.Patient.treatments), selectinload(models.Patient.medical)]
    if require_current_contribution:
        options.append(selectinload(models.Patient.contributions))
    result = await db.execute(
        select(models.Patient).options(*options).where(models.Patient.estado.in_(list(estados)))
    )
    candidates = result.scalars().unique().all()

    periodo_actual = current_periodo()
    patient_inputs: List[InsulinPatientInput] = []
    info: dict = {}
    excluded: List[dict] = []
    for patient in candidates:
        nombre = " ".join(p for p in (patient.nombres, patient.ap_paterno, patient.ap_materno) if p)
        daily: dict = {}
        has_insulin = False
        for tx in patient.treatments:
            if getattr(tx, "tipo", "INSULINA") != "INSULINA":
                continue
            ingredient = normalize_insulin_name(tx.nombre)
            if not ingredient:
                continue
            has_insulin = True
            daily[ingredient] = daily.get(ingredient, 0.0) + treatment_daily_units(tx)
        if not has_insulin:
            continue
        if require_current_contribution and not is_patient_current_on_contribution(patient, periodo_actual):
            excluded.append(
                {
                    "patient_id": patient.id,
                    "nombre_completo": nombre,
                    "motivo": f"Falta aporte periodo {periodo_actual}",
                }
            )
            continue
        if not any(units > 0 for units in daily.values()):
            excluded.append(
                {
                    "patient_id": patient.id,
                    "nombre_completo": nombre,
                    "motivo": "Tratamiento de insulina sin dosis diaria registrada",
                }
            )
            continue
        tipo_diabetes = patient.medical.tipo_diabetes if patient.medical else None
        patient_inputs.append(
            InsulinPatientInput(
                patient_id=patient.id,
                is_minor=patient.edad_calc < MINOR_AGE,
                daily_ui=daily,
                is_type1=is_type1_diabetes(tipo_diabetes),
            )
        )
        info[patient.id] = {
            "nombre": nombre,
            "ci": patient.ci,
            "estado": patient.estado,
            "depto": patient.depto,
            "edad": patient.edad_calc,
            "tipo_diabetes": tipo_diabetes,
        }
    return patient_inputs, info, excluded


def group_choice_issues(plan, info: dict) -> List[schemas.DistributionRecordIssue]:
    """Fichas con dos insulinas del mismo grupo: cuál se usó y por qué, para corregirlas."""
    reasons = {
        "STOCK": "es la que tiene stock disponible en esta donación",
        "SUSTITUTO": "no hay stock propio, pero se cubre con {sustituto} según las reglas de sustitución",
        "SIN_STOCK": "ninguna tiene stock ni sustituto en esta donación; se tomó la de mayor dosis registrada",
    }
    out: List[schemas.DistributionRecordIssue] = []
    for c in plan.group_choices:
        data = info.get(c.patient_id)
        if data is None:
            continue
        nombres_ins = ", ".join(sorted(c.options))
        razon = reasons[c.reason].format(sustituto=c.substitute)
        out.append(
            schemas.DistributionRecordIssue(
                patient_id=c.patient_id,
                nombre_completo=data["nombre"],
                ci=data.get("ci"),
                estado=data.get("estado"),
                depto=data.get("depto"),
                es_menor=(data.get("edad") or 0) < MINOR_AGE,
                grupo=c.group,
                grupo_nombre=GROUP_LABELS[c.group],
                insulinas=[
                    schemas.DistributionRecordInsulin(insulina=ing, dosis_diaria=round(dose, 1))
                    for ing, dose in sorted(c.options.items())
                ],
                insulina_usada=c.chosen,
                motivo=c.reason,
                sustituto=c.substitute,
                premezcla_descartada=c.premix_discarded,
                mensaje=(
                    f"Tiene {len(c.options)} insulinas {GROUP_LABELS[c.group]} registradas ({nombres_ins}) y solo "
                    f"puede usar una por grupo. Se calculó con {c.chosen} porque {razon}."
                    + (
                        " Una premezcla no puede sustituir a una basal, por eso se descartó la premezcla."
                        if c.premix_discarded
                        else ""
                    )
                    + " Corrige la ficha."
                ),
            )
        )
    return out


def plan_patient_items(plan, patient_inputs, info: dict, lot_meta: dict) -> List[schemas.DistributionReportPatient]:
    """Una fila por paciente con lo que recibe de cada insulina, en orden de prioridad."""
    # Por paciente e insulina que usa (no la del lote: una sustitución entrega otra).
    shown: dict = {}
    for item in plan.assignments:
        key = (item.patient_id, item.for_ingredient, item.lot_id)
        units, ui = shown.get(key, (0, 0.0))
        shown[key] = (units + item.units, ui + item.ui)
    lots_by_patient_ing: dict = {}
    for (patient_id, for_ingredient, lot_id), (units, ui) in shown.items():
        producto, lote, fecha_venc = lot_meta[lot_id]
        lots_by_patient_ing.setdefault((patient_id, for_ingredient), []).append(
            schemas.DistributionLotItem(
                lot_id=lot_id, producto=producto, unidades=units, ui=ui, lote=lote, fecha_venc=fecha_venc
            )
        )

    minors = {p.patient_id for p in patient_inputs if p.is_minor}
    type1 = {p.patient_id for p in patient_inputs if p.is_type1}
    items = []
    for patient_id, results in plan.patients.items():
        data = info[patient_id]
        items.append(
            schemas.DistributionReportPatient(
                patient_id=patient_id,
                nombre_completo=data["nombre"],
                es_menor=patient_id in minors,
                es_tipo1=patient_id in type1,
                ci=data.get("ci"),
                estado=data.get("estado"),
                depto=data.get("depto"),
                edad=data.get("edad"),
                tipo_diabetes=data.get("tipo_diabetes"),
                insulinas=[
                    schemas.DistributionPatientInsulin(
                        insulina=r.ingredient,
                        necesidad_ui=round(r.need_ui, 1),
                        entregado_ui=round(r.given_ui + r.substitute_equiv_ui, 1),
                        cobertura_pct=(
                            round(100 * (r.given_ui + r.substitute_equiv_ui) / r.need_ui, 1)
                            if r.need_ui
                            else 0.0
                        ),
                        sustituto=r.substitute,
                        sustituto_ui=round(r.substitute_ui, 1),
                        dosis_diaria_registrada=round(r.daily_registered, 1),
                        dosis_diaria_aplicada=round(r.daily_applied, 1),
                        dosis_limitada=r.daily_applied + 1e-9 < r.daily_registered,
                        lotes=lots_by_patient_ing.get((patient_id, r.ingredient), []),
                    )
                    for r in results
                ],
            )
        )
    # Mismo orden de prioridad que el reparto: menores, adultos tipo 1, resto.
    items.sort(key=lambda item: (0 if item.es_menor else 1 if item.es_tipo1 else 2, item.nombre_completo))
    return items


def plan_ingredient_items(plan) -> List[schemas.DistributionIngredientSummary]:
    return [
        schemas.DistributionIngredientSummary(
            insulina=s.ingredient,
            stock_ui=s.stock_ui,
            necesidad_ui=s.demand_ui,
            reserva_ui=s.reserve_ui,
            asignado_ui=s.allocated_ui,
            faltante_ui=s.unmet_ui,
            sobrante_ui=s.leftover_ui,
            pacientes_con_necesidad=s.patients_with_need,
            pacientes_sin_cubrir=s.patients_unmet,
            sustituido_ui=s.substituted_out_ui,
            entregado_como_sustituto_ui=s.substituted_in_ui,
        )
        for s in plan.ingredients
    ]


def plan_reserve_items(plan, lot_meta: dict) -> List[schemas.DistributionReserveItem]:
    return [
        schemas.DistributionReserveItem(
            lot_id=r.lot_id,
            insulina=r.ingredient,
            producto=lot_meta[r.lot_id][0],
            unidades=r.units,
            ui=r.ui,
            lote=lot_meta[r.lot_id][1],
            fecha_venc=lot_meta[r.lot_id][2],
        )
        for r in plan.reserve_lots
    ]


def group_assignments(plan) -> dict:
    """Un paciente puede recibir un lote en varias pasadas: se agrupa por (paciente, lote)."""
    grouped: dict = {}
    for item in plan.assignments:
        key = (item.patient_id, item.lot_id)
        grouped[key] = grouped.get(key, 0) + item.units
    return grouped
