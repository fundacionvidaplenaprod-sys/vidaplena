/**
 * SocialEvaluationSelfPage.jsx
 * Formulario Multi-Step (6 pasos) de autoservicio para que el propio
 * beneficiario registre su Evaluación Socioeconómica durante el
 * autoregistro, subiendo evidencias progresivamente a Firebase Storage.
 *
 * Acceso: cualquier usuario autenticado con rol PACIENTE (JWT vía axios,
 * igual que MyDocumentsPage.jsx).
 */
import { useEffect, useRef, useState } from 'react';
import { useForm, Controller } from 'react-hook-form';
import toast from 'react-hot-toast';
import { useNavigate } from 'react-router-dom';
import {
  submitMySocialEvaluation,
  uploadMyEvaluationDocument,
  getMyEvaluationEligibility,
} from '../../api/evaluations';

// ─────────────────────────────────────────────────────────────────────────────
//  CONSTANTES DE DATOS
// ─────────────────────────────────────────────────────────────────────────────

const DEPARTAMENTOS_BOLIVIA = [
  'Beni', 'Chuquisaca', 'Cochabamba', 'La Paz', 'Oruro',
  'Pando', 'Potosí', 'Santa Cruz', 'Tarija',
];

const TIPOS_SEGURO = [
  'Caja Nacional de Salud (CNS)',
  'Sistema Único de Salud (SUS)',
  'Seguro Privado',
  'Otra Caja',
];

const TIPOS_VIVIENDA = ['Propia', 'Alquilada', 'Familiar / Prestada', 'Anticrético', 'Otro'];

const CONDICION_LABORAL = [
  'Dependiente (relación de dependencia)',
  'Independiente / Cuenta propia',
  'Jubilado / Rentista',
  'Desempleado',
  'Estudiante',
  'Ama de casa (sin ingreso propio)',
];

const PASOS = [
  { numero: 1, titulo: 'Declaración de Veracidad' },
  { numero: 2, titulo: 'Datos del Hogar' },
  { numero: 3, titulo: 'Salud y Seguro' },
  { numero: 4, titulo: 'Ingresos' },
  { numero: 5, titulo: 'Vivienda y Evidencias' },
  { numero: 6, titulo: 'Confirmación y Envío' },
];

const MAX_FILE_SIZE_MB = 5;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

// ─────────────────────────────────────────────────────────────────────────────
//  COMPONENTES AUXILIARES
// ─────────────────────────────────────────────────────────────────────────────

/** Barra de progreso superior con indicadores de paso */
function ProgressBar({ pasoActual }) {
  return (
    <div className="mb-8">
      <div className="hidden md:flex justify-between text-xs font-semibold text-gray-400 mb-2 px-1">
        {PASOS.map((p) => (
          <span key={p.numero} className={pasoActual >= p.numero ? 'text-blue-700' : ''}>
            {p.numero}. {p.titulo}
          </span>
        ))}
      </div>
      <div className="flex gap-1.5">
        {PASOS.map((p) => (
          <div
            key={p.numero}
            className={`h-2 flex-1 rounded-full transition-all duration-500 ${
              pasoActual >= p.numero ? 'bg-blue-600' : 'bg-gray-200'
            }`}
          />
        ))}
      </div>
      <p className="md:hidden mt-2 text-sm font-semibold text-blue-700 text-center">
        Paso {pasoActual} de {PASOS.length}: {PASOS[pasoActual - 1]?.titulo}
      </p>
    </div>
  );
}

/**
 * Input de archivo que sube de inmediato a Firebase Storage (vía `onUpload`)
 * en cuanto el usuario lo selecciona, mostrando el progreso de la subida.
 */
