import { useEffect, useState } from 'react';
import * as XLSX from 'xlsx';
import { Download, FileSpreadsheet, FileText, ImageOff, ReceiptText } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '../../components/ui/Button';
import { getContributionsReview, downloadVouchersControlPdf, periodLabel } from '../../api/contributions';
import { DEPARTAMENTOS } from '../../constants/departamentos';

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
    const [desde, setDesde] = useState(currentPeriod());
    const [hasta, setHasta] = useState(currentPeriod());
    const [depto, setDepto] = useState('');
    const [todosLosPeriodos, setTodosLosPeriodos] = useState(false);
    const [loading, setLoading] = useState(true);
    const [items, setItems] = useState([]);
    const [downloading, setDownloading] = useState(false);

    // Rango efectivo: con «Todos los periodos» no se acota por fecha.
    const rango = todosLosPeriodos ? {} : { desde, hasta };
    const rangoInvalido = !todosLosPeriodos && desde && hasta && desde > hasta;
    const filtros = { ...rango, depto };

    const load = async () => {
        if (rangoInvalido) {
            toast.error('El mes «Desde» no puede ser posterior a «Hasta».');
            return;
        }
        try {
            setLoading(true);
            const data = await getContributionsReview(filtros);
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
    }, [todosLosPeriodos, desde, hasta, depto]);

    const handleDownload = async () => {
        try {
            setDownloading(true);
            await downloadVouchersControlPdf(filtros);
        } catch (error) {
            console.error(error);
            toast.error('No se pudo generar el reporte en PDF.');
        } finally {
            setDownloading(false);
        }
    };

    const handleExcel = () => {
        const rows = items.map((item) => ({
            Beneficiario: item.patient_nombre,
            CI: item.patient_ci || 'Sin CI',
            Departamento: item.depto || '-',
            'Fecha de pago': item.fecha_pago,
            'Monto (Bs.)': item.monto,
            Estado: item.estado,
            'Enlace al comprobante': item.url_comprobante || '',
            // A la derecha de los datos del beneficiario: a qué periodo pertenece el voucher de la fila.
            Periodo: item.periodo,
        }));
        const sorted = [...rows].sort(
            (a, b) => a.Beneficiario.localeCompare(b.Beneficiario, 'es') || a.Periodo.localeCompare(b.Periodo),
        );
        const worksheet = XLSX.utils.json_to_sheet(sorted);
        worksheet['!autofilter'] = { ref: worksheet['!ref'] };
        const workbook = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(workbook, worksheet, 'Vouchers');
        XLSX.writeFile(workbook, `Control_Vouchers_${periodLabel(filtros)}.xlsx`);
        toast.success('Reporte descargado exitosamente');
    };

    return (
        <div>
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-6">
                <div>
                    <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
                        <ReceiptText size={22} /> Control de Vouchers
                    </h2>
                    <p className="text-sm text-gray-500">
                        Lista general de todos los beneficiarios con la captura de su comprobante, para imprimir/descargar un PDF de control o un Excel. Elija un mes o un rango de meses; cada fila indica su periodo.
                    </p>
                </div>
                <div className="flex items-end gap-2 flex-wrap">
                    <div>
                        <label className="block text-xs font-semibold text-gray-700 mb-1" htmlFor="vouchers-desde">Desde</label>
                        <input
                            id="vouchers-desde"
                            type="month"
                            value={desde}
                            max={hasta || undefined}
                            onChange={(e) => setDesde(e.target.value)}
                            disabled={todosLosPeriodos}
                            className="border rounded-lg px-3 py-2 text-sm bg-white disabled:bg-gray-100 disabled:text-gray-400"
                        />
                    </div>
                    <div>
                        <label className="block text-xs font-semibold text-gray-700 mb-1" htmlFor="vouchers-hasta">Hasta</label>
                        <input
                            id="vouchers-hasta"
                            type="month"
                            value={hasta}
                            min={desde || undefined}
                            onChange={(e) => setHasta(e.target.value)}
                            disabled={todosLosPeriodos}
                            className="border rounded-lg px-3 py-2 text-sm bg-white disabled:bg-gray-100 disabled:text-gray-400"
                        />
                    </div>
                    <div>
                        <label className="block text-xs font-semibold text-gray-700 mb-1" htmlFor="vouchers-depto">Departamento</label>
                        <select
                            id="vouchers-depto"
                            value={depto}
                            onChange={(e) => setDepto(e.target.value)}
                            className="border rounded-lg px-3 py-2 text-sm bg-white"
                        >
                            <option value="">Todos</option>
                            {DEPARTAMENTOS.map((d) => (
                                <option key={d} value={d}>{d}</option>
                            ))}
                        </select>
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
                    <Button
                        onClick={handleExcel}
                        disabled={loading || items.length === 0}
                        className="bg-emerald-700 hover:bg-emerald-800 text-white w-auto justify-center"
                    >
                        <FileSpreadsheet size={18} />
                        Excel
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
                                <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Departamento</th>
                                <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Periodo</th>
                                <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Fecha de pago</th>
                                <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Estado</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                            {loading ? (
                                <tr>
                                    <td colSpan="7" className="px-4 py-10 text-center text-gray-500">Cargando...</td>
                                </tr>
                            ) : items.length === 0 ? (
                                <tr>
                                    <td colSpan="7" className="px-4 py-6 text-center text-gray-400">
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
                                        <td className="px-4 py-3 text-sm text-gray-600">{item.depto || '-'}</td>
                                        <td className="px-4 py-3 text-sm text-gray-600 whitespace-nowrap">{item.periodo}</td>
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
