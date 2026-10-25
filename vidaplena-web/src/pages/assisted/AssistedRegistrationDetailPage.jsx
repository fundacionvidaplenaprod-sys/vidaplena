import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'react-hot-toast';
import { AlertTriangle, ArrowLeft, CheckCircle, ClipboardCheck, Edit2, PackagePlus, ShieldOff } from 'lucide-react';
import { ReferentCard } from './ReferentPicker';
import { Button } from '../../components/ui/Button';
import { Modal } from '../../components/ui/Modal';
import { useAuth } from '../../context/AuthContext';
import {
  CESE_CAUSAS, CONSTANCIA_TIPOS, ENTIDAD_TIPOS, ESTADO_LABELS, ESTADO_STYLES, RANGOS_EDAD,
  RECEPTOR_TIPOS, REFERENTE_VINCULOS, labelOf,
} from '../../constants/assisted';
import { displayInsulinName } from '../../constants/insulins';
import {
  addAssistedDelivery, denyAssistedRegistration, endAssistedRegistration, getAssistedRegistration, getReferent,
  registerAssistedReview, updateAssistedRegistration, updateReferent,
} from '../../api/assistedRegistrations';
import AssistedRegistrationForm from './AssistedRegistrationForm';

const inputClass = 'w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white';
const fmtDate = (value) => (value ? new Date(value).toLocaleDateString('es-BO') : '-');
const hoy = () => new Date().toISOString().split('T')[0];

function Dato({ label, children }) {
  return (
    <div>
      <p className="text-xs font-semibold text-gray-400 uppercase">{label}</p>
      <p className="text-sm text-gray-800">{children || '-'}</p>
    </div>
  );
}

const ENTREGA_VACIA = { fecha: hoy(), insumo: '', cantidad: '', receptor_tipo: '', receptor_nombre: '', constancia_tipo: '' };

