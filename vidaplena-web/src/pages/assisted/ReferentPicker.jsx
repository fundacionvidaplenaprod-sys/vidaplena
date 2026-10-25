import { useEffect, useRef, useState } from 'react';
import { toast } from 'react-hot-toast';
import { Camera, Search, UserPlus, X } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { createReferent, searchReferents } from '../../api/assistedRegistrations';

const inputClass = 'w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-vida-main';
const FOTO_TIPOS = ['image/jpeg', 'image/png'];
const FOTO_MAX = 2 * 1024 * 1024;

export function ReferentCard({ referente, onClear }) {
  return (
    <div className="flex items-center gap-4 border border-vida-main/30 bg-vida-main/5 rounded-xl p-3">
      {referente.foto_url ? (
        <img src={referente.foto_url} alt={`Foto de ${referente.nombre_completo}`} className="w-14 h-14 rounded-full object-cover border" />
      ) : (
        <div className="w-14 h-14 rounded-full bg-gray-100 flex items-center justify-center text-gray-400"><Camera size={20} /></div>
      )}
      <div className="flex-1 text-sm">
        <p className="font-bold text-gray-800">{referente.nombre_completo}</p>
        <p className="text-gray-600">C.I. {referente.ci || '—'} · Contacto {referente.telefono || '—'}</p>
        {referente.registros_activos > 0 && (
          <p className="text-xs text-gray-500">Persona referente de {referente.registros_activos} registro(s) activo(s)</p>
        )}
      </div>
      {onClear && (
        <button type="button" aria-label="Cambiar persona referente" onClick={onClear} className="p-1 rounded-full hover:bg-gray-100 text-gray-400">
          <X size={18} />
        </button>
      )}
    </div>
  );
}

/**
 * Elige o registra a la persona referente. Es OBLIGATORIA: recibe la insulina para entregarla, así que
 * se piden su nombre completo, C.I., teléfono y una foto personal para identificarse. Una misma persona
 * puede ser referente de varios beneficiarios: se busca primero por C.I. o nombre y solo se crea una
 * nueva si no existe.
 */
export default function ReferentPicker({ value, onChange }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [nuevo, setNuevo] = useState({ nombre_completo: '', ci: '', telefono: '', foto: null });
  const fileRef = useRef(null);

  useEffect(() => {
    if (value || creating || query.trim().length < 2) {
      setResults([]);
      return undefined;
    }
    const timer = setTimeout(async () => {
      try {
        setSearching(true);
        setResults(await searchReferents(query.trim()));
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [query, value, creating]);

  const elegirFoto = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!FOTO_TIPOS.includes(file.type)) {
      toast.error('La foto debe ser una imagen JPG o PNG.');
      event.target.value = '';
      return;
    }
    if (file.size > FOTO_MAX) {
      toast.error('La foto supera el máximo de 2 MB.');
      event.target.value = '';
      return;
    }
    setNuevo((prev) => ({ ...prev, foto: file }));
  };

  const registrar = async () => {
    if (nuevo.nombre_completo.trim().length < 3) return toast.error('Indique el nombre completo de la persona referente.');
    if (nuevo.ci.trim().length < 4) return toast.error('Indique el C.I. de la persona referente.');
    if (nuevo.telefono.replace(/\D/g, '').length < 6) return toast.error('Indique un número de contacto válido.');
    if (!nuevo.foto) return toast.error('La foto personal de la persona referente es obligatoria.');
    try {
      setSaving(true);
      const creada = await createReferent(nuevo);
      toast.success('Persona referente registrada.');
      setCreating(false);
      setNuevo({ nombre_completo: '', ci: '', telefono: '', foto: null });
      onChange(creada);
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo registrar a la persona referente.');
    } finally {
      setSaving(false);
    }
  };

  if (value) return <ReferentCard referente={value} onClear={() => onChange(null)} />;

  if (creating) {
    return (
      <div className="border border-gray-200 rounded-xl p-4 space-y-3 bg-gray-50/50">
        <p className="text-sm font-semibold text-gray-800">Nueva persona referente</p>
        <div className="grid md:grid-cols-3 gap-3">
          <div>
            <label htmlFor="rf-nombre" className="block text-xs font-semibold text-gray-700 mb-1">Nombre completo *</label>
            <input id="rf-nombre" className={inputClass} value={nuevo.nombre_completo} onChange={(e) => setNuevo({ ...nuevo, nombre_completo: e.target.value })} maxLength={160} />
          </div>
          <div>
            <label htmlFor="rf-ci" className="block text-xs font-semibold text-gray-700 mb-1">C.I. *</label>
            <input id="rf-ci" className={inputClass} value={nuevo.ci} onChange={(e) => setNuevo({ ...nuevo, ci: e.target.value })} maxLength={32} />
          </div>
          <div>
            <label htmlFor="rf-tel" className="block text-xs font-semibold text-gray-700 mb-1">N.° de contacto *</label>
            <input id="rf-tel" className={inputClass} value={nuevo.telefono} onChange={(e) => setNuevo({ ...nuevo, telefono: e.target.value })} maxLength={40} />
          </div>
        </div>
        <div>
          <label htmlFor="rf-foto" className="block text-xs font-semibold text-gray-700 mb-1">Foto personal para identificarse * (JPG o PNG, máx. 2 MB)</label>
          <input id="rf-foto" ref={fileRef} type="file" accept="image/jpeg,image/png" onChange={elegirFoto} className="text-sm" />
          {nuevo.foto && <p className="text-xs text-gray-500 mt-1">{nuevo.foto.name}</p>}
        </div>
        <div className="flex justify-end gap-3">
          <Button type="button" variant="outline" onClick={() => setCreating(false)} className="w-auto px-5">Cancelar</Button>
          <Button type="button" onClick={registrar} disabled={saving} className="w-auto px-5">
            {saving ? 'Registrando…' : 'Registrar persona referente'}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
        <input
          aria-label="Buscar persona referente"
          placeholder="Buscar por C.I. o nombre de la persona referente…"
          className={`${inputClass} pl-9`}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {searching && <p className="text-xs text-gray-400">Buscando…</p>}
      {results.length > 0 && (
        <ul className="border border-gray-200 rounded-lg divide-y divide-gray-100 bg-white max-h-56 overflow-y-auto">
          {results.map((r) => (
            <li key={r.id}>
              <button type="button" onClick={() => onChange(r)} className="w-full text-left px-3 py-2 hover:bg-gray-50 text-sm">
                <span className="font-semibold text-gray-800">{r.nombre_completo}</span>
                <span className="text-gray-500"> · C.I. {r.ci || '—'}</span>
                {r.registros_activos > 0 && <span className="text-xs text-gray-400"> · referente de {r.registros_activos}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {!searching && query.trim().length >= 2 && results.length === 0 && (
        <p className="text-xs text-gray-500">No hay una persona referente con esos datos.</p>
      )}
      <button type="button" onClick={() => setCreating(true)} className="text-sm font-semibold text-vida-main inline-flex items-center gap-1 hover:underline">
        <UserPlus size={16} /> Registrar una nueva persona referente
      </button>
    </div>
  );
}
