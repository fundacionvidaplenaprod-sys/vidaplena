import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'react-hot-toast';
import { AlertTriangle, FileText, HeartHandshake, Plus, RefreshCcw, Search, X } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { DEPARTAMENTOS } from '../../constants/departamentos';
import { ENTIDAD_TIPOS, ESTADO_LABELS, ESTADO_STYLES, labelOf } from '../../constants/assisted';
import { displayInsulinName } from '../../constants/insulins';
import { createAssistedRegistration, listAssistedRegistrations } from '../../api/assistedRegistrations';
import AssistedRegistrationForm from './AssistedRegistrationForm';

const insulinasDe = (reg) =>
  reg.treatments
    .map((t) => `${displayInsulinName(t.insulina)}${t.dosis_diaria ? ` (${t.dosis_diaria} UI)` : ''}`)
    .join(', ');

export default function AssistedRegistrationPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [estado, setEstado] = useState('');
  const [depto, setDepto] = useState('');
  const [soloVencidos, setSoloVencidos] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setItems(await listAssistedRegistrations({ q: q.trim(), estado, depto, revision_vencida: soloVencidos ? true : '' }));
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo cargar el Registro Asistido.');
    } finally {
      setLoading(false);
    }
  }, [q, estado, depto, soloVencidos]);

  useEffect(() => {
    const timer = setTimeout(load, 300);
    return () => clearTimeout(timer);
  }, [load]);

  const create = async (payload) => {
    try {
      setSaving(true);
      const created = await createAssistedRegistration(payload);
      toast.success(`Registrado con el código ${created.codigo}.`);
      setShowForm(false);
      navigate(`/dashboard/registro-asistido/${created.id}`);
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo registrar a la persona.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto animate-fadeIn">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 mb-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-800 flex items-center gap-3">
            <HeartHandshake size={30} className="text-vida-main" /> Registro Asistido por Situación Excepcional
          </h1>
          <p className="text-gray-500 mt-1 max-w-3xl">
            Personas en centros de acogida, recintos penitenciarios, situación de calle u otra situación excepcional. Es
            100 % gratuito, no se exigen documentos ni datos, y la información es de acceso restringido.
          </p>
        </div>
        <Button onClick={() => setShowForm(true)} className="w-auto px-6">
          <Plus size={18} /> Nuevo registro asistido
        </Button>
      </div>

      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4 mb-4 flex flex-wrap items-end gap-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
          <input
            aria-label="Buscar"
            placeholder="Código, nombre, C.I., entidad o referente…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm w-72"
          />
        </div>
        <select aria-label="Estado" value={estado} onChange={(e) => setEstado(e.target.value)} className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          <option value="">Todos los estados</option>
          {Object.entries(ESTADO_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <select aria-label="Departamento" value={depto} onChange={(e) => setDepto(e.target.value)} className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          <option value="">Todos los departamentos</option>
          {DEPARTAMENTOS.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <label className="flex items-center gap-2 text-sm text-gray-700 pb-2">
          <input type="checkbox" checked={soloVencidos} onChange={(e) => setSoloVencidos(e.target.checked)} />
          Revisión semestral vencida
        </label>
        <div className="ml-auto flex items-end gap-3 flex-wrap">
          <Button variant="secondary" onClick={load} className="w-auto px-3" aria-label="Actualizar">
            <RefreshCcw size={18} className={loading ? 'animate-spin' : ''} />
          </Button>
          <Button onClick={() => navigate('/dashboard/registro-asistido/reporte')} className="bg-emerald-700 hover:bg-emerald-800 text-white w-auto">
            <FileText size={18} /> Generar reporte (PDF / Excel)
          </Button>
        </div>
      </div>

      <div className="bg-white rounded-2xl shadow-xl border border-gray-100 overflow-x-auto">
        <table className="w-full text-left">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {['Código', 'Nombre / apodo', 'Persona referente', 'Departamento', 'Insulinas', 'Última entrega', 'Estado'].map((h) => (
                <th key={h} className="px-4 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan="7" className="px-4 py-10 text-center text-gray-500">Cargando…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan="7" className="px-4 py-10 text-center text-gray-400">No hay registros con esos filtros.</td></tr>
            ) : (
              items.map((r) => (
                <tr
                  key={r.id}
                  onClick={() => navigate(`/dashboard/registro-asistido/${r.id}`)}
                  className="hover:bg-gray-50/70 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3 text-sm font-bold text-vida-primary whitespace-nowrap">{r.codigo}</td>
                  <td className="px-4 py-3 text-sm text-gray-800">{r.nombre || <span className="text-gray-400">Sin nombre</span>}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {r.referente ? r.referente.nombre_completo : <span className="text-red-500 font-semibold">Falta registrar</span>}
                    {r.entidad_nombre && (
                      <span className="block text-xs text-gray-400">
                        {r.entidad_nombre}{r.entidad_tipo ? ` · ${labelOf(ENTIDAD_TIPOS, r.entidad_tipo)}` : ''}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{r.depto || '-'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{insulinasDe(r) || '-'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600 whitespace-nowrap">{r.ultima_entrega || 'Sin entregas'}</td>
                  <td className="px-4 py-3 text-sm whitespace-nowrap space-x-1">
                    <span className={`inline-flex px-2 py-1 rounded-full text-xs font-bold border ${ESTADO_STYLES[r.estado]}`}>{ESTADO_LABELS[r.estado]}</span>
                    {r.urgente && r.estado === 'ACTIVO' && (
                      <span className="inline-flex px-2 py-1 rounded-full text-xs font-bold border bg-orange-100 text-orange-700 border-orange-200">Urgente</span>
                    )}
                    {r.revision_vencida && (
                      <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-bold border bg-yellow-100 text-yellow-800 border-yellow-200">
                        <AlertTriangle size={12} /> Revisar
                      </span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {showForm && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-start justify-center p-4 overflow-y-auto">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl my-8">
            <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
              <h2 className="text-lg font-bold text-gray-800">Nuevo registro asistido</h2>
              <button aria-label="Cerrar" onClick={() => setShowForm(false)} className="p-1 rounded-full hover:bg-gray-100 text-gray-400">
                <X size={20} />
              </button>
            </div>
            <div className="p-6">
              <AssistedRegistrationForm onSubmit={create} submitting={saving} submitLabel="Registrar y asignar código" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
