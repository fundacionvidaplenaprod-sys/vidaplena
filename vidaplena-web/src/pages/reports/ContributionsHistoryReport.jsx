import { useEffect, useState } from 'react';
import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';
import * as XLSX from 'xlsx';
import { CheckCircle, Clock, AlertTriangle, Wallet, Download, FileSpreadsheet, CircleSlash } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '../../components/ui/Button';
import { getContributionsReport } from '../../api/reports';
import { DEPARTAMENTOS } from '../../constants/departamentos';
import logoUrl from '../../assets/logo.png';
import { imageToBase64 } from '../../utils/imageToBase64';

const ESTADO_STYLES = {
    ACEPTADO: 'bg-green-100 text-green-700 border-green-200',
    DECLARADO: 'bg-yellow-100 text-yellow-700 border-yellow-200',
    OBSERVADO: 'bg-red-100 text-red-700 border-red-200',
};

// Con un periodo elegido la tabla pasa a una columna por mes; más meses que esto la vuelven ilegible.
const MAX_MESES = 4;

// Estado del aporte de un beneficiario en un mes (celdas de las columnas de los meses).
const ESTADO_MES_LABELS = {
    ACEPTADO: 'Aceptado',
    DECLARADO: 'Declarado',
    OBSERVADO: 'Observado',
    NO_REGISTRADO: 'No Registrado',
    EXONERADO: 'Exonerado',
};

const ESTADO_MES_STYLES = {
    ...ESTADO_STYLES,
    NO_REGISTRADO: 'bg-gray-100 text-gray-600 border-gray-200',
    EXONERADO: 'bg-blue-100 text-blue-700 border-blue-200',
};

// Color del texto en el PDF (RGB) para cada estado.
const ESTADO_MES_PDF_COLOR = {
    ACEPTADO: [21, 128, 61],
    DECLARADO: [161, 98, 7],
    OBSERVADO: [185, 28, 28],
    NO_REGISTRADO: [100, 116, 139],
    EXONERADO: [29, 78, 216],
};

const METODO_LABELS = {
    EFECTIVO: 'Efectivo',
    VOUCHER: 'Voucher/QR',
};

const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];

const currentPeriod = () => new Date().toISOString().slice(0, 7);

// «2026-04» -> «abril 2026»
const monthLabel = (periodo) => {
    const [year, month] = periodo.split('-');
    return new Date(Number(year), Number(month) - 1, 1).toLocaleDateString('es-BO', { month: 'long', year: 'numeric' });
};

// «2026-08» -> «Agosto 2026» (cabecera de la columna de ese mes)
const monthHeader = (periodo) => {
    const [year, month] = periodo.split('-');
    return `${MESES[Number(month) - 1]} ${year}`;
};

// Cantidad de meses de un rango «YYYY-MM» (ambos extremos incluidos).
const monthSpan = (desde, hasta) => {
    const [y1, m1] = desde.split('-').map(Number);
    const [y2, m2] = hasta.split('-').map(Number);
    return (y2 - y1) * 12 + (m2 - m1) + 1;
};

