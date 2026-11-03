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
const formatCount = (value) => Number(value).toLocaleString('es-BO');

// Viales de 3 ml por concentración (U100 = 300 UI por vial, U200 = 600 UI, U300 = 900 UI) y de 10 ml solo en U100
// (1.000 UI), redondeados hacia arriba.
const CONCENTRACIONES = ['U100', 'U200', 'U300'];
// Presentaciones del reparto por porcentajes, en el orden de las columnas.
const PRESENTACIONES = [
  { id: '3ml_U100', titulo: 'Cant. Vial 3ml U100', etiqueta: 'Vial 3ml U100' },
  { id: '3ml_U200', titulo: 'Cant. Vial 3ml U200', etiqueta: 'Vial 3ml U200' },
  { id: '3ml_U300', titulo: 'Cant. Vial 3ml U300', etiqueta: 'Vial 3ml U300' },
  { id: '10ml_U100', titulo: 'Cant. Vial 10ml U100', etiqueta: 'Vial 10ml U100' },
];
const pctCorto = (value) => `${Number(value).toLocaleString('es-BO', { maximumFractionDigits: 2 })} %`;

// Sin reparto: una columna por escenario (todo en esa presentación). Con reparto: una por presentación, con su porcentaje.
const encabezados = (dias, reparto) => [
  'Tipo de insulina',
  `Cantidad requerida (${dias} días)`,
  ...PRESENTACIONES.map((p) => (reparto ? `${p.titulo} (${pctCorto(reparto[p.id])})` : p.titulo)),
];
// Las celdas de envases de una insulina, en el mismo orden que los encabezados.
const vialesDe = (i, reparto) =>
  reparto
    ? PRESENTACIONES.map((p) => i.plan[p.id].envases)
    : [...CONCENTRACIONES.map((c) => i.viales_3ml[c]), i.viales_10ml.U100];

// Parte de 100 % que queda para las tres presentaciones de 3 ml, a partes iguales.
const restoEnTres = (pct10) => String(Number(((100 - Number(pct10 || 0)) / 3).toFixed(4)));
const REPARTO_INICIAL = { '10ml_U100': '30', '3ml_U100': restoEnTres(30), '3ml_U200': restoEnTres(30), '3ml_U300': restoEnTres(30) };
const repartoNumerico = (texto) => Object.fromEntries(Object.entries(texto).map(([k, v]) => [k, Number(v)]));
const sumaDe = (texto) => Object.values(texto).reduce((acc, v) => acc + (Number(v) || 0), 0);
const esValido = (texto) =>
  Object.values(texto).every((v) => v !== '' && Number(v) >= 0 && Number(v) <= 100) && Math.abs(sumaDe(texto) - 100) <= 0.05;
const formatPct = (value) => `${Number(value).toLocaleString('es-BO', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`;

// Los datos de abajo del cuadro, en dos bloques (rango etario y tipo de diabetes) y, al final, el total.
// Cada fila es [etiqueta, valor]; una fila con un solo elemento es el título de un bloque.
const resumenDe = (data) => [
  ['Porcentajes por Rango Etario'],
  ['Porcentaje de beneficiarios menores de 18 años', formatPct(data.menores_18.porcentaje)],
  ['Porcentaje de beneficiarios entre 18 y 60 años', formatPct(data.entre_18_y_60.porcentaje)],
  ['Porcentaje de adultos mayores de 61 años en adelante', formatPct(data.mayores_61.porcentaje)],
  ['Porcentaje por Tipo de Diabetes'],
  ['Porcentaje de diabéticos tipo 1', formatPct(data.diabeticos_tipo_1.porcentaje)],
  ['Porcentaje de diabéticos tipo 2 insulino requirentes', formatPct(data.diabeticos_tipo_2.porcentaje)],
  // Las personas del Registro Asistido por Situación Excepcional también son beneficiarias y suman al total.
  ...(data.asistidos_incluidos > 0 ? [['Del Registro Asistido (incluidos en el total)', String(data.asistidos_incluidos)]] : []),
  ['Total de beneficiarios', String(data.total_beneficiarios)],
];

