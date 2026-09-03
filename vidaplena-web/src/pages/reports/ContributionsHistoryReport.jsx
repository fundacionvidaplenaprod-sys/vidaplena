import { useEffect, useState } from 'react';
import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';
import * as XLSX from 'xlsx';
import { CheckCircle, Clock, AlertTriangle, Wallet, Download, FileSpreadsheet } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '../../components/ui/Button';
import { getContributionsReport } from '../../api/reports';
import logoUrl from '../../assets/logo.png';
import { imageToBase64 } from '../../utils/imageToBase64';

const ESTADO_STYLES = {
    ACEPTADO: 'bg-green-100 text-green-700 border-green-200',
    DECLARADO: 'bg-yellow-100 text-yellow-700 border-yellow-200',
    OBSERVADO: 'bg-red-100 text-red-700 border-red-200',
};

const METODO_LABELS = {
    EFECTIVO: 'Efectivo',
    VOUCHER: 'Voucher/QR',
};

const currentPeriod = () => new Date().toISOString().slice(0, 7);

export default function ContributionsHistoryReport() {
    const [periodo, setPeriodo] = useState(currentPeriod());
    const [loading, setLoading] = useState(true);
    const [data, setData] = useState(null);
    const [logoBase64, setLogoBase64] = useState(null);

    useEffect(() => {
        imageToBase64(logoUrl)
            .then((base64) => setLogoBase64(base64))
            .catch((err) => console.error('Error al cargar el logo en base64', err));
    }, []);

    const load = async (p) => {
        try {
            setLoading(true);
            const result = await getContributionsReport(p);
            setData(result);
        } catch (error) {
            toast.error(typeof error === 'string' ? error : 'No se pudo cargar el historial de aportes.');
            setData(null);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load(periodo);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [periodo]);

    const [year, month] = periodo.split('-');
    const periodoLabel = new Date(Number(year), Number(month) - 1, 1).toLocaleDateString('es-BO', {
        month: 'long',
        year: 'numeric',
    });

    const exportPDF = () => {
        if (!data || data.items.length === 0) {
            toast.error('No hay aportes registrados en este periodo para descargar.');
            return;
        }
        if (!logoBase64) {
            toast.error('El logo aún se está cargando, intente en un momento');
            return;
        }

        const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'letter' });
        const pageWidth = doc.internal.pageSize.getWidth();
        const margin = 14;

        const addHeader = () => {
            doc.setFillColor(248, 250, 252);
            doc.rect(0, 0, pageWidth, 35, 'F');
            doc.addImage(logoBase64, 'PNG', margin, 5, 25, 25);
            doc.setFontSize(18);
            doc.setTextColor(30, 58, 138);
            doc.setFont('helvetica', 'bold');
            doc.text('Fundación V.I.D.A. Plena', margin + 30, 16);
            doc.setFontSize(14);
            doc.text('Historial de Aportes Solidarios', margin + 30, 22);
            doc.setFontSize(9);
            doc.setTextColor(100, 116, 139);
            doc.setFont('helvetica', 'normal');
            doc.text(`Fecha de generación: ${new Date().toLocaleDateString('es-BO')} ${new Date().toLocaleTimeString('es-BO')}`, margin + 30, 27);
            doc.text(
                `Periodo: ${periodoLabel} | Aceptados: ${data.total_aceptados} | Pendientes: ${data.total_declarados} | Observados: ${data.total_observados}`,
                margin + 30, 32,
            );
        };

        autoTable(doc, {
            head: [['Beneficiario', 'CI', 'Depto', 'Monto (Bs.)', 'Fecha de pago', 'Método', 'Estado']],
            body: data.items.map((item) => [
                item.patient_nombre,
                item.patient_ci || 'Sin CI',
                item.depto || '-',
                item.monto.toFixed(2),
                item.fecha_pago,
                METODO_LABELS[item.metodo_pago] || item.metodo_pago,
                item.estado,
            ]),
            startY: 40,
            margin: { top: 40, left: margin, right: margin, bottom: 20 },
            styles: { fontSize: 8, cellPadding: 3, font: 'helvetica' },
            headStyles: { fillColor: [14, 165, 233], textColor: 255, fontStyle: 'bold' },
            alternateRowStyles: { fillColor: [248, 250, 252] },
            didDrawPage: () => {
                addHeader();
                const str = `Página ${doc.internal.getNumberOfPages()}`;
                doc.setFontSize(8);
                doc.setTextColor(150);
                doc.text(str, pageWidth / 2, doc.internal.pageSize.getHeight() - 10, { align: 'center' });
            },
        });

        doc.save(`Historial_Aportes_${periodo}.pdf`);
        toast.success('Reporte descargado exitosamente');
    };

    const exportXLS = () => {
        if (!data || data.items.length === 0) {
            toast.error('No hay aportes registrados en este periodo para descargar.');
            return;
        }
        const rows = data.items.map((item) => ({
            Beneficiario: item.patient_nombre,
            CI: item.patient_ci || 'Sin CI',
            Departamento: item.depto || '-',
            'Monto (Bs.)': item.monto,
            'Fecha de pago': item.fecha_pago,
            Método: METODO_LABELS[item.metodo_pago] || item.metodo_pago,
            Estado: item.estado,
        }));
        const worksheet = XLSX.utils.json_to_sheet(rows);
        const workbook = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(workbook, worksheet, 'Aportes');
        XLSX.writeFile(workbook, `Historial_Aportes_${periodo}.xlsx`);
        toast.success('Reporte descargado exitosamente');
    };

    return (
        <div>
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-6">
                <div>
                    <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
                        <Wallet size={22} /> Historial de Aportes Solidarios
                    </h2>
                    <p className="text-sm text-gray-500">
                        Elija un mes para ver cuántos beneficiarios hicieron su aporte ese periodo.
                    </p>
                </div>
                <div className="flex items-end gap-2">
                    <div>
                        <label className="block text-xs font-semibold text-gray-700 mb-1">Mes</label>
                        <input
                            type="month"
                            value={periodo}
                            onChange={(e) => setPeriodo(e.target.value)}
                            className="border rounded-lg px-3 py-2 text-sm bg-white"
                        />
                    </div>
                    <Button
                        onClick={exportPDF}
                        disabled={loading || !data || data.items.length === 0}
                        className="bg-green-600 hover:bg-green-700 text-white w-auto justify-center"
                    >
                        <Download size={18} />
                        PDF
                    </Button>
                    <Button
                        onClick={exportXLS}
                        disabled={loading || !data || data.items.length === 0}
                        className="bg-emerald-700 hover:bg-emerald-800 text-white w-auto justify-center"
                    >
                        <FileSpreadsheet size={18} />
                        Excel
                    </Button>
                </div>
            </div>

            {loading ? (
                <div className="p-10 text-center text-gray-500 font-semibold">Cargando...</div>
            ) : !data ? (
                <div className="bg-white border border-gray-100 rounded-xl p-6 text-sm text-gray-500">
                    No se pudo cargar el historial.
                </div>
            ) : (
                <>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                        <div className="bg-white rounded-2xl border border-green-100 shadow-sm p-4">
                            <p className="text-xs text-green-700 uppercase font-semibold flex items-center gap-1">
                                <CheckCircle size={14} /> Aportes aceptados
                            </p>
                            <p className="text-3xl font-bold text-green-700 mt-1">{data.total_aceptados}</p>
                            <p className="text-xs text-gray-400 mt-1 capitalize">Beneficiarios al día en {periodoLabel}</p>
                        </div>
                        <div className="bg-white rounded-2xl border border-yellow-100 shadow-sm p-4">
                            <p className="text-xs text-yellow-700 uppercase font-semibold flex items-center gap-1">
                                <Clock size={14} /> Pendientes de revisión
                            </p>
                            <p className="text-3xl font-bold text-yellow-700 mt-1">{data.total_declarados}</p>
                            <p className="text-xs text-gray-400 mt-1">Declarados, aún sin validar</p>
                        </div>
                        <div className="bg-white rounded-2xl border border-red-100 shadow-sm p-4">
                            <p className="text-xs text-red-700 uppercase font-semibold flex items-center gap-1">
                                <AlertTriangle size={14} /> Observados
                            </p>
                            <p className="text-3xl font-bold text-red-700 mt-1">{data.total_observados}</p>
                            <p className="text-xs text-gray-400 mt-1">Rechazados / con observación</p>
                        </div>
                    </div>

                    <div className="bg-white rounded-2xl shadow-xl border border-gray-100 overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead className="bg-gray-50 border-b border-gray-100">
                                    <tr>
                                        <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Beneficiario</th>
                                        <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">CI</th>
                                        <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Depto</th>
                                        <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Monto (Bs.)</th>
                                        <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Fecha de pago</th>
                                        <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Método</th>
                                        <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Estado</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100">
                                    {data.items.length === 0 ? (
                                        <tr>
                                            <td colSpan="7" className="px-4 py-6 text-center text-gray-400 capitalize">
                                                Nadie registró aportes en {periodoLabel}.
                                            </td>
                                        </tr>
                                    ) : (
                                        data.items.map((item) => (
                                            <tr key={item.patient_id} className="hover:bg-gray-50/70 transition-colors">
                                                <td className="px-4 py-3 text-sm text-gray-800 font-medium">{item.patient_nombre}</td>
                                                <td className="px-4 py-3 text-sm text-gray-600">{item.patient_ci || 'Sin CI'}</td>
                                                <td className="px-4 py-3 text-sm text-gray-600">{item.depto || '-'}</td>
                                                <td className="px-4 py-3 text-sm text-right text-gray-700">{item.monto.toFixed(2)}</td>
                                                <td className="px-4 py-3 text-sm text-gray-600">{item.fecha_pago}</td>
                                                <td className="px-4 py-3 text-sm text-gray-600">{item.metodo_pago === 'EFECTIVO' ? 'Efectivo' : 'Voucher/QR'}</td>
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
                </>
            )}
        </div>
    );
}
