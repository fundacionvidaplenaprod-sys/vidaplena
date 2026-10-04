import { useEffect, useState } from 'react';
import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';
import * as XLSX from 'xlsx';
import { AlertTriangle, Clock, XCircle, Download, FileSpreadsheet, UserX } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '../../components/ui/Button';
import { getMorososReport } from '../../api/reports';
import { DEPARTAMENTOS } from '../../constants/departamentos';
import logoUrl from '../../assets/logo.png';
import { imageToBase64 } from '../../utils/imageToBase64';

const MOTIVO_LABELS = {
    SIN_APORTE: 'No registró aporte',
    DECLARADO: 'Aporte pendiente de revisión',
    OBSERVADO: 'Aporte observado',
};

const MOTIVO_STYLES = {
    SIN_APORTE: 'bg-red-100 text-red-700 border-red-200',
    DECLARADO: 'bg-yellow-100 text-yellow-700 border-yellow-200',
    OBSERVADO: 'bg-orange-100 text-orange-700 border-orange-200',
};

// Mes anterior: el reporte evalúa por defecto el último mes ya cerrado, para
// no marcar como deudor a todo el mundo en los primeros días del mes en curso.
const mesAnterior = () => {
    const d = new Date();
    d.setDate(1);
    d.setMonth(d.getMonth() - 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};

export default function MorososReport() {
    const [periodo, setPeriodo] = useState(mesAnterior());
    const [depto, setDepto] = useState('');
    const [loading, setLoading] = useState(true);
    const [data, setData] = useState(null);
    const [logoBase64, setLogoBase64] = useState(null);

    useEffect(() => {
        imageToBase64(logoUrl)
            .then((base64) => setLogoBase64(base64))
            .catch((err) => console.error('Error al cargar el logo en base64', err));
    }, []);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            if (!/^\d{4}-\d{2}$/.test(periodo)) return;
            try {
                setLoading(true);
                const result = await getMorososReport(periodo, depto);
                if (!cancelled) setData(result);
            } catch (error) {
                if (!cancelled) {
                    toast.error(typeof error === 'string' ? error : 'No se pudo cargar el reporte de morosos.');
                    setData(null);
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [periodo, depto]);

    const [year, month] = periodo.split('-');
    const periodoLabel = new Date(Number(year), Number(month) - 1, 1).toLocaleDateString('es-BO', {
        month: 'long',
        year: 'numeric',
    });
    const sinDatos = !data || data.items.length === 0;
    const sufijoArchivo = `${periodo}${depto ? `_${depto.replace(/\s+/g, '')}` : ''}`;

    const exportPDF = () => {
        if (sinDatos) {
            toast.error('No hay morosos para descargar.');
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
            doc.text('Beneficiarios Morosos', margin + 30, 22);
            doc.setFontSize(9);
            doc.setTextColor(100, 116, 139);
            doc.setFont('helvetica', 'normal');
            doc.text(`Fecha de generación: ${new Date().toLocaleDateString('es-BO')} ${new Date().toLocaleTimeString('es-BO')}`, margin + 30, 27);
            doc.text(
                `Periodo: ${periodoLabel}${depto ? ` | Depto: ${depto}` : ''} | Total: ${data.total} | Sin aporte: ${data.sin_aporte} | Pendientes de revisión: ${data.declarados} | Observados: ${data.observados}`,
                margin + 30, 32,
            );
        };

        autoTable(doc, {
            head: [['Beneficiario', 'CI', 'Depto', 'Celular', 'Situación del aporte']],
            body: data.items.map((item) => [
                item.patient_nombre,
                item.patient_ci || 'Sin CI',
                item.depto || '-',
                item.tel_contacto || '-',
                MOTIVO_LABELS[item.motivo] || item.motivo,
            ]),
            startY: 40,
            margin: { top: 40, left: margin, right: margin, bottom: 20 },
            styles: { fontSize: 8, cellPadding: 3, font: 'helvetica' },
            headStyles: { fillColor: [185, 28, 28], textColor: 255, fontStyle: 'bold' },
            alternateRowStyles: { fillColor: [248, 250, 252] },
            didDrawPage: () => {
                addHeader();
                doc.setFontSize(8);
                doc.setTextColor(150);
                doc.text(`Página ${doc.internal.getNumberOfPages()}`, pageWidth / 2, doc.internal.pageSize.getHeight() - 10, { align: 'center' });
            },
        });

        doc.save(`Morosos_${sufijoArchivo}.pdf`);
        toast.success('Reporte descargado exitosamente');
    };

    const exportXLS = () => {
        if (sinDatos) {
            toast.error('No hay morosos para descargar.');
            return;
        }
        const rows = data.items.map((item) => ({
            Beneficiario: item.patient_nombre,
            CI: item.patient_ci || 'Sin CI',
            Departamento: item.depto || '-',
            Celular: item.tel_contacto || '-',
            'Situación del aporte': MOTIVO_LABELS[item.motivo] || item.motivo,
        }));
        const worksheet = XLSX.utils.json_to_sheet(rows);
        const workbook = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(workbook, worksheet, 'Morosos');
        XLSX.writeFile(workbook, `Morosos_${sufijoArchivo}.xlsx`);
        toast.success('Reporte descargado exitosamente');
    };

    return (
        <div>
            <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3 mb-6">
                <div>
                    <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
                        <UserX size={22} /> Beneficiarios Morosos
                    </h2>
                    <p className="text-sm text-gray-500">
                        Beneficiarios activos que no tienen un aporte <span className="font-semibold">aceptado</span> en el
                        mes elegido. No incluye a los exonerados ni a quienes fueron activados después de ese mes: cada beneficiario
                        paga desde el mes en que quedó activo. Por defecto se evalúa el mes anterior.
                    </p>
                </div>
                <div className="flex flex-wrap items-end gap-2">
                    <div>
                        <label className="block text-xs font-semibold text-gray-700 mb-1">Mes</label>
                        <input
                            type="month"
                            value={periodo}
                            onChange={(e) => setPeriodo(e.target.value)}
                            className="border rounded-lg px-3 py-2 text-sm bg-white"
                        />
                    </div>
                    <div>
                        <label className="block text-xs font-semibold text-gray-700 mb-1">Departamento</label>
                        <select
                            value={depto}
                            onChange={(e) => setDepto(e.target.value)}
                            className="border rounded-lg px-3 py-2 text-sm bg-white"
                        >
                            <option value="">Todos</option>
                            {DEPARTAMENTOS.map((d) => <option key={d} value={d}>{d}</option>)}
                        </select>
                    </div>
                    <Button
                        onClick={exportPDF}
                        disabled={loading || sinDatos}
                        className="bg-green-600 hover:bg-green-700 text-white w-auto justify-center"
                    >
                        <Download size={18} />
                        PDF
                    </Button>
                    <Button
                        onClick={exportXLS}
                        disabled={loading || sinDatos}
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
                    No se pudo cargar el reporte.
                </div>
            ) : (
                <>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                        <div className="bg-white rounded-2xl border border-red-100 shadow-sm p-4">
                            <p className="text-xs text-red-700 uppercase font-semibold flex items-center gap-1">
                                <XCircle size={14} /> No registraron aporte
                            </p>
                            <p className="text-3xl font-bold text-red-700 mt-1">{data.sin_aporte}</p>
                            <p className="text-xs text-gray-400 mt-1 capitalize">Sin voucher en {periodoLabel}</p>
                        </div>
                        <div className="bg-white rounded-2xl border border-yellow-100 shadow-sm p-4">
                            <p className="text-xs text-yellow-700 uppercase font-semibold flex items-center gap-1">
                                <Clock size={14} /> Pendientes de revisión
                            </p>
                            <p className="text-3xl font-bold text-yellow-700 mt-1">{data.declarados}</p>
                            <p className="text-xs text-gray-400 mt-1">Pagaron, falta validar el voucher</p>
                        </div>
                        <div className="bg-white rounded-2xl border border-orange-100 shadow-sm p-4">
                            <p className="text-xs text-orange-700 uppercase font-semibold flex items-center gap-1">
                                <AlertTriangle size={14} /> Observados
                            </p>
                            <p className="text-3xl font-bold text-orange-700 mt-1">{data.observados}</p>
                            <p className="text-xs text-gray-400 mt-1">Voucher con observación</p>
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
                                        <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Celular</th>
                                        <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Situación del aporte</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100">
                                    {data.items.length === 0 ? (
                                        <tr>
                                            <td colSpan="5" className="px-4 py-6 text-center text-gray-400 capitalize">
                                                No hay morosos en {periodoLabel}.
                                            </td>
                                        </tr>
                                    ) : (
                                        data.items.map((item) => (
                                            <tr key={item.patient_id} className="hover:bg-gray-50/70 transition-colors">
                                                <td className="px-4 py-3 text-sm text-gray-800 font-medium">{item.patient_nombre}</td>
                                                <td className="px-4 py-3 text-sm text-gray-600">{item.patient_ci || 'Sin CI'}</td>
                                                <td className="px-4 py-3 text-sm text-gray-600">{item.depto || '-'}</td>
                                                <td className="px-4 py-3 text-sm text-gray-600">{item.tel_contacto || '-'}</td>
                                                <td className="px-4 py-3 text-sm text-right">
                                                    <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-bold border ${MOTIVO_STYLES[item.motivo] || 'bg-gray-100 text-gray-600 border-gray-200'}`}>
                                                        {MOTIVO_LABELS[item.motivo] || item.motivo}
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
