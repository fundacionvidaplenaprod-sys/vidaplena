import { useEffect, useState } from 'react';
import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';
import * as XLSX from 'xlsx';
import { Download, FileSpreadsheet, HandHeart, RefreshCcw } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '../../components/ui/Button';
import { getDonationRequestReport } from '../../api/reports';
import logoUrl from '../../assets/logo.png';
import { imageToBase64 } from '../../utils/imageToBase64';

const formatUi = (value) => `${Number(value).toLocaleString('es-BO')} UI`;
const formatPct = (value) => `${Number(value).toLocaleString('es-BO', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`;

// Los datos de abajo del cuadro: porcentajes de la población y, al final, el total.
const resumenDe = (data) => [
  ['Porcentaje de beneficiarios menores de 18 años', formatPct(data.menores_18.porcentaje)],
  ['Porcentaje de adultos mayores de 65 años', formatPct(data.mayores_65.porcentaje)],
  ['Porcentaje de diabéticos tipo 1', formatPct(data.diabeticos_tipo_1.porcentaje)],
  ['Porcentaje de diabéticos tipo 2', formatPct(data.diabeticos_tipo_2.porcentaje)],
  ['Total de beneficiarios', String(data.total_beneficiarios)],
];

export default function DonationRequestReport() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [logoBase64, setLogoBase64] = useState(null);

  const load = async () => {
    try {
      setLoading(true);
      setData(await getDonationRequestReport());
    } catch (error) {
      toast.error(typeof error === 'string' ? error : 'No se pudo cargar el reporte.');
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    imageToBase64(logoUrl)
      .then(setLogoBase64)
      .catch((err) => console.error('Error al cargar el logo en base64', err));
  }, []);

  const fileDate = new Date().toISOString().split('T')[0];
  const sinDatos = !data || data.insulinas.length === 0;

  const exportPDF = () => {
    if (!logoBase64) {
      toast.error('El logo aún se está cargando, intente en un momento');
      return;
    }
    const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'letter' });
    const pageWidth = doc.internal.pageSize.getWidth();
    const margin = 14;

    doc.setFillColor(248, 250, 252);
    doc.rect(0, 0, pageWidth, 35, 'F');
    doc.addImage(logoBase64, 'PNG', margin, 5, 25, 25);
    doc.setFontSize(18);
    doc.setTextColor(30, 58, 138);
    doc.setFont('helvetica', 'bold');
    doc.text('Fundación V.I.D.A. Plena', margin + 30, 16);
    doc.setFontSize(13);
    doc.text('Solicitud de Cantidades Requeridas de Donación', margin + 30, 22);
    doc.setFontSize(9);
    doc.setTextColor(100, 116, 139);
    doc.setFont('helvetica', 'normal');
    doc.text(`Fecha de generación: ${new Date().toLocaleDateString('es-BO')} ${new Date().toLocaleTimeString('es-BO')}`, margin + 30, 27);
    doc.text(`Cantidad requerida calculada para ${data.dias} días de tratamiento`, margin + 30, 32);

    autoTable(doc, {
      head: [['Tipo de insulina', `Cantidad requerida (${data.dias} días)`]],
      body: data.insulinas.map((i) => [i.insulina, formatUi(i.cantidad_ui)]),
      startY: 42,
      margin: { left: margin, right: margin },
      styles: { fontSize: 10, cellPadding: 3, font: 'helvetica' },
      headStyles: { fillColor: [14, 165, 233], textColor: 255, fontStyle: 'bold' },
      alternateRowStyles: { fillColor: [248, 250, 252] },
      columnStyles: { 1: { halign: 'right' } },
    });

    autoTable(doc, {
      body: resumenDe(data),
      startY: doc.lastAutoTable.finalY + 8,
      margin: { left: margin, right: margin },
      theme: 'plain',
      styles: { fontSize: 10, cellPadding: 2, font: 'helvetica' },
      columnStyles: { 0: { cellWidth: 120 }, 1: { fontStyle: 'bold', halign: 'right' } },
      // El total va al final, resaltado.
      didParseCell: (hook) => {
        if (hook.section === 'body' && hook.row.index === 4) hook.cell.styles.fontStyle = 'bold';
      },
    });

    doc.save(`Solicitud_Donacion_${fileDate}.pdf`);
    toast.success('Reporte descargado exitosamente');
  };

  const exportXLS = () => {
    const rows = [
      ['Tipo de insulina', `Cantidad requerida (${data.dias} días)`],
      ...data.insulinas.map((i) => [i.insulina, i.cantidad_ui]),
      [],
      ...resumenDe(data),
    ];
    const worksheet = XLSX.utils.aoa_to_sheet(rows);
    worksheet['!cols'] = [{ wch: 48 }, { wch: 26 }];
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Solicitud');
    XLSX.writeFile(workbook, `Solicitud_Donacion_${fileDate}.xlsx`);
    toast.success('Reporte descargado exitosamente');
  };

  return (
    <div>
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-6">
        <div>
          <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
            <HandHeart size={22} /> Solicitud de cantidades requeridas de donación
          </h2>
          <p className="text-sm text-gray-500">
            Insulina necesaria para 60 días de tratamiento, sumando la dosis diaria de todos los beneficiarios registrados
            (estén o no al día con su aporte o les falten documentos).
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={load} disabled={loading} className="px-3">
            <RefreshCcw size={18} className={loading ? 'animate-spin' : ''} />
          </Button>
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
        <div className="bg-white border border-gray-100 rounded-xl p-6 text-sm text-gray-500">No se pudo cargar el reporte.</div>
      ) : (
        <div className="bg-white rounded-2xl shadow-xl border border-gray-100 overflow-hidden max-w-3xl">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Tipo de insulina</th>
                <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">
                  Cantidad requerida ({data.dias} días)
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.insulinas.length === 0 ? (
                <tr>
                  <td colSpan="2" className="px-4 py-6 text-center text-gray-400">
                    Ningún beneficiario tiene insulina con dosis diaria registrada.
                  </td>
                </tr>
              ) : (
                data.insulinas.map((i) => (
                  <tr key={i.insulina} className="hover:bg-gray-50/70 transition-colors">
                    <td className="px-4 py-3 text-sm text-gray-800 font-medium">{i.insulina}</td>
                    <td className="px-4 py-3 text-sm text-right text-gray-700">{formatUi(i.cantidad_ui)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>

          <dl className="border-t border-gray-100 px-4 py-4 space-y-2 text-sm">
            {resumenDe(data).map(([label, value], index, all) => (
              <div
                key={label}
                className={`flex justify-between gap-4 ${index === all.length - 1 ? 'pt-2 border-t border-gray-100 font-bold text-gray-900' : 'text-gray-700'}`}
              >
                <dt>{label}</dt>
                <dd className="font-semibold">{value}</dd>
              </div>
            ))}
          </dl>
          {data.sin_insulina_registrada > 0 && (
            <p className="px-4 pb-4 text-xs text-gray-400">
              {data.sin_insulina_registrada} beneficiario(s) no tienen insulina con dosis diaria registrada y no suman cantidad.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