export default function ContributionsHistoryReport() {
    const [desde, setDesde] = useState(currentPeriod());
    const [hasta, setHasta] = useState(currentPeriod());
    const [depto, setDepto] = useState('');
    const [todosLosPeriodos, setTodosLosPeriodos] = useState(false);
    const [loading, setLoading] = useState(true);
    const [data, setData] = useState(null);
    const [logoBase64, setLogoBase64] = useState(null);

    useEffect(() => {
        imageToBase64(logoUrl)
            .then((base64) => setLogoBase64(base64))
            .catch((err) => console.error('Error al cargar el logo en base64', err));
    }, []);

    const load = async () => {
        if (!todosLosPeriodos) {
            if (!desde || !hasta) return;
            if (desde > hasta) {
                toast.error('El mes «Desde» no puede ser posterior a «Hasta».');
                return;
            }
            if (monthSpan(desde, hasta) > MAX_MESES) {
                toast.error(`El rango puede abarcar como máximo ${MAX_MESES} meses.`);
                return;
            }
        }
        try {
            setLoading(true);
            const result = await getContributionsReport(todosLosPeriodos ? { depto } : { desde, hasta, depto });
            setData(result);
        } catch (error) {
            toast.error(typeof error === 'string' ? error : 'No se pudo cargar el historial de aportes.');
            setData(null);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [todosLosPeriodos, desde, hasta, depto]);

    const sameMonth = desde === hasta;
    const periodoLabel = todosLosPeriodos
        ? 'todos los periodos'
        : sameMonth ? monthLabel(desde) : `${monthLabel(desde)} a ${monthLabel(hasta)}`;
    const periodoSuffix = todosLosPeriodos ? 'TODOS' : sameMonth ? desde : `${desde}_a_${hasta}`;
    const fileSuffix = `${periodoSuffix}${depto ? `_${depto.replace(/\s+/g, '_')}` : ''}`;

    // Con un periodo elegido: una fila por beneficiario y una columna por mes.
    // Sin periodo: una fila por voucher, con su estado y su periodo.
    const meses = data?.meses || [];
    const porMes = meses.length > 0;
    const filas = (porMes ? data?.beneficiarios : data?.items) || [];
    const sinDatos = filas.length === 0;
    const noRegistrados = porMes
        ? filas.reduce((acc, f) => acc + meses.filter((mes) => f.meses[mes] === 'NO_REGISTRADO').length, 0)
        : 0;

    const cabecerasPorMes = () => [
        'Beneficiario', 'CI', 'Departamento', 'Monto (Bs.)', 'Fecha de pago', 'Método', ...meses.map(monthHeader),
    ];
    const celdasPorMes = (f) => [
        f.patient_nombre,
        f.patient_ci || 'Sin CI',
        f.depto || '-',
        f.monto == null ? '-' : f.monto.toFixed(2),
        f.fecha_pago || '-',
        f.metodo_pago ? (METODO_LABELS[f.metodo_pago] || f.metodo_pago) : '-',
        ...meses.map((mes) => ESTADO_MES_LABELS[f.meses[mes]] || f.meses[mes]),
    ];

    const exportPDF = () => {
        if (!data || sinDatos) {
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
                `Periodo: ${periodoLabel}${depto ? ` | Departamento: ${depto}` : ''} | Aceptados: ${data.total_aceptados} | Pendientes: ${data.total_declarados} | Observados: ${data.total_observados}`,
                margin + 30, 32,
            );
        };

        const tabla = porMes
            ? { head: [cabecerasPorMes()], body: filas.map(celdasPorMes) }
            : {
                head: [['Beneficiario', 'CI', 'Departamento', 'Monto (Bs.)', 'Fecha de pago', 'Método', 'Estado', 'Periodo']],
                body: filas.map((item) => [
                    item.patient_nombre,
                    item.patient_ci || 'Sin CI',
                    item.depto || '-',
                    item.monto.toFixed(2),
                    item.fecha_pago,
                    METODO_LABELS[item.metodo_pago] || item.metodo_pago,
                    item.estado,
                    item.periodo,
                ]),
            };

        autoTable(doc, {
            ...tabla,
            // En las columnas de los meses, el estado va en negrita y con su color.
            didParseCell: (hook) => {
                if (!porMes || hook.section !== 'body' || hook.column.index < 6) return;
                const estado = filas[hook.row.index]?.meses[meses[hook.column.index - 6]];
                hook.cell.styles.textColor = ESTADO_MES_PDF_COLOR[estado] || [30, 41, 59];
                hook.cell.styles.fontStyle = 'bold';
            },
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

        doc.save(`Historial_Aportes_${fileSuffix}.pdf`);
        toast.success('Reporte descargado exitosamente');
    };

    const exportXLS = () => {
        if (!data || sinDatos) {
            toast.error('No hay aportes registrados en este periodo para descargar.');
            return;
        }
        let rows;
        if (porMes) {
            const encabezados = cabecerasPorMes();
            rows = filas.map((f) => {
                const celdas = celdasPorMes(f);
                return Object.fromEntries(encabezados.map((titulo, i) => [titulo, celdas[i]]));
            });
        } else {
            rows = filas.map((item) => ({
                Beneficiario: item.patient_nombre,
                CI: item.patient_ci || 'Sin CI',
                Departamento: item.depto || '-',
                'Monto (Bs.)': item.monto,
                'Fecha de pago': item.fecha_pago,
                Método: METODO_LABELS[item.metodo_pago] || item.metodo_pago,
                Estado: item.estado,
                // A la derecha de los datos del beneficiario: a qué periodo pertenece el voucher de la fila.
                Periodo: item.periodo,
                Mes: monthLabel(item.periodo),
            }));
        }
        const worksheet = XLSX.utils.json_to_sheet(rows);
        worksheet['!autofilter'] = { ref: worksheet['!ref'] };
        const workbook = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(workbook, worksheet, 'Aportes');
        XLSX.writeFile(workbook, `Historial_Aportes_${fileSuffix}.xlsx`);
        toast.success('Reporte descargado exitosamente');
    };

    const thClass = 'px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider';

    return (
        <div>
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-6">
                <div>
                    <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
                        <Wallet size={22} /> Historial de Aportes Solidarios
                    </h2>
                    <p className="text-sm text-gray-500">
                        Elija un mes, o un rango de hasta {MAX_MESES} meses, para ver el estado del aporte de cada beneficiario mes por mes.
                        Con «Todos los periodos» se lista cada voucher registrado.
                    </p>
                </div>
                <div className="flex items-end gap-2 flex-wrap">
                    <div>
                        <label className="block text-xs font-semibold text-gray-700 mb-1" htmlFor="aportes-desde">Desde</label>
                        <input
                            id="aportes-desde"
                            type="month"
                            value={desde}
                            max={hasta || undefined}
                            onChange={(e) => setDesde(e.target.value)}
                            disabled={todosLosPeriodos}
                            className="border rounded-lg px-3 py-2 text-sm bg-white disabled:bg-gray-100 disabled:text-gray-400"
                        />
                    </div>
                    <div>
                        <label className="block text-xs font-semibold text-gray-700 mb-1" htmlFor="aportes-hasta">Hasta</label>
                        <input
                            id="aportes-hasta"
                            type="month"
                            value={hasta}
                            min={desde || undefined}
                            onChange={(e) => setHasta(e.target.value)}
                            disabled={todosLosPeriodos}
                            className="border rounded-lg px-3 py-2 text-sm bg-white disabled:bg-gray-100 disabled:text-gray-400"
                        />
                    </div>
                    <label className="flex items-center gap-2 text-sm text-gray-700 pb-2">
                        <input
                            type="checkbox"
                            checked={todosLosPeriodos}
                            onChange={(e) => setTodosLosPeriodos(e.target.checked)}
                        />
                        Todos los periodos
                    </label>
                    <div>
                        <label className="block text-xs font-semibold text-gray-700 mb-1" htmlFor="aportes-depto">Departamento</label>
                        <select
                            id="aportes-depto"
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
                    <Button
                        onClick={exportPDF}
                        disabled={loading || !data || sinDatos}
                        className="bg-green-600 hover:bg-green-700 text-white w-auto justify-center"
                    >
                        <Download size={18} />
                        PDF
                    </Button>
                    <Button
                        onClick={exportXLS}
                        disabled={loading || !data || sinDatos}
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
                    <div className={`grid grid-cols-1 ${porMes ? 'md:grid-cols-4' : 'md:grid-cols-3'} gap-4 mb-6`}>
                        <div className="bg-white rounded-2xl border border-green-100 shadow-sm p-4">
                            <p className="text-xs text-green-700 uppercase font-semibold flex items-center gap-1">
                                <CheckCircle size={14} /> Aportes aceptados
                            </p>
                            <p className="text-3xl font-bold text-green-700 mt-1">{data.total_aceptados}</p>
                            <p className="text-xs text-gray-400 mt-1 capitalize">Vouchers aceptados en {periodoLabel}</p>
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
                        {porMes && (
                            <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-4">
                                <p className="text-xs text-gray-600 uppercase font-semibold flex items-center gap-1">
                                    <CircleSlash size={14} /> No registrados
                                </p>
                                <p className="text-3xl font-bold text-gray-600 mt-1">{noRegistrados}</p>
                                <p className="text-xs text-gray-400 mt-1">Meses sin voucher (beneficiario × mes)</p>
                            </div>
                        )}
                    </div>

                    {porMes && (
                        <p className="text-xs text-gray-500 mb-2">
                            Estado del aporte en cada mes:{' '}
                            {['ACEPTADO', 'DECLARADO', 'OBSERVADO', 'NO_REGISTRADO', 'EXONERADO'].map((estado) => (
                                <span
                                    key={estado}
                                    className={`inline-flex items-center px-2 py-0.5 mr-1 rounded-full font-bold border ${ESTADO_MES_STYLES[estado]}`}
                                >
                                    {ESTADO_MES_LABELS[estado]}
                                </span>
                            ))}
                            «Exonerado» aparece en los meses sin voucher de quien está exonerado del aporte.
                        </p>
                    )}
                    <div className="bg-white rounded-2xl shadow-xl border border-gray-100 overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead className="bg-gray-50 border-b border-gray-100">
                                    <tr>
                                        <th className={thClass}>Beneficiario</th>
                                        <th className={thClass}>CI</th>
                                        <th className={thClass}>Departamento</th>
                                        <th className={`${thClass} text-right`}>Monto (Bs.)</th>
                                        <th className={thClass}>Fecha de pago</th>
                                        <th className={thClass}>Método</th>
                                        {porMes ? (
                                            meses.map((mes) => (
                                                <th key={mes} className={`${thClass} text-center whitespace-nowrap`}>{monthHeader(mes)}</th>
                                            ))
                                        ) : (
                                            <>
                                                <th className={`${thClass} text-right`}>Estado</th>
                                                <th className={thClass}>Periodo</th>
                                            </>
                                        )}
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100">
                                    {sinDatos ? (
                                        <tr>
                                            <td colSpan={6 + (porMes ? meses.length : 2)} className="px-4 py-6 text-center text-gray-400 capitalize">
                                                Nadie registró aportes en {periodoLabel}.
                                            </td>
                                        </tr>
                                    ) : porMes ? (
                                        filas.map((f) => (
                                            <tr key={f.patient_id} className="hover:bg-gray-50/70 transition-colors">
                                                <td className="px-4 py-3 text-sm text-gray-800 font-medium">{f.patient_nombre}</td>
                                                <td className="px-4 py-3 text-sm text-gray-600">{f.patient_ci || 'Sin CI'}</td>
                                                <td className="px-4 py-3 text-sm text-gray-600">{f.depto || '-'}</td>
                                                <td className="px-4 py-3 text-sm text-right text-gray-700">{f.monto == null ? '-' : f.monto.toFixed(2)}</td>
                                                <td className="px-4 py-3 text-sm text-gray-600">{f.fecha_pago || '-'}</td>
                                                <td className="px-4 py-3 text-sm text-gray-600">{f.metodo_pago ? (METODO_LABELS[f.metodo_pago] || f.metodo_pago) : '-'}</td>
                                                {meses.map((mes) => (
                                                    <td key={mes} className="px-4 py-3 text-sm text-center whitespace-nowrap">
                                                        <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-bold border ${ESTADO_MES_STYLES[f.meses[mes]] || 'bg-gray-100 text-gray-600 border-gray-200'}`}>
                                                            {ESTADO_MES_LABELS[f.meses[mes]] || f.meses[mes]}
                                                        </span>
                                                    </td>
                                                ))}
                                            </tr>
                                        ))
                                    ) : (
                                        filas.map((item) => (
                                            <tr key={item.id} className="hover:bg-gray-50/70 transition-colors">
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
                                                <td className="px-4 py-3 text-sm text-gray-600 whitespace-nowrap capitalize">{monthLabel(item.periodo)}</td>
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
