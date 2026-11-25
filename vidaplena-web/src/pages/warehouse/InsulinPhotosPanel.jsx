import { useEffect, useState } from 'react';
import { Camera, FileText } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { listInsulinPhotos } from '../../api/donations';
import { FOTO_ESTADOS, FOTO_TITULOS, esPdf } from '../../utils/insulinDistribution';
import PhotoReviewDialog from './PhotoReviewDialog';

const FILTROS = [
    { id: 'PENDIENTE', label: 'Por revisar' },
    { id: 'OBSERVADA', label: 'Observadas' },
    { id: 'APROBADA', label: 'Aprobadas' },
    { id: '', label: 'Todas' },
];

// Fotos de control que suben los beneficiarios desde su portal (sus insulinas ya usadas y su hemoglobina
// glucosilada), aunque todavía no tengan un reparto. El SUPER_ADMIN las revisa una tras otra: las aprueba o las
// observa diciendo qué corregir. `onCambio` avisa que cambió algo (para el contador de la pestaña).
export default function InsulinPhotosPanel({ onCambio }) {
    const [estado, setEstado] = useState('PENDIENTE');
    const [q, setQ] = useState('');
    const clave = `${estado}|${q.trim()}`;
    // Resultado de la búsqueda, marcado con la búsqueda que lo produjo: mientras no coincide, está cargando.
    const [resultado, setResultado] = useState({ clave: null, fotos: [] });
    const [revisandoId, setRevisandoId] = useState(null);

    useEffect(() => {
        let vigente = true;
        const t = setTimeout(
            () => {
                listInsulinPhotos({ estado: estado || null, q })
                    .then((fotos) => vigente && setResultado({ clave, fotos: Array.isArray(fotos) ? fotos : [] }))
                    .catch((error) => {
                        if (!vigente) return;
                        toast.error(typeof error === 'string' ? error : 'No se pudieron cargar las fotos');
                        setResultado({ clave, fotos: [] });
                    });
            },
            q.trim() ? 300 : 0
        );
        return () => {
            vigente = false;
            clearTimeout(t);
        };
    }, [estado, q, clave]);

    const cargando = resultado.clave !== clave;
    const fotos = cargando ? [] : resultado.fotos;
    const pendientes = fotos.filter((f) => f.estado === 'PENDIENTE');
    const revisando = fotos.find((f) => f.id === revisandoId);

    // Guarda la revisión en la lista y, si era una por revisar, abre la siguiente (después de la actual; si no, desde
    // el principio).
    const fotoRevisada = (revisada) => {
        const i = fotos.findIndex((f) => f.id === revisada.id);
        const eraPendiente = fotos[i]?.estado === 'PENDIENTE';
        const actualizadas = fotos.map((f) => (f.id === revisada.id ? { ...f, ...revisada } : f));
        const orden = [...actualizadas.slice(i + 1), ...actualizadas.slice(0, i)];
        const siguiente = eraPendiente ? orden.find((f) => f.estado === 'PENDIENTE') : null;
        // En «Por revisar», la revisada sale de la lista.
        setResultado({ clave, fotos: estado === 'PENDIENTE' ? actualizadas.filter((f) => f.id !== revisada.id) : actualizadas });
        setRevisandoId(siguiente ? siguiente.id : null);
        onCambio?.();
    };

    return (
        <div>
            <p className="text-sm text-gray-500 mb-4">
                Las fotos que suben los beneficiarios desde su portal: sus insulinas ya usadas (envases vacíos de la entrega
                anterior) y su último resultado de hemoglobina glucosilada. Apruébelas u obsérvelas diciendo qué debe
                corregir; el beneficiario ve el motivo en su portal y sube otra.
            </p>
            <div className="flex flex-wrap items-end gap-3 mb-4">
                <label className="text-xs font-semibold text-gray-500">
                    Estado
                    <select
                        value={estado}
                        onChange={(e) => setEstado(e.target.value)}
                        className="mt-1 block px-3 py-2 border rounded-lg text-sm text-gray-800 bg-white"
                    >
                        {FILTROS.map((f) => (
                            <option key={f.id} value={f.id}>
                                {f.label}
                            </option>
                        ))}
                    </select>
                </label>
                <label className="text-xs font-semibold text-gray-500">
                    Buscar beneficiario
                    <input
                        type="search"
                        value={q}
                        onChange={(e) => setQ(e.target.value.slice(0, 80))}
                        placeholder="Nombre o C.I."
                        className="mt-1 block w-64 max-w-full px-3 py-2 border rounded-lg text-sm text-gray-800"
                    />
                </label>
                {pendientes.length > 0 && (
                    <button
                        type="button"
                        onClick={() => setRevisandoId(pendientes[0].id)}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-amber-600 text-white hover:bg-amber-700"
                    >
                        <Camera size={16} /> Revisar una tras otra ({pendientes.length})
                    </button>
                )}
            </div>

            {cargando ? (
                <p className="text-sm text-gray-400 py-10 text-center">Cargando fotos...</p>
            ) : fotos.length === 0 ? (
                <p className="text-sm text-gray-400 py-10 text-center">
                    {estado === 'PENDIENTE' && !q.trim() ? 'No hay fotos por revisar.' : 'No hay fotos con ese filtro.'}
                </p>
            ) : (
                <div className="overflow-x-auto bg-white border border-gray-100 rounded-xl">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="text-left text-xs font-bold text-gray-500 uppercase bg-gray-50">
                                <th className="px-4 py-2">Beneficiario</th>
                                <th className="px-4 py-2">CI</th>
                                <th className="px-4 py-2">Foto</th>
                                <th className="px-4 py-2">Subida</th>
                                <th className="px-4 py-2">Estado</th>
                                <th className="px-4 py-2" />
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                            {fotos.map((f) => (
                                <tr key={f.id}>
                                    <td className="px-4 py-2 text-gray-800">{f.nombre_completo}</td>
                                    <td className="px-4 py-2 text-gray-500">{f.ci || '-'}</td>
                                    <td className="px-4 py-2">
                                        <span className="flex items-center gap-2 text-gray-700">
                                            {esPdf(f.url) ? (
                                                <span className="h-9 w-9 rounded bg-red-50 text-red-700 flex items-center justify-center">
                                                    <FileText size={18} />
                                                </span>
                                            ) : (
                                                <img src={f.url} alt="" className="h-9 w-9 rounded object-cover border border-gray-200" />
                                            )}
                                            {FOTO_TITULOS[f.tipo]}
                                        </span>
                                    </td>
                                    <td className="px-4 py-2 text-xs text-gray-500 whitespace-nowrap">
                                        {new Date(f.subida_at).toLocaleString('es-BO')}
                                    </td>
                                    <td className="px-4 py-2">
                                        <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${FOTO_ESTADOS[f.estado].clase}`}>
                                            {FOTO_ESTADOS[f.estado].label}
                                        </span>
                                        {f.estado === 'OBSERVADA' && f.observacion && (
                                            <p className="mt-1 text-xs text-red-700">{f.observacion}</p>
                                        )}
                                    </td>
                                    <td className="px-4 py-2 text-right">
                                        <button
                                            type="button"
                                            onClick={() => setRevisandoId(f.id)}
                                            aria-label={`Revisar ${FOTO_TITULOS[f.tipo].toLowerCase()} de ${f.nombre_completo}`}
                                            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-gray-100 text-gray-700 hover:bg-gray-200"
                                        >
                                            {f.estado === 'PENDIENTE' ? 'Revisar' : 'Ver'}
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {revisando && (
                <PhotoReviewDialog
                    key={revisando.id}
                    foto={revisando}
                    beneficiario={revisando}
                    restantes={pendientes.filter((f) => f.id !== revisando.id).length}
                    onClose={() => setRevisandoId(null)}
                    onReviewed={fotoRevisada}
                />
            )}
        </div>
    );
}
