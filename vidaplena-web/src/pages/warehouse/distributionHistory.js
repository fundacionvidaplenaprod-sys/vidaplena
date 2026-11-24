// Historial de repartos del almacén: filtros, packing lists de origen y lo que recibió un beneficiario.

// Fecha de un reparto: la de consolidación (cuando salió del almacén) o, si no se consolidó, la del cálculo.
export const fechaReparto = (h) => h.consolidated_at || h.created_at;

const pad = (n) => String(n).padStart(2, '0');

// «2026-11-24» en la hora local, para comparar con los <input type="date">.
export const diaLocal = (iso) => {
    const d = new Date(iso);
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

export const ESTADO_FILTROS = [
    { id: 'vigentes', label: 'Consolidados y borrador', estados: ['CONSOLIDADO', 'BORRADOR'] },
    { id: 'CONSOLIDADO', label: 'Solo consolidados', estados: ['CONSOLIDADO'] },
    { id: 'DESCARTADO', label: 'Solo descartados', estados: ['DESCARTADO'] },
    { id: 'todos', label: 'Todos, con descartados', estados: ['CONSOLIDADO', 'BORRADOR', 'DESCARTADO'] },
];

// `ingreso`: '' todos, el id del ingreso (como texto) o SIN_PACKING_LIST.
export const SIN_PACKING_LIST = 'sin';
export const FILTROS_INICIALES = { estado: 'vigentes', desde: '', hasta: '', ingreso: '' };

const estadosDe = (estado) => (ESTADO_FILTROS.find((f) => f.id === estado) || ESTADO_FILTROS[0]).estados;

export const incluyeDescartados = (estado) => estadosDe(estado).includes('DESCARTADO');

const claveIngreso = (o) => (o.ingreso_id == null ? SIN_PACKING_LIST : String(o.ingreso_id));

export function filterHistory(history, { estado = 'vigentes', desde = '', hasta = '', ingreso = '' } = {}) {
    const estados = estadosDe(estado);
    return history.filter((h) => {
        if (!estados.includes(h.estado)) return false;
        const dia = diaLocal(fechaReparto(h));
        if (desde && dia < desde) return false;
        if (hasta && dia > hasta) return false;
        if (ingreso && !(h.ingresos || []).some((o) => claveIngreso(o) === ingreso)) return false;
        return true;
    });
}

export const hayFiltros = (filtros) =>
    Object.entries(FILTROS_INICIALES).some(([campo, inicial]) => (filtros[campo] ?? inicial) !== inicial);

export const origenTexto = (o) => (o.ingreso_id == null ? 'Lotes sin packing list' : o.archivo || `Ingreso #${o.ingreso_id}`);

// Opciones del filtro por packing list: los que alimentaron algún reparto, del más reciente al más antiguo.
export function packingListOptions(history) {
    const vistos = new Map();
    history.forEach((h) =>
        (h.ingresos || []).forEach((o) => {
            const value = claveIngreso(o);
            if (vistos.has(value)) return;
            const label =
                o.ingreso_id == null
                    ? 'Lotes sin packing list'
                    : `${o.archivo} (ingreso #${o.ingreso_id}${o.ingresado_at ? `, ${new Date(o.ingresado_at).toLocaleDateString('es-BO')}` : ''})`;
            vistos.set(value, { value, label, orden: o.ingreso_id ?? -1 });
        })
    );
    return [...vistos.values()].sort((a, b) => b.orden - a.orden).map(({ value, label }) => ({ value, label }));
}

// Totales de lo que salió del almacén (solo los consolidados: un borrador todavía no se entregó).
export function totalesConsolidados(repartos) {
    return repartos
        .filter((r) => r.estado === 'CONSOLIDADO')
        .reduce(
            (acc, r) => ({ repartos: acc.repartos + 1, envases: acc.envases + (r.envases || 0), ui: acc.ui + (r.asignado_ui ?? r.ui ?? 0) }),
            { repartos: 0, envases: 0, ui: 0 }
        );
}
