import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'react-hot-toast';
import { CalendarClock, Ban, Search, Save, Trash2, Plus } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import {
  getAgenda,
  getBlockedDays,
  createBlockedDay,
  deleteBlockedDay,
  updateClinicalNote,
  getHistoryByCi,
} from '../../api/appointments';

function todayIso() {
  return new Date().toISOString().split('T')[0];
}

export default function DoctorAgendaPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState('agenda'); // agenda | bloqueados | historial

  // Agenda del día
  const [fecha, setFecha] = useState(todayIso());
  const [agenda, setAgenda] = useState([]);
  const [loadingAgenda, setLoadingAgenda] = useState(false);
  const [notaDrafts, setNotaDrafts] = useState({});
  const [savingNoteId, setSavingNoteId] = useState(null);

  // Días bloqueados
  const [blockedDays, setBlockedDays] = useState([]);
  const [loadingBlocked, setLoadingBlocked] = useState(false);
  const [newBlockedFecha, setNewBlockedFecha] = useState('');
  const [newBlockedMotivo, setNewBlockedMotivo] = useState('');

  // Historial por CI
  const [ciQuery, setCiQuery] = useState('');
  const [history, setHistory] = useState(null);
  const [loadingHistory, setLoadingHistory] = useState(false);

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || '{}');
    if (user.role !== 'SUPER_ADMIN') {
      toast.error('Solo SUPER_ADMIN puede acceder a la Agenda Médica.');
      navigate('/dashboard/lista-pacientes', { replace: true });
    }
  }, [navigate]);

  const loadAgenda = async (targetFecha) => {
    try {
      setLoadingAgenda(true);
      const data = await getAgenda(targetFecha);
      setAgenda(data);
      const drafts = {};
      data.forEach((item) => { drafts[item.id] = item.nota_consulta || ''; });
      setNotaDrafts(drafts);
    } catch (error) {
      toast.error('No se pudo cargar la agenda del día.');
    } finally {
      setLoadingAgenda(false);
    }
  };

  const loadBlockedDays = async () => {
    try {
      setLoadingBlocked(true);
      const data = await getBlockedDays();
      setBlockedDays(data);
    } catch (error) {
      toast.error('No se pudo cargar los días bloqueados.');
    } finally {
      setLoadingBlocked(false);
    }
  };

  useEffect(() => { loadAgenda(fecha); }, [fecha]);
  useEffect(() => { loadBlockedDays(); }, []);

  const handleSaveNote = async (appointmentId) => {
    try {
      setSavingNoteId(appointmentId);
      await updateClinicalNote(appointmentId, notaDrafts[appointmentId] || '');
      toast.success('Nota guardada.');
      loadAgenda(fecha);
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo guardar la nota.');
    } finally {
      setSavingNoteId(null);
    }
  };

  const handleAddBlockedDay = async () => {
    if (!newBlockedFecha) {
      toast.error('Selecciona una fecha para bloquear.');
      return;
    }
    try {
      await createBlockedDay({ fecha: newBlockedFecha, motivo: newBlockedMotivo || null });
      toast.success('Día bloqueado.');
      setNewBlockedFecha('');
      setNewBlockedMotivo('');
      loadBlockedDays();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo bloquear el día.');
    }
  };

  const handleDeleteBlockedDay = async (blockFecha) => {
    try {
      await deleteBlockedDay(blockFecha);
      toast.success('Bloqueo eliminado.');
      loadBlockedDays();
    } catch (error) {
      toast.error('No se pudo eliminar el bloqueo.');
    }
  };

  const handleSearchHistory = async () => {
    if (!ciQuery.trim()) {
      toast.error('Ingresa un número de C.I.');
      return;
    }
    try {
      setLoadingHistory(true);
      const data = await getHistoryByCi(ciQuery.trim());
      setHistory(data);
    } catch (error) {
      toast.error('No se pudo consultar el historial.');
    } finally {
      setLoadingHistory(false);
    }
  };

  const TABS = [
    { key: 'agenda', label: 'Agenda del día', icon: <CalendarClock size={16} /> },
    { key: 'bloqueados', label: 'Días bloqueados', icon: <Ban size={16} /> },
    { key: 'historial', label: 'Historial por C.I.', icon: <Search size={16} /> },
  ];

  return (
    <div className="p-6 md:p-8 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold text-vida-primary mb-6 flex items-center gap-2">
        <CalendarClock /> Agenda Médica
      </h1>

      <div className="flex gap-2 mb-6 border-b border-gray-200">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-bold border-b-2 transition-colors ${
              tab === t.key ? 'border-vida-main text-vida-main' : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {tab === 'agenda' && (
        <div className="space-y-4">
          <Input type="date" label="Fecha" value={fecha} onChange={(e) => setFecha(e.target.value)} className="max-w-xs" />

          {loadingAgenda && <p className="text-sm text-gray-500">Cargando...</p>}

          {!loadingAgenda && agenda.length === 0 && (
            <p className="text-sm text-gray-500">No hay citas confirmadas para esta fecha.</p>
          )}

          <div className="space-y-4">
            {agenda.map((item) => (
              <div key={item.id} className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
                <div className="flex justify-between items-start mb-2">
                  <div>
                    <p className="font-bold text-gray-800">
                      {item.hora_cita} — {item.nombres} {item.ap_paterno} {item.ap_materno || ''}
                    </p>
                    <p className="text-xs text-gray-500">C.I. {item.ci} · Nac. {item.fecha_nac}</p>
                  </div>
                </div>
                <textarea
                  rows={3}
                  placeholder="Notas de la consulta: diagnóstico, receta, estudios solicitados, insulina entregada..."
                  className="w-full bg-vida-bg rounded-xl p-3 text-sm outline-none border border-transparent focus:border-vida-main focus:bg-white"
                  value={notaDrafts[item.id] || ''}
                  onChange={(e) => setNotaDrafts((prev) => ({ ...prev, [item.id]: e.target.value }))}
                />
                <div className="flex justify-end mt-2">
                  <Button
                    type="button"
                    onClick={() => handleSaveNote(item.id)}
                    disabled={savingNoteId === item.id}
                    className="w-auto px-4 py-2 text-sm inline-flex items-center gap-1"
                  >
                    <Save size={14} /> {savingNoteId === item.id ? 'Guardando...' : 'Guardar nota'}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'bloqueados' && (
        <div className="space-y-6">
          <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 flex flex-col md:flex-row gap-3 md:items-end">
            <Input type="date" label="Fecha a bloquear" value={newBlockedFecha} onChange={(e) => setNewBlockedFecha(e.target.value)} />
            <Input label="Motivo (opcional)" value={newBlockedMotivo} onChange={(e) => setNewBlockedMotivo(e.target.value)} className="flex-1" />
            <Button type="button" onClick={handleAddBlockedDay} className="w-auto px-4 inline-flex items-center gap-1">
              <Plus size={16} /> Bloquear
            </Button>
          </div>

          {loadingBlocked && <p className="text-sm text-gray-500">Cargando...</p>}

          <div className="space-y-2">
            {blockedDays.map((b) => (
              <div key={b.id} className="flex justify-between items-center bg-white border border-gray-200 rounded-xl p-3">
                <div>
                  <p className="font-bold text-gray-800">{b.fecha}</p>
                  {b.motivo && <p className="text-xs text-gray-500">{b.motivo}</p>}
                </div>
                <button onClick={() => handleDeleteBlockedDay(b.fecha)} className="text-red-400 hover:text-red-600 p-1">
                  <Trash2 size={18} />
                </button>
              </div>
            ))}
            {!loadingBlocked && blockedDays.length === 0 && (
              <p className="text-sm text-gray-500">No hay días bloqueados.</p>
            )}
          </div>
        </div>
      )}

      {tab === 'historial' && (
        <div className="space-y-4">
          <div className="flex gap-3 items-end max-w-md">
            <Input label="N° de Cédula de Identidad" value={ciQuery} onChange={(e) => setCiQuery(e.target.value)} />
            <Button type="button" onClick={handleSearchHistory} className="w-auto px-4 inline-flex items-center gap-1">
              <Search size={16} /> Buscar
            </Button>
          </div>

          {loadingHistory && <p className="text-sm text-gray-500">Buscando...</p>}

          {history && history.length === 0 && (
            <p className="text-sm text-gray-500">No se encontraron citas para ese C.I.</p>
          )}

          <div className="space-y-3">
            {history?.map((item) => (
              <div key={item.id} className="bg-white border border-gray-200 rounded-xl p-4">
                <p className="font-bold text-gray-800">
                  {item.fecha_cita} {item.hora_cita} — <span className={item.estado === 'CONFIRMADA' ? 'text-green-600' : 'text-red-500'}>{item.estado}</span>
                </p>
                {item.motivo_rechazo && (
                  <p className="text-sm text-red-600 mt-2 bg-red-50 rounded-lg p-2">{item.motivo_rechazo}</p>
                )}
                {item.nota_consulta && (
                  <p className="text-sm text-gray-600 mt-2 bg-gray-50 rounded-lg p-2">{item.nota_consulta}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