export default function DonationRequestReport() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [logoBase64, setLogoBase64] = useState(null);
  // Reparto por porcentajes entre presentaciones (opcional).
  const [usarReparto, setUsarReparto] = useState(false);
  const [pcts, setPcts] = useState(REPARTO_INICIAL);
  const repartoValido = esValido(pcts);

  const load = async (reparto = null) => {
    try {
      setLoading(true);
      setData(await getDonationRequestReport(reparto));
    } catch (error) {
      toast.error(typeof error === 'string' ? error : 'No se pudo cargar el reporte.');
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    imageToBase64(logoUrl)
      .then(setLogoBase64)
      .catch((err) => console.error('Error al cargar el logo en base64', err));
  }, []);

  // Sin reparto se piden los escenarios; con reparto válido se vuelve a calcular al cambiar los porcentajes.
  useEffect(() => {
    if (usarReparto && !repartoValido) return undefined;
    const timer = setTimeout(() => load(usarReparto ? repartoNumerico(pcts) : null), usarReparto ? 400 : 0);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usarReparto, repartoValido, JSON.stringify(pcts)]);

  const cambiarPct = (id, valor) =>
    setPcts((prev) => {
      const next = { ...prev, [id]: valor };
      // Al cambiar el frasco de 10 ml, el resto se vuelve a dividir en partes iguales entre las de 3 ml.
      if (id === '10ml_U100') {
        const resto = restoEnTres(valor);
        next['3ml_U100'] = next['3ml_U200'] = next['3ml_U300'] = resto;
      }
      return next;
    });

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
    doc.text(
      data.reparto
        ? `Cantidad requerida para ${data.dias} días | Reparto: ${PRESENTACIONES.map((p) => `${p.etiqueta} ${pctCorto(data.reparto[p.id])}`).join(', ')}`
        : `Cantidad requerida calculada para ${data.dias} días de tratamiento`,
      margin + 30,
      32,
    );

    autoTable(doc, {
      head: [encabezados(data.dias, data.reparto)],
      body: data.insulinas.map((i) => [i.insulina, formatUi(i.cantidad_ui), ...vialesDe(i, data.reparto).map(formatCount)]),
      startY: 42,
      margin: { left: margin, right: margin },
      styles: { fontSize: 9, cellPadding: 3, font: 'helvetica' },
      headStyles: { fillColor: [14, 165, 233], textColor: 255, fontStyle: 'bold', halign: 'right' },
      alternateRowStyles: { fillColor: [248, 250, 252] },
      columnStyles: { 0: { halign: 'left' }, 1: { halign: 'right' }, 2: { halign: 'right' }, 3: { halign: 'right' }, 4: { halign: 'right' }, 5: { halign: 'right' } },
      // El título de la primera columna va a la izquierda, como sus datos.
      didParseCell: (hook) => {
        if (hook.section === 'head' && hook.column.index === 0) hook.cell.styles.halign = 'left';
      },
    });

    const resumen = resumenDe(data);
    autoTable(doc, {
      body: resumen.map((fila) => (fila.length === 1 ? [{ content: fila[0], colSpan: 2 }] : fila)),
      startY: doc.lastAutoTable.finalY + 8,
      margin: { left: margin, right: margin },
      theme: 'plain',
      styles: { fontSize: 10, cellPadding: 2, font: 'helvetica' },
      columnStyles: { 0: { cellWidth: 120 }, 1: { fontStyle: 'bold', halign: 'right' } },
      // El total va al final, resaltado.
      didParseCell: (hook) => {
        const fila = resumen[hook.row.index];
        if (hook.section !== 'body' || !fila) return;
        // Títulos de bloque y total, en negrita.
        if (fila.length === 1 || hook.row.index === resumen.length - 1) hook.cell.styles.fontStyle = 'bold';
      },
    });

    doc.save(`Solicitud_Donacion_${fileDate}.pdf`);
    toast.success('Reporte descargado exitosamente');
  };

  const exportXLS = () => {
    const rows = [
      encabezados(data.dias, data.reparto),
      ...data.insulinas.map((i) => [i.insulina, i.cantidad_ui, ...vialesDe(i, data.reparto)]),
      [],
      ...resumenDe(data),
    ];
    const worksheet = XLSX.utils.aoa_to_sheet(rows);
    worksheet['!cols'] = [{ wch: 48 }, { wch: 26 }, { wch: 20 }, { wch: 20 }, { wch: 20 }, { wch: 22 }];
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
            Insulina necesaria para 60 días de tratamiento, sumando la dosis diaria de todos los beneficiarios registrados.
            Además se indica cuántos viales de 3 ml hacen falta por concentración (U100 = 300 UI, U200 = 600 UI, U300 = 900 UI)
            y cuántos de 10 ml en U100 (1.000 UI), redondeando siempre hacia arriba.
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

      <div className="bg-white border border-gray-100 rounded-xl p-4 mb-4 max-w-5xl">
        <label className="flex items-center gap-2 text-sm font-semibold text-gray-700">
          <input type="checkbox" checked={usarReparto} onChange={(e) => setUsarReparto(e.target.checked)} />
          Calcular con un reparto por porcentajes entre presentaciones
        </label>
        <p className="text-xs text-gray-500 mt-1">
          Sin esto, cada columna muestra el escenario «toda la insulina en esa presentación». Con el reparto, cada columna indica
          los envases que corresponden al porcentaje que se pida en esa presentación.
        </p>
        {usarReparto && (
          <div className="mt-3">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[PRESENTACIONES[3], PRESENTACIONES[0], PRESENTACIONES[1], PRESENTACIONES[2]].map((p) => (
                <div key={p.id}>
                  <label htmlFor={`pct-${p.id}`} className="block text-xs font-semibold text-gray-700 mb-1">{p.etiqueta} (%)</label>
                  <input
                    id={`pct-${p.id}`}
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    value={pcts[p.id]}
                    onChange={(e) => cambiarPct(p.id, e.target.value)}
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
              ))}
            </div>
            <p className={`text-xs mt-2 font-semibold ${repartoValido ? 'text-green-700' : 'text-red-600'}`}>
              Suma: {pctCorto(sumaDe(pcts))} {repartoValido ? '' : '— los porcentajes deben sumar 100 %'}
            </p>
            <p className="text-xs text-gray-400 mt-1">
              Al cambiar el frasco de 10 ml, el resto se divide en partes iguales entre las tres de 3 ml; luego puede ajustar cada una.
            </p>
          </div>
        )}
      </div>

      {loading ? (
        <div className="p-10 text-center text-gray-500 font-semibold">Cargando...</div>
      ) : !data ? (
        <div className="bg-white border border-gray-100 rounded-xl p-6 text-sm text-gray-500">No se pudo cargar el reporte.</div>
      ) : (
        <div className="bg-white rounded-2xl shadow-xl border border-gray-100 overflow-hidden max-w-5xl">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                {encabezados(data.dias, data.reparto).map((titulo, index) => (
                  <th
                    key={titulo}
                    className={`px-4 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider ${index === 0 ? 'text-left' : 'text-right'}`}
                  >
                    {titulo}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.insulinas.length === 0 ? (
                <tr>
                  <td colSpan="6" className="px-4 py-6 text-center text-gray-400">
                    Ningún beneficiario tiene insulina con dosis diaria registrada.
                  </td>
                </tr>
              ) : (
                data.insulinas.map((i) => (
                  <tr key={i.insulina} className="hover:bg-gray-50/70 transition-colors">
                    <td className="px-4 py-3 text-sm text-gray-800 font-medium">{i.insulina}</td>
                    <td className="px-4 py-3 text-sm text-right text-gray-700">{formatUi(i.cantidad_ui)}</td>
                    {vialesDe(i, data.reparto).map((cantidad, index) => (
                      <td key={index} className="px-4 py-3 text-sm text-right text-gray-700">{formatCount(cantidad)}</td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>

          <dl className="border-t border-gray-100 px-4 py-4 space-y-2 text-sm">
            {resumenDe(data).map(([label, value], index, all) =>
              value === undefined ? (
                <div key={label} className="pt-2 font-bold text-gray-900 border-b border-gray-100 pb-1">
                  {label}
                </div>
              ) : (
                <div
                  key={label}
                  className={`flex justify-between gap-4 ${index === all.length - 1 ? 'pt-2 border-t border-gray-100 font-bold text-gray-900' : 'text-gray-700'}`}
                >
                  <dt>{label}</dt>
                  <dd className="font-semibold">{value}</dd>
                </div>
              ),
            )}
          </dl>
          {data.reparto && (
            <p className="px-4 py-3 text-xs text-gray-500 border-t border-gray-100">
              Los envases de cada presentación se redondean hacia arriba, por lo que el total pedido puede superar un poco las UI requeridas.
            </p>
          )}
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
