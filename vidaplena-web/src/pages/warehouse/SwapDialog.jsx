import { useEffect, useState } from 'react';
import { ArrowLeftRight, X } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { createDistributionSwap, getDistributionSwapOptions } from '../../api/donations';
import { fmt } from '../../utils/insulinDistribution';

// Intercambio equivalente: el beneficiario de la fila entrega `envases` de un lote y recibe de otro beneficiario
// la misma cantidad de UI de otro producto que le sirva. El servidor solo ofrece (y solo acepta) intercambios que no
// cambian la cobertura de nadie ni lo que sale de cada lote, y que respetan las reglas del reparto.
export default function SwapDialog({ distributionId, row, column, onClose, onSwapped }) {
    const lots = row.cells[column.donationId]?.lots || [];
    const [lotId, setLotId] = useState(lots[0]?.lot_id ?? null);
    const lot = lots.find((l) => l.lot_id === lotId) || lots[0];
    const [envases, setEnvases] = useState(1);
    const [options, setOptions] = useState(null);
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(null);

    const selectedLotId = lot?.lot_id;
    const beneficiarioId = row.paciente.patient_id;
    const insulina = row.insulina.insulina;

    useEffect(() => {
        if (!selectedLotId) return undefined;
        let cancelled = false;
        setLoading(true);
        getDistributionSwapOptions(distributionId, { beneficiarioId, insulina, lotId: selectedLotId, envases })
            .then((data) => !cancelled && setOptions(data))
            .catch((error) => {
                if (!cancelled) {
                    setOptions(null);
                    toast.error(typeof error === 'string' ? error : 'No se pudieron buscar intercambios');
                }
            })
            .finally(() => !cancelled && setLoading(false));
        return () => {
            cancelled = true;
        };
    }, [distributionId, beneficiarioId, insulina, selectedLotId, envases]);

    const handleSwap = async (option) => {
        try {
            setSaving(`${option.beneficiario_id}-${option.lot_id}`);
            const detail = await createDistributionSwap(distributionId, {
                beneficiario_id: row.paciente.patient_id,
                insulina: row.insulina.insulina,
                lot_id: lot.lot_id,
                envases,
                con_beneficiario_id: option.beneficiario_id,
                con_insulina: option.insulina,
                con_lot_id: option.lot_id,
                con_envases: option.envases,
            });
            toast.success('Intercambio hecho: la cobertura de los dos no cambió');
            onSwapped(detail);
        } catch (error) {
            toast.error(typeof error === 'string' ? error : 'No se pudo hacer el intercambio');
        } finally {
            setSaving(null);
        }
    };

    if (!lot) return null;
    return (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4" role="dialog" aria-label="Intercambiar envases">
            <div className="bg-white rounded-2xl shadow-2xl max-w-3xl w-full max-h-[90vh] flex flex-col overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-100 flex justify-between items-center bg-gray-50/50">
                    <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
                        <ArrowLeftRight size={20} /> Intercambio equivalente
                    </h3>
                    <button type="button" onClick={onClose} aria-label="Cerrar" className="p-1 rounded-full hover:bg-gray-200 text-gray-400">
                        <X size={20} />
                    </button>
                </div>
                <div className="p-6 overflow-y-auto">
                    <p className="text-sm text-gray-700 mb-4">
                        <b>{row.paciente.nombre_completo}</b> ({row.insulina.insulina}) entrega envases de <b>{column.producto}</b> y
                        recibe a cambio la misma cantidad de UI de otro producto que le sirva. A la otra persona le pasa lo mismo al
                        revés: la cobertura de los dos y el stock que sale no cambian.
                    </p>
                    <div className="flex flex-wrap gap-4 mb-5">
                        {lots.length > 1 && (
                            <label className="text-sm text-gray-700">
                                Lote
                                <select
                                    value={lot.lot_id}
                                    onChange={(e) => {
                                        setLotId(Number(e.target.value));
                                        setEnvases(1);
                                    }}
                                    className="ml-2 px-2 py-1 border rounded-lg text-sm"
                                >
                                    {lots.map((l) => (
                                        <option key={l.lot_id} value={l.lot_id}>
                                            {l.lote || `#${l.lot_id}`} · {l.unidades} env.{l.fecha_venc ? ` · vence ${l.fecha_venc}` : ''}
                                        </option>
                                    ))}
                                </select>
                            </label>
                        )}
                        <label className="text-sm text-gray-700">
                            Envases a entregar
                            <select
                                value={envases}
                                onChange={(e) => setEnvases(Number(e.target.value))}
                                className="ml-2 px-2 py-1 border rounded-lg text-sm"
                                aria-label="Envases a entregar"
                            >
                                {Array.from({ length: lot.unidades }, (_, k) => k + 1).map((n) => (
                                    <option key={n} value={n}>
                                        {n} ({fmt(n * column.uiPorEnvase)} UI)
                                    </option>
                                ))}
                            </select>
                        </label>
                    </div>

                    {loading && <p className="text-sm text-gray-400 py-6 text-center">Buscando intercambios posibles...</p>}
                    {!loading && options && options.opciones.length === 0 && (
                        <p className="text-sm text-gray-500 py-6 text-center">
                            Nadie puede darle {fmt(options.ui)} UI de otro producto sin cambiar el reparto ni romper una regla
                            (equivalencia, sustitutos permitidos, Lantus y sustitutos en menores).
                        </p>
                    )}
                    {!loading && options && options.opciones.length > 0 && (
                        <div className="overflow-x-auto border border-gray-100 rounded-xl">
                            <table className="w-full">
                                <thead className="bg-gray-50 border-b border-gray-100">
                                    <tr>
                                        {['Con', 'Su tratamiento', 'Recibe a cambio', ''].map((h) => (
                                            <th key={h} className="px-3 py-2 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">
                                                {h}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100">
                                    {options.opciones.map((o) => (
                                        <tr key={`${o.beneficiario_id}-${o.insulina}-${o.lot_id}`}>
                                            <td className="px-3 py-2 text-sm text-gray-800">
                                                {o.nombre_completo}
                                                <span className="block text-xs text-gray-400">
                                                    {o.ci || 'Sin CI'} · {o.grupo_prioridad_nombre}
                                                </span>
                                            </td>
                                            <td className="px-3 py-2 text-sm text-gray-700">{o.insulina}</td>
                                            <td className="px-3 py-2 text-sm text-gray-700">
                                                {o.envases} × {o.producto}
                                                <span className="block text-xs text-gray-400">
                                                    {fmt(o.ui)} UI · lote {o.lote || '-'}
                                                    {o.fecha_venc ? ` · vence ${o.fecha_venc}` : ''}
                                                </span>
                                                {!o.misma_insulina && (
                                                    <span className="block text-[10px] font-semibold text-blue-700">
                                                        sustituto permitido por la tabla del reparto
                                                    </span>
                                                )}
                                            </td>
                                            <td className="px-3 py-2 text-right">
                                                <button
                                                    type="button"
                                                    onClick={() => handleSwap(o)}
                                                    disabled={saving !== null}
                                                    className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-vida-main text-white hover:bg-vida-hover disabled:opacity-50"
                                                >
                                                    {saving === `${o.beneficiario_id}-${o.lot_id}` ? 'Intercambiando...' : 'Intercambiar'}
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
