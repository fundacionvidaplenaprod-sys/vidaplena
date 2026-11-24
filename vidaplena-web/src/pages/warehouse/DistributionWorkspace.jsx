import { useMemo, useState } from 'react';
import { Camera, CheckCircle2, Download, FileSpreadsheet, RotateCcw, Trash2, RefreshCw } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { ConfirmModal } from '../../components/ui/ConfirmModal';
import {
    consolidateWarehouseDistribution,
    discardWarehouseDistribution,
    resetWarehouseDistribution,
} from '../../api/donations';
import {
    COORDINAR_ENTREGA,
    FOTO_ESTADOS,
    FOTO_TIPOS,
    MOTIVO_BAJO_MINIMO,
    dentroDelMargen,
    diasCubiertos,
    dosisTexto,
    fmt,
    hoyIso,
    notasVisibles,
    ventanaEntregaPorDefecto,
    ventanaEntregaTexto,
} from '../../utils/insulinDistribution';
import { buildMatrix, filterRows } from './distributionMatrix';
import { ESTADO_REPARTO, exportDistributionPDF, exportDistributionXLS } from './distributionExport';
import { origenTexto } from './distributionHistory';
import PhotoReviewDialog from './PhotoReviewDialog';
import SwapDialog from './SwapDialog';

const ESTADO_CLASES = {
    BORRADOR: 'bg-amber-100 text-amber-700',
    CONSOLIDADO: 'bg-green-100 text-green-700',
    DESCARTADO: 'bg-gray-200 text-gray-600',
};

const AVISO_ESTADOS = {
    VISTO: { label: 'Lo vio', clase: 'bg-green-100 text-green-700' },
    PENDIENTE: { label: 'Pendiente', clase: 'bg-amber-100 text-amber-700' },
    SIN_CUENTA: { label: 'Sin cuenta en el portal', clase: 'bg-red-100 text-red-700' },
    SIN_PORTAL: { label: 'Registro Asistido: avisar a su referente', clase: 'bg-gray-200 text-gray-700' },
};

// Foto que subió el beneficiario en su aviso (insulinas ya usadas o HbA1c): su estado, que abre la revisión, o «-».
function FotoCelda({ foto, label, onOpen }) {
    if (!foto) return <span className="text-gray-400">-</span>;
    const estado = FOTO_ESTADOS[foto.estado];
    return (
        <button
            type="button"
            onClick={onOpen}
            aria-label={`${label}: ${estado.label}`}
            title={`Subida el ${new Date(foto.subida_at).toLocaleString('es-BO')}`}
            className={`px-2 py-0.5 rounded-full text-xs font-bold hover:ring-2 hover:ring-blue-300 ${estado.clase}`}
        >
            {estado.label}
        </button>
    );
}

const porRevisarDe = (aviso) => FOTO_TIPOS.filter((t) => aviso[`foto_${t}`]?.estado === 'PENDIENTE');

const GRUPOS = [
    { id: '', label: 'Todos los grupos' },
    { id: '1', label: 'Menores de 18' },
    { id: '2', label: 'Tipo 1' },
    { id: '3', label: 'Adultos mayores tipo 2' },
    { id: '4', label: 'Tipo 2 y resto' },
];

