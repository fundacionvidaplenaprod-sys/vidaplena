import { useEffect, useMemo, useState } from 'react';
import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';
import * as XLSX from 'xlsx';
import { Download, FileSpreadsheet, Upload, Syringe, ShieldCheck } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '../../components/ui/Button';
import { generateInsulinDistributionReport } from '../../api/reports';
import logoUrl from '../../assets/logo.png';
import { imageToBase64 } from '../../utils/imageToBase64';

const fmt = (n) => Math.round(n || 0).toLocaleString('es-BO');

const ESTADO_LABELS = {
    ACTIVO: 'Activo',
    PENDIENTE_DOC: 'Pendiente de documentos',
    HABILITADO: 'Habilitado',
};

const FILTERS = [
    { id: 'todos', label: 'Todos' },
    { id: 'menores', label: 'Menores de 18' },
    { id: 'tipo1', label: 'Tipo 1' },
    { id: 'sin_cubrir', label: 'Sin cubrir' },
    { id: 'sustituidos', label: 'Con sustituto' },
];

// Cobertura en días: lo que recibe ÷ lo que necesita al día. Con envases enteros puede pasar de
// los días del reporte (166 % de 60 días = 100 días): no se puede entregar medio pen.
const diasCubiertos = (cobertura, dias) => Math.round((cobertura * dias) / 100);

const TOPE_COBERTURA = 120;

const MOTIVO_ELECCION = {
    STOCK: 'tiene stock',
    SUSTITUTO: 'se cubre con sustituto',
    SIN_STOCK: 'sin stock: mayor dosis',
};

// «30 UI/día» o, si se limitó, «48 → 30 UI/día» (tope de 30 UI/día para menores).
const dosisTexto = (i) =>
    i.dosis_limitada
        ? `${i.dosis_diaria_registrada} → ${i.dosis_diaria_aplicada} UI/día`
        : `${i.dosis_diaria_aplicada} UI/día`;

const lotesTexto = (lotes) =>
    lotes.length
        ? lotes
              .map((l) => `${l.unidades} × ${l.producto}${l.lote ? ` (lote ${l.lote})` : ''}`)
              .join(', ')
        : '—';