export default function AssistedRegistrationDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const puedeDenegar = ['SUPER_ADMIN', 'EVALUADOR_SOCIAL'].includes(user?.role);

  const [reg, setReg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editando, setEditando] = useState(false);
  const [saving, setSaving] = useState(false);
  const [entrega, setEntrega] = useState(ENTREGA_VACIA);
  const [modal, setModal] = useState(null); // 'cese' | 'denegar'
  const [cese, setCese] = useState({ causa: 'SIN_NECESIDAD', detalle: '', patient_id: '' });
  const [motivo, setMotivo] = useState('');
  const [otrosCodigos, setOtrosCodigos] = useState([]);
  const [refEdit, setRefEdit] = useState({ nombre_completo: '', ci: '', telefono: '', foto: null });

  const load = useCallback(async () => {
    try {
      setReg(await getAssistedRegistration(id));
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo cargar el registro.');
      navigate('/dashboard/registro-asistido');
    } finally {
      setLoading(false);
    }
  }, [id, navigate]);

  useEffect(() => {
    load();
  }, [load]);

  // Otros beneficiarios de los que la misma persona es referente.
  const referenteId = reg?.referente?.id;
  const codigoActual = reg?.codigo;
  useEffect(() => {
    if (!referenteId) {
      setOtrosCodigos([]);
      return;
    }
    getReferent(referenteId)
      .then((r) => setOtrosCodigos((r.codigos || []).filter((c) => c !== codigoActual)))
      .catch(() => setOtrosCodigos([]));
  }, [referenteId, codigoActual]);

  // Ejecuta una acción que devuelve el registro actualizado y muestra el error del servidor, si lo hay.
  const run = async (action, okMessage) => {
    try {
      setSaving(true);
      setReg(await action());
      if (okMessage) toast.success(okMessage);
      return true;
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo completar la acción.');
      return false;
    } finally {
      setSaving(false);
    }
  };

  if (loading || !reg) return <div className="p-10 text-center text-gray-500">Cargando…</div>;

  const activo = reg.estado === 'ACTIVO';

  const guardarDatos = async (payload) => {
    if (await run(() => updateAssistedRegistration(id, payload), 'Datos actualizados.')) setEditando(false);
  };

  const guardarEntrega = async (event) => {
    event.preventDefault();
    if (!entrega.insumo.trim() || !entrega.cantidad.trim()) {
      toast.error('Indique el insumo y la cantidad entregados.');
      return;
    }
    const payload = {
      ...entrega,
      receptor_tipo: entrega.receptor_tipo || null,
      constancia_tipo: entrega.constancia_tipo || null,
      receptor_nombre: entrega.receptor_nombre || null,
    };
    if (await run(() => addAssistedDelivery(id, payload), 'Entrega registrada.')) setEntrega({ ...ENTREGA_VACIA, fecha: hoy() });
  };

  const abrirEdicionReferente = () => {
    setRefEdit({
      nombre_completo: reg.referente.nombre_completo || '',
      ci: reg.referente.ci || '',
      telefono: reg.referente.telefono || '',
      foto: null,
    });
    setModal('referente');
  };

  const guardarReferente = async () => {
    if (!reg.referente.foto_url && !refEdit.foto) {
      toast.error('La foto personal de la persona referente es obligatoria.');
      return;
    }
    try {
      setSaving(true);
      await updateReferent(reg.referente.id, refEdit);
      toast.success('Persona referente actualizada.');
      setModal(null);
      await load();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo actualizar a la persona referente.');
    } finally {
      setSaving(false);
    }
  };

  const confirmarCese = async () => {
    if (cese.causa === 'FALTA_GRAVE' && !cese.detalle.trim()) {
      toast.error('La falta grave exige indicar el detalle y que se cumplió el debido proceso.');
      return;
    }
    const payload = {
      causa: cese.causa,
      detalle: cese.detalle.trim() || null,
      patient_id: cese.causa === 'TRASLADO_REGIMEN_ORDINARIO' && cese.patient_id ? Number(cese.patient_id) : null,
    };
    if (await run(() => endAssistedRegistration(id, payload), 'Registro cesado.')) setModal(null);
  };

  const confirmarDenegacion = async () => {
    if (motivo.trim().length < 10) {
      toast.error('La resolución debe estar motivada (al menos 10 caracteres).');
      return;
    }
    if (await run(() => denyAssistedRegistration(id, motivo.trim()), 'Admisión denegada.')) setModal(null);
  };

  return (
    <div className="max-w-5xl mx-auto animate-fadeIn space-y-6">
      <button onClick={() => navigate('/dashboard/registro-asistido')} className="text-sm text-gray-500 hover:text-gray-800 inline-flex items-center gap-1">
        <ArrowLeft size={16} /> Volver al Registro Asistido
      </button>

      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-3xl font-bold text-gray-800">{reg.codigo}</h1>
        <span className={`px-3 py-1 rounded-full text-xs font-bold border ${ESTADO_STYLES[reg.estado]}`}>{ESTADO_LABELS[reg.estado]}</span>
        {reg.urgente && activo && <span className="px-3 py-1 rounded-full text-xs font-bold border bg-orange-100 text-orange-700 border-orange-200">Necesidad médica inmediata</span>}
        {reg.revision_vencida && (
          <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-bold border bg-yellow-100 text-yellow-800 border-yellow-200">
            <AlertTriangle size={12} /> Revisión semestral vencida
          </span>
        )}
      </div>

      {reg.estado === 'DENEGADO' && (
        <div className="bg-red-50 border border-red-100 rounded-xl p-4 text-sm text-red-800">
          <p className="font-semibold">Admisión denegada</p>
          <p>{reg.motivo_denegacion}</p>
        </div>
      )}
      {reg.estado === 'CESADO' && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 text-sm text-gray-700">
          <p className="font-semibold">Registro cesado el {fmtDate(reg.cese_at)}: {labelOf(CESE_CAUSAS, reg.cese_causa)}</p>
          {reg.cese_detalle && <p>{reg.cese_detalle}</p>}
          {reg.patient_id && <p>Pasó al registro ordinario (ficha N.° {reg.patient_id}).</p>}
        </div>
      )}

      <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-bold text-gray-800">Datos del registro</h2>
          {activo && !editando && (
            <button onClick={() => setEditando(true)} className="text-sm font-semibold text-vida-main inline-flex items-center gap-1 hover:underline">
              <Edit2 size={14} /> Completar o corregir datos
            </button>
          )}
        </div>
        {editando ? (
          <AssistedRegistrationForm initial={reg} onSubmit={guardarDatos} submitting={saving} submitLabel="Guardar cambios" />
        ) : (
          <div className="grid md:grid-cols-3 gap-4">
            <Dato label="Nombre, apodo o iniciales">{reg.nombre}</Dato>
            <Dato label="C.I.">{reg.ci}</Dato>
            <Dato label="Fecha de nacimiento">{reg.fecha_nacimiento && fmtDate(`${reg.fecha_nacimiento}T12:00:00`)}</Dato>
            <Dato label="Edad">{reg.edad_aproximada ? `${reg.edad_aproximada} años aprox.` : labelOf(RANGOS_EDAD, reg.rango_edad)}</Dato>
            <Dato label="Departamento / municipio / localidad">{[reg.depto, reg.municipio, reg.ciudad_localidad].filter(Boolean).join(' · ')}</Dato>
            <Dato label="Tipo de diabetes">{reg.tipo_diabetes}</Dato>
            <Dato label="Años con la diabetes">{reg.anios_diabetes != null && `${reg.anios_diabetes} años`}</Dato>
            <Dato label="Complicaciones u otras enfermedades">{reg.complicaciones_otras}</Dato>
            <Dato label="Entidad referente">{reg.entidad_nombre}</Dato>
            <Dato label="Tipo de entidad">{reg.entidad_tipo && labelOf(ENTIDAD_TIPOS, reg.entidad_tipo)}</Dato>
            <Dato label="Insulinas">
              {reg.treatments.length > 0 && reg.treatments.map((t) => `${displayInsulinName(t.insulina)}${t.dosis_diaria ? `: ${t.dosis_diaria} UI al día` : ''}`).join(' · ')}
            </Dato>
            <Dato label="Otros insumos">{reg.insumos_requeridos}</Dato>
          </div>
        )}
      </section>

      <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-bold text-gray-800">Persona referente (recibe la insulina)</h2>
          {activo && reg.referente && (
            <button onClick={abrirEdicionReferente} className="text-sm font-semibold text-vida-main inline-flex items-center gap-1 hover:underline">
              <Edit2 size={14} /> Corregir datos o foto
            </button>
          )}
        </div>
        {reg.referente ? (
          <>
            <ReferentCard referente={reg.referente} />
            <p className="text-sm text-gray-600">
              Vínculo con el beneficiario: <strong>{labelOf(REFERENTE_VINCULOS, reg.referente_vinculo)}</strong>
              {otrosCodigos.length > 0 && <> · También es persona referente de: {otrosCodigos.join(', ')}</>}
            </p>
            {(!reg.referente.ci || !reg.referente.foto_url) && (
              <p className="text-sm text-red-600 font-semibold flex items-center gap-1">
                <AlertTriangle size={14} /> Faltan {!reg.referente.ci && 'el C.I.'}{!reg.referente.ci && !reg.referente.foto_url && ' y '}{!reg.referente.foto_url && 'la foto personal'} de la persona referente.
              </p>
            )}
          </>
        ) : (
          <p className="text-sm text-red-600 font-semibold flex items-center gap-1">
            <AlertTriangle size={14} /> Este registro no tiene persona referente. Indíquela en «Completar o corregir datos»: es obligatoria.
          </p>
        )}
      </section>

      <section className="grid md:grid-cols-2 gap-4">
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
          <h2 className="font-bold text-gray-800 mb-2 flex items-center gap-2"><ClipboardCheck size={18} /> Revisión de vigencia</h2>
          <p className="text-sm text-gray-600 mb-3">
            Debe revisarse al menos cada 6 meses, por comunicación con la persona referente. Última revisión:{' '}
            <strong>{reg.ultima_revision_at ? fmtDate(reg.ultima_revision_at) : 'ninguna todavía'}</strong>.
          </p>
          {activo && (
            <Button disabled={saving} onClick={() => run(() => registerAssistedReview(id), 'Revisión registrada.')} className="w-auto px-5">
              Registrar revisión realizada
            </Button>
          )}
        </div>
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
          <h2 className="font-bold text-gray-800 mb-2 flex items-center gap-2"><CheckCircle size={18} /> Compromiso de buen uso</h2>
          {reg.buen_uso_comunicado_at ? (
            <p className="text-sm text-green-700">Comunicado a la persona referente el {fmtDate(reg.buen_uso_comunicado_at)}.</p>
          ) : (
            <p className="text-sm text-gray-600">
              Aún no consta que se haya comunicado que los insumos son de uso personal e intransferible y que su venta o desvío está prohibido.
              {activo && ' Márquelo en «Completar o corregir datos».'}
            </p>
          )}
        </div>
      </section>

      <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
        <h2 className="font-bold text-gray-800 mb-4 flex items-center gap-2"><PackagePlus size={18} /> Entregas de insumos</h2>
        {activo && (
          <form onSubmit={guardarEntrega} className="grid md:grid-cols-6 gap-3 items-end mb-5 pb-5 border-b border-gray-100">
            <div>
              <label htmlFor="en-fecha" className="block text-xs font-semibold text-gray-700 mb-1">Fecha</label>
              <input id="en-fecha" type="date" max={hoy()} className={inputClass} value={entrega.fecha} onChange={(e) => setEntrega({ ...entrega, fecha: e.target.value })} />
            </div>
            <div className="md:col-span-2">
              <label htmlFor="en-insumo" className="block text-xs font-semibold text-gray-700 mb-1">Insumo</label>
              <input id="en-insumo" className={inputClass} value={entrega.insumo} onChange={(e) => setEntrega({ ...entrega, insumo: e.target.value })} placeholder="Ej: Insulina Glargina, jeringas" />
            </div>
            <div>
              <label htmlFor="en-cantidad" className="block text-xs font-semibold text-gray-700 mb-1">Cantidad</label>
              <input id="en-cantidad" className={inputClass} value={entrega.cantidad} onChange={(e) => setEntrega({ ...entrega, cantidad: e.target.value })} placeholder="Ej: 2 frascos" />
            </div>
            <div>
              <label htmlFor="en-receptor" className="block text-xs font-semibold text-gray-700 mb-1">Recibió</label>
              <select id="en-receptor" className={inputClass} value={entrega.receptor_tipo} onChange={(e) => setEntrega({ ...entrega, receptor_tipo: e.target.value })}>
                <option value="">No se anota</option>
                {RECEPTOR_TIPOS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="en-constancia" className="block text-xs font-semibold text-gray-700 mb-1">Constancia (opcional)</label>
              <select id="en-constancia" className={inputClass} value={entrega.constancia_tipo} onChange={(e) => setEntrega({ ...entrega, constancia_tipo: e.target.value })}>
                <option value="">No se anota</option>
                {CONSTANCIA_TIPOS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div className="md:col-span-6 flex items-center justify-between gap-3">
              <p className="text-xs text-gray-400">La falta de constancia nunca impide la entrega.</p>
              <Button type="submit" disabled={saving} className="w-auto px-6">Registrar entrega</Button>
            </div>
          </form>
        )}
        {reg.deliveries.length === 0 ? (
          <p className="text-sm text-gray-400">Todavía no se registraron entregas.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-xs uppercase text-gray-400">
                <th className="py-2 pr-3">Fecha</th><th className="pr-3">Insumo</th><th className="pr-3">Cantidad</th><th className="pr-3">Recibió</th><th className="pr-3">Constancia</th><th>Registró</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {reg.deliveries.map((d) => (
                <tr key={d.id}>
                  <td className="py-2 pr-3 whitespace-nowrap">{fmtDate(d.fecha)}</td>
                  <td className="pr-3">{d.insumo}</td>
                  <td className="pr-3">{d.cantidad}</td>
                  <td className="pr-3">{d.receptor_tipo ? labelOf(RECEPTOR_TIPOS, d.receptor_tipo) : '-'}</td>
                  <td className="pr-3">{d.constancia_tipo ? labelOf(CONSTANCIA_TIPOS, d.constancia_tipo) : '-'}</td>
                  <td className="text-gray-500">{d.entregado_por || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {activo && (
        <section className="flex flex-wrap justify-end gap-3">
          {puedeDenegar && reg.deliveries.length === 0 && (
            <Button variant="outline" onClick={() => { setMotivo(''); setModal('denegar'); }} className="w-auto px-5">
              <ShieldOff size={16} /> Denegar admisión
            </Button>
          )}
          <Button variant="outline" onClick={() => setModal('cese')} className="w-auto px-5 border-red-300 text-red-600">
            Cesar registro
          </Button>
        </section>
      )}

      <Modal isOpen={modal === 'cese'} onClose={() => setModal(null)} title="Cesar el registro">
        <div className="space-y-4">
          <p className="text-sm text-gray-500">
            Solo por las causas del reglamento. La pérdida de contacto con la persona referente o el cambio de institución no son causales de cese.
          </p>
          <div>
            <label htmlFor="cese-causa" className="block text-xs font-semibold text-gray-700 mb-1">Causa</label>
            <select id="cese-causa" className={inputClass} value={cese.causa} onChange={(e) => setCese({ ...cese, causa: e.target.value })}>
              {CESE_CAUSAS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          {cese.causa === 'TRASLADO_REGIMEN_ORDINARIO' && (
            <div>
              <label htmlFor="cese-ficha" className="block text-xs font-semibold text-gray-700 mb-1">N.° de ficha del registro ordinario (si ya existe)</label>
              <input id="cese-ficha" type="number" className={inputClass} value={cese.patient_id} onChange={(e) => setCese({ ...cese, patient_id: e.target.value })} />
            </div>
          )}
          <div>
            <label htmlFor="cese-detalle" className="block text-xs font-semibold text-gray-700 mb-1">
              Detalle {cese.causa === 'FALTA_GRAVE' ? '(obligatorio)' : '(opcional)'}
            </label>
            <textarea id="cese-detalle" className={`${inputClass} min-h-[80px]`} value={cese.detalle} onChange={(e) => setCese({ ...cese, detalle: e.target.value })} />
          </div>
          <div className="flex justify-end gap-3">
            <Button variant="outline" onClick={() => setModal(null)} className="w-auto px-5">Cancelar</Button>
            <Button onClick={confirmarCese} disabled={saving} className="w-auto px-5 bg-red-600 hover:bg-red-700">Confirmar cese</Button>
          </div>
        </div>
      </Modal>

      <Modal isOpen={modal === 'referente'} onClose={() => setModal(null)} title="Corregir a la persona referente">
        <div className="space-y-3">
          <p className="text-xs text-gray-500">Los cambios valen para todos los beneficiarios de los que es persona referente.</p>
          <div>
            <label htmlFor="rfe-nombre" className="block text-xs font-semibold text-gray-700 mb-1">Nombre completo</label>
            <input id="rfe-nombre" className={inputClass} value={refEdit.nombre_completo} onChange={(e) => setRefEdit({ ...refEdit, nombre_completo: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="rfe-ci" className="block text-xs font-semibold text-gray-700 mb-1">C.I.</label>
              <input id="rfe-ci" className={inputClass} value={refEdit.ci} onChange={(e) => setRefEdit({ ...refEdit, ci: e.target.value })} />
            </div>
            <div>
              <label htmlFor="rfe-tel" className="block text-xs font-semibold text-gray-700 mb-1">N.° de contacto</label>
              <input id="rfe-tel" className={inputClass} value={refEdit.telefono} onChange={(e) => setRefEdit({ ...refEdit, telefono: e.target.value })} />
            </div>
          </div>
          <div>
            <label htmlFor="rfe-foto" className="block text-xs font-semibold text-gray-700 mb-1">
              Foto personal {reg.referente?.foto_url ? '(deje vacío para conservar la actual)' : '(obligatoria)'}
            </label>
            <input id="rfe-foto" type="file" accept="image/jpeg,image/png" className="text-sm" onChange={(e) => setRefEdit({ ...refEdit, foto: e.target.files?.[0] || null })} />
          </div>
          <div className="flex justify-end gap-3">
            <Button variant="outline" onClick={() => setModal(null)} className="w-auto px-5">Cancelar</Button>
            <Button onClick={guardarReferente} disabled={saving} className="w-auto px-5">Guardar</Button>
          </div>
        </div>
      </Modal>

      <Modal isOpen={modal === 'denegar'} onClose={() => setModal(null)} title="Denegar la admisión">
        <div className="space-y-4">
          <p className="text-sm text-gray-500">
            Solo procede por manifiesta ausencia de necesidad de insulina o de los insumos solicitados, mediante resolución motivada.
            La persona puede volver a solicitar.
          </p>
          <div>
            <label htmlFor="deny-motivo" className="block text-xs font-semibold text-gray-700 mb-1">Resolución motivada</label>
            <textarea id="deny-motivo" className={`${inputClass} min-h-[100px]`} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
          </div>
          <div className="flex justify-end gap-3">
            <Button variant="outline" onClick={() => setModal(null)} className="w-auto px-5">Cancelar</Button>
            <Button onClick={confirmarDenegacion} disabled={saving} className="w-auto px-5 bg-red-600 hover:bg-red-700">Denegar</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
