import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'react-hot-toast';
import {
  UserCog,
  Search,
  Save,
  X,
  Pencil,
  CheckCircle2,
  RotateCcw,
  UserPlus,
  Trash2,
  AlertTriangle,
} from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import {
  getPaginatedBeneficiariesAdmin,
  createBeneficiaryAdmin,
  updateBeneficiaryAdmin,
  deleteBeneficiaryAdmin,
  resetBeneficiaryRegistration,
} from '../../api/patients';

const emptyForm = { nombres: '', ap_paterno: '', ap_materno: '', depto: '' };
const LIMIT = 20;

export default function BeneficiaryNamesPage() {
  const navigate = useNavigate();

  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');

  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  const [showAddForm, setShowAddForm] = useState(false);
  const [addForm, setAddForm] = useState(emptyForm);
  const [adding, setAdding] = useState(false);

  const [rowToDelete, setRowToDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const totalPages = Math.ceil(total / LIMIT) || 1;

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || '{}');
    if (user.role !== 'SUPER_ADMIN') {
      toast.error('Solo SUPER_ADMIN puede acceder a esta herramienta.');
      navigate('/dashboard/lista-pacientes', { replace: true });
    }
  }, [navigate]);

  const loadBeneficiaries = useCallback(async (currentPage, search) => {
    try {
      setLoading(true);
      const data = await getPaginatedBeneficiariesAdmin({
        skip: (currentPage - 1) * LIMIT,
        limit: LIMIT,
        search,
      });
      setRows(data.items);
      setTotal(data.total);
    } catch {
      toast.error('No se pudo cargar el padrón.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      setPage(1);
      loadBeneficiaries(1, searchTerm);
    }, 400);
    return () => clearTimeout(timer);
  }, [searchTerm, loadBeneficiaries]);

  const handlePageChange = (newPage) => {
    if (newPage >= 1 && newPage <= totalPages) {
      setPage(newPage);
      loadBeneficiaries(newPage, searchTerm);
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

  const handleResetRegistration = async (item) => {
    const confirmado = window.confirm(
      `¿Borrar el paciente/usuario de prueba registrado como "${item.nombres} ${item.ap_paterno || ''}"? ` +
        `Esto elimina permanentemente ese registro (datos médicos, documentos, etc.) y libera el padrón.`
    );
    if (!confirmado) return;
    try {
      setSaving(true);
      const updated = await resetBeneficiaryRegistration(item.id);
      setRows((prev) => prev.map((r) => (r.id === item.id ? updated : r)));
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
      await createBeneficiaryAdmin(addForm);
      toast.success('Beneficiario agregado al padrón. Ya puede autoregistrarse.');
      setAddForm(emptyForm);
      setShowAddForm(false);
      setPage(1);
      loadBeneficiaries(1, searchTerm);
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
      setRows((prev) => prev.map((r) => (r.id === id ? updated : r)));
      toast.success('Registro corregido correctamente.');
      cancelEdit();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo guardar el cambio.');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!rowToDelete) return;
    try {
      setDeleting(true);
      await deleteBeneficiaryAdmin(rowToDelete.id);
      toast.success('Registro eliminado del padrón.');
      setRowToDelete(null);
      const remainingOnPage = rows.length - 1;
      if (remainingOnPage === 0 && page > 1) {
        setPage(page - 1);
        loadBeneficiaries(page - 1, searchTerm);
      } else {
        loadBeneficiaries(page, searchTerm);
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo eliminar el registro.');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <>
      <div className="p-6 md:p-8 max-w-6xl mx-auto">
        <h1 className="text-2xl font-bold text-vida-primary mb-2 flex items-center gap-2">
          <UserCog /> Padrón de Beneficiarios
        </h1>
        <p className="text-sm text-gray-500 mb-6">
          Lista completa del padrón precargado (pacientes.csv). Corrige nombres/apellidos
          incompletos o mal escritos, elimina registros duplicados (ej. "Fabiana" vs "Faviana")
          y agrega beneficiarios nuevos que no forman parte del padrón original.
        </p>

        <div className="flex flex-col sm:flex-row gap-3 sm:items-end max-w-lg mb-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Buscar por nombre, apellido o departamento..."
              className="w-full pl-10 pr-4 py-2 rounded-lg bg-gray-50 border border-gray-200 focus:bg-white focus:ring-2 focus:ring-vida-light/30 outline-none transition-all text-sm"
            />
          </div>
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
                tanto no pueden encontrar su coincidencia en el autoregistro público. Antes de
                agregar, busca arriba para confirmar que no exista ya con otra ortografía.
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

        <div className="bg-white rounded-2xl shadow-xl overflow-hidden border border-gray-100">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Nombres</th>
                  <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Ap. Paterno</th>
                  <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Ap. Materno</th>
                  <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Depto</th>
                  <th className="px-4 py-3 text-center text-xs font-bold text-gray-500 uppercase tracking-wider">Estado</th>
                  <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading ? (
                  <tr><td colSpan="6" className="px-6 py-10 text-center text-gray-400">Cargando...</td></tr>
                ) : rows.length === 0 ? (
                  <tr><td colSpan="6" className="px-6 py-10 text-center text-gray-400">No se encontraron registros en el padrón.</td></tr>
                ) : (
                  rows.map((item) =>
                    editingId === item.id ? (
                      <tr key={item.id} className="bg-vida-bg/30">
                        <td className="px-4 py-3">
                          <Input
                            value={form.nombres}
                            onChange={(e) => setForm((f) => ({ ...f, nombres: e.target.value }))}
                          />
                        </td>
                        <td className="px-4 py-3">
                          <Input
                            value={form.ap_paterno}
                            onChange={(e) => setForm((f) => ({ ...f, ap_paterno: e.target.value }))}
                          />
                        </td>
                        <td className="px-4 py-3">
                          <Input
                            value={form.ap_materno}
                            onChange={(e) => setForm((f) => ({ ...f, ap_materno: e.target.value }))}
                          />
                        </td>
                        <td className="px-4 py-3">
                          <Input
                            value={form.depto}
                            onChange={(e) => setForm((f) => ({ ...f, depto: e.target.value }))}
                          />
                        </td>
                        <td className="px-4 py-3 text-center">
                          {item.already_registered && (
                            <span className="text-xs font-normal text-green-600 inline-flex items-center gap-1">
                              <CheckCircle2 size={14} /> Registrado
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              onClick={cancelEdit}
                              className="p-1.5 rounded-full text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                              title="Cancelar"
                            >
                              <X size={16} />
                            </button>
                            <button
                              onClick={() => handleSave(item.id)}
                              disabled={saving}
                              className="p-1.5 rounded-full text-vida-main hover:text-vida-primary hover:bg-green-50 transition-colors"
                              title="Guardar"
                            >
                              <Save size={16} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ) : (
                      <tr key={item.id} className="hover:bg-gray-50/80 transition-colors">
                        <td className="px-4 py-3 text-sm font-bold text-gray-900">{item.nombres}</td>
                        <td className="px-4 py-3 text-sm text-gray-700">{item.ap_paterno || '-'}</td>
                        <td className="px-4 py-3 text-sm text-gray-700">{item.ap_materno || '-'}</td>
                        <td className="px-4 py-3 text-sm text-gray-500">{item.depto || '-'}</td>
                        <td className="px-4 py-3 text-center">
                          {item.already_registered ? (
                            <span className="text-xs font-normal text-green-600 inline-flex items-center gap-1">
                              <CheckCircle2 size={14} /> Registrado
                            </span>
                          ) : (
                            <span className="text-xs text-gray-400">Pendiente</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-1">
                            {item.already_registered && (
                              <button
                                onClick={() => handleResetRegistration(item)}
                                disabled={saving}
                                className="p-1.5 rounded-full text-amber-500 hover:text-amber-700 hover:bg-amber-50 transition-colors"
                                title="Borrar paciente/usuario de prueba y liberar este beneficiario (herramienta temporal de pruebas)"
                              >
                                <RotateCcw size={16} />
                              </button>
                            )}
                            <button
                              onClick={() => startEdit(item)}
                              className="p-1.5 rounded-full text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
                              title="Editar"
                            >
                              <Pencil size={16} />
                            </button>
                            <button
                              onClick={() => setRowToDelete(item)}
                              disabled={item.already_registered}
                              className="p-1.5 rounded-full text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-gray-400 disabled:cursor-not-allowed"
                              title={
                                item.already_registered
                                  ? 'No se puede borrar: ya está vinculado a un paciente registrado'
                                  : 'Borrar del padrón'
                              }
                            >
                              <Trash2 size={16} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  )
                )}
              </tbody>
            </table>
          </div>

          {!loading && totalPages > 1 && (
            <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100 bg-gray-50">
              <div className="text-sm text-gray-500">
                Página <span className="font-medium text-gray-900">{page}</span> de{' '}
                <span className="font-medium text-gray-900">{totalPages}</span>{' '}
                ({total} registros)
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handlePageChange(page - 1)}
                  disabled={page === 1}
                  className="px-4 py-2 border border-gray-200 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  Anterior
                </button>
                <button
                  onClick={() => handlePageChange(page + 1)}
                  disabled={page === totalPages}
                  className="px-4 py-2 border border-gray-200 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  Siguiente
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {rowToDelete && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 animate-fadeIn">
            <div className="flex items-center gap-4 mb-4">
              <div className="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center flex-shrink-0">
                <AlertTriangle className="text-red-600" size={24} />
              </div>
              <div>
                <h3 className="text-lg font-bold text-gray-800">Eliminar del Padrón</h3>
                <p className="text-sm text-gray-500">Esta acción no se puede deshacer.</p>
              </div>
            </div>
            <p className="text-gray-700 mb-6 bg-red-50 p-3 rounded-lg border border-red-100 text-sm">
              ¿Está seguro que desea eliminar a{' '}
              <strong>
                {rowToDelete.nombres} {rowToDelete.ap_paterno || ''}
              </strong>{' '}
              del padrón? Úsalo para borrar registros duplicados o mal escritos.
            </p>
            <div className="flex gap-3 justify-end">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setRowToDelete(null)}
                disabled={deleting}
                className="px-5"
              >
                Cancelar
              </Button>
              <Button
                type="button"
                onClick={handleDeleteConfirm}
                disabled={deleting}
                className="bg-red-600 hover:bg-red-700 text-white px-5 shadow-lg shadow-red-200"
              >
                {deleting ? 'Eliminando...' : 'Sí, eliminar'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