// Un reparto del almacén: resumen, avisos y la matriz beneficiario × producto. En BORRADOR cada celda con envases
// abre el intercambio equivalente; CONSOLIDADO y DESCARTADO se muestran tal como quedaron. En el consolidado, el
// SUPER_ADMIN revisa las fotos que subieron los beneficiarios. `onDetailUpdate` reemplaza el reparto en pantalla sin
// recargar el historial (si no viene, se usa `onChange`).
export default function DistributionWorkspace({
    detail,
    logoBase64,
    onChange,
    onDetailUpdate,
    onRecalculate,
    recalculating,
    initialSearch = '',
}) {
    const [search, setSearch] = useState(initialSearch);
    const [grupo, setGrupo] = useState('');
    const [insulina, setInsulina] = useState('');
    const [soloCambios, setSoloCambios] = useState(false);
    const [swapTarget, setSwapTarget] = useState(null);
    const [confirm, setConfirm] = useState(null);
    const [processing, setProcessing] = useState(false);
    const [avisoMensaje, setAvisoMensaje] = useState('');
    const [entrega, setEntrega] = useState(() => ventanaEntregaPorDefecto());
    const hoy = hoyIso();
    const entregaValida = !!entrega.desde && !!entrega.hasta && entrega.desde <= entrega.hasta && entrega.hasta >= hoy;
    const [revisando, setRevisando] = useState(null); // { beneficiarioId, tipo }
    const [soloPorRevisar, setSoloPorRevisar] = useState(false);

    // Fotos por revisar, en el orden de la tabla de avisos.
    const porRevisar = useMemo(
        () => (detail.avisos || []).flatMap((a) => porRevisarDe(a).map((tipo) => ({ beneficiarioId: a.beneficiario_id, tipo }))),
        [detail.avisos]
    );
    const avisoRevisado = revisando && (detail.avisos || []).find((a) => a.beneficiario_id === revisando.beneficiarioId);

    // Guarda la revisión en pantalla y abre la siguiente por revisar (después de la actual; si no, desde el principio).
    const fotoRevisada = (foto) => {
        const { beneficiarioId, tipo } = revisando;
        const avisos = detail.avisos.map((a) => (a.beneficiario_id === beneficiarioId ? { ...a, [`foto_${tipo}`]: foto } : a));
        (onDetailUpdate || onChange)({ ...detail, avisos });
        const orden = avisos.flatMap((a) => FOTO_TIPOS.map((t) => ({ beneficiarioId: a.beneficiario_id, tipo: t, foto: a[`foto_${t}`] })));
        const i = orden.findIndex((x) => x.beneficiarioId === beneficiarioId && x.tipo === tipo);
        const siguiente = [...orden.slice(i + 1), ...orden.slice(0, i)].find((x) => x.foto?.estado === 'PENDIENTE');
        setRevisando(siguiente ? { beneficiarioId: siguiente.beneficiarioId, tipo: siguiente.tipo } : null);
    };

    const { columns, rows } = useMemo(() => buildMatrix(detail), [detail]);
    const visibles = useMemo(
        () => filterRows(rows, { search, grupo, insulina, soloCambios }),
        [rows, search, grupo, insulina, soloCambios]
    );
    const insulinas = useMemo(() => [...new Set(rows.map((r) => r.insulina.insulina))].sort(), [rows]);

    const data = detail.resultado;
    const editable = detail.estado === 'BORRADOR';
    const reservaPct = data.stock_total_ui ? (100 * data.reserva_ui) / data.stock_total_ui : 0;

    const runAction = async (action) => {
        const actions = {
            consolidate: [
                (id) =>
                    consolidateWarehouseDistribution(id, {
                        mensaje: avisoMensaje,
                        entregaDesde: entrega.desde,
                        entregaHasta: entrega.hasta,
                    }),
                'Reparto consolidado: el stock asignado salió del almacén y cada beneficiario tiene el aviso en su portal',
            ],
            reset: [resetWarehouseDistribution, 'Se volvió a la propuesta del motor'],
            discard: [discardWarehouseDistribution, 'Borrador descartado'],
        };
        const [fn, ok] = actions[action];
        try {
            setProcessing(true);
            const updated = await fn(detail.id);
            toast.success(ok);
            setConfirm(null);
            onChange(updated);
        } catch (error) {
            toast.error(typeof error === 'string' ? error : 'No se pudo completar la acción');
            setConfirm(null);
        } finally {
            setProcessing(false);
        }
    };

    const confirmTexts = {
        consolidate: {
            title: 'Consolidar reparto',
            message:
                `Se congela el reparto #${detail.id} y salen del almacén ${detail.envases} envases (${fmt(data.asignado_ui)} UI). ` +
                'La reserva y el sobrante quedan en stock. Después ya no se puede modificar.\n\n' +
                'Cada beneficiario verá en su portal cuánta insulina le corresponde, con el número de lote, la fecha de ' +
                'entrega y las indicaciones que escriba aquí. ¿Consolidar?',
            label: 'Sí, consolidar',
        },
        reset: {
            title: 'Restablecer la propuesta',
            message: `Se deshacen los ${detail.intercambios} intercambio(s) y el reparto vuelve a la propuesta del motor. ¿Continuar?`,
            label: 'Sí, restablecer',
        },
        discard: {
            title: 'Descartar borrador',
            message: 'El borrador queda descartado en el historial y no descuenta stock. ¿Descartar?',
            label: 'Sí, descartar',
            danger: true,
        },
    };

    return (
        <div>
            <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3 mb-4">
                <div>
                    <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
                        Reparto #{detail.id}
                        <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${ESTADO_CLASES[detail.estado]}`}>
                            {ESTADO_REPARTO[detail.estado]}
                        </span>
                    </h2>
                    <p className="text-xs text-gray-500">
                        Calculado el {new Date(detail.created_at).toLocaleString('es-BO')}
                        {detail.autor ? ` por ${detail.autor}` : ''}
                        {detail.consolidated_at &&
                            ` · consolidado el ${new Date(detail.consolidated_at).toLocaleString('es-BO')}${detail.consolidado_por ? ` por ${detail.consolidado_por}` : ''}`}
                        {detail.entrega_desde && ` · entrega ${ventanaEntregaTexto(detail.entrega_desde, detail.entrega_hasta)}`}
                        {detail.discarded_at && ` · descartado el ${new Date(detail.discarded_at).toLocaleString('es-BO')}`}
                    </p>
                </div>
                <div className="flex flex-wrap gap-2">
                    {editable && (
                        <>
                            <button
                                type="button"
                                onClick={() => setConfirm('consolidate')}
                                disabled={!detail.stock_vigente || processing}
                                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
                            >
                                <CheckCircle2 size={16} /> Consolidar
                            </button>
                            <button
                                type="button"
                                onClick={() => setConfirm('reset')}
                                disabled={!detail.intercambios || processing}
                                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-gray-100 text-gray-700 hover:bg-gray-200 disabled:opacity-50"
                            >
                                <RotateCcw size={16} /> Restablecer propuesta
                            </button>
                            <button
                                type="button"
                                onClick={() => setConfirm('discard')}
                                disabled={processing}
                                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-gray-100 text-red-600 hover:bg-red-50"
                            >
                                <Trash2 size={16} /> Descartar
                            </button>
                        </>
                    )}
                    <button
                        type="button"
                        onClick={() => exportDistributionPDF(detail, logoBase64)}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-red-600 text-white hover:bg-red-700"
                    >
                        <Download size={16} /> PDF
                    </button>
                    <button
                        type="button"
                        onClick={() => exportDistributionXLS(detail)}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-green-700 text-white hover:bg-green-800"
                    >
                        <FileSpreadsheet size={16} /> Excel
                    </button>
                </div>
            </div>

            {detail.ingresos?.length > 0 && (
                <div className="flex flex-wrap items-center gap-2 mb-4 text-xs text-gray-600">
                    <span className="font-semibold text-gray-500">Sale de:</span>
                    {detail.ingresos.map((o) => (
                        <span key={o.ingreso_id ?? 'sin'} className="px-2.5 py-1 rounded-full bg-gray-100">
                            {origenTexto(o)}
                            {o.ingreso_id != null && (
                                <span className="text-gray-400">
                                    {' '}
                                    · ingreso #{o.ingreso_id}
                                    {o.ingresado_at ? ` del ${new Date(o.ingresado_at).toLocaleDateString('es-BO')}` : ''}
                                </span>
                            )}{' '}
                            · <b>{o.envases}</b> env. ({fmt(o.ui)} UI)
                        </span>
                    ))}
                </div>
            )}

            {porRevisar.length > 0 && (
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3 border border-amber-200 bg-amber-50 rounded-xl px-4 py-3 text-sm text-amber-900">
                    <span>
                        Hay <b>{porRevisar.length}</b> foto(s) de beneficiarios por revisar (insulinas ya usadas y HbA1c).
                    </span>
                    <button
                        type="button"
                        onClick={() => setRevisando(porRevisar[0])}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-amber-600 text-white hover:bg-amber-700"
                    >
                        <Camera size={16} /> Revisar fotos
                    </button>
                </div>
            )}

            {detail.avisos?.length > 0 && (
                <details className="mb-4 border border-blue-100 bg-blue-50/60 rounded-xl p-4 text-sm text-gray-700">
                    <summary className="cursor-pointer">
                        <b className="text-blue-900">Aviso en el Portal del Beneficiario:</b>{' '}
                        {Object.entries(AVISO_ESTADOS)
                            .map(([estado, { label }]) => [label, detail.avisos.filter((a) => a.estado === estado).length])
                            .filter(([, n]) => n > 0)
                            .map(([label, n]) => `${label}: ${n}`)
                            .join(' · ')}
                        {` · Fotos enviadas: insulinas usadas ${detail.avisos.filter((a) => a.foto_envases).length}, HbA1c ${
                            detail.avisos.filter((a) => a.foto_hba1c).length
                        } (${porRevisar.length} por revisar)`}
                    </summary>
                    {detail.entrega_desde && (
                        <p className="mt-2 text-blue-900">
                            <b>Entrega:</b> {ventanaEntregaTexto(detail.entrega_desde, detail.entrega_hasta)}. Cada
                            beneficiario coordina el día y la hora con el(la) responsable de su departamento.
                        </p>
                    )}
                    {detail.aviso_mensaje && (
                        <p className="mt-2 text-blue-900">
                            <b>Indicaciones:</b> {detail.aviso_mensaje}
                        </p>
                    )}
                    <label className="mt-3 flex items-center gap-2 text-xs font-semibold text-gray-600">
                        <input type="checkbox" checked={soloPorRevisar} onChange={(e) => setSoloPorRevisar(e.target.checked)} />
                        Solo con fotos por revisar
                    </label>
                    <table className="mt-2 w-full">
                        <thead>
                            <tr className="text-left text-xs font-bold text-gray-500 uppercase">
                                <th className="py-1 pr-3">Beneficiario</th>
                                <th className="py-1 pr-3">CI</th>
                                <th className="py-1 pr-3">Aviso</th>
                                <th className="py-1 pr-3">Visto el</th>
                                <th className="py-1 pr-3">Insulinas usadas</th>
                                <th className="py-1">HbA1c</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-blue-100">
                            {(soloPorRevisar ? detail.avisos.filter((a) => porRevisarDe(a).length) : detail.avisos).map((a) => (
                                <tr key={a.beneficiario_id}>
                                    <td className="py-1.5 pr-3">{a.nombre_completo}</td>
                                    <td className="py-1.5 pr-3 text-gray-500">{a.ci || '-'}</td>
                                    <td className="py-1.5 pr-3">
                                        <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${AVISO_ESTADOS[a.estado].clase}`}>
                                            {AVISO_ESTADOS[a.estado].label}
                                        </span>
                                    </td>
                                    <td className="py-1.5 pr-3 text-xs text-gray-500">
                                        {a.visto_at ? new Date(a.visto_at).toLocaleString('es-BO') : '-'}
                                    </td>
                                    <td className="py-1.5 pr-3">
                                        <FotoCelda
                                            foto={a.foto_envases}
                                            label={`Insulinas usadas de ${a.nombre_completo}`}
                                            onOpen={() => setRevisando({ beneficiarioId: a.beneficiario_id, tipo: 'envases' })}
                                        />
                                    </td>
                                    <td className="py-1.5">
                                        <FotoCelda
                                            foto={a.foto_hba1c}
                                            label={`HbA1c de ${a.nombre_completo}`}
                                            onOpen={() => setRevisando({ beneficiarioId: a.beneficiario_id, tipo: 'hba1c' })}
                                        />
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </details>
            )}

            {editable && !detail.stock_vigente && (
                <div role="alert" className="mb-4 border border-red-300 bg-red-50 rounded-xl p-4">
                    <h3 className="text-base font-bold text-red-800">El stock cambió desde que se calculó este reparto</h3>
                    <ul className="list-disc pl-5 text-sm text-red-800 mb-2">
                        {detail.stock_cambios.map((c) => (
                            <li key={c}>{c}</li>
                        ))}
                    </ul>
                    <p className="text-sm text-red-800 mb-3">
                        No se puede consolidar: el reparto se calculó para otro stock. Vuelva a calcularlo (los intercambios de este
                        borrador no se conservan).
                    </p>
                    {onRecalculate && (
                        <button
                            type="button"
                            onClick={onRecalculate}
                            disabled={recalculating}
                            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
                        >
                            <RefreshCw size={16} /> {recalculating ? 'Calculando...' : 'Volver a calcular'}
                        </button>
                    )}
                </div>
            )}

            <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-4">
                <div className="bg-vida-bg rounded-xl p-4">
                    <p className="text-xs text-gray-500">Stock considerado</p>
                    <p className="text-lg font-bold text-gray-800">{fmt(data.stock_total_ui)} UI</p>
                    <p className="text-xs text-gray-400">{data.lotes_considerados} lotes</p>
                </div>
                <div className="bg-vida-bg rounded-xl p-4">
                    <p className="text-xs text-gray-500">Reserva ({Math.round(data.reserva_pct * 100)} %)</p>
                    <p className="text-lg font-bold text-gray-800">{fmt(data.reserva_ui)} UI</p>
                    <p className="text-xs text-gray-400">{reservaPct.toFixed(1)} % del total · queda en el almacén</p>
                </div>
                <div className="bg-vida-bg rounded-xl p-4">
                    <p className="text-xs text-gray-500">Asignado</p>
                    <p className="text-lg font-bold text-gray-800">{fmt(data.asignado_ui)} UI</p>
                    <p className="text-xs text-gray-400">{detail.envases} envases</p>
                </div>
                <div className="bg-vida-bg rounded-xl p-4">
                    <p className="text-xs text-gray-500">Beneficiarios</p>
                    <p className="text-lg font-bold text-gray-800">{data.pacientes.length}</p>
                    <p className="text-xs text-gray-400">
                        {data.asistidos_incluidos} del Registro Asistido · {data.excluded_patients.length} sin dosis
                    </p>
                </div>
                <div className="bg-vida-bg rounded-xl p-4">
                    <p className="text-xs text-gray-500">Intercambios</p>
                    <p className="text-lg font-bold text-gray-800">{detail.intercambios}</p>
                    <p className="text-xs text-gray-400">equivalentes, sin cambiar coberturas</p>
                </div>
            </div>

            {data.minimo_imposible?.length > 0 && (
                <div role="alert" className="mb-4 border border-red-300 bg-red-50 rounded-xl p-4 text-sm text-red-800">
                    <b>Con este stock NO se puede cumplir el mínimo de todos:</b>{' '}
                    {data.minimo_imposible
                        .map((g) => `${g.insulina}: faltan ${fmt(g.falta_ui)} UI (≈ ${g.envases_faltantes} envases)`)
                        .join('; ')}
                </div>
            )}
            {(data.advertencias?.length > 0 || data.bajo_minimo?.length > 0 || data.registros_por_corregir?.length > 0) && (
                <details className="mb-4 border border-amber-200 bg-amber-50 rounded-xl p-4 text-sm text-amber-800">
                    <summary className="font-bold cursor-pointer">
                        Avisos del reparto ({(data.advertencias?.length || 0) + (data.bajo_minimo?.length || 0) + (data.registros_por_corregir?.length || 0)})
                    </summary>
                    <ul className="mt-2 list-disc pl-5 space-y-1">
                        {data.advertencias.map((a) => (
                            <li key={a}>{a}</li>
                        ))}
                        {data.bajo_minimo.map((b) => (
                            <li key={`bm-${b.patient_id}-${b.insulina}`}>
                                {b.nombre_completo}: {b.insulina} al {b.cobertura_pct} % (mínimo {b.margen_min_pct} %) —{' '}
                                {MOTIVO_BAJO_MINIMO[b.motivo] || b.motivo}
                            </li>
                        ))}
                        {data.registros_por_corregir.map((r) => (
                            <li key={`fc-${r.patient_id}-${r.grupo}`}>{r.nombre_completo}: {r.mensaje}</li>
                        ))}
                    </ul>
                </details>
            )}

            {editable && (
                <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3 text-sm text-blue-800 mb-4">
                    <b>Cómo ajustar:</b> el reparto es el del motor del reporte (mismas reglas: 75–100 %, máximo 65 días,
                    prioridades, reserva del 3 %, Lantus para menores). Solo se modifica con <b>intercambios equivalentes</b>:
                    pulse una celda con envases y elija con quién intercambiarlos. El sistema solo ofrece cambios con las
                    <b> mismas UI</b> y con insulinas que sirvan a cada tratamiento (la propia o un sustituto permitido), así
                    que la cobertura de cada persona y lo que sale de cada lote no cambian. Las celdas cambiadas se marcan en
                    amarillo.
                </div>
            )}

            <div className="flex flex-wrap items-center gap-2 mb-3">
                <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Buscar nombre o CI"
                    className="px-3 py-1.5 border rounded-lg text-sm outline-none focus:ring-2 focus:ring-vida-primary"
                />
                <select value={grupo} onChange={(e) => setGrupo(e.target.value)} aria-label="Grupo de prioridad" className="px-3 py-1.5 border rounded-lg text-sm">
                    {GRUPOS.map((g) => (
                        <option key={g.id} value={g.id}>
                            {g.label}
                        </option>
                    ))}
                </select>
                <select value={insulina} onChange={(e) => setInsulina(e.target.value)} aria-label="Insulina del tratamiento" className="px-3 py-1.5 border rounded-lg text-sm">
                    <option value="">Todas las insulinas</option>
                    {insulinas.map((i) => (
                        <option key={i} value={i}>
                            {i}
                        </option>
                    ))}
                </select>
                <label className="text-sm text-gray-600 flex items-center gap-1">
                    <input type="checkbox" checked={soloCambios} onChange={(e) => setSoloCambios(e.target.checked)} />
                    Solo con intercambios
                </label>
                <span className="text-xs text-gray-400">
                    {visibles.length} de {rows.length} tratamientos
                </span>
            </div>

            <div className="overflow-auto border border-gray-100 rounded-xl mb-6 max-h-[36rem]">
                <table className="text-sm border-separate border-spacing-0">
                    <thead className="bg-gray-50 sticky top-0 z-20">
                        <tr>
                            <th className="sticky left-0 z-30 bg-gray-50 px-3 py-2 text-left text-xs font-bold text-gray-500 uppercase border-b min-w-[14rem]">
                                Beneficiario
                            </th>
                            <th className="px-3 py-2 text-left text-xs font-bold text-gray-500 uppercase border-b">Tratamiento</th>
                            {columns.map((c) => (
                                <th key={c.donationId} className="px-2 py-2 text-center text-[11px] font-bold text-gray-600 border-b min-w-[6.5rem]">
                                    {c.producto}
                                    <span className="block font-normal text-gray-400">
                                        {c.insulina} · {fmt(c.uiPorEnvase)} UI
                                    </span>
                                </th>
                            ))}
                            <th className="px-3 py-2 text-left text-xs font-bold text-gray-500 uppercase border-b">Cobertura</th>
                        </tr>
                    </thead>
                    <tbody>
                        {visibles.length === 0 && (
                            <tr>
                                <td colSpan={columns.length + 3} className="px-4 py-6 text-center text-gray-400">
                                    Sin tratamientos para este filtro.
                                </td>
                            </tr>
                        )}
                        {visibles.map((row) => {
                            const { paciente: p, insulina: i } = row;
                            return (
                                <tr key={row.key} className="hover:bg-gray-50/60">
                                    <td className="sticky left-0 z-10 bg-white px-3 py-2 border-b text-gray-800">
                                        {p.nombre_completo}
                                        <span className="block text-xs text-gray-400">
                                            {p.ci || 'Sin CI'} · {p.grupo_prioridad_nombre}
                                        </span>
                                    </td>
                                    <td className="px-3 py-2 border-b text-gray-700">
                                        {i.insulina}
                                        {i.sustituto && (
                                            <span className="ml-1 px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-blue-100 text-blue-700">
                                                + {i.sustituto}
                                            </span>
                                        )}
                                        <span className="block text-[10px] text-gray-400">{dosisTexto(i)}</span>
                                        {notasVisibles(i).map((n) => (
                                            <span key={n} className="block text-[10px] font-semibold text-purple-700">
                                                {n}
                                            </span>
                                        ))}
                                    </td>
                                    {columns.map((c) => {
                                        const cell = row.cells[c.donationId];
                                        const envases = cell?.envases || 0;
                                        const cambiada = cell && cell.envases !== cell.propuesta;
                                        const clickable = editable && envases > 0;
                                        return (
                                            <td
                                                key={c.donationId}
                                                className={`px-2 py-2 border-b text-center ${cambiada ? 'bg-amber-100' : ''}`}
                                                title={cambiada ? `Propuesta del motor: ${cell.propuesta}` : undefined}
                                            >
                                                {clickable ? (
                                                    <button
                                                        type="button"
                                                        onClick={() => setSwapTarget({ row, column: c })}
                                                        aria-label={`Intercambiar ${envases} de ${c.producto} de ${p.nombre_completo}`}
                                                        className="min-w-[2.5rem] px-2 py-1 rounded-md font-bold text-vida-primary bg-vida-light/30 hover:bg-vida-light/60"
                                                    >
                                                        {envases}
                                                    </button>
                                                ) : (
                                                    <span className={envases ? 'font-bold text-gray-800' : 'text-gray-300'}>{envases || '·'}</span>
                                                )}
                                                {cambiada && <span className="block text-[10px] text-amber-700">antes {cell.propuesta}</span>}
                                            </td>
                                        );
                                    })}
                                    <td className={`px-3 py-2 border-b font-semibold ${dentroDelMargen(i) ? 'text-green-600' : 'text-red-600'}`}>
                                        {i.cobertura_pct}%
                                        <span className="block text-[10px] font-normal text-gray-400">
                                            {fmt(i.entregado_ui)} de {fmt(i.necesidad_ui)} UI · ≈ {diasCubiertos(i.cobertura_pct, data.dias)} días
                                        </span>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                    <tfoot className="bg-gray-50 sticky bottom-0 z-20">
                        {[
                            ['Asignados', 'asignados'],
                            ['Reserva (queda)', 'reserva'],
                            ['Sobrante (queda)', 'sobrante'],
                            ['Disponibles', 'disponibles'],
                        ].map(([label, field]) => (
                            <tr key={field}>
                                <td className="sticky left-0 z-30 bg-gray-50 px-3 py-1.5 text-xs font-bold text-gray-600 border-t">{label}</td>
                                <td className="border-t" />
                                {columns.map((c) => (
                                    <td key={c.donationId} className="px-2 py-1.5 text-center text-xs font-semibold text-gray-700 border-t">
                                        {c[field]}
                                    </td>
                                ))}
                                <td className="border-t" />
                            </tr>
                        ))}
                    </tfoot>
                </table>
            </div>

            {detail.intercambios_detalle?.length > 0 && (
                <>
                    <h3 className="text-lg font-bold text-gray-700 mb-3">Intercambios ({detail.intercambios_detalle.length})</h3>
                    <div className="overflow-x-auto border border-gray-100 rounded-xl mb-6">
                        <table className="w-full">
                            <thead className="bg-gray-50 border-b border-gray-100">
                                <tr>
                                    {['Fecha', 'Entrega', 'A cambio de', 'UI', 'Autor'].map((h) => (
                                        <th key={h} className="px-4 py-2 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">
                                            {h}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                {detail.intercambios_detalle.map((s) => (
                                    <tr key={s.id}>
                                        <td className="px-4 py-2 text-xs text-gray-600">{new Date(s.created_at).toLocaleString('es-BO')}</td>
                                        <td className="px-4 py-2 text-sm text-gray-700">
                                            {s.nombre_a}: {s.envases_a} × {s.producto_a}
                                        </td>
                                        <td className="px-4 py-2 text-sm text-gray-700">
                                            {s.nombre_b}: {s.envases_b} × {s.producto_b}
                                        </td>
                                        <td className="px-4 py-2 text-sm text-gray-700">{fmt(s.ui)}</td>
                                        <td className="px-4 py-2 text-xs text-gray-500">{s.autor || '-'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </>
            )}

            {avisoRevisado?.[`foto_${revisando.tipo}`] && (
                <PhotoReviewDialog
                    key={`${revisando.beneficiarioId}-${revisando.tipo}`}
                    aviso={avisoRevisado}
                    tipo={revisando.tipo}
                    restantes={porRevisar.filter((x) => x.beneficiarioId !== revisando.beneficiarioId || x.tipo !== revisando.tipo).length}
                    onClose={() => setRevisando(null)}
                    onReviewed={fotoRevisada}
                />
            )}

            {swapTarget && (
                <SwapDialog
                    distributionId={detail.id}
                    row={swapTarget.row}
                    column={swapTarget.column}
                    onClose={() => setSwapTarget(null)}
                    onSwapped={(updated) => {
                        setSwapTarget(null);
                        onChange(updated);
                    }}
                />
            )}

            <ConfirmModal
                isOpen={!!confirm}
                title={confirm ? confirmTexts[confirm].title : ''}
                message={confirm ? confirmTexts[confirm].message : ''}
                confirmLabel={confirm ? confirmTexts[confirm].label : ''}
                danger={confirm ? !!confirmTexts[confirm].danger : false}
                processing={processing}
                onConfirm={() => runAction(confirm)}
                onCancel={() => setConfirm(null)}
                inputLabel={confirm === 'consolidate' ? 'Indicaciones para los beneficiarios (opcional)' : undefined}
                inputValue={avisoMensaje}
                onInputChange={(value) => setAvisoMensaje(value.slice(0, 500))}
                inputPlaceholder="Ej.: llevar su carnet de identidad y una conservadora"
                confirmDisabled={confirm === 'consolidate' && !entregaValida}
            >
                {confirm === 'consolidate' && (
                    <fieldset className="mb-6">
                        <legend className="block text-sm font-bold text-gray-700 mb-1">Fecha de entrega</legend>
                        <div className="grid grid-cols-2 gap-3">
                            <label className="text-xs font-semibold text-gray-500">
                                Desde
                                <input
                                    type="date"
                                    value={entrega.desde}
                                    min={hoy}
                                    onChange={(e) => setEntrega((prev) => ({ ...prev, desde: e.target.value }))}
                                    className="mt-1 w-full px-3 py-2 border rounded-lg text-sm text-gray-800 focus:ring-2 focus:ring-vida-primary outline-none"
                                />
                            </label>
                            <label className="text-xs font-semibold text-gray-500">
                                Hasta
                                <input
                                    type="date"
                                    value={entrega.hasta}
                                    min={entrega.desde || hoy}
                                    onChange={(e) => setEntrega((prev) => ({ ...prev, hasta: e.target.value }))}
                                    className="mt-1 w-full px-3 py-2 border rounded-lg text-sm text-gray-800 focus:ring-2 focus:ring-vida-primary outline-none"
                                />
                            </label>
                        </div>
                        <p className={`mt-2 text-xs ${entregaValida ? 'text-gray-500' : 'text-red-600'}`}>
                            {entregaValida
                                ? `El aviso dirá: «Entrega ${ventanaEntregaTexto(entrega.desde, entrega.hasta)}. ${COORDINAR_ENTREGA}»`
                                : 'Revise las fechas: la entrega no puede terminar antes de hoy ni antes de empezar.'}
                        </p>
                    </fieldset>
                )}
            </ConfirmModal>
        </div>
    );
}
