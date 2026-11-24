import { useEffect, useMemo, useState } from 'react';
import { Search, X } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { getBeneficiaryDistributions, searchDistributionBeneficiaries } from '../../api/donations';
import { diasCubiertos, dosisTexto, fmt, lotesConNumeroTexto } from '../../utils/insulinDistribution';
import { ESTADO_REPARTO } from './distributionExport';
import {
    ESTADO_FILTROS,
    FILTROS_INICIALES,
    fechaReparto,
    filterHistory,
    hayFiltros,
    incluyeDescartados,
    origenTexto,
    packingListOptions,
    totalesConsolidados,
} from './distributionHistory';

const ESTADO_CLASES = {
    BORRADOR: 'bg-amber-100 text-amber-700',
    CONSOLIDADO: 'bg-green-100 text-green-700',
    DESCARTADO: 'bg-gray-200 text-gray-600',
};

const fechaHora = (iso) => (iso ? new Date(iso).toLocaleString('es-BO') : '-');
const fechaCorta = (iso) => (iso ? new Date(iso).toLocaleDateString('es-BO') : '-');

const Estado = ({ estado }) => (
    <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${ESTADO_CLASES[estado]}`}>{ESTADO_REPARTO[estado]}</span>
);

const TH = ({ children }) => (
    <th className="px-4 py-2 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">{children}</th>
);

// Historial del almacén: repartos con sus packing lists de origen, filtros por fecha, estado y packing list, y la
// búsqueda de un beneficiario en todos los repartos guardados («¿qué recibió en los últimos 3 meses?»).
export default function DistributionHistoryPanel({ history, currentId, onOpen }) {
    const [filtros, setFiltros] = useState(FILTROS_INICIALES);
    const [query, setQuery] = useState('');
    // Resultados de la búsqueda con el texto que los pidió, y lo que recibió la persona con su id: así no se
    // muestra una respuesta que ya no corresponde a lo escrito o a la persona elegida.
    const [busqueda, setBusqueda] = useState(null);
    const [seleccion, setSeleccion] = useState(null);
    const [respuestaPersona, setRespuestaPersona] = useState(null);
    const incluir = incluyeDescartados(filtros.estado);

    const filtrados = useMemo(() => filterHistory(history, filtros), [history, filtros]);
    const visibles = useMemo(() => new Set(filtrados.map((h) => h.id)), [filtrados]);
    const opcionesPackingList = useMemo(() => packingListOptions(history), [history]);
    const beneficiarioId = seleccion?.beneficiario_id ?? null;
    const q = query.trim();
    const matches = beneficiarioId == null && busqueda && busqueda.q === q && busqueda.incluir === incluir ? busqueda.resultados : null;
    const persona = respuestaPersona && respuestaPersona.id === beneficiarioId ? respuestaPersona.datos : null;
    const cargandoPersona = beneficiarioId != null && !persona;

    // Búsqueda con una pausa al escribir.
    useEffect(() => {
        if (beneficiarioId != null || q.length < 2) return undefined;
        let vigente = true;
        const timer = setTimeout(() => {
            searchDistributionBeneficiaries(q, incluir)
                .then((resultados) => vigente && setBusqueda({ q, incluir, resultados }))
                .catch((error) => vigente && toast.error(typeof error === 'string' ? error : 'No se pudo buscar'));
        }, 300);
        return () => {
            vigente = false;
            clearTimeout(timer);
        };
    }, [q, incluir, beneficiarioId]);

    // Lo que recibió la persona elegida; se vuelve a pedir si cambia el historial (otro cálculo, una consolidación).
    useEffect(() => {
        if (beneficiarioId == null) return undefined;
        let vigente = true;
        getBeneficiaryDistributions(beneficiarioId, incluir)
            .then((datos) => vigente && setRespuestaPersona({ id: beneficiarioId, datos }))
            .catch(() => vigente && setRespuestaPersona({ id: beneficiarioId, datos: { repartos: [] } }));
        return () => {
            vigente = false;
        };
    }, [beneficiarioId, incluir, history]);

    const setFiltro = (campo) => (e) => setFiltros((f) => ({ ...f, [campo]: e.target.value }));

    const elegir = (m) => {
        setSeleccion(m);
        setQuery(m.nombre_completo);
    };

    const quitarPersona = () => {
        setSeleccion(null);
        setQuery('');
    };

    const entregas = (persona?.repartos || []).filter((r) => visibles.has(r.distribution_id));
    const totales = totalesConsolidados(seleccion ? entregas : filtrados);

    return (
        <div>
            <div className="flex flex-wrap items-end gap-3 mb-4">
                <div className="relative flex-1 min-w-[16rem]">
                    <label htmlFor="historial-beneficiario" className="block text-xs font-semibold text-gray-500 mb-1">
                        Beneficiario
                    </label>
                    <div className="relative">
                        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                        <input
                            id="historial-beneficiario"
                            type="text"
                            value={query}
                            autoComplete="off"
                            onChange={(e) => {
                                setQuery(e.target.value);
                                if (seleccion) setSeleccion(null);
                            }}
                            placeholder="Nombre o CI, en todos los repartos"
                            className="w-full pl-9 pr-9 py-2 border rounded-lg text-sm outline-none focus:ring-2 focus:ring-vida-primary"
                        />
                        {query && (
                            <button
                                type="button"
                                onClick={quitarPersona}
                                aria-label="Quitar búsqueda"
                                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-600"
                            >
                                <X size={14} />
                            </button>
                        )}
                    </div>
                    {matches && (
                        <ul
                            aria-label="Beneficiarios encontrados"
                            className="absolute z-30 mt-1 w-full bg-white border border-gray-200 rounded-xl shadow-lg max-h-72 overflow-auto"
                        >
                            {matches.length === 0 && (
                                <li className="px-3 py-2 text-sm text-gray-400">Nadie con ese nombre o CI en los repartos.</li>
                            )}
                            {matches.map((m) => (
                                <li key={m.beneficiario_id}>
                                    <button
                                        type="button"
                                        onClick={() => elegir(m)}
                                        className="w-full text-left px-3 py-2 hover:bg-gray-50"
                                    >
                                        <span className="text-sm text-gray-800">{m.nombre_completo}</span>
                                        <span className="block text-xs text-gray-400">
                                            {m.ci || 'Sin CI'}
                                            {m.registro_asistido ? ' · Registro asistido' : ''} · {m.repartos} reparto(s) · último{' '}
                                            {fechaCorta(m.ultimo_reparto)}
                                        </span>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
                <label className="text-xs font-semibold text-gray-500">
                    Estado
                    <select value={filtros.estado} onChange={setFiltro('estado')} className="block mt-1 px-3 py-2 border rounded-lg text-sm font-normal text-gray-700">
                        {ESTADO_FILTROS.map((f) => (
                            <option key={f.id} value={f.id}>
                                {f.label}
                            </option>
                        ))}
                    </select>
                </label>
                <label className="text-xs font-semibold text-gray-500">
                    Desde
                    <input type="date" value={filtros.desde} max={filtros.hasta || undefined} onChange={setFiltro('desde')} className="block mt-1 px-3 py-1.5 border rounded-lg text-sm font-normal text-gray-700" />
                </label>
                <label className="text-xs font-semibold text-gray-500">
                    Hasta
                    <input type="date" value={filtros.hasta} min={filtros.desde || undefined} onChange={setFiltro('hasta')} className="block mt-1 px-3 py-1.5 border rounded-lg text-sm font-normal text-gray-700" />
                </label>
                <label className="text-xs font-semibold text-gray-500">
                    Packing list
                    <select value={filtros.ingreso} onChange={setFiltro('ingreso')} className="block mt-1 px-3 py-2 border rounded-lg text-sm font-normal text-gray-700 max-w-[16rem]">
                        <option value="">Todos</option>
                        {opcionesPackingList.map((o) => (
                            <option key={o.value} value={o.value}>
                                {o.label}
                            </option>
                        ))}
                    </select>
                </label>
                {hayFiltros(filtros) && (
                    <button
                        type="button"
                        onClick={() => setFiltros(FILTROS_INICIALES)}
                        className="px-3 py-2 rounded-lg text-sm font-semibold bg-gray-100 text-gray-700 hover:bg-gray-200"
                    >
                        Limpiar filtros
                    </button>
                )}
            </div>
            <p className="text-xs text-gray-400 mb-3">
                Las fechas son las de consolidación (cuando salió del almacén) o, si no se consolidó, las del cálculo.
            </p>

            {seleccion ? (
                <div>
                    <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2 bg-vida-bg rounded-xl p-4 mb-4">
                        <div>
                            <h3 className="text-lg font-bold text-gray-800">{persona?.nombre_completo || seleccion.nombre_completo}</h3>
                            <p className="text-xs text-gray-500">
                                {(persona?.ci ?? seleccion.ci) || 'Sin CI'}
                                {seleccion.registro_asistido ? ' · Registro asistido' : ''}
                            </p>
                        </div>
                        <p className="text-sm text-gray-700">
                            Recibió en <b>{totales.repartos}</b> reparto(s) consolidado(s): <b>{totales.envases}</b> envases ·{' '}
                            <b>{fmt(totales.ui)}</b> UI
                        </p>
                    </div>
                    <div className="overflow-x-auto border border-gray-100 rounded-xl">
                        <table className="w-full">
                            <thead className="bg-gray-50 border-b border-gray-100">
                                <tr>
                                    <TH>Reparto</TH>
                                    <TH>Fecha</TH>
                                    <TH>Tratamiento</TH>
                                    <TH>Recibió (lote, vencimiento)</TH>
                                    <TH>Cobertura</TH>
                                    <TH> </TH>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                {cargandoPersona && !persona && (
                                    <tr>
                                        <td colSpan="6" className="px-4 py-6 text-center text-gray-400">
                                            Cargando repartos...
                                        </td>
                                    </tr>
                                )}
                                {persona && entregas.length === 0 && (
                                    <tr>
                                        <td colSpan="6" className="px-4 py-6 text-center text-gray-400">
                                            No aparece en ningún reparto con estos filtros.
                                        </td>
                                    </tr>
                                )}
                                {entregas.flatMap((e) =>
                                    e.paciente.insulinas.map((i, idx) => (
                                        <tr key={`${e.distribution_id}-${i.insulina}`}>
                                            <td className="px-4 py-2 text-sm text-gray-700 align-top">
                                                {idx === 0 && (
                                                    <>
                                                        #{e.distribution_id} <Estado estado={e.estado} />
                                                        {e.intercambios > 0 && (
                                                            <span className="block text-[11px] text-amber-700">con {e.intercambios} intercambio(s)</span>
                                                        )}
                                                    </>
                                                )}
                                            </td>
                                            <td className="px-4 py-2 text-sm text-gray-700 align-top">
                                                {idx === 0 && fechaCorta(fechaReparto(e))}
                                            </td>
                                            <td className="px-4 py-2 text-sm text-gray-700">
                                                {i.insulina}
                                                {i.sustituto && (
                                                    <span className="ml-1 px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-blue-100 text-blue-700">
                                                        + {i.sustituto}
                                                    </span>
                                                )}
                                                <span className="block text-[11px] text-gray-400">{dosisTexto(i)}</span>
                                            </td>
                                            <td className="px-4 py-2 text-sm text-gray-700">
                                                {i.lotes.length ? lotesConNumeroTexto(i.lotes) : <span className="text-red-600">No recibió envases</span>}
                                            </td>
                                            <td className="px-4 py-2 text-sm text-gray-700">
                                                {i.cobertura_pct}%
                                                <span className="block text-[11px] text-gray-400">
                                                    {fmt(i.entregado_ui)} UI · ≈ {diasCubiertos(i.cobertura_pct, e.dias)} días
                                                </span>
                                            </td>
                                            <td className="px-4 py-2 text-right align-top">
                                                {idx === 0 && (
                                                    <button
                                                        type="button"
                                                        onClick={() => onOpen(e.distribution_id, persona.ci || persona.nombre_completo)}
                                                        aria-label={`Ver el reparto #${e.distribution_id}`}
                                                        className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-gray-100 text-gray-700 hover:bg-gray-200"
                                                    >
                                                        Ver
                                                    </button>
                                                )}
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            ) : (
                <>
                    <p className="text-sm text-gray-600 mb-3">
                        {filtrados.length} de {history.length} reparto(s)
                        {totales.repartos > 0 && (
                            <>
                                {' '}· salió del almacén en {totales.repartos} consolidado(s): <b>{totales.envases}</b> envases ·{' '}
                                <b>{fmt(totales.ui)}</b> UI
                            </>
                        )}
                    </p>
                    <div className="overflow-x-auto border border-gray-100 rounded-xl">
                        <table className="w-full">
                            <thead className="bg-gray-50 border-b border-gray-100">
                                <tr>
                                    {['#', 'Calculado', 'Estado', 'Packing lists', 'Beneficiarios', 'Envases', 'Asignado', 'Intercambios', 'Consolidado', ''].map((h) => (
                                        <TH key={h}>{h}</TH>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                {filtrados.length === 0 && (
                                    <tr>
                                        <td colSpan="10" className="px-4 py-6 text-center text-gray-400">
                                            {history.length === 0 ? 'Todavía no se calculó ningún reparto.' : 'Ningún reparto con estos filtros.'}
                                        </td>
                                    </tr>
                                )}
                                {filtrados.map((h) => (
                                    <tr key={h.id} className={currentId === h.id ? 'bg-vida-light/20' : ''}>
                                        <td className="px-4 py-2 text-sm text-gray-500">{h.id}</td>
                                        <td className="px-4 py-2 text-sm text-gray-700">
                                            {fechaHora(h.created_at)}
                                            <span className="block text-xs text-gray-400">{h.autor || ''}</span>
                                        </td>
                                        <td className="px-4 py-2 text-sm">
                                            <Estado estado={h.estado} />
                                        </td>
                                        <td className="px-4 py-2 text-xs text-gray-600">
                                            {(h.ingresos || []).length === 0
                                                ? '-'
                                                : h.ingresos.map((o) => (
                                                      <span key={o.ingreso_id ?? 'sin'} className="block">
                                                          {origenTexto(o)} · {o.envases} env.
                                                      </span>
                                                  ))}
                                        </td>
                                        <td className="px-4 py-2 text-sm text-gray-700">{h.beneficiarios}</td>
                                        <td className="px-4 py-2 text-sm text-gray-700">{h.envases}</td>
                                        <td className="px-4 py-2 text-sm text-gray-700">{fmt(h.asignado_ui)} UI</td>
                                        <td className="px-4 py-2 text-sm text-gray-700">{h.intercambios}</td>
                                        <td className="px-4 py-2 text-xs text-gray-500">
                                            {h.consolidated_at ? fechaHora(h.consolidated_at) : '-'}
                                            {h.consolidado_por && <span className="block">{h.consolidado_por}</span>}
                                        </td>
                                        <td className="px-4 py-2 text-right">
                                            <button
                                                type="button"
                                                onClick={() => onOpen(h.id)}
                                                aria-label={`Ver el reparto #${h.id}`}
                                                className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-gray-100 text-gray-700 hover:bg-gray-200"
                                            >
                                                Ver
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </>
            )}
        </div>
    );
}
