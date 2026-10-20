import { useEffect, useMemo, useState } from 'react';
import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';
import * as XLSX from 'xlsx';
import { BookOpen, Download, FileSpreadsheet, Loader2, Search } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '../../components/ui/Button';
import { getDirectorDeliveries } from '../../api/directorDeliveries';
import logoUrl from '../../assets/logo.png';
import { imageToBase64 } from '../../utils/imageToBase64';

const toDateInput = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

const daysAgo = (n) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return toDateInput(d);
};

const fullName = (item) =>
  [item.patient_nombres, item.patient_ap_paterno, item.patient_ap_materno].filter(Boolean).join(' ');

const formatDate = (iso) => {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y}`;
};

// Reporte del cuaderno de la Directora: todo lo que registró (persona, insulina, marca,
// presentación, cantidad y fecha), con filtro por fechas y búsqueda, descargable en PDF y Excel.
export default function DirectorNotebookReport() {
  const [desde, setDesde] = useState(daysAgo(30));
  const [hasta, setHasta] = useState(toDateInput(new Date()));
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState({ total: 0, items: [] });
  const [logoBase64, setLogoBase64] = useState(null);

  useEffect(() => {
    imageToBase64(logoUrl)
      .then(setLogoBase64)
      .catch((err) => console.error('Error al cargar el logo en base64', err));
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), 400);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (desde && hasta && desde > hasta) {
      toast.error('La fecha «desde» no puede ser posterior a «hasta».');
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const result = await getDirectorDeliveries({ desde, hasta, q: debouncedSearch });
        if (!cancelled) setData(result || { total: 0, items: [] });
      } catch (error) {
        if (!cancelled) {
          toast.error(error?.response?.data?.detail || 'No se pudo cargar el cuaderno.');
          setData({ total: 0, items: [] });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [desde, hasta, debouncedSearch]);

  const personas = useMemo(() => new Set(data.items.map((i) => fullName(i))).size, [data.items]);
  const rango = `${desde ? formatDate(desde) : 'inicio'} al ${hasta ? formatDate(hasta) : 'hoy'}`;
  const sufijo = `${desde || 'inicio'}_${hasta || 'hoy'}`;

  const rows = () =>
    data.items.map((i) => ({
      Fecha: formatDate(i.delivery_date),
      Beneficiario: fullName(i),
      'C.I.': i.patient_ci || '',
      Departamento: i.patient_depto || '',
      Insulina: i.insulin_type,
      Marca: i.marca || '',
      Presentación: i.presentacion || '',
      Cantidad: i.quantity,
      'Registrado por': i.registrado_por || '',
    }));

  const exportXLS = () => {
    if (!data.items.length) {
      toast.error('No hay registros para descargar.');
      return;
    }
    const worksheet = XLSX.utils.json_to_sheet(rows());
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Cuaderno');
    XLSX.writeFile(workbook, `Cuaderno_Directora_${sufijo}.xlsx`);
    toast.success('Reporte descargado exitosamente');
  };

  const exportPDF = () => {
    if (!data.items.length) {
      toast.error('No hay registros para descargar.');
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
      doc.text('Cuaderno de la Directora — Entregas de insulina', margin + 30, 22);
      doc.setFontSize(9);
      doc.setTextColor(100, 116, 139);
      doc.setFont('helvetica', 'normal');
      doc.text(
        `Generado: ${new Date().toLocaleDateString('es-BO')} ${new Date().toLocaleTimeString('es-BO')} | Periodo: ${rango} | Registros: ${data.items.length} | Personas: ${personas}`,
        margin + 30,
        28,
      );
    };
    autoTable(doc, {
      head: [['Fecha', 'Beneficiario', 'C.I.', 'Depto', 'Insulina', 'Marca', 'Presentación', 'Cantidad', 'Registró']],
      body: data.items.map((i) => [
        formatDate(i.delivery_date),
        fullName(i),
        i.patient_ci || '-',
        i.patient_depto || '-',
        i.insulin_type,
        i.marca || '-',
        i.presentacion || '-',
        i.quantity,
        i.registrado_por || '-',
      ]),
      startY: 40,
      margin: { top: 40, left: margin, right: margin, bottom: 20 },
      styles: { fontSize: 8, cellPadding: 2.5, font: 'helvetica' },
      headStyles: { fillColor: [21, 128, 61], textColor: 255, fontStyle: 'bold' },
      alternateRowStyles: { fillColor: [248, 250, 252] },
      didDrawPage: () => {
        addHeader();
        doc.setFontSize(8);
        doc.setTextColor(150);
        doc.text(`Página ${doc.internal.getNumberOfPages()}`, pageWidth / 2, doc.internal.pageSize.getHeight() - 10, {
          align: 'center',
        });
      },
    });
    doc.save(`Cuaderno_Directora_${sufijo}.pdf`);
    toast.success('Reporte descargado exitosamente');
  };

  return (
    <div>
      <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-3 mb-6">
        <div>
          <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
            <BookOpen size={22} /> Cuaderno de la Directora
          </h2>
          <p className="text-sm text-gray-500 max-w-2xl">
            Lo que se registró en el cuaderno: persona, insulina, marca, presentación y cantidad entregada.
          </p>
        </div>
        <div className="flex items-end gap-2 flex-wrap">
          <div>
            <label className="block text-xs font-semibold text-gray-700 mb-1" htmlFor="cuaderno-desde">Desde</label>
            <input id="cuaderno-desde" type="date" value={desde} onChange={(e) => setDesde(e.target.value)} className="border rounded-lg px-3 py-2 text-sm bg-white" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-700 mb-1" htmlFor="cuaderno-hasta">Hasta</label>
            <input id="cuaderno-hasta" type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} className="border rounded-lg px-3 py-2 text-sm bg-white" />
          </div>
          <div className="relative">
            <label className="block text-xs font-semibold text-gray-700 mb-1" htmlFor="cuaderno-buscar">Buscar</label>
            <Search size={14} className="absolute left-3 top-[2.1rem] text-gray-400" />
            <input
              id="cuaderno-buscar"
              type="text"
              placeholder="Nombre, C.I., insulina o marca"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="border rounded-lg pl-8 pr-3 py-2 text-sm bg-white w-60"
            />
          </div>
          <Button
            type="button"
            onClick={exportPDF}
            disabled={loading || data.items.length === 0}
            className="!w-auto shrink-0 px-5 bg-red-600 hover:bg-red-700 text-white"
          >
            <Download size={18} /> PDF
          </Button>
          <Button
            type="button"
            onClick={exportXLS}
            disabled={loading || data.items.length === 0}
            className="!w-auto shrink-0 px-5 bg-green-600 hover:bg-green-700 text-white"
          >
            <FileSpreadsheet size={18} /> Excel
          </Button>
        </div>
      </div>

      <p className="text-sm text-gray-500 mb-3">
        {loading ? (
          <span className="inline-flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Cargando…</span>
        ) : (
          <>
            <strong>{data.total}</strong> registros · <strong>{personas}</strong> personas · {rango}
            {data.total > data.items.length && ` (se muestran los ${data.items.length} más recientes)`}
          </>
        )}
      </p>

      <div className="bg-white rounded-2xl shadow-xl border border-gray-100 overflow-hidden">
        <div className="overflow-x-auto max-h-[34rem] overflow-y-auto">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-100 sticky top-0">
              <tr>
                {['Fecha', 'Beneficiario', 'C.I.', 'Depto', 'Insulina', 'Marca', 'Presentación', 'Cantidad', 'Registró'].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {!loading && data.items.length === 0 && (
                <tr>
                  <td colSpan="9" className="px-4 py-8 text-center text-gray-400">
                    No hay entregas registradas para este filtro.
                  </td>
                </tr>
              )}
              {data.items.map((i) => (
                <tr key={i.id} className="hover:bg-gray-50/70 transition-colors">
                  <td className="px-4 py-3 text-sm text-gray-600 whitespace-nowrap">{formatDate(i.delivery_date)}</td>
                  <td className="px-4 py-3 text-sm text-gray-800 font-medium">{fullName(i)}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{i.patient_ci || '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{i.patient_depto || '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{i.insulin_type}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{i.marca || '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{i.presentacion || '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-700">{i.quantity}</td>
                  <td className="px-4 py-3 text-xs text-gray-500">{i.registrado_por || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
