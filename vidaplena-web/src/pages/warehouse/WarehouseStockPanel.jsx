import { Fragment, useMemo, useState } from 'react';
import { toast } from 'react-hot-toast';
import { listLotMovements } from '../../api/donations';
import { fmt } from '../../utils/insulinDistribution';

const vencePronto = (fecha) => fecha && (new Date(fecha) - new Date()) / 86400000 < 60;

// Stock del almacén por lote: lo ingresado, lo disponible y sus movimientos (entradas y salidas por reparto).
export default function WarehouseStockPanel({ stock, soloDisponibles, onToggleDisponibles }) {
    const [abierto, setAbierto] = useState(null);
    const [movimientos, setMovimientos] = useState([]);

    const porInsulina = useMemo(() => {
        const out = new Map();
        stock.forEach((s) => {
            if (s.vencido) return;
            const key = s.insulina || 'Sin catálogo';
            out.set(key, (out.get(key) || 0) + s.disponibles * s.ui_por_envase);
        });
        return [...out.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    }, [stock]);

    const toggleMovimientos = async (lotId) => {
        if (abierto === lotId) {
            setAbierto(null);
            return;
        }
        try {
            setMovimientos(await listLotMovements(lotId));
            setAbierto(lotId);
        } catch (error) {
            toast.error(typeof error === 'string' ? error : 'No se pudieron cargar los movimientos');
        }
    };

    return (
        <div>
            <div className="flex flex-wrap gap-3 mb-4">
                {porInsulina.map(([insulina, ui]) => (
                    <div key={insulina} className="bg-vida-bg rounded-xl px-4 py-3">
                        <p className="text-xs text-gray-500">{insulina}</p>
                        <p className="text-base font-bold text-gray-800">{fmt(ui)} UI</p>
                    </div>
                ))}
            </div>
            <label className="text-sm text-gray-600 flex items-center gap-1 mb-3">
                <input type="checkbox" checked={soloDisponibles} onChange={(e) => onToggleDisponibles(e.target.checked)} />
                Solo lotes con envases disponibles
            </label>
            <div className="overflow-x-auto border border-gray-100 rounded-xl">
                <table className="w-full">
                    <thead className="bg-gray-50 border-b border-gray-100">
                        <tr>
                            {['Insulina', 'Producto', 'Presentación', 'UI/envase', 'Lote', 'Vence', 'Ingresados', 'Disponibles', 'Ingreso', ''].map((h) => (
                                <th key={h} className="px-3 py-2 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">
                                    {h}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                        {stock.length === 0 && (
                            <tr>
                                <td colSpan="10" className="px-4 py-6 text-center text-gray-400">
                                    Sin lotes en el almacén.
                                </td>
                            </tr>
                        )}
                        {stock.map((s) => (
                            <Fragment key={s.lot_id}>
                                <tr className={s.vencido ? 'bg-red-50/50' : ''}>
                                    <td className="px-3 py-2 text-sm text-gray-700">{s.insulina || <span className="text-red-600">sin catálogo</span>}</td>
                                    <td className="px-3 py-2 text-sm text-gray-800">{s.producto}</td>
                                    <td className="px-3 py-2 text-sm text-gray-700">
                                        {s.presentacion_ml ? `${s.presentacion_ml} ml · U${s.concentracion_ui_ml}` : '-'}
                                    </td>
                                    <td className="px-3 py-2 text-sm text-gray-700">{fmt(s.ui_por_envase)}</td>
                                    <td className="px-3 py-2 text-sm text-gray-700">{s.lote || '-'}</td>
                                    <td
                                        className={`px-3 py-2 text-sm ${
                                            s.vencido ? 'text-red-600 font-semibold' : vencePronto(s.fecha_venc) ? 'text-amber-600 font-semibold' : 'text-gray-700'
                                        }`}
                                    >
                                        {s.fecha_venc || '-'}
                                        {s.vencido && <span className="block text-[10px]">vencido: no se reparte</span>}
                                    </td>
                                    <td className="px-3 py-2 text-sm text-gray-700">{s.cantidad_total}</td>
                                    <td className="px-3 py-2 text-sm font-semibold text-gray-800">{s.disponibles}</td>
                                    <td className="px-3 py-2 text-xs text-gray-500">{s.ingreso_archivo || '-'}</td>
                                    <td className="px-3 py-2 text-right">
                                        <button
                                            type="button"
                                            onClick={() => toggleMovimientos(s.lot_id)}
                                            className="px-2 py-1 rounded-md text-xs font-semibold bg-gray-100 text-gray-700 hover:bg-gray-200"
                                        >
                                            {abierto === s.lot_id ? 'Ocultar' : 'Movimientos'}
                                        </button>
                                    </td>
                                </tr>
                                {abierto === s.lot_id && (
                                    <tr>
                                        <td colSpan="10" className="px-6 py-3 bg-gray-50">
                                            {movimientos.length === 0 ? (
                                                <p className="text-xs text-gray-400">Sin movimientos.</p>
                                            ) : (
                                                <ul className="text-xs text-gray-700 space-y-1">
                                                    {movimientos.map((m) => (
                                                        <li key={m.id}>
                                                            {new Date(m.created_at).toLocaleString('es-BO')} ·{' '}
                                                            <b className={m.tipo === 'ENTRADA' ? 'text-blue-700' : 'text-orange-700'}>{m.tipo}</b> ·{' '}
                                                            {m.cantidad} envases · {m.referencia || '-'}
                                                        </li>
                                                    ))}
                                                </ul>
                                            )}
                                        </td>
                                    </tr>
                                )}
                            </Fragment>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
