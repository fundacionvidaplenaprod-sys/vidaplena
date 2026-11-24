"""Intercambios equivalentes en un reparto de insulina del almacén (funciones puras, sin base de datos).

El reparto lo calcula el motor del reporte (`distribution_service.run_equitable_plan`). Después solo se puede
modificar con intercambios entre dos beneficiarios que no cambian el reparto propuesto:

  A entrega `n_a` envases del lote X (los que recibía para su tratamiento) y recibe `n_b` envases del lote Y;
  B entrega esos `n_b` envases del lote Y y recibe los `n_a` del lote X.

Un intercambio es válido solo si:
  1. son dos beneficiarios distintos y dos productos distintos;
  2. cada uno tiene esos envases en ese tratamiento;
  3. las UI son exactamente iguales (n_a x UI del envase X = n_b x UI del envase Y): la cobertura, los días y el
     margen (75 % - 65 días) de cada uno no cambian, y el stock que sale de cada lote tampoco;
  4. cada envase sirve para el tratamiento que lo recibe: su propia insulina o un sustituto de la tabla del reporte
     (`EQUITABLE_SUBSTITUTIONS`); un menor con degludec la conserva siempre;
  5. un menor no recibe por intercambio un sustituto que no tenía (exige aval médico) y no entrega su Lantus a
     cambio de otra marca (la glargina de los menores se cubre con Lantus).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

from app.core.equitable_distribution import EQUITABLE_SUBSTITUTIONS
from app.core.insulin_distribution import MINOR_KEEP_INSULINS, MINOR_PREFERRED_BRANDS, PRIORITY_MINOR

EPS = 1e-6

_TARGETS: Dict[str, List[str]] = defaultdict(list)
for _rule in EQUITABLE_SUBSTITUTIONS:
    _TARGETS[_rule.source].append(_rule.target)

# (beneficiario, insulina del tratamiento, lote) -> envases
LineKey = Tuple[int, str, int]


@dataclass(frozen=True)
class LotInfo:
    lot_id: int
    donation_id: int
    insulina: str
    producto: str
    ui_por_envase: float
    lote: Optional[str] = None
    fecha_venc: Optional[date] = None


@dataclass(frozen=True)
class Holder:
    """Un tratamiento de un beneficiario dentro del reparto."""

    beneficiario_id: int
    insulina: str
    grupo: int

    @property
    def es_menor(self) -> bool:
        return self.grupo == PRIORITY_MINOR


class SwapError(ValueError):
    """El intercambio no es equivalente o rompe una regla del reparto."""


def compatible_insulins(insulina: str, grupo: int) -> set:
    """Insulinas con las que se puede cubrir un tratamiento: la propia y sus sustitutos (como el motor)."""
    out = {insulina}
    if not (grupo == PRIORITY_MINOR and insulina in MINOR_KEEP_INSULINS):
        out |= set(_TARGETS.get(insulina, []))
    return out


def is_preferred_for_minors(lot: LotInfo) -> bool:
    """Marca que se reserva a menores (Lantus en glargina), reconocida por el nombre del producto como el motor."""
    return any(fragment in lot.producto.lower() for fragment in MINOR_PREFERRED_BRANDS.get(lot.insulina, ()))


def _insulins_received(lines: Dict[LineKey, int], lots: Dict[int, LotInfo], bid: int, insulina: str) -> set:
    return {lots[k[2]].insulina for k, n in lines.items() if k[0] == bid and k[1] == insulina and n > 0}


def _check_receiver(
    holder: Holder,
    gives: LotInfo,
    receives: LotInfo,
    lines: Dict[LineKey, int],
    lots: Dict[int, LotInfo],
    nombre: str,
) -> None:
    if receives.insulina not in compatible_insulins(holder.insulina, holder.grupo):
        if holder.es_menor and holder.insulina in MINOR_KEEP_INSULINS:
            raise SwapError(f"{nombre} es menor y usa {holder.insulina}: la conserva siempre, no se sustituye.")
        raise SwapError(
            f"{receives.producto} ({receives.insulina}) no sirve para el tratamiento de {holder.insulina} de {nombre}: "
            "no es su insulina ni uno de sus sustitutos."
        )
    if not holder.es_menor:
        return
    if receives.insulina != holder.insulina and receives.insulina not in _insulins_received(
        lines, lots, holder.beneficiario_id, holder.insulina
    ):
        raise SwapError(
            f"{nombre} es menor: no se le puede dar {receives.insulina} en lugar de {holder.insulina} por intercambio "
            "(un sustituto en un menor requiere aval médico)."
        )
    if is_preferred_for_minors(gives) and not is_preferred_for_minors(receives):
        raise SwapError(f"{nombre} es menor: conserva {gives.producto} (la glargina de los menores se cubre con Lantus).")


def validate_swap(
    lines: Dict[LineKey, int],
    lots: Dict[int, LotInfo],
    a: Holder,
    lot_a: int,
    n_a: int,
    b: Holder,
    lot_b: int,
    n_b: int,
    nombres: Optional[Dict[int, str]] = None,
) -> float:
    """Comprueba el intercambio y devuelve las UI que se intercambian. Lanza `SwapError` si no es válido."""
    nombres = nombres or {}
    nombre_a = nombres.get(a.beneficiario_id, f"el beneficiario {a.beneficiario_id}")
    nombre_b = nombres.get(b.beneficiario_id, f"el beneficiario {b.beneficiario_id}")
    if a.beneficiario_id == b.beneficiario_id:
        raise SwapError("El intercambio es entre dos beneficiarios distintos.")
    if n_a <= 0 or n_b <= 0:
        raise SwapError("La cantidad de envases debe ser mayor a 0.")
    if lot_a not in lots or lot_b not in lots:
        raise SwapError("El lote no forma parte de este reparto.")
    la, lb = lots[lot_a], lots[lot_b]
    if la.donation_id == lb.donation_id:
        raise SwapError("Es el mismo producto: el intercambio no cambiaría nada.")
    if lines.get((a.beneficiario_id, a.insulina, lot_a), 0) < n_a:
        raise SwapError(f"{nombre_a} no tiene {n_a} envase(s) de {la.producto} para su {a.insulina}.")
    if lines.get((b.beneficiario_id, b.insulina, lot_b), 0) < n_b:
        raise SwapError(f"{nombre_b} no tiene {n_b} envase(s) de {lb.producto} para su {b.insulina}.")
    ui_a, ui_b = n_a * la.ui_por_envase, n_b * lb.ui_por_envase
    if abs(ui_a - ui_b) > EPS:
        raise SwapError(
            f"No es equivalente: {n_a} x {la.producto} son {ui_a:g} UI y {n_b} x {lb.producto} son {ui_b:g} UI. "
            "Las UI deben ser iguales para que la cobertura de cada uno no cambie."
        )
    _check_receiver(a, la, lb, lines, lots, nombre_a)
    _check_receiver(b, lb, la, lines, lots, nombre_b)
    return ui_a


def apply_swap(lines: Dict[LineKey, int], a: Holder, lot_a: int, n_a: int, b: Holder, lot_b: int, n_b: int) -> None:
    """Aplica un intercambio ya validado sobre las líneas del reparto."""
    for key, delta in (
        ((a.beneficiario_id, a.insulina, lot_a), -n_a),
        ((a.beneficiario_id, a.insulina, lot_b), n_b),
        ((b.beneficiario_id, b.insulina, lot_b), -n_b),
        ((b.beneficiario_id, b.insulina, lot_a), n_a),
    ):
        lines[key] = lines.get(key, 0) + delta
        if lines[key] < 0:
            raise SwapError("El intercambio deja una cantidad negativa.")
        if lines[key] == 0:
            del lines[key]


def swap_options(
    lines: Dict[LineKey, int],
    lots: Dict[int, LotInfo],
    holders: Dict[Tuple[int, str], Holder],
    a: Holder,
    lot_a: int,
    n_a: int,
) -> List[dict]:
    """Todos los intercambios válidos para `n_a` envases del lote `lot_a` del tratamiento `a`.

    Cada opción: beneficiario B, su tratamiento, el lote que entrega y cuántos envases (mismas UI)."""
    if lot_a not in lots:
        return []
    la = lots[lot_a]
    target_ui = n_a * la.ui_por_envase
    out: List[dict] = []
    for (bid, insulina, lot_b), have in sorted(lines.items()):
        if bid == a.beneficiario_id or lot_b not in lots:
            continue
        lb = lots[lot_b]
        if lb.donation_id == la.donation_id or lb.ui_por_envase <= 0:
            continue
        exact = target_ui / lb.ui_por_envase
        n_b = round(exact)
        if n_b <= 0 or abs(exact - n_b) > EPS or n_b > have:
            continue
        b = holders.get((bid, insulina))
        if b is None:
            continue
        try:
            validate_swap(lines, lots, a, lot_a, n_a, b, lot_b, n_b)
        except SwapError:
            continue
        out.append(
            {
                "beneficiario_id": bid,
                "insulina": insulina,
                "lot_id": lot_b,
                "envases": n_b,
                "ui": n_b * lb.ui_por_envase,
                "misma_insulina": lb.insulina == la.insulina,
            }
        )
    return out


def _round1(x: float) -> float:
    return round(x + 0.0, 1)


def rebuild_result(resultado: dict, lines: Dict[LineKey, int], lots: Dict[int, LotInfo]) -> dict:
    """Actualiza el resultado guardado (formato del reporte) con las líneas del reparto tras los intercambios.

    La cobertura de cada tratamiento no cambia con un intercambio equivalente; sí cambian los envases y lotes que
    recibe, si recibe un sustituto (y su nota) y, por insulina, cuánto se entrega como sustituto de otra."""
    by_treatment: Dict[Tuple[int, str], List[Tuple[int, int]]] = defaultdict(list)
    for (bid, insulina, lot_id), n in lines.items():
        if n > 0:
            by_treatment[(bid, insulina)].append((lot_id, n))

    sustitutos: Dict[Tuple[int, str], Optional[str]] = {}
    for paciente in resultado.get("pacientes", []):
        bid = paciente["patient_id"]
        for item in paciente["insulinas"]:
            entries = sorted(by_treatment.get((bid, item["insulina"]), []))
            lotes, total, otros_ui = [], 0.0, 0.0
            otros: List[str] = []
            for lot_id, n in entries:
                lot = lots[lot_id]
                ui = n * lot.ui_por_envase
                total += ui
                if lot.insulina != item["insulina"]:
                    otros_ui += ui
                    if lot.insulina not in otros:
                        otros.append(lot.insulina)
                lotes.append(
                    {
                        "lot_id": lot_id,
                        "producto": lot.producto,
                        "unidades": n,
                        "ui": ui,
                        "lote": lot.lote,
                        "fecha_venc": lot.fecha_venc.isoformat() if lot.fecha_venc else None,
                    }
                )
            item["lotes"] = lotes
            item["entregado_ui"] = _round1(total)
            need = item.get("necesidad_ui") or 0
            item["cobertura_pct"] = _round1(100 * total / need) if need else 0.0
            item["sustituto"] = " + ".join(sorted(otros)) if otros else None
            item["sustituto_ui"] = _round1(otros_ui)
            notas = [n for n in item.get("notas", []) if not n.startswith("SUSTITUCION")]
            if otros:
                notas.append("SUSTITUCION" + (" (MENOR: requiere aval médico)" if paciente.get("grupo_prioridad") == PRIORITY_MINOR else ""))
            item["notas"] = notas
            sustitutos[(bid, item["insulina"])] = item["sustituto"]

    for fila in resultado.get("bajo_minimo", []):
        fila["sustituto"] = sustitutos.get((fila["patient_id"], fila["insulina"]), fila.get("sustituto"))

    entregado: Dict[str, float] = defaultdict(float)
    cubierto_con_otra: Dict[str, float] = defaultdict(float)
    como_sustituto: Dict[str, float] = defaultdict(float)
    for (bid, insulina, lot_id), n in lines.items():
        lot = lots[lot_id]
        ui = n * lot.ui_por_envase
        entregado[lot.insulina] += ui
        if lot.insulina != insulina:
            cubierto_con_otra[insulina] += ui
            como_sustituto[lot.insulina] += ui
    for fila in resultado.get("insulinas", []):
        ing = fila["insulina"]
        fila["asignado_ui"] = entregado.get(ing, 0.0)
        fila["sustituido_ui"] = cubierto_con_otra.get(ing, 0.0)
        fila["entregado_como_sustituto_ui"] = como_sustituto.get(ing, 0.0)
    return resultado


def lines_from_rows(rows: Iterable) -> Dict[LineKey, int]:
    """Líneas del reparto desde filas con beneficiario_id, insulina, lot_id y envases (modelos o dicts)."""
    lines: Dict[LineKey, int] = {}
    for row in rows:
        get = row.get if isinstance(row, dict) else lambda k, r=row: getattr(r, k)
        key = (int(get("beneficiario_id")), get("insulina"), int(get("lot_id")))
        lines[key] = lines.get(key, 0) + int(get("envases"))
    return {k: v for k, v in lines.items() if v > 0}
