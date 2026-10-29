import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';
import * as XLSX from 'xlsx';
import { toast } from 'react-hot-toast';
import { Columns, Download, FileSpreadsheet, HeartHandshake, RefreshCcw, Search } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { DEPARTAMENTOS } from '../../constants/departamentos';
import { ESTADO_LABELS } from '../../constants/assisted';
import { listAssistedRegistrations } from '../../api/assistedRegistrations';
import { ASSISTED_COLUMNS, DEFAULT_ASSISTED_COLUMNS } from '../../utils/assistedReportColumns';
import logoUrl from '../../assets/logo.png';
import { imageToBase64 } from '../../utils/imageToBase64';

const selectClass = 'border border-gray-200 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-vida-main';

/**
 * Reporte de las personas del Registro Asistido por Situación Excepcional: se eligen las columnas y se
 * descarga en PDF o Excel. Con «solo con código» se quitan las columnas que identifican a la persona o a
 * quien la atiende, para informes a donantes (Art. 19 IV del reglamento).
 */
export default function AssistedBeneficiariesReport() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [estado, setEstado] = useState('ACTIVO');
  const [depto, setDepto] = useState('');
  const [soloVencidos, setSoloVencidos] = useState(false);
  const [soloCodigo, setSoloCodigo] = useState(false);
  const [selected, setSelected] = useState(DEFAULT_ASSISTED_COLUMNS);
  const [showSelector, setShowSelector] = useState(false);
  const selectorRef = useRef(null);
  const [logoBase64, setLogoBase64] = useState(null);

  useEffect(() => {
    imageToBase64(logoUrl)
      .then(setLogoBase64)
      .catch((err) => console.error('Error al cargar el logo en base64', err));
  }, []);

  useEffect(() => {
    const onClickOutside = (event) => {
      if (selectorRef.current && !selectorRef.current.contains(event.target)) setShowSelector(false);
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setItems(await listAssistedRegistrations({ q: q.trim(), estado, depto, revision_vencida: soloVencidos ? true : '' }));
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo cargar el Registro Asistido.');
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [q, estado, depto, soloVencidos]);

  useEffect(() => {
    const timer = setTimeout(load, 300);
    return () => clearTimeout(timer);
  }, [load]);

  // Con «solo con código» no se pueden elegir las columnas que identifican a alguien.
  const disponible = (col) => !(soloCodigo && col.identifica);
  const activeColumns = useMemo(
    () => ASSISTED_COLUMNS.filter((col) => selected.includes(col.id) && disponible(col)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selected, soloCodigo],
  );

  const toggleColumn = (id) =>
    setSelected((prev) => {
      if (prev.includes(id)) return prev.length === 1 ? prev : prev.filter((c) => c !== id);
      return [...prev, id];
    });

  const sinColumnas = activeColumns.length === 0;
  const fileDate = new Date().toISOString().split('T')[0];
  const fileName = `Registro_Asistido${soloCodigo ? '_solo_codigo' : ''}_${fileDate}`;

  const exportPDF = () => {
    if (items.length === 0 || sinColumnas) {
      toast.error(sinColumnas ? 'Elija al menos una columna.' : 'No hay registros para descargar.');
      return;
    }
    if (!logoBase64) {
      toast.error('El logo aún se está cargando, intente en un momento');
      return;
    }
    const doc = new jsPDF({ orientation: activeColumns.length >= 6 ? 'landscape' : 'portrait', unit: 'mm', format: 'letter' });
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
      doc.setFontSize(13);
      doc.text('Registro Asistido por Situación Excepcional', margin + 30, 22);
      doc.setFontSize(9);
      doc.setTextColor(100, 116, 139);
      doc.setFont('helvetica', 'normal');
      doc.text(`Fecha de generación: ${new Date().toLocaleDateString('es-BO')} ${new Date().toLocaleTimeString('es-BO')}`, margin + 30, 27);
      const filtros = [
        `Total registros: ${items.length}`,
        estado ? `Estado: ${ESTADO_LABELS[estado]}` : null,
        depto ? `Departamento: ${depto}` : null,
        soloVencidos ? 'Revisión semestral vencida' : null,
        soloCodigo ? 'Identificación solo por Código Interno' : null,
      ].filter(Boolean);
      doc.text(filtros.join(' | '), margin + 30, 32);
    };

    autoTable(doc, {
      head: [activeColumns.map((c) => c.label)],
      body: items.map((r) => activeColumns.map((c) => String(c.getValue(r)))),
      startY: 40,
      margin: { top: 40, left: margin, right: margin, bottom: 20 },
      styles: { fontSize: activeColumns.length > 9 ? 7 : 8, cellPadding: 3, font: 'helvetica' },
      headStyles: { fillColor: [14, 165, 233], textColor: 255, fontStyle: 'bold' },
      alternateRowStyles: { fillColor: [248, 250, 252] },
      didDrawPage: () => {
        addHeader();
        doc.setFontSize(8);
        doc.setTextColor(150);
        doc.text(`Página ${doc.internal.getNumberOfPages()}`, pageWidth / 2, doc.internal.pageSize.getHeight() - 10, { align: 'center' });
      },
    });

    doc.save(`${fileName}.pdf`);
    toast.success('Reporte descargado exitosamente');
  };

  const exportXLS = () => {
    if (items.length === 0 || sinColumnas) {
      toast.error(sinColumnas ? 'Elija al menos una columna.' : 'No hay registros para descargar.');
      return;
    }
    const rows = items.map((r) => Object.fromEntries(activeColumns.map((c) => [c.label, c.getValue(r)])));
    const worksheet = XLSX.utils.json_to_sheet(rows);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Registro asistido');
    XLSX.writeFile(workbook, `${fileName}.xlsx`);
    toast.success('Reporte descargado exitosamente');
  };

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
          <HeartHandshake size={22} /> Registro Asistido por Situación Excepcional
        </h2>
        <p className="text-sm text-gray-500">
          Elija los filtros y las columnas que quiere en el informe y descárguelo en PDF o Excel. Para informes a donantes use
          «solo con código»: se quitan los datos que identifican a la persona y a su persona referente.
        </p>
      </div>

      <div className="bg-white rounded-2xl shadow-xl border border-gray-100 p-6">
        <div className="flex flex-col lg:flex-row justify-between items-start lg:items-end gap-4 mb-6">
          <div className="flex flex-wrap gap-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
              <input
                aria-label="Buscar"
                placeholder="Código, nombre, C.I., entidad o referente…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                className={`${selectClass} pl-9 w-72`}
              />
            </div>
            <select aria-label="Estado" value={estado} onChange={(e) => setEstado(e.target.value)} className={selectClass}>
              <option value="">Todos los estados</option>
              {Object.entries(ESTADO_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <select aria-label="Departamento" value={depto} onChange={(e) => setDepto(e.target.value)} className={selectClass}>
              <option value="">Todos los departamentos</option>
              {DEPARTAMENTOS.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={soloVencidos} onChange={(e) => setSoloVencidos(e.target.checked)} />
              Revisión semestral vencida
            </label>

            <div className="relative" ref={selectorRef}>
              <button
                type="button"
                onClick={() => setShowSelector((v) => !v)}
                className="flex items-center gap-2 px-4 py-2 bg-gray-50 border border-gray-200 text-gray-700 rounded-xl hover:bg-gray-100 transition-colors"
              >
                <Columns size={18} /> Columnas ({activeColumns.length})
              </button>
              {showSelector && (
                <div className="absolute z-10 mt-2 w-72 bg-white rounded-xl shadow-lg border border-gray-100 py-2 top-full left-0">
                  <div className="px-3 pb-2 mb-2 border-b border-gray-100 text-xs font-bold text-gray-500">SELECCIONAR COLUMNAS</div>
                  <div className="max-h-72 overflow-y-auto px-2">
                    {ASSISTED_COLUMNS.map((col) => (
                      <label
                        key={col.id}
                        className={`flex items-center gap-2 p-2 rounded-lg ${disponible(col) ? 'hover:bg-gray-50 cursor-pointer' : 'opacity-40 cursor-not-allowed'}`}
                        title={disponible(col) ? undefined : 'Identifica a la persona: no va en un informe solo con código'}
                      >
                        <input
                          type="checkbox"
                          checked={selected.includes(col.id) && disponible(col)}
                          disabled={!disponible(col)}
                          onChange={() => toggleColumn(col.id)}
                          className="rounded text-vida-main focus:ring-vida-main"
                        />
                        <span className="text-sm text-gray-700">{col.label}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={soloCodigo} onChange={(e) => setSoloCodigo(e.target.checked)} />
              Solo con código (para donantes)
            </label>
          </div>

          <div className="flex gap-2">
            <Button variant="secondary" onClick={load} disabled={loading} className="px-3" aria-label="Actualizar">
              <RefreshCcw size={18} className={loading ? 'animate-spin' : ''} />
            </Button>
            <Button onClick={exportPDF} disabled={loading || items.length === 0 || sinColumnas} className="bg-green-600 hover:bg-green-700 text-white w-auto justify-center">
              <Download size={18} /> {items.length === 0 ? 'Sin datos' : 'PDF'}
            </Button>
            <Button onClick={exportXLS} disabled={loading || items.length === 0 || sinColumnas} className="bg-emerald-700 hover:bg-emerald-800 text-white w-auto justify-center">
              <FileSpreadsheet size={18} /> {items.length === 0 ? 'Sin datos' : 'Excel'}
            </Button>
          </div>
        </div>

        <div className="overflow-x-auto border border-gray-100 rounded-xl">
          <table className="w-full text-left">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                {activeColumns.map((col) => (
                  <th key={col.id} className="px-4 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider whitespace-nowrap">{col.label}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                <tr><td colSpan={Math.max(activeColumns.length, 1)} className="px-4 py-10 text-center text-gray-500">Cargando…</td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={Math.max(activeColumns.length, 1)} className="px-4 py-10 text-center text-gray-400">No hay registros con esos filtros.</td></tr>
              ) : (
                items.map((r) => (
                  <tr key={r.id} className="hover:bg-gray-50/50 transition-colors">
                    {activeColumns.map((col) => (
                      <td key={col.id} className={`px-4 py-3 text-sm text-gray-700 ${col.multiline ? 'whitespace-pre-line' : 'whitespace-nowrap'}`}>
                        {col.getValue(r)}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-gray-400">{items.length} registro(s)</p>
      </div>
    </div>
  );
}
