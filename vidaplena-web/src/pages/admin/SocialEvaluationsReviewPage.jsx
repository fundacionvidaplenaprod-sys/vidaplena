import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle, CheckCircle, ExternalLink, RefreshCcw, ChevronDown, ChevronUp,
  Video, History, ShieldAlert, UserCheck, Trash2,
} from 'lucide-react';
import { toast } from 'react-hot-toast';
import {
  listSocialEvaluations,
  markEvaluationInterviewDone,
  reviewSocialEvaluation,
  getEvaluationHistory,
  reactivatePatientEvaluation,
  debugDeleteSocialEvaluation,
} from '../../api/evaluations';
import { Button } from '../../components/ui/Button';

const ESTADO_STYLES = {
  PENDIENTE: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  APROBADO: 'bg-green-100 text-green-700 border-green-200',
  RECHAZADO: 'bg-red-100 text-red-700 border-red-200',
  RECHAZADO_FRAUDE: 'bg-red-200 text-red-900 border-red-400',
};

const DECISION_LABELS = {
  APROBADO: 'Aprobado',
  RECHAZADO: 'Rechazado (estándar)',
  RECHAZADO_FRAUDE: 'Rechazado por falsedad',
  REACTIVADO: 'Reactivado',
};

// Orden fijo: de MAYOR a MENOR vulnerabilidad. No reordenar — evita que un
// evaluador nuevo o rotativo confunda "BAJA" con "necesita más ayuda".
const CATEGORIA_INFO = {
  ALTA: {
    subtitle: 'Mayor necesidad',
    rango: 'CFNR ≤ 0 Bs',
    descripcion: 'Déficit: no le alcanza para cubrir la canasta básica ni sus gastos esenciales.',
    badge: 'bg-red-100 text-red-700 border-red-300',
    selected: 'border-red-600 bg-red-600 text-white',
    idle: 'border-red-200 text-red-700 hover:border-red-400',
  },
  MEDIA: {
    subtitle: 'Necesidad moderada',
    rango: '0 – 1.500 Bs',
    descripcion: 'Cubre lo esencial, con margen ajustado para sostener un aporte.',
    badge: 'bg-amber-100 text-amber-700 border-amber-300',
    selected: 'border-amber-600 bg-amber-500 text-white',
    idle: 'border-amber-200 text-amber-700 hover:border-amber-400',
  },
  BAJA: {
    subtitle: 'Situación acomodada',
    rango: '> 1.500 Bs',
    descripcion: 'Sin vulnerabilidad económica: en principio NO requeriría exoneración.',
    badge: 'bg-green-100 text-green-700 border-green-300',
    selected: 'border-green-600 bg-green-600 text-white',
    idle: 'border-green-200 text-green-700 hover:border-green-400',
  },
};
const CATEGORIA_ORDEN = ['ALTA', 'MEDIA', 'BAJA'];

// Evaluaciones de antes del motor CFNR usaban otro esquema (ingreso per cápita +
// seguro médico) con sus propios códigos A/B/C/N. Siguen teniendo un significado
// preciso — no son basura ni "no reconocidos" — pero no son comparables 1:1 con
// ALTA/MEDIA/BAJA (fórmula distinta), así que nunca se muestran en crudo.
const LEGACY_CATEGORIA_INFO = {
  A: { label: 'Extrema pobreza', descripcion: 'Ingreso per cápita menor a Bs. 500 y sin seguro médico.' },
  B: { label: 'Pobreza moderada', descripcion: 'Ingreso per cápita entre Bs. 500 y Bs. 1.200.' },
  C: { label: 'Vulnerabilidad leve', descripcion: 'Ingreso per cápita entre Bs. 1.201 y Bs. 2.250.' },
  N: { label: 'No prioritario', descripcion: 'Ingreso per cápita mayor a Bs. 2.250 (no elegible para beneficios prioritarios).' },
};
function categoriaBadgeClass(code) {
  if (CATEGORIA_INFO[code]) return CATEGORIA_INFO[code].badge;
  if (LEGACY_CATEGORIA_INFO[code]) return 'bg-slate-100 text-slate-700 border-slate-300';
  return 'bg-gray-100 text-gray-500 border-gray-300 border-dashed';
}
function categoriaLabel(code) {
  if (!code) return '—';
  if (CATEGORIA_INFO[code]) return code;
  if (LEGACY_CATEGORIA_INFO[code]) return `${code} · ${LEGACY_CATEGORIA_INFO[code].label}`;
  return `${code} (código no reconocido)`;
}

