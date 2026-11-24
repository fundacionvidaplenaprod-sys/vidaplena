// Matriz del reparto del almacén: una fila por tratamiento de cada beneficiario y una columna por producto
// (los lotes del mismo producto se suman en la celda). Cada celda guarda también lo que propuso el motor,
// para marcar lo que cambió con los intercambios.

const lineKey = (beneficiarioId, insulina, lotId) => `${beneficiarioId}|${insulina}|${lotId}`;

export function buildMatrix(detail) {
    const resultado = detail?.resultado;
    if (!resultado) return { columns: [], rows: [] };
    const stock = resultado.stock || [];

    const lotToDonation = new Map(stock.map((s) => [s.lot_id, s.donation_id]));
    const columnsById = new Map();
    stock.forEach((s) => {
        const col = columnsById.get(s.donation_id) || {
            donationId: s.donation_id,
            producto: s.producto,
            insulina: s.insulina,
            uiPorEnvase: s.ui_por_envase,
            presentacionMl: s.presentacion_ml,
            concentracion: s.concentracion_ui_ml,
            disponibles: 0,
            asignados: 0,
            reserva: 0,
            sobrante: 0,
        };
        col.disponibles += s.disponibles;
        col.asignados += s.asignados;
        col.reserva += s.reserva;
        col.sobrante += s.sobrante;
        columnsById.set(s.donation_id, col);
    });
    const columns = [...columnsById.values()].sort(
        (a, b) => a.insulina.localeCompare(b.insulina) || a.producto.localeCompare(b.producto) || a.uiPorEnvase - b.uiPorEnvase
    );

    const propuesta = new Map(
        (detail.propuesta || []).map((p) => [lineKey(p.beneficiario_id, p.insulina, p.lot_id), p.envases])
    );
    const propuestaPorCelda = new Map();
    (detail.propuesta || []).forEach((p) => {
        const key = `${p.beneficiario_id}|${p.insulina}|${lotToDonation.get(p.lot_id)}`;
        propuestaPorCelda.set(key, (propuestaPorCelda.get(key) || 0) + p.envases);
    });

    const rows = [];
    (resultado.pacientes || []).forEach((p) => {
        p.insulinas.forEach((i) => {
            const cells = {};
            (i.lotes || []).forEach((l) => {
                const donationId = lotToDonation.get(l.lot_id);
                const cell = cells[donationId] || { envases: 0, lots: [] };
                cell.envases += l.unidades;
                cell.lots.push({ ...l, propuesta: propuesta.get(lineKey(p.patient_id, i.insulina, l.lot_id)) || 0 });
                cells[donationId] = cell;
            });
            columns.forEach((c) => {
                const original = propuestaPorCelda.get(`${p.patient_id}|${i.insulina}|${c.donationId}`) || 0;
                if (cells[c.donationId]) cells[c.donationId].propuesta = original;
                else if (original) cells[c.donationId] = { envases: 0, lots: [], propuesta: original };
            });
            const cambiada = columns.some((c) => (cells[c.donationId]?.envases || 0) !== (cells[c.donationId]?.propuesta || 0));
            rows.push({ key: `${p.patient_id}|${i.insulina}`, paciente: p, insulina: i, cells, cambiada });
        });
    });
    return { columns, rows };
}

// Filtros de la matriz: texto (nombre o CI), grupo de prioridad, insulina del tratamiento y solo lo modificado.
export function filterRows(rows, { search = '', grupo = '', insulina = '', soloCambios = false }) {
    const term = search.trim().toLowerCase();
    return rows.filter(({ paciente, insulina: i, cambiada }) => {
        if (grupo && String(paciente.grupo_prioridad) !== String(grupo)) return false;
        if (insulina && i.insulina !== insulina) return false;
        if (soloCambios && !cambiada) return false;
        if (!term) return true;
        return paciente.nombre_completo.toLowerCase().includes(term) || (paciente.ci || '').toLowerCase().includes(term);
    });
}