function FileInput({ label, accept, onUpload }) {
  const [status, setStatus] = useState('idle'); // idle | uploading | done | error
  const [fileName, setFileName] = useState('');
  const inputRef = useRef(null);

  const handleChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > MAX_FILE_SIZE_BYTES) {
      toast.error(`"${file.name}" supera el límite de ${MAX_FILE_SIZE_MB} MB.`);
      inputRef.current.value = '';
      return;
    }

    setFileName(file.name);
    setStatus('uploading');
    try {
      await onUpload(file);
      setStatus('done');
    } catch (error) {
      setStatus('error');
      setFileName('');
      inputRef.current.value = '';
      toast.error(error?.response?.data?.detail || 'No se pudo subir el archivo. Intenta nuevamente.');
    }
  };

  return (
    <div>
      <label className="block text-sm font-semibold text-gray-700 mb-1">{label}</label>
      <label
        className={`flex items-center gap-3 p-3 border-2 border-dashed rounded-xl cursor-pointer
          transition-colors hover:border-blue-400 hover:bg-blue-50
          ${status === 'error' ? 'border-red-400 bg-red-50' : status === 'done' ? 'border-green-400 bg-green-50' : 'border-gray-300 bg-gray-50'}`}
      >
        <svg className="w-5 h-5 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
        </svg>
        <span className="text-sm text-gray-500 truncate flex-1">
          {fileName || 'Seleccionar archivo (JPG, PNG, PDF — máx. 5 MB)'}
        </span>
        {status === 'uploading' && <span className="text-xs font-bold text-blue-600">Subiendo...</span>}
        {status === 'done' && <span className="text-xs font-bold text-green-600">✓ Subido</span>}
        <input
          ref={inputRef}
          type="file"
          accept={accept || 'image/*,application/pdf'}
          className="hidden"
          onChange={handleChange}
        />
      </label>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
//  COMPONENTE PRINCIPAL
// ─────────────────────────────────────────────────────────────────────────────

export default function SocialEvaluationSelfPage() {
  const navigate = useNavigate();

  const [checkingEligibility, setCheckingEligibility] = useState(true);
  const [eligibility, setEligibility] = useState(null);

  useEffect(() => {
    let cancelado = false;
    (async () => {
      try {
        const data = await getMyEvaluationEligibility();
        if (!cancelado) setEligibility(data);
      } catch (error) {
        // Si falla la verificación (ej. red), no bloqueamos al beneficiario
        // por un problema técnico ajeno a su elegibilidad.
        if (!cancelado) setEligibility({ puede_evaluar: true });
      } finally {
        if (!cancelado) setCheckingEligibility(false);
      }
    })();
    return () => { cancelado = true; };
  }, []);

  const [pasoActual, setPasoActual] = useState(1);
  const [submitting, setSubmitting] = useState(false);

  // URLs de Firebase ya subidas, según van avanzando los pasos.
  const [urls, setUrls] = useState({
    foto_ci_url: null,
    foto_fachada_url: null,
    foto_sala_url: null,
    foto_dormitorio_url: null,
  });

  const {
    register,
    handleSubmit,
    watch,
    control,
    trigger,
    formState: { errors },
  } = useForm({
    defaultValues: {
      declaracion_jurada: false,
      departamento: '',
      integrantes_hogar: 1,
      dependientes: 0,
      tiene_seguro: 'no',
      tipo_seguro: '',
      condicion_laboral: '',
      recibe_ayuda_otra_institucion: 'no',
      nombre_institucion_ayuda: '',
      ingreso_titular: 0,
      ingreso_conyuge: 0,
      monto_servicios_basicos: 0,
      monto_transporte: 0,
      tiene_deudas_comprometen_ingresos: 'no',
      monto_deuda_mensual: 0,
      tipo_vivienda: '',
      monto_alquiler: 0,
    },
  });

  const uploadDoc = async (docType, file) => {
    const { url } = await uploadMyEvaluationDocument(docType, file);
    setUrls((prev) => ({ ...prev, [`foto_${docType}_url`]: url }));
    return url;
  };

  // ── Cálculo en tiempo real de la Capacidad Financiera Neta Residual (CFNR) ──
  // Mismo modelo que el backend (_build_categorization en evaluations.py):
  // CFNR = Ingresos Totales - (Canasta Básica + Vivienda/Servicios/Salud + Transporte + Deudas)
  const ingreso_titular = parseFloat(watch('ingreso_titular') || 0);
  const ingreso_conyuge = parseFloat(watch('ingreso_conyuge') || 0);
  const integrantes_hogar = Math.max(1, parseInt(watch('integrantes_hogar') || 1, 10));
  const dependientes_watch = Math.max(0, parseInt(watch('dependientes') || 0, 10));
  const tiene_seguro = watch('tiene_seguro') === 'si';
  const tipo_vivienda = watch('tipo_vivienda');
  const monto_alquiler_watch = parseFloat(watch('monto_alquiler') || 0);
  const monto_servicios_watch = parseFloat(watch('monto_servicios_basicos') || 0);
  const monto_transporte_watch = parseFloat(watch('monto_transporte') || 0);
  const tiene_deudas = watch('tiene_deudas_comprometen_ingresos') === 'si';
  const monto_deuda_watch = tiene_deudas ? parseFloat(watch('monto_deuda_mensual') || 0) : 0;

  const ingreso_total = ingreso_titular + ingreso_conyuge;
  const ingreso_per_capita = ingreso_total / integrantes_hogar;

  const canasta_familiar = integrantes_hogar === 1
    ? 1000
    : 1000 + 800 + 700 * (integrantes_hogar - 2);
  const costo_vivienda = (tipo_vivienda || '').trim().toLowerCase() === 'propia'
    ? 225
    : monto_alquiler_watch;
  const costo_salud_educacion = dependientes_watch * 275;
  const costo_vida_estimado =
    canasta_familiar + costo_vivienda + monto_servicios_watch + costo_salud_educacion + monto_transporte_watch + monto_deuda_watch;
  const cfnr = ingreso_total - costo_vida_estimado;

  const categoriaEstimada = (() => {
    if (cfnr <= 0) return { label: 'Vulnerabilidad Económica Alta', color: 'text-red-600 bg-red-50' };
    if (cfnr <= 1500) return { label: 'Vulnerabilidad Económica Media', color: 'text-orange-600 bg-orange-50' };
    return { label: 'Vulnerabilidad Económica Baja / Nula', color: 'text-gray-600 bg-gray-100' };
  })();

  // ── Navegación entre pasos ───────────────────────────────────────────────
  const camposValidadosPorPaso = {
    1: ['declaracion_jurada', 'habeas_data_accepted'],
    2: ['departamento', 'integrantes_hogar', 'dependientes'],
    3: ['tiene_seguro', 'recibe_ayuda_otra_institucion', 'nombre_institucion_ayuda'],
    4: [
      'ingreso_titular', 'ingreso_conyuge', 'monto_servicios_basicos', 'monto_transporte',
      'tiene_deudas_comprometen_ingresos', 'monto_deuda_mensual',
    ],
    5: ['tipo_vivienda', 'imagen_consent_accepted'],
    6: [],
  };

  const irAlSiguiente = async () => {
    const campos = camposValidadosPorPaso[pasoActual] || [];
    const valido = await trigger(campos);
    if (!valido) return;

    if (pasoActual === 1) {
      if (!watch('declaracion_jurada') || !watch('habeas_data_accepted')) {
        toast.error('Debe aceptar ambas declaraciones para continuar.');
        return;
      }
      if (!urls.foto_ci_url) {
        toast.error('Suba la fotografía de su Carnet de Identidad antes de continuar.');
        return;
      }
    }
    if (pasoActual === 5 && (!urls.foto_fachada_url || !urls.foto_sala_url || !urls.foto_dormitorio_url)) {
      toast.error('Suba las 3 fotos de evidencia del domicilio antes de continuar.');
      return;
    }

    setPasoActual((prev) => Math.min(prev + 1, PASOS.length));
  };

  const irAlAnterior = () => setPasoActual((prev) => Math.max(prev - 1, 1));

  // ── Envío del formulario ─────────────────────────────────────────────────
  const onSubmit = async (formData) => {
    setSubmitting(true);
    const loadingToast = toast.loading('Enviando evaluación...');

    try {
      const payload = {
        departamento: formData.departamento,
        integrantes_hogar: parseInt(formData.integrantes_hogar, 10),
        dependientes: parseInt(formData.dependientes, 10),
        tipo_vivienda: formData.tipo_vivienda,
        monto_alquiler: parseFloat(formData.monto_alquiler || 0),
        tiene_seguro: formData.tiene_seguro === 'si',
        tipo_seguro: formData.tiene_seguro === 'si' ? formData.tipo_seguro : null,
        condicion_laboral: formData.condicion_laboral || null,
        recibe_ayuda_otra_institucion: formData.recibe_ayuda_otra_institucion === 'si',
        nombre_institucion_ayuda:
          formData.recibe_ayuda_otra_institucion === 'si' ? formData.nombre_institucion_ayuda : null,
        ingreso_titular: parseFloat(formData.ingreso_titular || 0),
        ingreso_conyuge: parseFloat(formData.ingreso_conyuge || 0),
        monto_servicios_basicos: parseFloat(formData.monto_servicios_basicos || 0),
        monto_transporte: parseFloat(formData.monto_transporte || 0),
        tiene_deudas_comprometen_ingresos: formData.tiene_deudas_comprometen_ingresos === 'si',
        monto_deuda_mensual:
          formData.tiene_deudas_comprometen_ingresos === 'si' ? parseFloat(formData.monto_deuda_mensual || 0) : 0,
        habeas_data_accepted: formData.habeas_data_accepted === true,
        imagen_consent_accepted: formData.imagen_consent_accepted === true,
        foto_ci_url: urls.foto_ci_url,
        foto_fachada_url: urls.foto_fachada_url,
        foto_sala_url: urls.foto_sala_url,
        foto_dormitorio_url: urls.foto_dormitorio_url,
      };

      await submitMySocialEvaluation(payload);
      toast.success('✅ Evaluación socioeconómica enviada. Quedó pendiente de revisión.', { id: loadingToast });
      navigate('/mi-portal', { replace: true });
    } catch (error) {
      const msg =
        error?.response?.data?.detail ||
        'Error al registrar la evaluación. Verifique los datos e intente nuevamente.';
      toast.error(msg, { id: loadingToast });
    } finally {
      setSubmitting(false);
    }
  };

  // ─────────────────────────────────────────────────────────────────────────
  //  RENDER DE PASOS
  // ─────────────────────────────────────────────────────────────────────────

  const renderPaso = () => {
    switch (pasoActual) {
      case 1:
        return (
          <div className="space-y-6">
            <div className="bg-blue-50 border border-blue-200 rounded-2xl p-6">
              <h3 className="font-bold text-blue-900 text-lg mb-3 flex items-center gap-2">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                Declaración de Veracidad de la Información
              </h3>
              <div className="text-sm text-blue-800 space-y-2 leading-relaxed">
                <p>
                  Declaro conscientemente que la información proporcionada en este formulario
                  es <strong>correcta, completa y verdadera</strong>.
                </p>
                <p>
                  Entiendo que la Fundación V.I.D.A. Plena podrá validar los datos presentados
                  y que la falsificación de información es una falta regulada por el{' '}
                  <strong>Art. 169 del Código Penal del Estado Plurinacional de Bolivia</strong>.
                </p>
                <p>
                  Acepto que cualquier omisión o dato no verídico podrá ser motivo para la
                  suspensión de los beneficios recibidos y la aplicación de las acciones que
                  determina el Estado Plurinacional de Bolivia.
                </p>
              </div>
            </div>

            <Controller
              name="declaracion_jurada"
              control={control}
              rules={{ validate: (v) => v === true || 'Debe aceptar la declaración para continuar.' }}
              render={({ field }) => (
                <label className={`flex items-start gap-3 p-4 rounded-xl border-2 cursor-pointer transition-colors
                  ${field.value ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-blue-300'}`}>
                  <input
                    type="checkbox"
                    checked={field.value}
                    onChange={(e) => field.onChange(e.target.checked)}
                    className="mt-0.5 w-5 h-5 rounded accent-blue-600 flex-shrink-0"
                  />
                  <span className="text-sm font-semibold text-gray-700">
                    Acepto la declaración de veracidad anterior y confirmo que toda la información
                    que proporcionaré es correcta, completa y verdadera. Art. 169 C.P. Bolivia.
                  </span>
                </label>
              )}
            />
            {errors.declaracion_jurada && (
              <p className="text-sm text-red-600">{errors.declaracion_jurada.message}</p>
            )}

            <Controller
              name="habeas_data_accepted"
              control={control}
              rules={{ validate: (v) => v === true || 'El consentimiento de Habeas Data es obligatorio.' }}
              render={({ field }) => (
                <label className={`flex items-start gap-3 p-4 rounded-xl border-2 cursor-pointer transition-colors mt-4
                  ${field.value ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-blue-300'}`}>
                  <input
                    type="checkbox"
                    checked={field.value}
                    onChange={(e) => field.onChange(e.target.checked)}
                    className="mt-0.5 w-5 h-5 rounded accent-blue-600 flex-shrink-0"
                  />
                  <span className="text-sm font-semibold text-gray-700">
                    Autorizo a la Fundación V.I.D.A. Plena a recopilar, procesar y verificar los datos personales,
                    de salud, laborales y de vivienda aquí declarados, de conformidad con el Art. 130 de la C.P.E.
                    y la Ley 164 de Telecomunicaciones y Tecnologías de Información.
                  </span>
                </label>
              )}
            />
            {errors.habeas_data_accepted && (
              <p className="text-sm text-red-600">{errors.habeas_data_accepted.message}</p>
            )}

            <div className="mt-4">
              <FileInput
                label="📎 Fotografía / Escaneo de su Carnet de Identidad (C.I.) — anverso y reverso en un solo documento"
                accept="image/*,application/pdf"
                onUpload={(file) => uploadDoc('ci', file)}
              />
              <p className="mt-1 text-xs text-gray-400">
                Ambos lados del CI en una sola imagen o PDF. Máximo 5 MB. JPG, PNG o PDF.
              </p>
            </div>
          </div>
        );

      case 2:
        return (
          <div className="space-y-6">
            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-1">
                Departamento de residencia *
              </label>
              <select
                {...register('departamento', { required: 'Seleccione un departamento.' })}
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500"
              >
                <option value="">— Seleccionar departamento —</option>
                {DEPARTAMENTOS_BOLIVIA.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
              {errors.departamento && (
                <p className="mt-1 text-xs text-red-600">{errors.departamento.message}</p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-1">
                  N° de integrantes del hogar *
                </label>
                <input
                  type="number"
                  min="1"
                  {...register('integrantes_hogar', {
                    required: 'Campo obligatorio.',
                    min: { value: 1, message: 'Mínimo 1 integrante.' },
                  })}
                  className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500"
                />
                {errors.integrantes_hogar && (
                  <p className="mt-1 text-xs text-red-600">{errors.integrantes_hogar.message}</p>
                )}
                <p className="mt-1 text-xs text-gray-400">Todas las personas que viven en el hogar.</p>
              </div>

              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-1">
                  N° de dependientes
                </label>
                <input
                  type="number"
                  min="0"
                  {...register('dependientes', { min: { value: 0, message: 'No puede ser negativo.' } })}
                  className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500"
                />
                {errors.dependientes && (
                  <p className="mt-1 text-xs text-red-600">{errors.dependientes.message}</p>
                )}
                <p className="mt-1 text-xs text-gray-400">Menores de 18 o adultos sin ingresos propios.</p>
              </div>
            </div>
          </div>
        );

      case 3:
        return (
          <div className="space-y-6">
            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-3">
                ¿Cuenta con algún seguro médico activo? *
              </label>
              <div className="flex gap-4">
                {[
                  { value: 'si', label: '✅ Sí, tengo seguro' },
                  { value: 'no', label: '❌ No tengo seguro' },
                ].map(({ value, label }) => (
                  <label
                    key={value}
                    className={`flex-1 flex items-center gap-3 p-4 rounded-xl border-2 cursor-pointer transition-colors
                      ${watch('tiene_seguro') === value
                        ? 'border-blue-500 bg-blue-50'
                        : 'border-gray-200 hover:border-blue-300'}`}
                  >
                    <input
                      type="radio"
                      value={value}
                      {...register('tiene_seguro', { required: true })}
                      className="accent-blue-600"
                    />
                    <span className="text-sm font-semibold text-gray-700">{label}</span>
                  </label>
                ))}
              </div>
            </div>

            {watch('tiene_seguro') === 'si' && (
              <div className="animate-fade-in">
                <label className="block text-sm font-semibold text-gray-700 mb-1">
                  Tipo de seguro médico *
                </label>
                <select
                  {...register('tipo_seguro', {
                    validate: (v) =>
                      watch('tiene_seguro') !== 'si' || !!v || 'Seleccione el tipo de seguro.',
                  })}
                  className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500"
                >
                  <option value="">— Seleccionar tipo de seguro —</option>
                  {TIPOS_SEGURO.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
                {errors.tipo_seguro && (
                  <p className="mt-1 text-xs text-red-600">{errors.tipo_seguro.message}</p>
                )}
              </div>
            )}

            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-1">
                Mi condición laboral
              </label>
              <select
                {...register('condicion_laboral')}
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500"
              >
                <option value="">— Seleccionar condición —</option>
                {CONDICION_LABORAL.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-3">
                ¿Usted recibe ayuda para su diabetes de otra institución (Fundación, ONG, Asociación, etc.)? *
              </label>
              <div className="flex gap-4">
                {[
                  { value: 'si', label: '✅ Sí' },
                  { value: 'no', label: '❌ No' },
                ].map(({ value, label }) => (
                  <label
                    key={value}
                    className={`flex-1 flex items-center gap-3 p-4 rounded-xl border-2 cursor-pointer transition-colors
                      ${watch('recibe_ayuda_otra_institucion') === value
                        ? 'border-blue-500 bg-blue-50'
                        : 'border-gray-200 hover:border-blue-300'}`}
                  >
                    <input
                      type="radio"
                      value={value}
                      {...register('recibe_ayuda_otra_institucion', { required: true })}
                      className="accent-blue-600"
                    />
                    <span className="text-sm font-semibold text-gray-700">{label}</span>
                  </label>
                ))}
              </div>

              {watch('recibe_ayuda_otra_institucion') === 'si' && (
                <div className="animate-fade-in mt-3">
                  <label className="block text-sm font-semibold text-gray-700 mb-1">
                    ¿Cuál institución? *
                  </label>
                  <input
                    type="text"
                    {...register('nombre_institucion_ayuda', {
                      validate: (v) =>
                        watch('recibe_ayuda_otra_institucion') !== 'si' || !!(v || '').trim() ||
                        'Indique el nombre de la institución.',
                    })}
                    className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500"
                    placeholder="Ej: Fundación XYZ"
                  />
                  {errors.nombre_institucion_ayuda && (
                    <p className="mt-1 text-xs text-red-600">{errors.nombre_institucion_ayuda.message}</p>
                  )}
                </div>
              )}
            </div>
          </div>
        );

      case 4:
        return (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-1">
                  Mi ingreso mensual (Bs.) *
                </label>
                <div className="relative">
                  <span className="absolute left-4 top-3 text-gray-400 text-sm font-bold">Bs.</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    {...register('ingreso_titular', {
                      required: 'Campo obligatorio.',
                      min: { value: 0, message: 'No puede ser negativo.' },
                    })}
                    className="w-full pl-12 pr-4 py-3 border-2 border-gray-200 rounded-xl text-sm focus:outline-none focus:border-blue-500"
                    placeholder="0.00"
                  />
                </div>
                {errors.ingreso_titular && (
                  <p className="mt-1 text-xs text-red-600">{errors.ingreso_titular.message}</p>
                )}
              </div>

              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-1">
                  Ingreso mensual del cónyuge (Bs.)
                </label>
                <div className="relative">
                  <span className="absolute left-4 top-3 text-gray-400 text-sm font-bold">Bs.</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    {...register('ingreso_conyuge', {
                      min: { value: 0, message: 'No puede ser negativo.' },
                    })}
                    className="w-full pl-12 pr-4 py-3 border-2 border-gray-200 rounded-xl text-sm focus:outline-none focus:border-blue-500"
                    placeholder="0.00"
                  />
                </div>
                {errors.ingreso_conyuge && (
                  <p className="mt-1 text-xs text-red-600">{errors.ingreso_conyuge.message}</p>
                )}
                <p className="mt-1 text-xs text-gray-400">Si no aplica, dejar en 0.</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-1">
                  Servicios básicos: agua, luz, gas (Bs./mes) *
                </label>
                <div className="relative">
                  <span className="absolute left-4 top-3 text-gray-400 text-sm font-bold">Bs.</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    {...register('monto_servicios_basicos', {
                      required: 'Campo obligatorio.',
                      min: { value: 0, message: 'No puede ser negativo.' },
                    })}
                    className="w-full pl-12 pr-4 py-3 border-2 border-gray-200 rounded-xl text-sm focus:outline-none focus:border-blue-500"
                    placeholder="0.00"
                  />
                </div>
                {errors.monto_servicios_basicos && (
                  <p className="mt-1 text-xs text-red-600">{errors.monto_servicios_basicos.message}</p>
                )}
              </div>

              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-1">
                  Transporte y conectividad: pasajes, internet, celular (Bs./mes) *
                </label>
                <div className="relative">
                  <span className="absolute left-4 top-3 text-gray-400 text-sm font-bold">Bs.</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    {...register('monto_transporte', {
                      required: 'Campo obligatorio.',
                      min: { value: 0, message: 'No puede ser negativo.' },
                    })}
                    className="w-full pl-12 pr-4 py-3 border-2 border-gray-200 rounded-xl text-sm focus:outline-none focus:border-blue-500"
                    placeholder="0.00"
                  />
                </div>
                {errors.monto_transporte && (
                  <p className="mt-1 text-xs text-red-600">{errors.monto_transporte.message}</p>
                )}
              </div>
            </div>

            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-3">
                ¿Usted tiene deudas que comprometan sus ingresos mensuales en un 20% o más? *
              </label>
              <div className="flex gap-4">
                {[
                  { value: 'si', label: '✅ Sí' },
                  { value: 'no', label: '❌ No' },
                ].map(({ value, label }) => (
                  <label
                    key={value}
                    className={`flex-1 flex items-center gap-3 p-4 rounded-xl border-2 cursor-pointer transition-colors
                      ${watch('tiene_deudas_comprometen_ingresos') === value
                        ? 'border-blue-500 bg-blue-50'
                        : 'border-gray-200 hover:border-blue-300'}`}
                  >
                    <input
                      type="radio"
                      value={value}
                      {...register('tiene_deudas_comprometen_ingresos', { required: true })}
                      className="accent-blue-600"
                    />
                    <span className="text-sm font-semibold text-gray-700">{label}</span>
                  </label>
                ))}
              </div>

              {tiene_deudas && (
                <div className="animate-fade-in mt-3">
                  <label className="block text-sm font-semibold text-gray-700 mb-1">
                    Cuota mensual total de sus deudas (Bs.) *
                  </label>
                  <div className="relative">
                    <span className="absolute left-4 top-3 text-gray-400 text-sm font-bold">Bs.</span>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      {...register('monto_deuda_mensual', {
                        validate: (v) =>
                          watch('tiene_deudas_comprometen_ingresos') !== 'si' ||
                          (Number(v) > 0) || 'Indique el monto mensual de sus deudas.',
                      })}
                      className="w-full pl-12 pr-4 py-3 border-2 border-gray-200 rounded-xl text-sm focus:outline-none focus:border-blue-500"
                      placeholder="0.00"
                    />
                  </div>
                  {errors.monto_deuda_mensual && (
                    <p className="mt-1 text-xs text-red-600">{errors.monto_deuda_mensual.message}</p>
                  )}
                </div>
              )}
            </div>

            <div className="bg-gradient-to-br from-blue-700 to-indigo-800 rounded-2xl p-6 text-white shadow-lg">
              <h4 className="font-bold text-lg mb-4 flex items-center gap-2">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 11h.01M12 11h.01M15 11h.01M4 19h16a2 2 0 002-2V7a2 2 0 00-2-2H4a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
                Cálculo automático de ingresos
              </h4>
              <div className="grid grid-cols-3 gap-4 text-center">
                <div className="bg-white/10 rounded-xl p-3">
                  <p className="text-xs text-white/70 mb-1">Ingreso Total</p>
                  <p className="text-2xl font-bold">Bs. {ingreso_total.toFixed(2)}</p>
                </div>
                <div className="bg-white/10 rounded-xl p-3">
                  <p className="text-xs text-white/70 mb-1">Integrantes</p>
                  <p className="text-2xl font-bold">{integrantes_hogar}</p>
                </div>
                <div className="bg-white/10 rounded-xl p-3">
                  <p className="text-xs text-white/70 mb-1">Per Cápita/mes</p>
                  <p className="text-2xl font-bold">Bs. {ingreso_per_capita.toFixed(2)}</p>
                </div>
              </div>
              <p className="text-xs text-white/50 mt-2 text-center">
                * Su categoría de vulnerabilidad se calcula al final, considerando también su
                situación de vivienda (Paso 5).
              </p>
            </div>
          </div>
        );

      case 5:
        return (
          <div className="space-y-6">
            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-1">
                Tipo de vivienda *
              </label>
              <select
                {...register('tipo_vivienda', { required: 'Seleccione el tipo de vivienda.' })}
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500"
              >
                <option value="">— Seleccionar tipo —</option>
                {TIPOS_VIVIENDA.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              {errors.tipo_vivienda && (
                <p className="mt-1 text-xs text-red-600">{errors.tipo_vivienda.message}</p>
              )}
            </div>

            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-1">
                Monto mensual de alquiler / anticrético (Bs.)
              </label>
              <div className="relative">
                <span className="absolute left-4 top-3 text-gray-400 text-sm font-bold">Bs.</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  disabled={tipo_vivienda === 'Propia'}
                  {...register('monto_alquiler', { min: { value: 0, message: 'No puede ser negativo.' } })}
                  className={`w-full pl-12 pr-4 py-3 border-2 rounded-xl text-sm focus:outline-none focus:border-blue-500
                    ${tipo_vivienda === 'Propia' ? 'bg-gray-100 border-gray-100 text-gray-400 cursor-not-allowed' : 'border-gray-200'}`}
                  placeholder="0.00"
                />
              </div>
              {tipo_vivienda === 'Propia' && (
                <p className="mt-1 text-xs text-gray-400">
                  Este campo se deshabilita automáticamente cuando la vivienda es propia.
                </p>
              )}
            </div>

            <div className="border-t border-gray-100 pt-5">
              <h4 className="font-bold text-gray-700 mb-4 flex items-center gap-2">
                <svg className="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                Fotos de evidencia de mi domicilio
              </h4>
              <p className="text-xs text-gray-400 mb-4">
                Las fotos son confidenciales y se usan exclusivamente para validar las condiciones
                socioeconómicas declaradas.
              </p>
              <div className="space-y-4">
                <FileInput
                  label="📸 Foto de la fachada exterior de mi domicilio"
                  accept="image/*"
                  onUpload={(file) => uploadDoc('fachada', file)}
                />
                <FileInput
                  label="🛋️ Foto de la sala / living principal"
                  accept="image/*"
                  onUpload={(file) => uploadDoc('sala', file)}
                />
                <FileInput
                  label="🛏️ Foto del dormitorio principal"
                  accept="image/*"
                  onUpload={(file) => uploadDoc('dormitorio', file)}
                />
              </div>

              <Controller
                name="imagen_consent_accepted"
                control={control}
                rules={{ validate: (v) => v === true || 'El consentimiento de uso de imágenes es obligatorio.' }}
                render={({ field }) => (
                  <label className={`flex items-start gap-3 p-4 rounded-xl border-2 cursor-pointer transition-colors mt-6
                    ${field.value ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-blue-300'}`}>
                    <input
                      type="checkbox"
                      checked={field.value}
                      onChange={(e) => field.onChange(e.target.checked)}
                      className="mt-0.5 w-5 h-5 rounded accent-blue-600 flex-shrink-0"
                    />
                    <span className="text-sm font-semibold text-gray-700">
                      Declaro que las fotografías aportadas son de mi propiedad y autorizo su uso exclusivo
                      para auditoría socioeconómica interna de la Fundación V.I.D.A. Plena.
                    </span>
                  </label>
                )}
              />
              {errors.imagen_consent_accepted && (
                <p className="text-sm text-red-600">{errors.imagen_consent_accepted.message}</p>
              )}
            </div>
          </div>
        );

      case 6:
        return (
          <div className="space-y-6">
            <div className="bg-amber-50 border border-amber-200 rounded-2xl p-5">
              <h4 className="font-bold text-amber-800 flex items-center gap-2 mb-2">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Próximo paso: entrevista virtual
              </h4>
              <p className="text-sm text-amber-700">
                Al enviar su declaración jurada acepta que realizará una programación de una
                entrevista virtual con el profesional del área para culminar su evaluación.
              </p>
            </div>

            <div className="bg-gray-50 rounded-2xl p-5 border border-gray-200">
              <h4 className="font-bold text-gray-700 mb-3">Resumen de mi evaluación</h4>
              <div className="grid grid-cols-2 gap-2 text-sm text-gray-600">
                <div>
                  <span className="font-semibold">Departamento:</span> {watch('departamento') || '—'}
                </div>
                <div>
                  <span className="font-semibold">Integrantes:</span> {watch('integrantes_hogar')}
                </div>
                <div>
                  <span className="font-semibold">Ingreso total:</span> Bs. {ingreso_total.toFixed(2)}
                </div>
                <div>
                  <span className="font-semibold">Costo de vida estimado:</span> Bs. {costo_vida_estimado.toFixed(2)}
                </div>
                <div>
                  <span className="font-semibold">Tengo seguro:</span>{' '}
                  {watch('tiene_seguro') === 'si' ? 'Sí' : 'No'}
                </div>
                <div>
                  <span className="font-semibold">Tipo vivienda:</span> {watch('tipo_vivienda') || '—'}
                </div>
                <div>
                  <span className="font-semibold">Ayuda de otra institución:</span>{' '}
                  {watch('recibe_ayuda_otra_institucion') === 'si'
                    ? watch('nombre_institucion_ayuda') || 'Sí'
                    : 'No'}
                </div>
                <div>
                  <span className="font-semibold">Deudas que comprometen ingresos:</span>{' '}
                  {tiene_deudas ? `Sí (Bs. ${monto_deuda_watch.toFixed(2)}/mes)` : 'No'}
                </div>
              </div>
              <div className={`mt-3 rounded-xl px-4 py-2 font-bold text-sm text-center ${categoriaEstimada.color}`}>
                Capacidad Financiera Neta Residual: Bs. {cfnr.toFixed(2)} — {categoriaEstimada.label}
              </div>
              <p className="text-xs text-gray-400 mt-2 text-center">
                * La categoría final es calculada y asignada por el sistema.
              </p>
            </div>
          </div>
        );

      default:
        return null;
    }
  };

  // ─────────────────────────────────────────────────────────────────────────
  //  RENDER PRINCIPAL
  // ─────────────────────────────────────────────────────────────────────────

  if (checkingEligibility) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-100 to-blue-50 flex items-center justify-center">
        <p className="text-gray-500">Verificando su elegibilidad...</p>
      </div>
    );
  }

  if (eligibility && !eligibility.puede_evaluar) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-100 to-blue-50 py-10 px-4 flex items-center justify-center">
        <div className="max-w-lg w-full bg-white rounded-3xl shadow-xl p-8 md:p-10 border border-gray-100 text-center">
          <div className={`w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4 ${
            eligibility.suspendido ? 'bg-red-50 text-red-600' : 'bg-amber-50 text-amber-600'
          }`}>
            <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-gray-900 mb-2">
            {eligibility.suspendido ? 'Acceso suspendido' : 'Evaluación no disponible por el momento'}
          </h1>
          <p className="text-sm text-gray-600">{eligibility.motivo}</p>
          <button
            type="button"
            onClick={() => navigate('/mi-portal')}
            className="mt-6 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-bold transition-all"
          >
            Volver a mi portal
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 to-blue-50 py-10 px-4">
      <div className="max-w-2xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl md:text-3xl font-bold text-gray-900">
            Evaluación Socioeconómica
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Complete este formulario si no puede cubrir el aporte solidario mensual.
            Un evaluador social revisará su información y podrá exonerarla del aporte.
          </p>
        </div>

        <div className="bg-white rounded-3xl shadow-xl p-6 md:p-10 border border-gray-100">
          <ProgressBar pasoActual={pasoActual} />

          <form onSubmit={handleSubmit(onSubmit)}>
            <div className="min-h-[320px]">
              {renderPaso()}
            </div>

            <div className={`flex mt-8 gap-3 ${pasoActual > 1 ? 'justify-between' : 'justify-end'}`}>
              {pasoActual > 1 && (
                <button
                  type="button"
                  onClick={irAlAnterior}
                  className="px-6 py-3 border-2 border-gray-200 text-gray-600 rounded-xl font-semibold
                    hover:border-gray-300 hover:bg-gray-50 transition-all"
                >
                  ← Atrás
                </button>
              )}

              {pasoActual < PASOS.length ? (
                <button
                  type="button"
                  onClick={irAlSiguiente}
                  className="px-8 py-3 bg-blue-600 text-white rounded-xl font-bold
                    hover:bg-blue-700 active:scale-95 transition-all shadow-md shadow-blue-200"
                >
                  Siguiente →
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={submitting}
                  className={`px-8 py-3 rounded-xl font-bold text-white transition-all shadow-md
                    ${submitting
                      ? 'bg-gray-300 cursor-not-allowed shadow-none'
                      : 'bg-green-600 hover:bg-green-700 active:scale-95 shadow-green-200'}`}
                >
                  {submitting ? 'Enviando...' : '✅ Confirmar y Enviar Evaluación'}
                </button>
              )}
            </div>
          </form>
        </div>

        <p className="text-center text-xs text-gray-400 mt-6">
          Sus datos son confidenciales y están protegidos por la Ley 1173 de Bolivia.
        </p>
      </div>
    </div>
  );
}
