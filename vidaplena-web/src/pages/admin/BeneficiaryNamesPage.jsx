import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'react-hot-toast';
import { UserCog, Search, Save, X, Pencil, CheckCircle2, RotateCcw, UserPlus } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import {
  searchBeneficiariesAdmin,
  createBeneficiaryAdmin,
  updateBeneficiaryAdmin,
  resetBeneficiaryRegistration,
} from '../../api/patients';

const emptyForm = { nombres: '', ap_paterno: '', ap_materno: '', depto: '' };

export default function BeneficiaryNamesPage() {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  const [showAddForm, setShowAddForm] = useState(false);
  const [addForm, setAddForm] = useState(emptyForm);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || '{}');
    if (user.role !== 'SUPER_ADMIN') {
      toast.error('Solo SUPER_ADMIN puede acceder a esta herramienta.');
      navigate('/dashboard/lista-pacientes', { replace: true });
    }
  }, [navigate]);

  const handleSearch = async () => {
    if (!q.trim() || q.trim().length < 2) {
      toast.error('Escribe al menos 2 caracteres para buscar.');
      return;
    }
    try {
      setLoading(true);
      setSearched(true);
      const data = await searchBeneficiariesAdmin(q.trim());
      setResults(data);
      setEditingId(null);
    } catch (error) {
      toast.error('No se pudo buscar en el padrón.');
    } finally {
      setLoading(false);
    }
  };

  const startEdit = (item) => {
    setEditingId(item.id);
    setForm({
      nombres: item.nombres || '',
      ap_paterno: item.ap_paterno || '',
      ap_materno: item.ap_materno || '',
      depto: item.depto || '',
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setForm(emptyForm);
  };

  // Herramienta temporal (solo pruebas): borra el paciente/usuario de prueba
  // que quedó vinculado a este beneficiario al autoregistrarse, y libera el
  // padrón para que un beneficiario real pueda reclamarlo. No toca
  // nombres/apellidos/depto del padrón.
  const handleResetRegistration = async (item) => {
    const confirmado = window.confirm(
      `¿Borrar el paciente/usuario de prueba registrado como "${item.nombres} ${item.ap_paterno || ''}"? ` +
        `Esto elimina permanentemente ese registro (datos médicos, documentos, etc.) y libera el padrón.`
    );
    if (!confirmado) return;
    try {
      setSaving(true);
      const updated = await resetBeneficiaryRegistration(item.id);
      setResults((prev) => prev.map((r) => (r.id === item.id ? updated : r)));
      toast.success('Paciente de prueba eliminado. El padrón quedó libre.');
      if (editingId === item.id) cancelEdit();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo restablecer el registro.');
    } finally {
      setSaving(false);
    }
  };

  const handleAddBeneficiary = async () => {
    if (!addForm.nombres.trim()) {
      toast.error('El nombre no puede estar vacío.');
      return;
    }
    try {
      setAdding(true);
      const created = await createBeneficiaryAdmin(addForm);
      toast.success('Beneficiario agregado al padrón. Ya puede autoregistrarse.');
      setResults((prev) => [created, ...prev]);
      setSearched(true);
      setAddForm(emptyForm);
      setShowAddForm(false);
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo agregar el beneficiario.');
    } finally {
      setAdding(false);
    }
  };

  const handleSave = async (id) => {
    if (!form.nombres.trim()) {
      toast.error('El nombre no puede estar vacío.');
      return;
    }
    try {
      setSaving(true);
      const updated = await updateBeneficiaryAdmin(id, form);
      setResults((prev) => prev.map((r) => (r.id === id ? updated : r)));
      toast.success('Registro corregido correctamente.');
      cancelEdit();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo guardar el cambio.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-6 md:p-8 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold text-vida-primary mb-2 flex items-center gap-2">
        <UserCog /> Padrón de Beneficiarios
      </h1>
      <p className="text-sm text-gray-500 mb-6">
        Herramienta para corregir beneficiarios precargados cuyo nombre o apellidos están
        incompletos (lo que les impide encontrar su coincidencia al autoregistrarse), y para
        agregar beneficiarios nuevos que no forman parte del padrón original. Busca por nombre o
        apellido para corregir un registro existente.
      </p>

      <div className="flex flex-col sm:flex-row gap-3 sm:items-end max-w-lg mb-3">
        <Input
          label="Buscar por nombre o apellido"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="Ej. Juan Mamani"
        />
        <Button type="button" onClick={handleSearch} className="w-auto px-4 inline-flex items-center gap-1">
          <Search size={16} /> Buscar
        </Button>
      </div>

      <div className="mb-6">
        <button
          type="button"
          onClick={() => setShowAddForm((prev) => !prev)}
          className="text-sm font-bold text-vida-main hover:text-vida-primary inline-flex items-center gap-1"
        >
          <UserPlus size={16} /> {showAddForm ? 'Cancelar' : 'Agregar Beneficiario Nuevo'}
        </button>

        {showAddForm && (
          <div className="mt-3 bg-vida-bg/50 border border-vida-main/20 rounded-xl p-4 max-w-lg space-y-3">
            <p className="text-xs text-gray-600">
              Para pacientes nuevos que no están en el padrón (pacientes.csv original) y por lo
              tanto no pueden encontrar su coincidencia en el autoregistro público.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Input
                label="Nombres"
                value={addForm.nombres}
                onChange={(e) => setAddForm((f) => ({ ...f, nombres: e.target.value }))}
              />
              <Input
                label="Apellido Paterno"
                value={addForm.ap_paterno}
                onChange={(e) => setAddForm((f) => ({ ...f, ap_paterno: e.target.value }))}
              />
              <Input
                label="Apellido Materno"
                value={addForm.ap_materno}
                onChange={(e) => setAddForm((f) => ({ ...f, ap_materno: e.target.value }))}
              />
              <Input
                label="Departamento"
                value={addForm.depto}
                onChange={(e) => setAddForm((f) => ({ ...f, depto: e.target.value }))}
              />
            </div>
            <div className="flex justify-end">
              <Button
                type="button"
                onClick={handleAddBeneficiary}
                disabled={adding}
                className="w-auto px-4 py-2 text-sm inline-flex items-center gap-1"
              >
                <UserPlus size={14} /> {adding ? 'Agregando...' : 'Agregar al Padrón'}
              </Button>
            </div>
          </div>
        )}
      </div>

      {loading && <p className="text-sm text-gray-500">Buscando...</p>}

      {!loading && searched && results.length === 0 && (
        <p className="text-sm text-gray-500">No se encontraron beneficiarios con ese nombre.</p>
      )}

      <div className="space-y-3">
        {results.map((item) => (
          <div key={item.id} className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
            {editingId === item.id ? (
              <div className="space-y-3">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <Input
                    label="Nombres"
                    value={form.nombres}
                    onChange={(e) => setForm((f) => ({ ...f, nombres: e.target.value }))}
                  />
                  <Input
                    label="Apellido Paterno"
                    value={form.ap_paterno}
                    onChange={(e) => setForm((f) => ({ ...f, ap_paterno: e.target.value }))}
                  />
                  <Input
                    label="Apellido Materno"
                    value={form.ap_materno}
                    onChange={(e) => setForm((f) => ({ ...f, ap_materno: e.target.value }))}
                  />
                  <Input
                    label="Departamento"
                    value={form.depto}
                    onChange={(e) => setForm((f) => ({ ...f, depto: e.target.value }))}
                  />
                </div>
                <div className="flex justify-end gap-2">
                  <Button
                    type="button"
                    onClick={cancelEdit}
                    className="w-auto px-4 py-2 text-sm bg-gray-200 text-gray-700 hover:bg-gray-300 inline-flex items-center gap-1"
                  >
                    <X size={14} /> Cancelar
                  </Button>
                  <Button
                    type="button"
                    onClick={() => handleSave(item.id)}
                    disabled={saving}
                    className="w-auto px-4 py-2 text-sm inline-flex items-center gap-1"
                  >
                    <Save size={14} /> {saving ? 'Guardando...' : 'Guardar'}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex justify-between items-start gap-3">
                <div>
                  <p className="font-bold text-gray-800 flex items-center gap-2">
                    {item.nombres} {item.ap_paterno || ''} {item.ap_materno || ''}
                    {item.already_registered && (
                      <span className="text-xs font-normal text-green-600 inline-flex items-center gap-1">
                        <CheckCircle2 size={14} /> Ya registrado
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-gray-500">{item.depto || 'Sin departamento'}</p>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  {item.already_registered && (
                    <button
                      onClick={() => handleResetRegistration(item)}
                      disabled={saving}
                      className="text-amber-600 hover:text-amber-700 p-1"
                      title="Borrar paciente/usuario de prueba y liberar este beneficiario (herramienta temporal de pruebas)"
                    >
                      <RotateCcw size={18} />
                    </button>
                  )}
                  <button
                    onClick={() => startEdit(item)}
                    className="text-vida-main hover:text-vida-primary p-1"
                    title="Editar"
                  >
                    <Pencil size={18} />
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
