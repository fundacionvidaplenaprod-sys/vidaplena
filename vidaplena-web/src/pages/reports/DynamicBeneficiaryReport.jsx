import { useState, useEffect, useMemo, useRef } from 'react';
import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';
import { getPatients } from '../../api/patients';
import { Download, Filter, Search, Columns, RefreshCcw } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '../../components/ui/Button';
import logoUrl from '../../assets/logo.png';

// Función para convertir imagen a Base64
const imageToBase64 = (url) => {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'Anonymous';
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = img.width;
      canvas.height = img.height;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0);
      const dataURL = canvas.toDataURL('image/png');
      resolve(dataURL);
    };
    img.onerror = (error) => reject(error);
    img.src = url;
  });
};

const ALL_COLUMNS = [
  { id: 'nombres', label: 'Nombres', getValue: p => p.nombres },
  { id: 'ap_paterno', label: 'Ap. Paterno', getValue: p => p.ap_paterno },
  { id: 'ap_materno', label: 'Ap. Materno', getValue: p => p.ap_materno || '-' },
  { id: 'ci', label: 'CI', getValue: p => p.ci },
  { id: 'edad', label: 'Edad', getValue: p => {
      if (!p.fecha_nac) return '-';
      const diff = new Date() - new Date(p.fecha_nac);
      return Math.floor(diff / 31557600000);
  }},
  { id: 'fecha_nac', label: 'Fecha Nac.', getValue: p => p.fecha_nac ? new Date(p.fecha_nac).toLocaleDateString('es-BO') : '-' },
  { id: 'celular', label: 'Celular', getValue: p => p.tel_contacto || p.celular || '-' },
  { id: 'departamento', label: 'Departamento', getValue: p => p.depto || p.departamento || '-' },
  { id: 'municipio', label: 'Municipio', getValue: p => p.municipio || '-' },
  { id: 'zona', label: 'Zona', getValue: p => p.zona || '-' },
  { id: 'tipo_sangre', label: 'Tipo Sangre', getValue: p => p.tipo_sangre || '-' },
  { id: 'tipo_diabetes', label: 'Tipo Diabetes', getValue: p => p.medical?.tipo_diabetes || '-' },
  { id: 'tutor_nombres', label: 'Tutor', getValue: p => p.tutor ? `${p.tutor.nombres} ${p.tutor.apellidos}` : '-' },
  { id: 'estado', label: 'Estado', getValue: p => p.estado || '-' },
];

const DEFAULT_COLUMNS = ['nombres', 'ap_paterno', 'ci', 'edad', 'tipo_diabetes', 'celular'];