const EVIDENCIAS = [
  { key: 'foto_ci_url', label: 'Carnet de Identidad' },
  { key: 'foto_fachada_url', label: 'Fachada del domicilio' },
  { key: 'foto_sala_url', label: 'Sala / living' },
  { key: 'foto_dormitorio_url', label: 'Dormitorio' },
];

export default function SocialEvaluationsReviewPage() {
  const isSuperAdmin = (() => {
    try {
      return JSON.parse(localStorage.getItem('user') || '{}').role === 'SUPER_ADMIN';
    } catch {
      return false;
    }
  })();

  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState([]);
  const [estadoFilter, setEstadoFilter] = useState('PENDIENTE');
  const [expandedId, setExpandedId] = useState(null);
  const [submittingId, setSubmittingId] = useState(null);
  const [rejectModal, setRejectModal] = useState({ open: false, patientId: null });
  const [rejectReason, setRejectReason] = useState('');
  const [approveModal, setApproveModal] = useState({ open: false, patientId: null, categoriaSugerida: null, cfnr: null });
  const [approveCategoria, setApproveCategoria] = useState('');
  const [bajaAcknowledged, setBajaAcknowledged] = useState(false);
  const [interviewNotesById, setInterviewNotesById] = useState({});
  const [interviewSubmittingId, setInterviewSubmittingId] = useState(null);
  const [historyByPatientId, setHistoryByPatientId] = useState({});
  const [loadingHistoryId, setLoadingHistoryId] = useState(null);
  const [reactivatingId, setReactivatingId] = useState(null);
  const [debugDeletingId, setDebugDeletingId] = useState(null);

  const fetchEvaluations = async () => {
    try {
      setLoading(true);
      const params = estadoFilter ? { estado_revision: estadoFilter } : {};
      const data = await listSocialEvaluations(params);
      setItems(Array.isArray(data) ? data : []);
    } catch (error) {
      console.error(error);
      toast.error('No se pudo cargar la revisión de evaluaciones socioeconómicas.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEvaluations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [estadoFilter]);

  const toggleExpanded = (item) => {
    setExpandedId((prev) => (prev === item.id ? null : item.id));
    if (!historyByPatientId[item.patient_id]) {
      loadHistory(item.patient_id);
    }
  };

  const loadHistory = async (patientId) => {
    try {
      setLoadingHistoryId(patientId);
      const data = await getEvaluationHistory(patientId);
      setHistoryByPatientId((prev) => ({ ...prev, [patientId]: data }));
    } catch (error) {
      console.error(error);
      toast.error('No se pudo cargar el historial de este beneficiario.');
    } finally {
      setLoadingHistoryId(null);
    }
  };

  const handleReactivate = async (patientId) => {
    const confirmado = window.confirm(
      '¿Reactivar a este beneficiario? Podrá volver a enviar una evaluación socioeconómica de inmediato.'
    );
    if (!confirmado) return;
    try {
      setReactivatingId(patientId);
      await reactivatePatientEvaluation(patientId);
      toast.success('Beneficiario reactivado.');
      loadHistory(patientId);
    } catch (error) {
      console.error(error);
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'No se pudo reactivar al beneficiario.');
    } finally {
      setReactivatingId(null);
    }
  };

  // TODO: ELIMINAR AL TERMINAR QA (MODO PRUEBAS)
  const handleDebugDelete = async (patientId) => {
    const confirmado = window.confirm(
      '[MODO PRUEBAS] ¿Eliminar físicamente esta evaluación socioeconómica? ' +
        'Esta acción NO se puede deshacer y el beneficiario podrá volver a llenar el formulario desde cero.'
    );
    if (!confirmado) return;
    try {
      setDebugDeletingId(patientId);
      await debugDeleteSocialEvaluation(patientId);
      toast.success('Evaluación eliminada físicamente');
      await fetchEvaluations();
    } catch (error) {
      console.error(error);
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'No se pudo eliminar la evaluación.');
    } finally {
      setDebugDeletingId(null);
    }
  };

  const handleMarkInterview = async (patientId) => {
    try {
      setInterviewSubmittingId(patientId);
      await markEvaluationInterviewDone(patientId, (interviewNotesById[patientId] || '').trim());
      toast.success('Entrevista registrada. Ya puede emitir un veredicto.');
      await fetchEvaluations();
    } catch (error) {
      console.error(error);
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'No se pudo registrar la entrevista.');
    } finally {
      setInterviewSubmittingId(null);
    }
  };

  const openApproveModal = (item) => {
    setApproveModal({ open: true, patientId: item.patient_id, categoriaSugerida: item.categoria_asignada, cfnr: item.cfnr });
    // Solo precargar la sugerencia si es una categoría válida (ALTA/MEDIA/BAJA).
    // Si es un código del esquema anterior (ej. "A"), no es un valor válido de
    // categoria_final hoy: se deja vacío para forzar una elección informada.
    setApproveCategoria(CATEGORIA_INFO[item.categoria_asignada] ? item.categoria_asignada : '');
    setBajaAcknowledged(false);
  };

  const closeApproveModal = () => {
    setApproveModal({ open: false, patientId: null, categoriaSugerida: null, cfnr: null });
    setApproveCategoria('');
    setBajaAcknowledged(false);
  };

  const submitApprove = async () => {
    if (!approveCategoria) {
      toast.error('Debe elegir la categoría final del beneficiario.');
      return;
    }
    if (approveCategoria === 'BAJA' && !bajaAcknowledged) {
      toast.error('Marque la casilla de confirmación: BAJA significa que el beneficiario no tiene vulnerabilidad económica.');
      return;
    }
    try {
      setSubmittingId(approveModal.patientId);
      await reviewSocialEvaluation(approveModal.patientId, {
        decision: 'APROBADO',
        categoria_final: approveCategoria,
      });
      toast.success('Evaluación avalada. El beneficiario quedó exonerado del aporte.');
      closeApproveModal();
      await fetchEvaluations();
    } catch (error) {
      console.error(error);
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'No se pudo avalar la evaluación.');
    } finally {
      setSubmittingId(null);
    }
  };

  const openRejectModal = (patientId) => {
    setRejectModal({ open: true, patientId });
    setRejectReason('');
  };

  const closeRejectModal = () => {
    setRejectModal({ open: false, patientId: null });
    setRejectReason('');
  };

  const submitReject = async (decision) => {
    if (!rejectReason.trim()) {
      toast.error('Debe indicar el motivo del rechazo.');
      return;
    }
    try {
      setSubmittingId(rejectModal.patientId);
      await reviewSocialEvaluation(rejectModal.patientId, {
        decision,
        motivo: rejectReason.trim(),
      });
      toast.success(
        decision === 'RECHAZADO_FRAUDE'
          ? 'Evaluación rechazada por falsedad. El beneficiario quedó suspendido permanentemente.'
          : 'Evaluación rechazada. El beneficiario podrá volver a intentar en 6 meses.'
      );
      closeRejectModal();
      await fetchEvaluations();
    } catch (error) {
      console.error(error);
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'No se pudo rechazar la evaluación.');
    } finally {
      setSubmittingId(null);
    }
  };

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Revisión de Evaluación Socioeconómica</h1>
          <p className="text-sm text-gray-500">
            Avale o rechace las evaluaciones enviadas por los beneficiarios desde su autoregistro.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={estadoFilter}
            onChange={(event) => setEstadoFilter(event.target.value)}
            className="border rounded-lg px-3 py-2 text-sm bg-white"
          >
            <option value="">Todos</option>
            <option value="PENDIENTE">PENDIENTE</option>
            <option value="APROBADO">APROBADO</option>
            <option value="RECHAZADO">RECHAZADO</option>
            <option value="RECHAZADO_FRAUDE">RECHAZADO POR FALSEDAD</option>
          </select>
          <Button
            type="button"
            variant="secondary"
            className="border border-gray-200 text-gray-700"
            onClick={fetchEvaluations}
          >
            <RefreshCcw size={16} className="mr-2" />
            Recargar
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="p-10 text-center text-gray-500 font-semibold">Cargando evaluaciones...</div>
      ) : items.length === 0 ? (
        <div className="bg-white border border-gray-100 rounded-xl p-6 text-sm text-gray-500">
          No hay evaluaciones para el filtro seleccionado.
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <div key={item.id} className="bg-white border border-gray-100 rounded-xl shadow-sm overflow-hidden">
              <div className="p-4 flex flex-col md:flex-row md:items-start md:justify-between gap-3">
                <div>
                  <p className="font-semibold text-gray-800">
                    {item.patient_nombre || `Paciente #${item.patient_id}`} — CI {item.patient_ci || 'Sin registrar'}
                  </p>
                  <p className="text-sm text-gray-500 mt-1 flex items-center flex-wrap gap-1.5">
                    <span>Depto. {item.departamento} | Sugerida (sistema):</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${categoriaBadgeClass(item.categoria_asignada)}`}>
                      {categoriaLabel(item.categoria_asignada)}
                    </span>
                    <span>| CFNR Bs. {item.cfnr.toFixed(2)}</span>
                  </p>
                  {item.categoria_final && (
                    <p className="text-sm mt-1 flex items-center flex-wrap gap-1.5">
                      <span className="font-semibold text-gray-700">Categoría final:</span>
                      <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${categoriaBadgeClass(item.categoria_final)}`}>
                        {categoriaLabel(item.categoria_final)}
                      </span>
                      {item.categoria_final !== item.categoria_asignada && (
                        <span className="font-normal text-xs text-gray-500">(corregida por el evaluador)</span>
                      )}
                    </p>
                  )}
                  {item.estado_alerta === 'REVISIÓN MANUAL URGENTE' && (
                    <p className="text-xs text-red-600 mt-2 font-bold flex items-center gap-1">
                      <AlertTriangle size={14} /> {item.estado_alerta}
                    </p>
                  )}
                  {item.motivo_rechazo && (
                    <p className="text-xs text-red-600 mt-2">Motivo del rechazo: {item.motivo_rechazo}</p>
                  )}
                  <div className="flex items-center gap-3 mt-3">
                    <button
                      type="button"
                      onClick={() => toggleExpanded(item)}
                      className="text-sm text-blue-600 hover:text-blue-700 font-semibold inline-flex items-center gap-1"
                    >
                      {expandedId === item.id ? 'Ocultar detalle' : 'Ver detalle'}
                      {expandedId === item.id ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                    </button>
                    <Link
                      to={`/dashboard/pacientes/${item.patient_id}`}
                      className="text-sm text-vida-primary hover:underline"
                    >
                      Ver ficha del paciente
                    </Link>
                  </div>
                </div>

                <div className="flex flex-col items-end gap-2">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs font-bold px-2 py-1 rounded-full border ${ESTADO_STYLES[item.estado_revision] || 'bg-gray-100 text-gray-600'}`}>
                      {item.estado_revision}
                    </span>
                    <button
                      type="button"
                      className="px-4 py-2 rounded-xl font-bold text-sm bg-green-600 hover:bg-green-700 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                      disabled={submittingId === item.patient_id || item.estado_revision === 'APROBADO' || !item.entrevista_realizada}
                      title={!item.entrevista_realizada ? 'Debe registrar la entrevista virtual antes de emitir un veredicto.' : undefined}
                      onClick={() => openApproveModal(item)}
                    >
                      Aprobar y Exonerar
                    </button>
                    <button
                      type="button"
                      className="px-4 py-2 rounded-xl font-bold text-sm bg-red-600 hover:bg-red-700 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                      disabled={submittingId === item.patient_id || !item.entrevista_realizada}
                      title={!item.entrevista_realizada ? 'Debe registrar la entrevista virtual antes de emitir un veredicto.' : undefined}
                      onClick={() => openRejectModal(item.patient_id)}
                    >
                      Rechazar
                    </button>
                  </div>
                  {!item.entrevista_realizada && (
                    <p className="text-xs text-orange-600 font-semibold max-w-[220px] text-right">
                      Registre la entrevista virtual (ver detalle) para poder emitir un veredicto.
                    </p>
                  )}
                  {isSuperAdmin && (item.estado_revision === 'RECHAZADO' || item.estado_revision === 'RECHAZADO_FRAUDE') && (
                    <button
                      type="button"
                      onClick={() => handleReactivate(item.patient_id)}
                      disabled={reactivatingId === item.patient_id}
                      className="text-xs font-bold text-vida-primary hover:underline inline-flex items-center gap-1 disabled:opacity-50"
                    >
                      <UserCheck size={14} /> {reactivatingId === item.patient_id ? 'Reactivando...' : 'Reactivar beneficiario'}
                    </button>
                  )}
                  {isSuperAdmin && (
                    <button
                      type="button"
                      onClick={() => handleDebugDelete(item.patient_id)}
                      disabled={debugDeletingId === item.patient_id}
                      title="Herramienta temporal de QA: borra físicamente el registro."
                      className="text-xs font-bold px-3 py-1.5 rounded-lg bg-red-700 hover:bg-red-800 text-white inline-flex items-center gap-1 disabled:opacity-50"
                    >
                      <Trash2 size={14} /> {debugDeletingId === item.patient_id ? 'Eliminando...' : 'Eliminar Evaluación (Modo Prueba)'}
                    </button>
                  )}
                </div>
              </div>

              {expandedId === item.id && (
                <div className="border-t border-gray-100 bg-gray-50 p-4 space-y-6">
                  <div className={`rounded-xl p-4 border ${item.entrevista_realizada ? 'bg-green-50 border-green-200' : 'bg-orange-50 border-orange-200'}`}>
                    <h4 className="font-semibold text-gray-800 mb-2 flex items-center gap-2">
                      <Video size={16} /> Entrevista virtual con el beneficiario
                    </h4>
                    {item.entrevista_realizada ? (
                      <div className="text-sm text-green-700">
                        <p className="font-semibold flex items-center gap-1">
                          <CheckCircle size={14} /> Realizada
                          {item.entrevista_fecha ? ` el ${new Date(item.entrevista_fecha).toLocaleString()}` : ''}
                        </p>
                        {item.entrevista_notas && (
                          <p className="mt-1 text-gray-700">Notas: {item.entrevista_notas}</p>
                        )}
                      </div>
                    ) : (
                      <div className="space-y-2">
                        <p className="text-xs text-orange-700">
                          Reúnase con el beneficiario por videollamada u otro medio externo al sistema y
                          registre aquí un resumen antes de poder avalar o rechazar.
                        </p>
                        <textarea
                          value={interviewNotesById[item.patient_id] || ''}
                          onChange={(event) =>
                            setInterviewNotesById((prev) => ({ ...prev, [item.patient_id]: event.target.value }))
                          }
                          className="w-full border rounded-lg px-3 py-2 text-sm min-h-[80px] bg-white"
                          placeholder="Ej: Se confirmó la información declarada por videollamada el 12/08."
                        />
                        <button
                          type="button"
                          onClick={() => handleMarkInterview(item.patient_id)}
                          disabled={interviewSubmittingId === item.patient_id}
                          className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-bold disabled:opacity-50"
                        >
                          {interviewSubmittingId === item.patient_id ? 'Guardando...' : 'Marcar entrevista realizada'}
                        </button>
                      </div>
                    )}
                  </div>

                  <div className="grid md:grid-cols-2 gap-6">
                  <div className="space-y-2 text-sm text-gray-700">
                    <p><span className="font-semibold">Integrantes del hogar:</span> {item.integrantes_hogar}</p>
                    <p><span className="font-semibold">Dependientes:</span> {item.dependientes}</p>
                    <p><span className="font-semibold">Tipo de vivienda:</span> {item.tipo_vivienda}</p>
                    <p><span className="font-semibold">Monto alquiler:</span> Bs. {item.monto_alquiler.toFixed(2)}</p>
                    <p><span className="font-semibold">Tiene seguro:</span> {item.tiene_seguro ? `Sí (${item.tipo_seguro || 'no especificado'})` : 'No'}</p>
                    <p><span className="font-semibold">Condición laboral:</span> {item.condicion_laboral || 'No especificada'}</p>
                    <p><span className="font-semibold">Ingreso titular:</span> Bs. {item.ingreso_titular.toFixed(2)}</p>
                    <p><span className="font-semibold">Ingreso cónyuge:</span> Bs. {item.ingreso_conyuge.toFixed(2)}</p>
                    <p><span className="font-semibold">Servicios básicos:</span> Bs. {item.monto_servicios_basicos.toFixed(2)}</p>
                    <p>
                      <span className="font-semibold">Cuenta con:</span>{' '}
                      {[
                        item.tiene_agua && 'Agua',
                        item.tiene_luz && 'Luz',
                        item.tiene_gas_domiciliario && 'Gas domiciliario',
                        item.tiene_internet && 'Internet',
                      ].filter(Boolean).join(', ') || 'Ninguno declarado'}
                    </p>
                    <p><span className="font-semibold">Transporte y conectividad:</span> Bs. {item.monto_transporte.toFixed(2)}</p>
                    <p>
                      <span className="font-semibold">Deudas que comprometen ingresos (≥20%):</span>{' '}
                      {item.tiene_deudas_comprometen_ingresos ? `Sí (Bs. ${item.monto_deuda_mensual.toFixed(2)}/mes)` : 'No'}
                    </p>
                    <p><span className="font-semibold">Ingreso per cápita:</span> Bs. {item.ingreso_per_capita.toFixed(2)}</p>
                    <p><span className="font-semibold">Costo de vida estimado:</span> Bs. {item.costo_vida_estimado.toFixed(2)}</p>
                    <p><span className="font-semibold">CFNR (Capacidad Financiera Neta Residual):</span> Bs. {item.cfnr.toFixed(2)}</p>
                    <p>
                      <span className="font-semibold">Ayuda de otra institución:</span>{' '}
                      {item.recibe_ayuda_otra_institucion
                        ? `Sí (${item.nombre_institucion_ayuda || 'no especificada'})`
                        : 'No'}
                    </p>
                  </div>
                  <div>
                    <p className="font-semibold text-gray-700 mb-2">Evidencias</p>
                    <div className="grid grid-cols-2 gap-2">
                      {EVIDENCIAS.map(({ key, label }) => (
                        item[key] ? (
                          <a
                            key={key}
                            href={item[key]}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 font-medium px-3 py-2 bg-white border border-gray-100 rounded-lg"
                          >
                            {label} <ExternalLink size={14} />
                          </a>
                        ) : (
                          <span key={key} className="text-sm text-gray-400 px-3 py-2 bg-white border border-gray-100 rounded-lg">
                            {label}: no cargada
                          </span>
                        )
                      ))}
                    </div>
                  </div>
                  </div>

                  <div className="border-t border-gray-200 pt-4">
                    <h4 className="font-semibold text-gray-800 mb-2 flex items-center gap-2">
                      <History size={16} /> Historial de evaluaciones anteriores
                    </h4>
                    {loadingHistoryId === item.patient_id ? (
                      <p className="text-sm text-gray-500">Cargando historial...</p>
                    ) : (historyByPatientId[item.patient_id] || []).length === 0 ? (
                      <p className="text-sm text-gray-500">Sin veredictos anteriores registrados.</p>
                    ) : (
                      <div className="space-y-2">
                        {historyByPatientId[item.patient_id].map((h) => (
                          <div
                            key={h.id}
                            className={`rounded-lg p-3 text-sm border ${
                              h.accion === 'RECHAZADO_FRAUDE'
                                ? 'bg-red-100 border-red-300'
                                : h.accion === 'RECHAZADO'
                                  ? 'bg-red-50 border-red-200'
                                  : h.accion === 'APROBADO'
                                    ? 'bg-green-50 border-green-200'
                                    : 'bg-gray-50 border-gray-200'
                            }`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-bold flex items-center gap-1">
                                {h.accion === 'RECHAZADO_FRAUDE' && <ShieldAlert size={14} className="text-red-700" />}
                                {DECISION_LABELS[h.accion] || h.accion}
                              </span>
                              <span className="text-xs text-gray-500">
                                {new Date(h.created_at).toLocaleString()}
                              </span>
                            </div>
                            {h.payload?.motivo_rechazo && (
                              <p className="mt-1 text-gray-700">Motivo: {h.payload.motivo_rechazo}</p>
                            )}
                            {h.payload?.categoria_asignada && (
                              <p className="mt-1 text-xs text-gray-500">
                                Sugerida: {categoriaLabel(h.payload.categoria_asignada)}
                                {h.payload?.categoria_final && ` — Final asignada: ${categoriaLabel(h.payload.categoria_final)}`}
                                {' '}(CFNR Bs. {Number(h.payload.cfnr).toFixed(2)})
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {rejectModal.open && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6">
            <h3 className="text-lg font-bold text-gray-800 mb-2">Rechazar evaluación</h3>
            <p className="text-sm text-gray-500 mb-4">
              Registre el motivo. Elija el nivel de rechazo según corresponda.
            </p>
            <textarea
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              className="w-full border rounded-lg px-3 py-2 text-sm min-h-[110px]"
              placeholder="Ej: Las fotos de evidencia no son legibles."
            />

            <div className="mt-4 space-y-2">
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
                <p className="text-sm font-bold text-amber-800">Nivel 1 — Rechazo estándar</p>
                <p className="text-xs text-amber-700 mt-0.5">
                  No cumple los criterios (sí tiene capacidad de aportar). El beneficiario podrá
                  volver a intentarlo recién en 6 meses.
                </p>
                <button
                  type="button"
                  onClick={() => submitReject('RECHAZADO')}
                  disabled={submittingId === rejectModal.patientId}
                  className="mt-2 px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-sm font-bold disabled:opacity-50"
                >
                  Confirmar rechazo estándar
                </button>
              </div>

              <div className="rounded-lg border border-red-300 bg-red-50 p-3">
                <p className="text-sm font-bold text-red-800 flex items-center gap-1">
                  <ShieldAlert size={14} /> Nivel 2 — Rechazo por falsedad
                </p>
                <p className="text-xs text-red-700 mt-0.5">
                  Falsificación de documentos, ocultamiento de ingresos comprobados o
                  inconsistencias graves y malintencionadas. Suspende permanentemente al
                  beneficiario; solo un SUPER_ADMIN podrá reactivarlo.
                </p>
                <button
                  type="button"
                  onClick={() => submitReject('RECHAZADO_FRAUDE')}
                  disabled={submittingId === rejectModal.patientId}
                  className="mt-2 px-4 py-2 rounded-lg bg-red-700 hover:bg-red-800 text-white text-sm font-bold disabled:opacity-50"
                >
                  Confirmar rechazo por falsedad
                </button>
              </div>
            </div>

            <div className="mt-4 flex justify-end">
              <button
                type="button"
                onClick={closeRejectModal}
                className="px-4 py-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
              >
                Cancelar
              </button>
            </div>
          </div>
        </div>
      )}

      {approveModal.open && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4 overflow-y-auto">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-xl p-6 my-8">
            <h3 className="text-lg font-bold text-gray-800 mb-2 flex items-center gap-2">
              <CheckCircle size={18} className="text-green-600" /> Aprobar evaluación
            </h3>
            <p className="text-sm text-gray-500 mb-4">
              Orden fijo de <span className="font-semibold">mayor a menor</span> vulnerabilidad: ALTA → MEDIA → BAJA.
              El sistema sugiere una categoría según el CFNR declarado; usted la confirma o la corrige.
            </p>

            {CATEGORIA_INFO[approveModal.categoriaSugerida] ? (
              <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 mb-4 flex items-center justify-between gap-3">
                <p className="text-sm text-blue-800">
                  <span className="font-semibold">Sugerencia del sistema:</span> {approveModal.categoriaSugerida}
                </p>
                {approveModal.cfnr !== null && approveModal.cfnr !== undefined && (
                  <p className="text-sm text-blue-800 font-semibold">CFNR: Bs. {Number(approveModal.cfnr).toFixed(2)}</p>
                )}
              </div>
            ) : LEGACY_CATEGORIA_INFO[approveModal.categoriaSugerida] ? (
              <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 mb-4">
                <p className="text-sm text-blue-800">
                  <span className="font-semibold">
                    Sugerencia del sistema: "{approveModal.categoriaSugerida}" —{' '}
                    {LEGACY_CATEGORIA_INFO[approveModal.categoriaSugerida].label}.
                  </span>{' '}
                  {LEGACY_CATEGORIA_INFO[approveModal.categoriaSugerida].descripcion} Confírmela o corríjala
                  usando el CFNR
                  {approveModal.cfnr !== null && approveModal.cfnr !== undefined
                    ? ` (Bs. ${Number(approveModal.cfnr).toFixed(2)})`
                    : ''}{' '}
                  y su criterio de la entrevista.
                </p>
              </div>
            ) : (
              <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 mb-4">
                <p className="text-sm text-amber-800">
                  <AlertTriangle size={14} className="inline mr-1 -mt-0.5" />
                  <span className="font-semibold">Sin sugerencia válida</span> (código guardado: "
                  {approveModal.categoriaSugerida || 'vacío'}"). Elija la categoría final usando el CFNR
                  {approveModal.cfnr !== null && approveModal.cfnr !== undefined
                    ? ` (Bs. ${Number(approveModal.cfnr).toFixed(2)})`
                    : ''}{' '}
                  y su criterio de la entrevista.
                </p>
              </div>
            )}

            <label className="block text-sm font-semibold text-gray-700 mb-2">Categoría final *</label>
            <div className="space-y-2 mb-4">
              {CATEGORIA_ORDEN.map((cat) => {
                const info = CATEGORIA_INFO[cat];
                const isSelected = approveCategoria === cat;
                return (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => {
                      setApproveCategoria(cat);
                      setBajaAcknowledged(false);
                    }}
                    className={`w-full text-left px-4 py-3 rounded-lg border-2 transition-colors flex items-center justify-between gap-3 ${
                      isSelected ? info.selected : `bg-white ${info.idle}`
                    }`}
                  >
                    <div>
                      <span className="font-bold">{cat}</span>
                      <span className={`ml-2 text-sm ${isSelected ? 'text-white/90' : 'text-gray-500'}`}>
                        {info.subtitle}
                      </span>
                      <p className={`text-xs mt-0.5 ${isSelected ? 'text-white/80' : 'text-gray-400'}`}>
                        {info.descripcion}
                      </p>
                    </div>
                    <span
                      className={`text-xs font-bold px-2 py-1 rounded-full border whitespace-nowrap ${
                        isSelected ? 'border-white/50 text-white' : info.badge
                      }`}
                    >
                      {info.rango}
                    </span>
                  </button>
                );
              })}
            </div>

            {approveCategoria === 'BAJA' && (
              <label className="flex items-start gap-2 p-3 rounded-lg border-2 border-amber-300 bg-amber-50 mb-4 cursor-pointer">
                <input
                  type="checkbox"
                  checked={bajaAcknowledged}
                  onChange={(e) => setBajaAcknowledged(e.target.checked)}
                  className="mt-0.5 w-4 h-4 accent-amber-600"
                />
                <span className="text-sm text-amber-800">
                  Entiendo que <span className="font-bold">BAJA</span> significa que el beneficiario está en una
                  situación económica acomodada, <span className="font-bold">sin vulnerabilidad</span>, y que
                  normalmente no correspondería exonerarlo del aporte solidario. Confirmo que igual corresponde
                  aprobar en este caso.
                </span>
              </label>
            )}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={closeApproveModal}
                className="px-4 py-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={submitApprove}
                disabled={submittingId === approveModal.patientId || (approveCategoria === 'BAJA' && !bajaAcknowledged)}
                className="px-4 py-2 rounded-lg bg-green-600 hover:bg-green-700 text-white font-bold disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submittingId === approveModal.patientId ? 'Guardando...' : 'Confirmar aprobación'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