// Reporte de planificación: recibe el Excel de la donación y calcula el reparto con las
// reglas definidas, sobre beneficiarios activos, pendientes de documentos y habilitados.
// No guarda nada ni toca el stock del almacén.
export default function InsulinDistributionReport() {
    const [file, setFile] = useState(null);
    const [loading, setLoading] = useState(false);
    const [data, setData] = useState(null);
    const [filter, setFilter] = useState('todos');
    const [estado, setEstado] = useState('');
    const [search, setSearch] = useState('');
    const [logoBase64, setLogoBase64] = useState(null);

    useEffect(() => {
        imageToBase64(logoUrl)
            .then(setLogoBase64)
            .catch((err) => console.error('Error al cargar el logo en base64', err));
    }, []);

    const handleGenerate = async () => {
        if (!file) {
            toast.error('Selecciona primero el Excel de la donación.');
            return;
        }
        try {
            setLoading(true);
            const result = await generateInsulinDistributionReport(file);
            setData(result);
            toast.success('Reporte generado. No se guardó nada.');
        } catch (error) {
            toast.error(typeof error === 'string' ? error : 'No se pudo generar el reporte.');
            setData(null);
        } finally {
            setLoading(false);
        }
    };

    const patients = useMemo(() => {
        if (!data) return [];
        const term = search.trim().toLowerCase();
        return data.pacientes.filter((p) => {
            if (estado && p.estado !== estado) return false;
            if (filter === 'menores' && !p.es_menor) return false;
            if (filter === 'tipo1' && !p.es_tipo1) return false;
            if (filter === 'sin_cubrir' && !p.insulinas.some((i) => i.cobertura_pct < 99.9)) return false;
            if (filter === 'sustituidos' && !p.insulinas.some((i) => i.sustituto)) return false;
            if (!term) return true;
            return (
                p.nombre_completo.toLowerCase().includes(term) ||
                (p.ci || '').toLowerCase().includes(term)
            );
        });
    }, [data, filter, estado, search]);

    const reservaPct = data && data.stock_total_ui ? (100 * data.reserva_ui) / data.stock_total_ui : 0;
    const sufijo = new Date().toISOString().slice(0, 10);

    const patientRows = (list) =>
        list.flatMap((p) =>
            p.insulinas.map((i) => ({
                p,
                i,
                grupo: p.es_menor ? 'Menor' : p.es_tipo1 ? 'Adulto tipo 1' : 'Adulto',
            }))
        );

    const exportPDF = () => {
        if (!data) return;
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
            // Alias + compresión: el logo se incrusta una sola vez y sin inflar el PDF.
            doc.addImage(logoBase64, 'PNG', margin, 5, 25, 25, 'logo', 'FAST');
            doc.setFontSize(18);
            doc.setTextColor(30, 58, 138);
            doc.setFont('helvetica', 'bold');
            doc.text('Fundación V.I.D.A. Plena', margin + 30, 16);
            doc.setFontSize(14);
            doc.text('Distribución de insulina de la donación', margin + 30, 22);
            doc.setFontSize(9);
            doc.setTextColor(100, 116, 139);
            doc.setFont('helvetica', 'normal');
            doc.text(
                `Generado: ${new Date().toLocaleDateString('es-BO')} ${new Date().toLocaleTimeString('es-BO')} | Archivo: ${data.archivo} | Horizonte: ${data.dias} días`,
                margin + 30,
                27
            );
            doc.text(
                `Stock: ${fmt(data.stock_total_ui)} UI | Reserva: ${fmt(data.reserva_ui)} UI (${reservaPct.toFixed(1)} %) | Asignado: ${fmt(data.asignado_ui)} UI | Beneficiarios: ${data.pacientes.length}`,
                margin + 30,
                32
            );
        };

        // 1) Resumen por insulina
        autoTable(doc, {
            head: [['Insulina', 'Stock (UI)', 'Necesidad', 'Reserva', 'Asignado', 'Falta', 'Sobra', 'Sin cubrir']],
            body: data.insulinas.map((s) => [
                s.insulina,
                fmt(s.stock_ui),
                fmt(s.necesidad_ui),
                fmt(s.reserva_ui),
                fmt(s.asignado_ui),
                fmt(s.faltante_ui),
                fmt(s.sobrante_ui),
                `${s.pacientes_sin_cubrir} / ${s.pacientes_con_necesidad}`,
            ]),
            startY: 40,
            margin: { top: 40, left: margin, right: margin, bottom: 20 },
            styles: { fontSize: 8, cellPadding: 2.5, font: 'helvetica' },
            headStyles: { fillColor: [30, 58, 138], textColor: 255, fontStyle: 'bold' },
            alternateRowStyles: { fillColor: [248, 250, 252] },
            didDrawPage: addHeader,
        });

        // 1b) Fichas con dos insulinas del mismo grupo
        if (data.registros_por_corregir.length) {
            autoTable(doc, {
                head: [['Ficha por corregir', 'CI', 'Estado', 'Grupo', 'Insulinas registradas', 'Se usó']],
                body: data.registros_por_corregir.map((r) => [
                    r.nombre_completo,
                    r.ci || '-',
                    ESTADO_LABELS[r.estado] || r.estado || '-',
                    r.grupo_nombre,
                    r.insulinas.map((i) => `${i.insulina} (${i.dosis_diaria} UI/día)`).join(' + '),
                    r.insulina_usada,
                ]),
                startY: doc.lastAutoTable.finalY + 8,
                margin: { top: 40, left: margin, right: margin, bottom: 20 },
                styles: { fontSize: 8, cellPadding: 2.5, font: 'helvetica' },
                headStyles: { fillColor: [180, 83, 9], textColor: 255, fontStyle: 'bold' },
                alternateRowStyles: { fillColor: [255, 251, 235] },
                didDrawPage: addHeader,
            });
        }

        // 2) Detalle por beneficiario
        autoTable(doc, {
            head: [['Beneficiario', 'CI', 'Estado', 'Grupo', 'Insulina', 'Dosis/día', 'Necesita', 'Recibe', 'Cobertura', 'Días', 'Envases / lote']],
            body: patientRows(data.pacientes).map(({ p, i, grupo }) => [
                p.nombre_completo,
                p.ci || '-',
                ESTADO_LABELS[p.estado] || p.estado || '-',
                grupo,
                i.sustituto ? `${i.insulina} → ${i.sustituto}` : i.insulina,
                dosisTexto(i),
                `${fmt(i.necesidad_ui)} UI`,
                `${fmt(i.entregado_ui)} UI`,
                `${i.cobertura_pct}%`,
                `${diasCubiertos(i.cobertura_pct, data.dias)}`,
                lotesTexto(i.lotes),
            ]),
            startY: doc.lastAutoTable.finalY + 8,
            margin: { top: 40, left: margin, right: margin, bottom: 20 },
            styles: { fontSize: 7, cellPadding: 2, font: 'helvetica' },
            headStyles: { fillColor: [21, 128, 61], textColor: 255, fontStyle: 'bold' },
            alternateRowStyles: { fillColor: [248, 250, 252] },
            columnStyles: { 10: { cellWidth: 60 } },
            didDrawPage: () => {
                addHeader();
                doc.setFontSize(8);
                doc.setTextColor(150);
                doc.text(
                    `Página ${doc.internal.getNumberOfPages()}`,
                    pageWidth / 2,
                    doc.internal.pageSize.getHeight() - 10,
                    { align: 'center' }
                );
            },
        });

        doc.save(`Distribucion_insulina_${sufijo}.pdf`);
        toast.success('Reporte descargado exitosamente');
    };

    const exportXLS = () => {
        if (!data) return;
        const workbook = XLSX.utils.book_new();

        const beneficiarios = patientRows(data.pacientes).map(({ p, i, grupo }) => ({
            Beneficiario: p.nombre_completo,
            CI: p.ci || '',
            Departamento: p.depto || '',
            Estado: ESTADO_LABELS[p.estado] || p.estado || '',
            Edad: p.edad ?? '',
            'Tipo de diabetes': p.tipo_diabetes || '',
            Grupo: grupo,
            Insulina: i.insulina,
            'Se le da en su lugar': i.sustituto || '',
            'Dosis diaria registrada (UI)': i.dosis_diaria_registrada,
            'Dosis diaria usada (UI)': i.dosis_diaria_aplicada,
            'Dosis limitada (tope menores)': i.dosis_limitada ? 'Sí' : '',
            'Necesita (UI)': Math.round(i.necesidad_ui),
            'Recibe (UI)': Math.round(i.entregado_ui),
            'Cobertura (%)': i.cobertura_pct,
            [`Días cubiertos (de ${data.dias})`]: diasCubiertos(i.cobertura_pct, data.dias),
            'Envases / lote': lotesTexto(i.lotes),
        }));
        XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(beneficiarios), 'Beneficiarios');

        const porInsulina = data.insulinas.map((s) => ({
            Insulina: s.insulina,
            'Stock (UI)': Math.round(s.stock_ui),
            'Necesidad (UI)': Math.round(s.necesidad_ui),
            'Reserva (UI)': Math.round(s.reserva_ui),
            'Asignado (UI)': Math.round(s.asignado_ui),
            'Cubierto con otra insulina (UI)': Math.round(s.sustituido_ui),
            'Entregado como sustituto (UI)': Math.round(s.entregado_como_sustituto_ui),
            'Falta (UI)': Math.round(s.faltante_ui),
            'Sobra (UI)': Math.round(s.sobrante_ui),
            'Beneficiarios sin cubrir': s.pacientes_sin_cubrir,
            'Beneficiarios con necesidad': s.pacientes_con_necesidad,
        }));
        XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(porInsulina), 'Por insulina');

        if (data.registros_por_corregir.length) {
            const porCorregir = data.registros_por_corregir.map((r) => ({
                Beneficiario: r.nombre_completo,
                CI: r.ci || '',
                Departamento: r.depto || '',
                Estado: ESTADO_LABELS[r.estado] || r.estado || '',
                Menor: r.es_menor ? 'Sí' : '',
                Grupo: r.grupo_nombre,
                'Insulinas registradas': r.insulinas.map((i) => `${i.insulina} (${i.dosis_diaria} UI/día)`).join(' + '),
                'Insulina usada en el cálculo': r.insulina_usada,
                Motivo: `${MOTIVO_ELECCION[r.motivo] || r.motivo}${r.premezcla_descartada ? ' · premezcla descartada (no sustituye a una basal)' : ''}`,
                'Qué hacer': 'Dejar una sola insulina de este grupo en la ficha',
            }));
            XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(porCorregir), 'Por corregir');
        }

        const reserva = data.reserva.map((r) => ({
            Producto: r.producto,
            Insulina: r.insulina,
            Lote: r.lote || '',
            Vencimiento: r.fecha_venc || '',
            Envases: r.unidades,
            UI: Math.round(r.ui),
        }));
        XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(reserva), 'Reserva');

        const donacion = data.donacion.map((d) => ({
            Fila: d.fila,
            Producto: d.producto,
            Insulina: d.insulina,
            Cantidad: d.cantidad,
            'Presentación (ml)': d.presentacion_ml,
            'Concentración (UI/ml)': d.concentracion_ui_ml,
            'UI por envase': d.ui_por_envase,
            'UI total': d.ui_total,
            Lote: d.lote || '',
            Vencimiento: d.fecha_venc || '',
        }));
        XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(donacion), 'Donación');

        XLSX.writeFile(workbook, `Distribucion_insulina_${sufijo}.xlsx`);
        toast.success('Reporte descargado exitosamente');
    };

    return (
        <div>
            <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3 mb-6">
                <div>
                    <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
                        <Syringe size={22} /> Distribución de insulina de una donación
                    </h2>
                    <p className="text-sm text-gray-500 max-w-3xl">
                        Sube el Excel con la insulina que llegó. Se calcula el reparto a 60 días con las reglas
                        definidas (menores y tipo 1 primero, Lantus para menores, reserva del 10 % y
                        sustituciones) para los beneficiarios <b>activos, pendientes de documentos y
                        habilitados</b>, sin exigir aporte al día. Es solo un reporte: no guarda nada ni
                        descuenta stock.
                    </p>
                </div>
                {data && (
                    <div className="flex gap-2">
                        <Button type="button" className="bg-red-600 hover:bg-red-700 text-white" onClick={exportPDF}>
                            <Download size={18} /> PDF
                        </Button>
                        <Button type="button" className="bg-green-600 hover:bg-green-700 text-white" onClick={exportXLS}>
                            <FileSpreadsheet size={18} /> Excel
                        </Button>
                    </div>
                )}
            </div>

            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 mb-6 flex flex-col md:flex-row md:items-end gap-4">
                <div className="flex-1">
                    <label className="text-sm font-bold text-vida-primary ml-1">Excel de la donación (.xlsx)</label>
                    <input
                        type="file"
                        accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        onChange={(e) => setFile(e.target.files?.[0] || null)}
                        className="mt-2 block w-full text-sm text-gray-600 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-vida-light/40 file:text-vida-primary hover:file:bg-vida-light/60"
                    />
                    <p className="mt-2 text-xs text-gray-500">
                        Columnas: CANTIDAD, PRODUCTO, TIPO DE INSULINA, PRESENTACIÓN, CONCENTRACIÓN y, opcionales,
                        FECHA VENCIMIENTO y NRO LOTE.
                    </p>
                </div>
                <Button
                    type="button"
                    className="bg-vida-main hover:bg-vida-hover text-white shadow-lg shadow-vida-main/20"
                    onClick={handleGenerate}
                    disabled={loading || !file}
                >
                    <Upload size={18} /> {loading ? 'Calculando...' : 'Generar reporte'}
                </Button>
            </div>

            {!data && !loading && (
                <p className="text-sm text-gray-400 py-10 text-center">
                    Selecciona el Excel y pulsa «Generar reporte».
                </p>
            )}

            {data && (
                <>
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
                        <div className="bg-vida-bg rounded-xl p-4">
                            <p className="text-xs text-gray-500">Stock de la donación</p>
                            <p className="text-lg font-bold text-gray-800">{fmt(data.stock_total_ui)} UI</p>
                            <p className="text-xs text-gray-400">{data.lotes_considerados} filas válidas</p>
                        </div>
                        <div className="bg-vida-bg rounded-xl p-4">
                            <p className="text-xs text-gray-500 flex items-center gap-1">
                                <ShieldCheck size={12} /> Reserva ({Math.round(data.reserva_pct * 100)} %)
                            </p>
                            <p className="text-lg font-bold text-gray-800">{fmt(data.reserva_ui)} UI</p>
                            <p className="text-xs text-gray-400">{reservaPct.toFixed(1)} % del total</p>
                        </div>
                        <div className="bg-vida-bg rounded-xl p-4">
                            <p className="text-xs text-gray-500">Asignado</p>
                            <p className="text-lg font-bold text-gray-800">{fmt(data.asignado_ui)} UI</p>
                        </div>
                        <div className="bg-vida-bg rounded-xl p-4">
                            <p className="text-xs text-gray-500">Beneficiarios</p>
                            <p className="text-lg font-bold text-gray-800">{data.pacientes.length}</p>
                            <p className="text-xs text-gray-400">
                                {data.excluded_patients.length} sin dosis · {data.registros_por_corregir.length} fichas por corregir
                            </p>
                        </div>
                        <div className="bg-vida-bg rounded-xl p-4">
                            <p className="text-xs text-gray-500">Filas del Excel</p>
                            <p className="text-lg font-bold text-gray-800">{data.filas_leidas}</p>
                            <p className="text-xs text-gray-400">
                                {data.filas_con_error.length} omitidas ({data.lotes_vencidos} vencidas)
                            </p>
                        </div>
                    </div>

                    {data.registros_por_corregir.length > 0 && (
                        <div className="mb-6 border border-amber-200 bg-amber-50 rounded-xl p-4">
                            <h3 className="text-base font-bold text-amber-800">
                                Fichas por corregir ({data.registros_por_corregir.length})
                            </h3>
                            <p className="text-sm text-amber-800 mb-3">
                                Cada beneficiario usa <b>una sola insulina de cada grupo</b>: rápidas (lispro, aspart,
                                glulisina, regular) y basales / intermedias / premezclas (glargina, protamina, NPH,
                                detemir, degludec). Estas fichas traen dos del mismo grupo: el reparto usó <b>una</b>,
                                la que mejor se puede atender con el stock de esta donación o con una sustitución
                                conocida. Conviene dejar una sola en la ficha.
                            </p>
                            <div className="overflow-x-auto bg-white border border-amber-100 rounded-lg max-h-64 overflow-y-auto">
                                <table className="w-full">
                                    <thead className="bg-amber-100/60">
                                        <tr>
                                            {['Beneficiario', 'Estado', 'Grupo', 'Insulinas registradas', 'Se usó'].map((h) => (
                                                <th key={h} className="px-4 py-2 text-left text-xs font-bold text-amber-800 uppercase tracking-wider">
                                                    {h}
                                                </th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-amber-100">
                                        {data.registros_por_corregir.map((r) => (
                                            <tr key={`${r.patient_id}-${r.grupo}`}>
                                                <td className="px-4 py-2 text-sm text-gray-800">
                                                    {r.nombre_completo}
                                                    <span className="block text-xs text-gray-400">{r.ci || 'Sin CI'}</span>
                                                    {r.es_menor && (
                                                        <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-700">
                                                            MENOR
                                                        </span>
                                                    )}
                                                </td>
                                                <td className="px-4 py-2 text-xs text-gray-600">
                                                    {ESTADO_LABELS[r.estado] || r.estado}
                                                </td>
                                                <td className="px-4 py-2 text-sm text-gray-700">{r.grupo_nombre}</td>
                                                <td className="px-4 py-2 text-sm text-gray-700">
                                                    {r.insulinas.map((i) => `${i.insulina} (${i.dosis_diaria} UI/día)`).join(' + ')}
                                                </td>
                                                <td className="px-4 py-2 text-sm font-semibold text-gray-800">
                                                    {r.insulina_usada}
                                                    <span className="block text-[10px] font-normal text-gray-500">
                                                        {MOTIVO_ELECCION[r.motivo] || r.motivo}
                                                        {r.sustituto ? ` (${r.sustituto})` : ''}
                                                    </span>
                                                    {r.premezcla_descartada && (
                                                        <span className="block text-[10px] font-semibold text-amber-600">
                                                            premezcla descartada: no sustituye a una basal
                                                        </span>
                                                    )}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}

                    <h3 className="text-lg font-bold text-gray-700 mb-3">Por insulina</h3>
                    <div className="overflow-x-auto border border-gray-100 rounded-xl mb-6">
                        <table className="w-full">
                            <thead className="bg-gray-50 border-b border-gray-100">
                                <tr>
                                    {['Insulina', 'Stock', 'Necesidad', 'Reserva', 'Asignado', 'Sustitución', 'Falta', 'Sobra', 'Sin cubrir'].map((h) => (
                                        <th key={h} className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">
                                            {h}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                {data.insulinas.map((s) => (
                                    <tr key={s.insulina}>
                                        <td className="px-4 py-3 text-sm font-semibold text-gray-800">{s.insulina}</td>
                                        <td className="px-4 py-3 text-sm text-gray-700">{fmt(s.stock_ui)}</td>
                                        <td className="px-4 py-3 text-sm text-gray-700">{fmt(s.necesidad_ui)}</td>
                                        <td className="px-4 py-3 text-sm text-gray-700">{fmt(s.reserva_ui)}</td>
                                        <td className="px-4 py-3 text-sm text-gray-700">{fmt(s.asignado_ui)}</td>
                                        <td className="px-4 py-3 text-xs text-gray-600">
                                            {s.sustituido_ui > 0 && <span>−{fmt(s.sustituido_ui)} cubiertas con otra </span>}
                                            {s.entregado_como_sustituto_ui > 0 && (
                                                <span className="text-blue-700">+{fmt(s.entregado_como_sustituto_ui)} como sustituto</span>
                                            )}
                                            {!s.sustituido_ui && !s.entregado_como_sustituto_ui && '—'}
                                        </td>
                                        <td className={`px-4 py-3 text-sm font-semibold ${s.faltante_ui > 0 ? 'text-red-600' : 'text-gray-400'}`}>
                                            {fmt(s.faltante_ui)}
                                        </td>
                                        <td className="px-4 py-3 text-sm text-gray-700">{fmt(s.sobrante_ui)}</td>
                                        <td className="px-4 py-3 text-sm text-gray-700">
                                            {s.pacientes_sin_cubrir} / {s.pacientes_con_necesidad}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3 text-sm text-blue-800 mb-4">
                        <b>Cómo leer la cobertura:</b> es lo que recibe ÷ lo que necesita para {data.dias} días.
                        Menos de 100 % significa que no alcanzó el stock (la insulina o su sustituto se agotó);
                        más de 100 % es solo el envase entero: un pen de 300 UI no se puede partir, así que a quien
                        le faltan 360 UI se le entregan 2 pens (600 UI ≈ 100 días). Menores y tipo 1 se completan
                        primero y se busca la combinación de envases que quede entre 100 % y {TOPE_COBERTURA} %; si
                        ninguna cabe, se les garantiza el 100 % aunque pase del tope
                        {data.prioritarios_sobre_120 > 0 && (
                            <b> ({data.prioritarios_sobre_120} tratamientos en este reporte)</b>
                        )}
                        . En menores de 18, glargina, lispro, glulisina, aspart, detemir y degludec se calculan
                        con un máximo de 30 UI/día sin importar la dosis registrada.
                    </div>

                    <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 mb-3">
                        <h3 className="text-lg font-bold text-gray-700">Beneficiarios</h3>
                        <div className="flex flex-wrap items-center gap-2">
                            {FILTERS.map((f) => (
                                <button
                                    key={f.id}
                                    type="button"
                                    onClick={() => setFilter(f.id)}
                                    className={`px-3 py-1.5 rounded-full text-xs font-semibold border ${
                                        filter === f.id
                                            ? 'bg-vida-main text-white border-vida-main'
                                            : 'bg-white text-gray-600 border-gray-200'
                                    }`}
                                >
                                    {f.label}
                                </button>
                            ))}
                            <select
                                value={estado}
                                onChange={(e) => setEstado(e.target.value)}
                                aria-label="Estado del beneficiario"
                                className="px-3 py-1.5 border rounded-lg text-sm outline-none focus:ring-2 focus:ring-vida-primary"
                            >
                                <option value="">Todos los estados</option>
                                {data.estados_considerados.map((e) => (
                                    <option key={e} value={e}>
                                        {ESTADO_LABELS[e] || e}
                                    </option>
                                ))}
                            </select>
                            <input
                                type="text"
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                                placeholder="Buscar nombre o CI"
                                className="px-3 py-1.5 border rounded-lg text-sm outline-none focus:ring-2 focus:ring-vida-primary"
                            />
                        </div>
                    </div>
                    <div className="overflow-x-auto border border-gray-100 rounded-xl mb-6 max-h-[32rem] overflow-y-auto">
                        <table className="w-full">
                            <thead className="bg-gray-50 border-b border-gray-100 sticky top-0">
                                <tr>
                                    {['Beneficiario', 'Estado', 'Insulina', 'Necesita', 'Recibe', 'Cobertura', 'Envases / lote'].map((h) => (
                                        <th key={h} className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">
                                            {h}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                {patients.length === 0 && (
                                    <tr>
                                        <td colSpan="7" className="px-4 py-6 text-center text-gray-400">
                                            Sin beneficiarios para este filtro.
                                        </td>
                                    </tr>
                                )}
                                {patients.flatMap((p) =>
                                    p.insulinas.map((i) => (
                                        <tr key={`${p.patient_id}-${i.insulina}`}>
                                            <td className="px-4 py-3 text-sm text-gray-800">
                                                {p.nombre_completo}
                                                <span className="block text-xs text-gray-400">{p.ci || 'Sin CI'}</span>
                                                {p.es_menor && (
                                                    <span className="mr-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-700">
                                                        MENOR
                                                    </span>
                                                )}
                                                {p.es_tipo1 && (
                                                    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 text-purple-700">
                                                        TIPO 1
                                                    </span>
                                                )}
                                            </td>
                                            <td className="px-4 py-3 text-xs text-gray-600">
                                                {ESTADO_LABELS[p.estado] || p.estado}
                                            </td>
                                            <td className="px-4 py-3 text-sm text-gray-700">
                                                {i.insulina}
                                                {i.sustituto && (
                                                    <span className="ml-2 px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-100 text-blue-700">
                                                        + {i.sustituto}
                                                    </span>
                                                )}
                                            </td>
                                            <td className="px-4 py-3 text-sm text-gray-700">
                                                {fmt(i.necesidad_ui)} UI
                                                <span className="block text-[10px] text-gray-400">{dosisTexto(i)}</span>
                                                {i.dosis_limitada && (
                                                    <span className="block text-[10px] font-semibold text-amber-600">
                                                        dosis limitada a {i.dosis_diaria_aplicada} UI/día
                                                    </span>
                                                )}
                                            </td>
                                            <td className="px-4 py-3 text-sm text-gray-700">{fmt(i.entregado_ui)} UI</td>
                                            <td
                                                className={`px-4 py-3 text-sm font-semibold ${
                                                    i.cobertura_pct >= 99.9 ? 'text-green-600' : 'text-red-600'
                                                }`}
                                            >
                                                {i.cobertura_pct}%
                                                {(p.es_menor || p.es_tipo1) && i.cobertura_pct > TOPE_COBERTURA + 0.05 && (
                                                    <span className="block text-[10px] font-semibold text-amber-600">
                                                        pasa de {TOPE_COBERTURA} % (envase entero)
                                                    </span>
                                                )}
                                                <span className="block text-[10px] font-normal text-gray-400">
                                                    ≈ {diasCubiertos(i.cobertura_pct, data.dias)} de {data.dias} días
                                                </span>
                                            </td>
                                            <td className="px-4 py-3 text-xs text-gray-600">{lotesTexto(i.lotes)}</td>
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>

                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                        <div>
                            <h3 className="text-lg font-bold text-gray-700 mb-3">Reserva apartada</h3>
                            <div className="overflow-x-auto border border-gray-100 rounded-xl max-h-64 overflow-y-auto">
                                <table className="w-full">
                                    <thead className="bg-gray-50 border-b border-gray-100">
                                        <tr>
                                            {['Producto', 'Lote', 'Envases', 'UI'].map((h) => (
                                                <th key={h} className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">
                                                    {h}
                                                </th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-100">
                                        {data.reserva.length === 0 && (
                                            <tr>
                                                <td colSpan="4" className="px-4 py-6 text-center text-gray-400">
                                                    Sin reserva.
                                                </td>
                                            </tr>
                                        )}
                                        {data.reserva.map((r, idx) => (
                                            <tr key={`${r.lot_id}-${idx}`}>
                                                <td className="px-4 py-3 text-sm text-gray-700">{r.producto}</td>
                                                <td className="px-4 py-3 text-xs text-gray-600">{r.lote || '—'}</td>
                                                <td className="px-4 py-3 text-sm text-gray-700">{r.unidades}</td>
                                                <td className="px-4 py-3 text-sm text-gray-700">{fmt(r.ui)}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                        <div>
                            <h3 className="text-lg font-bold text-gray-700 mb-3">Filas del Excel omitidas y beneficiarios sin dosis</h3>
                            <div className="overflow-x-auto border border-gray-100 rounded-xl max-h-64 overflow-y-auto">
                                <table className="w-full">
                                    <tbody className="divide-y divide-gray-100">
                                        {data.filas_con_error.length === 0 && data.excluded_patients.length === 0 && (
                                            <tr>
                                                <td className="px-4 py-6 text-center text-gray-400">Nada omitido.</td>
                                            </tr>
                                        )}
                                        {data.filas_con_error.map((e) => (
                                            <tr key={`fila-${e.fila}`}>
                                                <td className="px-4 py-3 text-sm text-gray-700">
                                                    <span className="font-semibold">Fila {e.fila}</span>
                                                    {e.producto ? ` · ${e.producto}` : ''}
                                                    <span className="block text-xs text-red-600">{e.mensaje}</span>
                                                </td>
                                            </tr>
                                        ))}
                                        {data.excluded_patients.map((e) => (
                                            <tr key={`pac-${e.patient_id}`}>
                                                <td className="px-4 py-3 text-sm text-gray-700">
                                                    {e.nombre_completo}
                                                    <span className="block text-xs text-gray-500">{e.motivo}</span>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </>
            )}
        </div>
    );
}