export default function DynamicBeneficiaryReport() {
  const [patients, setPatients] = useState([]);
  const [loading, setLoading] = useState(true);
  
  // States for filters
  const [searchTerm, setSearchTerm] = useState('');
  const [filterDiabetes, setFilterDiabetes] = useState('');
  
  // Columns
  const [selectedColumnIds, setSelectedColumnIds] = useState(DEFAULT_COLUMNS);
  const [showColumnSelector, setShowColumnSelector] = useState(false);
  const selectorRef = useRef(null);

  // Logo caching
  const [logoBase64, setLogoBase64] = useState(null);

  useEffect(() => {
    fetchData();
    // Precargar el logo
    imageToBase64(logoUrl)
      .then(base64 => setLogoBase64(base64))
      .catch(err => console.error("Error al cargar el logo en base64", err));
  }, []);

  // Cerrar selector al hacer clic afuera
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (selectorRef.current && !selectorRef.current.contains(event.target)) {
        setShowColumnSelector(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      const data = await getPatients();
      setPatients(data || []);
    } catch (error) {
      toast.error('Error al cargar beneficiarios');
    } finally {
      setLoading(false);
    }
  };

  // Filtrado reactivo
  const filteredPatients = useMemo(() => {
    return patients.filter(p => {
      const matchSearch = searchTerm === '' || 
        `${p.nombres} ${p.ap_paterno} ${p.ap_materno} ${p.ci}`.toLowerCase().includes(searchTerm.toLowerCase());
      
      const matchDiabetes = filterDiabetes === '' || 
        (p.medical?.tipo_diabetes && p.medical.tipo_diabetes.toUpperCase().includes(filterDiabetes.toUpperCase()));

      return matchSearch && matchDiabetes;
    });
  }, [patients, searchTerm, filterDiabetes]);

  // Columnas activas
  const activeColumns = useMemo(() => {
    return ALL_COLUMNS.filter(col => selectedColumnIds.includes(col.id));
  }, [selectedColumnIds]);

  const toggleColumn = (colId) => {
    setSelectedColumnIds(prev => {
      if (prev.includes(colId)) {
        if (prev.length === 1) return prev; // Avoid empty table
        return prev.filter(id => id !== colId);
      }
      return [...prev, colId];
    });
  };

  // Exportar a PDF
  const exportPDF = () => {
    if (!logoBase64) {
      toast.error('El logo aún se está cargando, intente en un momento');
      return;
    }

    const orientation = activeColumns.length >= 6 ? 'landscape' : 'portrait';
    const doc = new jsPDF({ orientation, unit: 'mm', format: 'letter' });

    // Header properties
    const pageWidth = doc.internal.pageSize.getWidth();
    const margin = 14;

    // Header Callback
    const addHeader = (data) => {
      // Background for header
      doc.setFillColor(248, 250, 252); // slate-50
      doc.rect(0, 0, pageWidth, 35, 'F');

      // Logo
      doc.addImage(logoBase64, 'PNG', margin, 5, 25, 25);

      // Titles
      doc.setFontSize(18);
      doc.setTextColor(30, 58, 138); // blue-900 (vida-primary approx)
      doc.setFont("helvetica", "bold");
      doc.text("Fundación V.I.D.A. Plena", margin + 30, 16);
      doc.setFontSize(14);
      doc.text("Reporte de Beneficiarios Registrados", margin + 30, 22);

      doc.setFontSize(9);
      doc.setTextColor(100, 116, 139); // slate-500
      doc.setFont("helvetica", "normal");
      doc.text(`Fecha de generación: ${new Date().toLocaleDateString('es-BO')} ${new Date().toLocaleTimeString('es-BO')}`, margin + 30, 27);
      
      const filterText = `Total Registros: ${filteredPatients.length} ${filterDiabetes ? `| Filtro Diabetes: ${filterDiabetes}` : ''}`;
      doc.text(filterText, margin + 30, 28);
    };

    // Body Data
    const tableBody = filteredPatients.map(p => {
      return activeColumns.map(col => String(col.getValue(p)));
    });

    // AutoTable Options
    autoTable(doc, {
      head: [activeColumns.map(col => col.label)],
      body: tableBody,
      startY: 40,
      margin: { top: 40, left: margin, right: margin, bottom: 20 },
      styles: {
        fontSize: 8,
        cellPadding: 3,
        font: 'helvetica',
      },
      headStyles: {
        fillColor: [14, 165, 233], // sky-500 (vida-main approx)
        textColor: 255,
        fontStyle: 'bold',
      },
      alternateRowStyles: {
        fillColor: [248, 250, 252], // slate-50
      },
      didDrawPage: function (data) {
        addHeader(data);
        // Footer
        const str = `Página ${doc.internal.getNumberOfPages()}`;
        doc.setFontSize(8);
        doc.setTextColor(150);
        doc.text(str, pageWidth / 2, doc.internal.pageSize.getHeight() - 10, { align: 'center' });
      }
    });

    doc.save(`Beneficiarios_${new Date().toISOString().split('T')[0]}.pdf`);
    toast.success('Reporte descargado exitosamente');
  };

  return (
    <div className="bg-white rounded-2xl shadow-xl border border-gray-100 p-6 animate-fadeIn">
      {/* TOOLBAR */}
      <div className="flex flex-col lg:flex-row justify-between items-start lg:items-end gap-4 mb-6">
        
        <div className="flex flex-col md:flex-row gap-3 w-full lg:w-auto">
          {/* Buscar */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            <input 
              type="text" 
              placeholder="Buscar por nombre o CI..." 
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10 pr-4 py-2 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-vida-main w-full md:w-64"
            />
          </div>

          {/* Filtro Diabetes */}
          <div className="relative">
            <Filter className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            <select 
              value={filterDiabetes}
              onChange={(e) => setFilterDiabetes(e.target.value)}
              className="pl-10 pr-4 py-2 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-vida-main w-full md:w-48 appearance-none bg-white"
            >
              <option value="">Todos los tipos</option>
              <option value="TIPO 1">Tipo 1</option>
              <option value="TIPO 2">Tipo 2</option>
              <option value="GESTACIONAL">Gestacional</option>
              <option value="OTRA">Otra</option>
            </select>
          </div>

          {/* Selector de Columnas */}
          <div className="relative" ref={selectorRef}>
            <button 
              onClick={() => setShowColumnSelector(!showColumnSelector)}
              className="flex items-center gap-2 px-4 py-2 bg-gray-50 border border-gray-200 text-gray-700 rounded-xl hover:bg-gray-100 transition-colors w-full md:w-auto justify-center"
            >
              <Columns size={18} />
              Columnas
            </button>
            
            {showColumnSelector && (
              <div className="absolute z-10 mt-2 w-56 bg-white rounded-xl shadow-lg border border-gray-100 py-2 top-full right-0 lg:left-0 lg:right-auto">
                <div className="px-3 pb-2 mb-2 border-b border-gray-100 text-xs font-bold text-gray-500">
                  SELECCIONAR COLUMNAS
                </div>
                <div className="max-h-60 overflow-y-auto px-2">
                  {ALL_COLUMNS.map(col => (
                    <label key={col.id} className="flex items-center gap-2 p-2 hover:bg-gray-50 rounded-lg cursor-pointer">
                      <input 
                        type="checkbox" 
                        checked={selectedColumnIds.includes(col.id)}
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
        </div>

        <div className="flex gap-2 w-full lg:w-auto mt-4 lg:mt-0">
          <Button variant="secondary" onClick={fetchData} disabled={loading} className="px-3">
            <RefreshCcw size={18} className={loading ? 'animate-spin' : ''} />
          </Button>
          <Button 
            onClick={exportPDF} 
            disabled={loading || filteredPatients.length === 0}
            className="bg-green-600 hover:bg-green-700 text-white w-full lg:w-auto flex-1 justify-center"
          >
            <Download size={18} />
            {filteredPatients.length === 0 ? 'Sin datos' : 'Descargar PDF'}
          </Button>
        </div>

      </div>

      {/* TABLA REACTIVA */}
      <div className="overflow-x-auto border border-gray-100 rounded-xl">
        <table className="w-full text-left">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {activeColumns.map(col => (
                <th key={col.id} className="px-4 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider whitespace-nowrap">
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr>
                <td colSpan={activeColumns.length} className="px-4 py-10 text-center text-gray-500">
                  <div className="flex justify-center items-center gap-2">
                    <RefreshCcw size={18} className="animate-spin text-vida-main" />
                    Cargando datos...
                  </div>
                </td>
              </tr>
            ) : filteredPatients.length > 0 ? (
              filteredPatients.map((patient) => (
                <tr key={patient.id} className="hover:bg-gray-50/50 transition-colors">
                  {activeColumns.map(col => (
                    <td key={`${patient.id}-${col.id}`} className="px-4 py-3 text-sm text-gray-700 whitespace-nowrap">
                      {col.getValue(patient)}
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={activeColumns.length} className="px-4 py-10 text-center text-gray-500">
                  No se encontraron beneficiarios con los filtros actuales.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="mt-4 text-xs text-gray-400 text-right">
        Mostrando {filteredPatients.length} de {patients.length} registros
      </div>
    </div>
  );
}
