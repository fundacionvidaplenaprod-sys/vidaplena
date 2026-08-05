import { useState } from 'react';
import { toast } from 'react-hot-toast';
import { Search, Loader2, AlertTriangle, Download, HeartHandshake } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { getAvailability, getFichaUrl, createAdminSocialCaseAppointment } from '../../api/appointments';
import { getPatients } from '../../api/patients';

const MIN_DAYS_AHEAD = 1;
const MAX_DAYS_AHEAD = 15;

function getDateOffset(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().split('T')[0];
}

const EMPTY_FORM = {
  nombres: '',
  ap_paterno: '',
  ap_materno: '',
  ci: '',
  fecha_nac: '',
};

export function SocialCaseAppointmentModal({ isOpen, onClose, onSuccess }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [ciSearch, setCiSearch] = useState('');
  const [searching, setSearching] = useState(false);
  const [fechaCita, setFechaCita] = useState('');
  const [availability, setAvailability] = useState(null);
  const [loadingAvailability, setLoadingAvailability] = useState(false);
  const [selectedHora, setSelectedHora] = useState(null);
  const [motivo, setMotivo] = useState('Evaluación Socioeconómica / Trabajo Social');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  const reset = () => {
    setForm(EMPTY_FORM);
    setCiSearch('');
    setSearching(false);
    setFechaCita('');
    setAvailability(null);
    setLoadingAvailability(false);
    setSelectedHora(null);
    setMotivo('Evaluación Socioeconómica / Trabajo Social');
    setSubmitting(false);
    setResult(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const setField = (field) => (e) => setForm((prev) => ({ ...prev, [field]: e.target.value }));

  const handleSearchByCi = async () => {
    if (!ciSearch.trim()) {
      toast.error('Ingresa un número de C.I. para buscar.');
      return;
    }
    try {
      setSearching(true);
      const matches = await getPatients(0, 10, ciSearch.trim());
      const match = matches.find((p) => p.ci === ciSearch.trim()) || matches[0];
      if (!match) {
        toast.error('No se encontró un paciente con ese C.I. Completa los datos manualmente.');
        return;
      }
      setForm({
        nombres: match.nombres || '',
        ap_paterno: match.ap_paterno || '',
        ap_materno: match.ap_materno || '',
        ci: match.ci || ciSearch.trim(),
        fecha_nac: match.fecha_nac || '',
      });
      toast.success('Datos del paciente cargados.');
    } catch (error) {
      toast.error('No se pudo buscar el paciente.');
    } finally {
      setSearching(false);
    }
  };

  const handleDateChange = async (fecha) => {
    setFechaCita(fecha);
    setSelectedHora(null);
    setAvailability(null);
    if (!fecha) return;
    try {
      setLoadingAvailability(true);
      const data = await getAvailability(fecha);
      setAvailability(data);
    } catch (error) {
      toast.error('No se pudo consultar la disponibilidad de esa fecha.');
    } finally {
      setLoadingAvailability(false);
    }
  };

  const handleSubmit = async () => {
    if (!form.nombres.trim() || !form.ap_paterno.trim() || !form.ci.trim() || !form.fecha_nac) {
      toast.error('Completa nombres, apellido paterno, C.I. y fecha de nacimiento.');
      return;
    }
    if (!fechaCita || !selectedHora) {
      toast.error('Selecciona la fecha y el horario de la cita.');
      return;
    }
    try {
      setSubmitting(true);
      const created = await createAdminSocialCaseAppointment({
        nombres: form.nombres.trim(),
        ap_paterno: form.ap_paterno.trim(),
        ap_materno: form.ap_materno.trim() || null,
        ci: form.ci.trim(),
        fecha_nac: form.fecha_nac,
        fecha_cita: fechaCita,
        hora_cita: selectedHora,
        motivo: motivo.trim() || null,
      });
      toast.success('Cita creada y confirmada como caso social.');
      setResult(created);
      onSuccess?.();
    } catch (error) {
      toast.error(error.message || 'No se pudo crear la cita.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Nueva Reserva (Asistencia Social)">
      {result ? (
        <div className="space-y-4">
          <div className="bg-purple-50 border border-purple-200 rounded-xl p-4 text-sm text-purple-800">
            <p className="font-bold mb-1">Cita confirmada</p>
            <p>{result.nombre_completo}</p>
            <p>{result.fecha_cita} — {result.hora_cita}</p>
            <p className="mt-1">Código: <span className="font-mono font-bold">{result.security_code}</span></p>
          </div>
          <div className="flex gap-3">
            <Button
              type="button"
              variant="secondary"
              className="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-700"
              onClick={handleClose}
            >
              Cerrar
            </Button>
            <a
              href={getFichaUrl(result.id, result.security_code)}
              target="_blank"
              rel="noreferrer"
              className="flex-1"
            >
              <Button type="button" className="w-full inline-flex items-center justify-center gap-2">
                <Download size={16} /> Descargar ficha
              </Button>
            </a>
          </div>
        </div>
      ) : (
        <div className="space-y-4 max-h-[75vh] overflow-y-auto pr-1">
          <div>
            <label className="text-sm font-bold text-vida-primary ml-1 block mb-1">
              Buscar paciente frecuente por C.I. (opcional)
            </label>
            <div className="flex gap-2">
              <Input
                value={ciSearch}
                onChange={(e) => setCiSearch(e.target.value)}
                placeholder="N° de Cédula de Identidad"
                className="flex-1"
              />
              <Button
                type="button"
                variant="outline"
                onClick={handleSearchByCi}
                disabled={searching}
                className="w-auto px-4 inline-flex items-center gap-1"
              >
                {searching ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
                Buscar
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Input label="Nombre(s)" value={form.nombres} onChange={setField('nombres')} />
            <Input label="Apellido Paterno" value={form.ap_paterno} onChange={setField('ap_paterno')} />
            <Input label="Apellido Materno" value={form.ap_materno} onChange={setField('ap_materno')} />
            <Input label="N° de Cédula de Identidad" value={form.ci} onChange={setField('ci')} />
            <Input type="date" label="Fecha de nacimiento" value={form.fecha_nac} onChange={setField('fecha_nac')} />
          </div>

          <Input
            type="date"
            label="Día de la cita"
            min={getDateOffset(MIN_DAYS_AHEAD)}
            max={getDateOffset(MAX_DAYS_AHEAD)}
            value={fechaCita}
            onChange={(e) => handleDateChange(e.target.value)}
          />

          {loadingAvailability && (
            <p className="text-sm text-gray-500 flex items-center gap-2">
              <Loader2 className="animate-spin" size={16} /> Consultando disponibilidad...
            </p>
          )}

          {availability && !availability.disponible && (
            <div className="bg-red-50 border-l-4 border-red-500 p-3 rounded-r-xl text-sm text-red-700 flex gap-2">
              <AlertTriangle size={18} className="flex-shrink-0 mt-0.5" />
              {availability.motivo || 'Esa fecha no está disponible. Elige otra.'}
            </div>
          )}

          {availability && availability.disponible && (
            <div>
              <p className="text-sm font-bold text-gray-700 mb-2">Hora</p>
              {availability.slots.every((s) => !s.disponible) ? (
                <p className="text-sm text-amber-700 bg-amber-50 border-l-4 border-amber-500 p-3 rounded-r-xl">
                  No hay horarios disponibles ese día. Por favor elige otra fecha.
                </p>
              ) : (
                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                  {availability.slots.map((s) => (
                    <button
                      key={s.hora}
                      type="button"
                      disabled={!s.disponible}
                      onClick={() => setSelectedHora(s.hora)}
                      className={`px-3 py-2 rounded-lg text-sm font-semibold border transition-colors
                        ${!s.disponible ? 'bg-gray-100 text-gray-300 border-gray-100 cursor-not-allowed' : ''}
                        ${s.disponible && selectedHora === s.hora ? 'bg-vida-main text-white border-vida-main' : ''}
                        ${s.disponible && selectedHora !== s.hora ? 'bg-white text-gray-700 border-gray-200 hover:border-vida-main' : ''}
                      `}
                    >
                      {s.hora}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          <Input
            label="Motivo de la exención"
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
          />

          <div className="flex gap-3 pt-2">
            <Button
              type="button"
              variant="secondary"
              className="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-700"
              onClick={handleClose}
            >
              Cancelar
            </Button>
            <Button
              type="button"
              className="flex-1 bg-purple-600 hover:bg-purple-700 text-white inline-flex items-center justify-center gap-2"
              onClick={handleSubmit}
              disabled={submitting}
            >
              <HeartHandshake size={16} /> {submitting ? 'Creando...' : 'Crear y confirmar cita'}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
