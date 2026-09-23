import { useEffect, useState } from 'react';
import { Download, FileText, ImageOff, ReceiptText } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '../../components/ui/Button';
import { getContributionsReview, downloadVouchersControlPdf } from '../../api/contributions';

const ESTADO_STYLES = {
    ACEPTADO: 'bg-green-100 text-green-700 border-green-200',
    DECLARADO: 'bg-yellow-100 text-yellow-700 border-yellow-200',
    OBSERVADO: 'bg-red-100 text-red-700 border-red-200',
};

const currentPeriod = () => new Date().toISOString().slice(0, 7);

// Control de Vouchers (Reportes): a diferencia del historial de un
// beneficiario puntual (en su ficha) o de la Revisión de Aportes (que
// filtra por estado, sin imagen), esta vista lista TODOS los beneficiarios
// con la captura de su comprobante, para poder imprimir/descargar un PDF
// general de control.
export default function VoucherControlReport() {
    const [periodo, setPeriodo] = useState(currentPeriod());
    const [todosLosPeriodos, setTodosLosPeriodos] = useState(false);
    const [loading, setLoading] = useState(true);
    const [items, setItems] = useState([]);
    const [downloading, setDownloading] = useState(false);

    const periodoEfectivo = todosLosPeriodos ? '' : periodo;

    const load = async () => {
        try {
            setLoading(true);
            const data = await getContributionsReview({ periodo: periodoEfectivo || undefined });
            setItems(Array.isArray(data) ? data : []);
        } catch (error) {
            console.error(error);
            toast.error('No se pudo cargar la lista de vouchers.');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [periodoEfectivo]);

    const handleDownload = async () => {
        try {
            setDownloading(true);
            await downloadVouchersControlPdf(periodoEfectivo);
        } catch (error) {
            console.error(error);
            toast.error('No se pudo generar el reporte en PDF.');
        } finally {
            setDownloading(false);
        }
    };

    return (
        <div>
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-6">
                <div>
                    <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
                        <ReceiptText size={22} /> Control de Vouchers
                    </h2>
                    <p className="text-sm text-gray-500">
                        Lista general de todos los beneficiarios con la captura de su comprobante, para imprimir/descargar un PDF de control.
                    </p>
                </div>
                <div className="flex items-end gap-2 flex-wrap">
                    <div>
                        <label className="block text-xs font-semibold text-gray-700 mb-1">Mes</label>
                        <input
                            type="month"
                            value={periodo}
                            onChange={(e) => setPeriodo(e.target.value)}
                            disabled={todosLosPeriodos}
                            className="border rounded-lg px-3 py-2 text-sm bg-white disabled:bg-gray-100 disabled:text-gray-400"
                        />
                    </div>
                    <label className="flex items-center gap-2 text-sm text-gray-600 pb-2 cursor-pointer select-none">
                        <input
                            type="checkbox"
                            checked={todosLosPeriodos}
                            onChange={(e) => setTodosLosPeriodos(e.target.checked)}
                            className="rounded text-vida-main focus:ring-vida-main"
                        />
                        Todos los periodos
                    </label>
                    <Button
                        onClick={handleDownload}
                        disabled={downloading || loading || items.length === 0}
                        className="bg-green-600 hover:bg-green-700 text-white w-auto justify-center"
                    >
                        <Download size={18} />
                        {downloading ? 'Generando...' : 'Descargar PDF'}
                    </Button>
                </div>
            </div>

            {todosLosPeriodos && items.length > 100 && (
                <div className="mb-4 bg-amber-50 border border-amber-100 rounded-xl p-3 text-xs text-amber-700">
                    Con "Todos los periodos" hay {items.length} vouchers — el PDF con capturas incrustadas puede tardar en generarse.
                </div>
            )}

            <div className="bg-white rounded-2xl shadow-xl border border-gray-100 overflow-hidden">
                <div className="overflow-x-auto">
                    <table className="w-full">
                        <thead className="bg-gray-50 border-b border-gray-100">
                            <tr>
                                <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Captura</th>
                                <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Beneficiario</th>
                                <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">CI</th>
                                <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Fecha de pago</th>
                                <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Estado</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                            {loading ? (
                                <tr>
                                    <td colSpan="5" className="px-4 py-10 text-center text-gray-500">Cargando...</td>
                                </tr>
                            ) : items.length === 0 ? (
                                <tr>
                                    <td colSpan="5" className="px-4 py-6 text-center text-gray-400">
                                        No hay vouchers para el filtro seleccionado.
                                    </td>
                                </tr>
                            ) : (
                                items.map((item) => (
                                    <tr key={item.id} className="hover:bg-gray-50/70 transition-colors">
                                        <td className="px-4 py-2">
                                            {item.url_comprobante ? (
                                                <a href={item.url_comprobante} target="_blank" rel="noreferrer">
                                                    <img
                                                        src={item.url_comprobante}
                                                        alt="Comprobante"
                                                        className="w-10 h-12 object-cover rounded border border-gray-200"
                                                        onError={(e) => { e.currentTarget.style.display = 'none'; e.currentTarget.nextSibling.style.display = 'flex'; }}
                                                    />
                                                    <span className="hidden w-10 h-12 items-center justify-center rounded border border-gray-200 bg-gray-50 text-gray-400">
                                                        <FileText size={16} />
                                                    </span>
                                                </a>
                                            ) : (
                                                <span className="flex w-10 h-12 items-center justify-center rounded border border-dashed border-gray-200 bg-gray-50 text-gray-300">
                                                    <ImageOff size={16} />
                                                </span>
                                            )}
                                        </td>
                                        <td className="px-4 py-3 text-sm text-gray-800 font-medium">{item.patient_nombre}</td>
                                        <td className="px-4 py-3 text-sm text-gray-600">{item.patient_ci || 'Sin CI'}</td>
                                        <td className="px-4 py-3 text-sm text-gray-600">{item.fecha_pago}</td>
                                        <td className="px-4 py-3 text-sm text-right">
                                            <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-bold border ${ESTADO_STYLES[item.estado] || 'bg-gray-100 text-gray-600 border-gray-200'}`}>
                                                {item.estado}
                                            </span>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
