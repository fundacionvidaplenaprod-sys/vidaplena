import { useState, useEffect } from 'react';
import { useForm, useFieldArray } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import { checkBeneficiary, selfRegisterPatient } from '../../api/patients';
import { useAuth } from '../../context/AuthContext';
import { Input } from '../../components/ui/Input';
import { Button } from '../../components/ui/Button';
import { INSULIN_OPTIONS } from '../../constants/insulins';
import {
  User, MapPin, Phone, Mail, Lock, ShieldCheck,
  HeartPulse, Activity, AlertTriangle, Plus, Trash2, CheckCircle, MessageCircle
} from 'lucide-react';
import { toast } from 'react-hot-toast';
import { DEPARTAMENTOS } from '../../constants/departamentos';

// --- OPCIONES FIJAS ---
const TIPOS_SANGRE = ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"];
const COMPLICATION_OPTIONS = [
  { code: 'RETINOPATIA', label: 'Retinopatía' },
  { code: 'NEFROPATIA', label: 'Nefropatía' },
  { code: 'NEUROPATIA', label: 'Neuropatía' },
  { code: 'PIE_DIABETICO', label: 'Pie Diabético' },
  { code: 'CARDIOVASCULAR', label: 'Enf. Cardiovasculares' },
  { code: 'OTRAS', label: 'Otras (Especificar)' },
];

const WHATSAPP_CONTACT = '59172966106';
const WHATSAPP_DISPLAY = '+591 72966106';

const LabelRequired = ({ text }) => (
  <span className="flex items-center gap-1 font-semibold text-gray-700 text-sm">
    {text} <span className="text-red-500">*</span>
  </span>
);

const STEP_LABELS = ['Identidad', 'Datos Generales', 'Información Médica', 'Confirmación'];

export default function SelfRegisterPatientPage() {
  const navigate = useNavigate();
  const { login } = useAuth();

  const [step, setStep] = useState(0);
  const [isMinor, setIsMinor] = useState(false);
  const [serverError, setServerError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  // --- ESTADO DEL PASO 0 (verificación de identidad) ---
  const [matchStatus, setMatchStatus] = useState('idle'); // idle | checking | match | no-match
  const [tieneCI, setTieneCI] = useState(true);

  const { register, control, handleSubmit, watch, trigger, setValue, formState: { errors, isSubmitting } } = useForm({
    defaultValues: {
      nombres: '', ap_paterno: '', ap_materno: '',
      email: '', ci: '', customPassword: '',
      fecha_nac: '', peso: '', altura: '', imc: '', tipo_sangre: '',
      departamento: 'La Paz', municipio: '', zona: '', direccion: '',
      tel_contacto: '', tel_referencia: '',

      tutor: { nombres: '', apellidos: '', ci: '', direccion: '', telefonos: '', email: '' },
      medical: { tipo_diabetes: '', tiempo_enfermedad_anios: '', tiempo_enfermedad_meses: '' },

      treatments: [{ nombre: 'Glargina', dosis_diaria: 0 }],
      complications_selected: []
    },
    mode: "onChange"
  });

  const { fields: treatmentFields, append, remove } = useFieldArray({
    control, name: "treatments"
  });

  const fechaNacimiento = watch('fecha_nac');
  const selectedComplications = watch('complications_selected');
  const currentTreatments = watch('treatments') || [];
  const nombresVal = watch('nombres');
  const apPaternoVal = watch('ap_paterno');
  const apMaternoVal = watch('ap_materno');
  const tiempoEnfAnios = watch('medical.tiempo_enfermedad_anios');
  const tiempoEnfMeses = watch('medical.tiempo_enfermedad_meses');

  // Helpers de validación inline (mismo patrón que alerta de monto/compromiso)
  const isAniosInvalid = (v) => v !== '' && v !== null && v !== undefined && (Number(v) < 0 || Number(v) > 99);
  const isMesesInvalid = (v) => v !== '' && v !== null && v !== undefined && (Number(v) < 0 || Number(v) > 11);

  useEffect(() => {
    if (fechaNacimiento) {
      const birthDate = new Date(fechaNacimiento);
      const today = new Date();
      let age = today.getFullYear() - birthDate.getFullYear();
      const m = today.getMonth() - birthDate.getMonth();
      if (m < 0 || (m === 0 && today.getDate() < birthDate.getDate())) age--;
      setIsMinor(age < 18);
    }
  }, [fechaNacimiento]);

  const peso = watch('peso');
  const altura = watch('altura');
  useEffect(() => {
    if (peso && altura) {
      const p = parseFloat(peso);
      const a = parseFloat(altura);
      if (p > 0 && a > 0) {
        const calculatedImc = (p / (a * a)).toFixed(2);
        if (!isNaN(calculatedImc)) setValue('imc', calculatedImc);
      }
    }
  }, [peso, altura, setValue]);

  // --- PASO 0: Verificación contra el padrón de beneficiarios ---
  const handleVerify = async () => {
    const isValid = await trigger(['nombres', 'ap_paterno']);
    if (!isValid) {
      toast.error('Ingresa al menos tus nombres y apellido paterno.');
      return;
    }
    try {
      setMatchStatus('checking');
      const { match, already_registered } = await checkBeneficiary({
        nombres: nombresVal, ap_paterno: apPaternoVal, ap_materno: apMaternoVal
      });
      if (!match) {
        setMatchStatus('no-match');
      } else if (already_registered) {
        setMatchStatus('already-registered');
      } else {
        setMatchStatus('match');
      }
    } catch (error) {
      setMatchStatus('idle');
      toast.error('No se pudo verificar el nombre. Intenta nuevamente.');
    }
  };

  const nextFromStep0 = async () => {
    const fields = ['email'];
    if (tieneCI) fields.push('ci'); else fields.push('customPassword');
    const isValid = await trigger(fields);
    if (!isValid) {
      toast.error('Completa el correo y la contraseña para continuar.');
      return;
    }
    setStep(1);
  };

  const nextStep = async () => {
    let isValid = false;
    if (step === 1) {
      if (!isMinor && !tieneCI) {
        toast.error('El Carnet de Identidad es obligatorio para mayores de edad. Vuelve al paso anterior.');
        setStep(0);
        return;
      }
      const fields = [
        'fecha_nac', 'peso', 'altura', 'imc', 'tipo_sangre',
        'departamento', 'municipio', 'zona', 'direccion', 'tel_contacto'
      ];
      if (isMinor) fields.push('tutor.nombres', 'tutor.apellidos', 'tutor.ci', 'tutor.direccion', 'tutor.telefonos');
      isValid = await trigger(fields);
    } else if (step === 2) {
      const fields = ['medical.tipo_diabetes'];
      if (selectedComplications?.includes('OTRAS')) fields.push('otra_complicacion_detalle');
      isValid = await trigger(fields);
    }

    if (isValid) {
      setServerError(null);
      setStep(prev => prev + 1);
    } else {
      toast.error('Por favor completa los campos obligatorios marcados en rojo.');
    }
  };

  const prevStep = () => setStep(prev => prev - 1);

  const onSubmit = async (data) => {
    try {
      setServerError(null);
      setSubmitting(true);

      const formattedComplications = (data.complications_selected || []).map(code => ({
        complication_code: code,
        detalle: code === 'OTRAS' ? (data.otra_complicacion_detalle || 'Sin especificar') : null
      }));

      const normalizedTreatments = (data.treatments || []).map((tx) => ({
        nombre: (tx.nombre || '').trim(),
        dosis_diaria: Number(tx.dosis_diaria || 0),
        tiempo_uso_anios: tx.tiempo_uso_anios ? Number(tx.tiempo_uso_anios) : null,
        tiempo_uso_meses: tx.tiempo_uso_meses ? Number(tx.tiempo_uso_meses) : null,
      }));

      const invalidInsulin = normalizedTreatments.find((tx) => !tx.nombre || Number(tx.dosis_diaria || 0) <= 0);
      if (invalidInsulin) {
        setServerError('Cada tratamiento debe tener tipo de insulina y UI por día mayores a 0.');
        setSubmitting(false);
        return;
      }

      const capitalizeWords = (str) => {
        if (!str) return str;
        return str.trim().toLowerCase().split(' ')
          .filter(w => w.length > 0)
          .map(w => w.charAt(0).toUpperCase() + w.slice(1))
          .join(' ');
      };

      const parsedPeso = Number(data.peso);
      const parsedAltura = Number(data.altura);
      const password = tieneCI ? data.ci : data.customPassword;

      const payload = {
        email: data.email,
        password,
        ci: tieneCI ? data.ci : null,
        nombres: capitalizeWords(data.nombres),
        ap_paterno: capitalizeWords(data.ap_paterno),
        ap_materno: capitalizeWords(data.ap_materno) || null,
        fecha_nac: data.fecha_nac,
        peso: Number.isFinite(parsedPeso) ? parsedPeso : null,
        altura: Number.isFinite(parsedAltura) ? parsedAltura : null,
        imc: data.imc ? Number(data.imc) : null,
        tipo_sangre: data.tipo_sangre || null,
        depto: data.departamento || null,
        municipio: data.municipio || null,
        zona: data.zona || null,
        direccion: data.direccion || null,
        tel_contacto: data.tel_contacto || null,
        tel_referencia: data.tel_referencia || null,
        medical: {
          tipo_diabetes: data.medical?.tipo_diabetes,
          tiempo_enfermedad: [
            data.medical?.tiempo_enfermedad_anios ? `${data.medical.tiempo_enfermedad_anios} años` : '',
            data.medical?.tiempo_enfermedad_meses ? `${data.medical.tiempo_enfermedad_meses} meses` : '',
          ].filter(Boolean).join(' ') || null,
        },
        tutor: isMinor ? {
          ...data.tutor,
          nombres: capitalizeWords(data.tutor?.nombres),
          apellidos: capitalizeWords(data.tutor?.apellidos),
        } : null,
        treatments: normalizedTreatments,
        complications: formattedComplications,
      };

      await selfRegisterPatient(payload);
      toast.success('¡Registro exitoso! Ahora carga tus documentos.');

      await login({ email: data.email, password });
      navigate('/mi-portal', { replace: true });

    } catch (err) {
      if (typeof err === 'string') {
        setServerError(err);
      } else if (err?.response?.data?.detail) {
        const detail = err.response.data.detail;
        setServerError(Array.isArray(detail) ? `Error: ${detail[0].msg} en ${detail[0].loc.join(' -> ')}` : detail);
      } else {
        setServerError('Error al procesar el registro. Verifica los datos.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-vida-bg py-10 px-4">
      <div className="max-w-5xl mx-auto p-8 bg-white rounded-2xl shadow-xl relative">

        <div className="mb-8 pb-4 border-b border-gray-100">
          <h2 className="text-3xl font-bold text-vida-primary">Registro de Beneficiario</h2>
          <p className="text-gray-500 mt-1">
            Completa tus datos para iniciar tu trámite como beneficiario de la Fundación V.I.D.A. Plena.
          </p>

          <div className="flex gap-2 mt-4">
            {[0, 1, 2, 3].map(num => (
              <div key={num} className={`h-2 flex-1 rounded-full transition-all duration-300 ${step >= num ? 'bg-vida-main' : 'bg-gray-200'}`} />
            ))}
          </div>
          <p className="text-sm text-right text-gray-500 mt-2 font-medium">
            Paso {step + 1} de 4 — {STEP_LABELS[step]}
          </p>
        </div>

        <form onSubmit={(e) => e.preventDefault()}>

          {/* PASO 0: IDENTIDAD Y CREDENCIALES */}
          {step === 0 && (
            <div className="space-y-8 animate-fadeIn">
              <section>
                <h3 className="text-xl font-bold flex items-center gap-2 text-vida-primary mb-4 border-b pb-2">
                  <ShieldCheck /> Verificación de Identidad
                </h3>
                <p className="text-sm text-gray-500 mb-4">
                  Escribe tu nombre completo tal como está registrado ante la Fundación. Lo verificaremos antes de continuar.
                </p>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                  <Input
                    label={<LabelRequired text="Nombres" />}
                    disabled={matchStatus === 'match'}
                    {...register('nombres', { required: 'Requerido', onChange: () => setMatchStatus('idle') })}
                    error={errors.nombres}
                  />
                  <Input
                    label={<LabelRequired text="Ap. Paterno" />}
                    disabled={matchStatus === 'match'}
                    {...register('ap_paterno', { required: 'Requerido', onChange: () => setMatchStatus('idle') })}
                    error={errors.ap_paterno}
                  />
                  <Input
                    label="Ap. Materno"
                    disabled={matchStatus === 'match'}
                    {...register('ap_materno', { onChange: () => setMatchStatus('idle') })}
                  />
                </div>

                {matchStatus !== 'match' && (
                  <div className="mt-4">
                    <Button
                      type="button"
                      onClick={handleVerify}
                      disabled={matchStatus === 'checking'}
                      className="bg-vida-main hover:bg-vida-hover text-white w-full md:w-auto px-8"
                    >
                      {matchStatus === 'checking' ? 'Verificando...' : 'Verificar mi nombre'}
                    </Button>
                  </div>
                )}

                {matchStatus === 'no-match' && (
                  <div className="mt-6 bg-red-50 border-l-4 border-red-500 p-5 rounded-r-xl animate-fadeIn">
                    <div className="flex items-start gap-3">
                      <AlertTriangle className="text-red-500 mt-0.5 flex-shrink-0" size={24} />
                      <div>
                        <h4 className="font-bold text-red-800">No encontramos tu nombre en nuestra base de datos</h4>
                        <p className="text-sm text-red-700 mt-1">
                          Si crees que se trata de un error, o eres una persona nueva que aún no está registrada,
                          por favor comunícate al WhatsApp{' '}
                          <a href={`https://wa.me/${WHATSAPP_CONTACT}`} target="_blank" rel="noreferrer" className="underline font-bold inline-flex items-center gap-1">
                            <MessageCircle size={14} /> {WHATSAPP_DISPLAY}
                          </a>.
                        </p>
                        <button
                          type="button"
                          onClick={() => setMatchStatus('idle')}
                          className="mt-3 text-sm font-bold text-red-700 underline"
                        >
                          Corregir mi nombre e intentar de nuevo
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {matchStatus === 'already-registered' && (
                  <div className="mt-6 bg-amber-50 border-l-4 border-amber-500 p-5 rounded-r-xl animate-fadeIn">
                    <div className="flex items-start gap-3">
                      <AlertTriangle className="text-amber-500 mt-0.5 flex-shrink-0" size={24} />
                      <div>
                        <h4 className="font-bold text-amber-800">Este beneficiario ya tiene una cuenta registrada</h4>
                        <p className="text-sm text-amber-700 mt-1">
                          Si esta cuenta no es tuya, si necesitas corregir tus datos, o crees que es un error,
                          por favor comunícate al WhatsApp{' '}
                          <a href={`https://wa.me/${WHATSAPP_CONTACT}`} target="_blank" rel="noreferrer" className="underline font-bold inline-flex items-center gap-1">
                            <MessageCircle size={14} /> {WHATSAPP_DISPLAY}
                          </a>.
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {matchStatus === 'match' && (
                  <div className="mt-6 bg-green-50 border-l-4 border-green-500 p-4 rounded-r-xl animate-fadeIn flex items-center gap-3">
                    <CheckCircle className="text-green-600 flex-shrink-0" size={22} />
                    <p className="text-sm text-green-800 font-medium">
                      ¡Te encontramos en la lista de beneficiarios! Continúa creando tu acceso al portal.
                    </p>
                  </div>
                )}
              </section>

              {matchStatus === 'match' && (
                <section className="bg-gray-50 p-6 rounded-2xl border border-gray-100 animate-fadeIn">
                  <h4 className="font-bold text-lg text-gray-700 mb-4 flex items-center gap-2">
                    <Lock size={20} /> Tu acceso al portal
                  </h4>
                  <Input
                    type="email"
                    label={<LabelRequired text="Correo Electrónico" />}
                    icon={<Mail size={16} />}
                    {...register('email', { required: 'Requerido' })}
                    error={errors.email}
                  />

                  <div className="flex items-center gap-2 mt-4 ml-1">
                    <input
                      type="checkbox"
                      id="tieneCI"
                      className="w-4 h-4 accent-vida-main cursor-pointer"
                      checked={tieneCI}
                      onChange={(e) => setTieneCI(e.target.checked)}
                    />
                    <label htmlFor="tieneCI" className="text-sm text-gray-700 cursor-pointer">
                      Cuento con Carnet de Identidad (CI)
                    </label>
                  </div>

                  {tieneCI ? (
                    <div className="mt-3">
                      <Input
                        label={<LabelRequired text="Carnet de Identidad (CI)" />}
                        {...register('ci', { required: tieneCI ? 'Requerido' : false })}
                        error={errors.ci}
                      />
                      <p className="text-xs text-gray-500 mt-1 ml-1">Este número será también tu contraseña para ingresar al portal.</p>
                    </div>
                  ) : (
                    <div className="mt-3">
                      <Input
                        type="password"
                        label={<LabelRequired text="Contraseña personalizada" />}
                        {...register('customPassword', { required: !tieneCI ? 'Requerido' : false, minLength: { value: 4, message: 'Mínimo 4 caracteres' } })}
                        error={errors.customPassword}
                      />
                      <p className="text-xs text-gray-500 mt-1 ml-1">
                        Usa esta opción solo si el beneficiario es menor de edad y todavía no tiene CI. El tutor define esta contraseña.
                      </p>
                    </div>
                  )}
                </section>
              )}
            </div>
          )}

          {/* PASO 1: DATOS GENERALES */}
          {step === 1 && (
            <div className="space-y-8 animate-fadeIn">
              <section>
                <h3 className="text-xl font-bold flex items-center gap-2 text-vida-primary mb-4 border-b pb-2">
                  <User /> Datos Generales
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
                  <Input type="date" label={<LabelRequired text="Nacimiento" />} {...register('fecha_nac', { required: 'Requerido' })} error={errors.fecha_nac} />
                  <div className="flex flex-col gap-1">
                    <label htmlFor="tipo_sangre" className="text-sm font-bold text-gray-700 ml-1">Tipo Sangre</label>
                    <select id="tipo_sangre" {...register('tipo_sangre')} className="w-full bg-vida-bg p-3 rounded-xl border border-transparent focus:bg-white outline-none">
                      <option value="">--</option>
                      {TIPOS_SANGRE.map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </div>
                  <Input type="number" step="0.1" label={<LabelRequired text="Peso (Kg)" />} {...register('peso', { required: 'Requerido' })} error={errors.peso} />
                  <Input type="number" step="0.01" label={<LabelRequired text="Altura (m)" />} {...register('altura', { required: 'Requerido' })} error={errors.altura} />
                </div>
              </section>

              <section className="bg-gray-50 p-6 rounded-2xl border border-gray-100">
                <h4 className="font-bold text-lg text-gray-700 mb-4 flex items-center gap-2"><MapPin size={20} /> Ubicación y Contacto</h4>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                  <div className="flex flex-col gap-1">
                    <label htmlFor="departamento" className="text-sm font-bold text-gray-700 ml-1">Departamento <span className="text-red-500">*</span></label>
                    <select id="departamento" {...register('departamento', { required: 'Requerido' })} className="w-full bg-white p-3 rounded-xl border border-gray-200 outline-none">
                      {DEPARTAMENTOS.map(d => <option key={d} value={d}>{d}</option>)}
                    </select>
                  </div>
                  <Input label={<LabelRequired text="Municipio" />} {...register('municipio', { required: 'Requerido' })} error={errors.municipio} />
                  <Input label={<LabelRequired text="Zona" />} {...register('zona', { required: 'Requerido' })} error={errors.zona} />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mt-4">
                  <Input label={<LabelRequired text="Dirección Detallada" />} className="w-full" {...register('direccion', { required: 'Requerido' })} error={errors.direccion} />
                  <div className="grid grid-cols-2 gap-2">
                    <Input label={<LabelRequired text="Tel. Contacto" />} icon={<Phone size={16} />} {...register('tel_contacto', { required: 'Requerido' })} error={errors.tel_contacto} />
                    <Input label="Tel. Referencia" icon={<Phone size={16} />} {...register('tel_referencia')} />
                  </div>
                </div>
              </section>

              {isMinor && (
                <section className="bg-orange-50 p-6 rounded-2xl border border-orange-200 animate-slideDown">
                  <div className="flex items-center gap-2 text-orange-800 font-bold mb-4 border-b border-orange-200 pb-2">
                    <AlertTriangle className="h-5 w-5" />
                    <span>Tutor Legal (Obligatorio)</span>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                    <Input label={<LabelRequired text="Nombre Tutor" />} {...register('tutor.nombres', { required: 'Requerido' })} error={errors.tutor?.nombres} />
                    <Input label={<LabelRequired text="Apellidos Tutor" />} {...register('tutor.apellidos', { required: 'Requerido' })} error={errors.tutor?.apellidos} />
                    <Input label={<LabelRequired text="C.I. Tutor" />} {...register('tutor.ci', { required: 'Requerido' })} error={errors.tutor?.ci} />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mt-4">
                    <Input label={<LabelRequired text="Dirección Tutor" />} {...register('tutor.direccion', { required: 'Requerido' })} error={errors.tutor?.direccion} />
                    <div className="flex gap-2">
                      <Input label={<LabelRequired text="Teléfonos" />} {...register('tutor.telefonos', { required: 'Requerido' })} error={errors.tutor?.telefonos} />
                      <Input label="Email Tutor" {...register('tutor.email')} />
                    </div>
                  </div>
                </section>
              )}
            </div>
          )}

          {/* PASO 2: INFORMACIÓN MÉDICA */}
          {step === 2 && (
            <div className="space-y-8 animate-fadeIn">
              <section>
                <h3 className="text-xl font-bold flex items-center gap-2 text-vida-primary mb-4 border-b pb-2">
                  <HeartPulse /> Información Médica
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <label htmlFor="tipo_diabetes" className="text-sm font-bold text-gray-700 ml-1 block mb-1">Tipo de Diabetes <span className="text-red-500">*</span></label>
                    <select id="tipo_diabetes" {...register('medical.tipo_diabetes', { required: 'Requerido' })} className="w-full bg-vida-bg p-3 rounded-xl border border-transparent focus:bg-white outline-none">
                      <option value="">-- Seleccionar --</option>
                      <option value="Tipo 1">Tipo 1</option>
                      <option value="Tipo 2">Tipo 2</option>
                      <option value="Gestacional">Gestacional</option>
                      <option value="Otra">Otra</option>
                    </select>
                    {errors.medical?.tipo_diabetes && <span className="text-red-500 text-xs font-bold">{errors.medical.tipo_diabetes.message}</span>}
                  </div>
                  <div>
                    <label className="text-sm font-bold text-gray-700 ml-1 block mb-1">Tiempo con la enfermedad</label>
                    <div className="flex gap-2">
                      <div className="flex-1">
                        <input
                          type="number"
                          min="0" max="99"
                          placeholder="Años"
                          {...register('medical.tiempo_enfermedad_anios', { min: 0, max: 99 })}
                          className={`w-full bg-vida-bg p-3 rounded-xl border-2 focus:bg-white outline-none text-sm transition-all ${
                            isAniosInvalid(tiempoEnfAnios)
                              ? 'border-red-500 shadow-[0_0_8px_rgba(239,68,68,0.6)]'
                              : 'border-transparent'
                          }`}
                        />
                        {isAniosInvalid(tiempoEnfAnios) && (
                          <div className="text-red-100 text-xs mt-1 flex items-center bg-red-600/80 px-2 py-1 rounded-md font-medium animate-pulse">
                            <AlertTriangle size={12} className="mr-1 flex-shrink-0" />
                            Máx. 99 años
                          </div>
                        )}
                        <span className="text-xs text-gray-400 ml-1">Años</span>
                      </div>
                      <div className="flex-1">
                        <input
                          type="number"
                          min="0" max="11"
                          placeholder="Meses"
                          {...register('medical.tiempo_enfermedad_meses', { min: 0, max: 11 })}
                          className={`w-full bg-vida-bg p-3 rounded-xl border-2 focus:bg-white outline-none text-sm transition-all ${
                            isMesesInvalid(tiempoEnfMeses)
                              ? 'border-red-500 shadow-[0_0_8px_rgba(239,68,68,0.6)]'
                              : 'border-transparent'
                          }`}
                        />
                        {isMesesInvalid(tiempoEnfMeses) && (
                          <div className="text-red-100 text-xs mt-1 flex items-center bg-red-600/80 px-2 py-1 rounded-md font-medium animate-pulse">
                            <AlertTriangle size={12} className="mr-1 flex-shrink-0" />
                            Máx. 11 meses
                          </div>
                        )}
                        <span className="text-xs text-gray-400 ml-1">Meses</span>
                      </div>
                    </div>
                  </div>
                </div>
              </section>

              <section className="p-6 bg-blue-50/50 rounded-2xl border border-blue-100">
                <div className="flex justify-between items-center mb-4">
                  <h4 className="font-bold text-lg text-blue-800 flex items-center gap-2"><Activity size={20} /> Tratamiento de Insulina</h4>
                  <button
                    type="button"
                    onClick={() => {
                      const availableInsulins = INSULIN_OPTIONS.map(o => o.value).filter(val => !currentTreatments.some(tx => tx.nombre === val));
                      if (availableInsulins.length === 0) {
                        toast.error('Ya tienes asignados todos los tipos de insulina disponibles.');
                        return;
                      }
                      append({ nombre: availableInsulins[0], dosis_diaria: 0 });
                    }}
                    className="text-sm bg-white border border-blue-200 text-blue-600 px-3 py-1 rounded-lg hover:bg-blue-50 font-bold flex items-center gap-1 shadow-sm"
                  >
                    <Plus size={16} /> Agregar
                  </button>
                </div>

                <div className="space-y-3">
                  {treatmentFields.map((field, index) => (
                    <div key={field.id} className="flex flex-col md:flex-row gap-3 items-start bg-white p-3 rounded-xl shadow-sm border border-blue-100">
                      <div className="w-full md:w-1/2">
                        <label className="text-xs font-bold text-gray-500 ml-1">Tipo de Insulina <span className="text-red-500">*</span></label>
                        <select
                          {...register(`treatments.${index}.nombre`, { required: 'Requerido' })}
                          className="w-full text-sm bg-gray-50 p-2 rounded-lg border border-gray-200"
                        >
                          {INSULIN_OPTIONS.map((opt) => {
                            const isSelectedElsewhere = currentTreatments.some((tx, txIndex) => txIndex !== index && tx.nombre === opt.value);
                            return (
                              <option key={opt.value} value={opt.value} disabled={isSelectedElsewhere}>
                                {opt.label} {isSelectedElsewhere ? '(Ya asignada)' : ''}
                              </option>
                            );
                          })}
                        </select>
                      </div>
                      <div className="w-full md:w-1/3">
                        <label className="text-xs font-bold text-gray-500 ml-1">UI por día <span className="text-red-500">*</span></label>
                        <input
                          type="number"
                          min="0.1"
                          step="0.1"
                          {...register(`treatments.${index}.dosis_diaria`, { valueAsNumber: true, required: true, min: 0.1 })}
                          className="w-full text-sm bg-gray-50 p-2 rounded-lg border border-gray-200 outline-none"
                          placeholder="Ej: 24"
                        />
                      </div>
                      <div className="w-full md:w-1/4">
                        <label className="text-xs font-bold text-gray-500 ml-1">Tiempo uso</label>
                        <div className="flex gap-1">
                          <div className="flex-1">
                            <input
                              type="number" min="0" max="99"
                              placeholder="Años"
                              {...register(`treatments.${index}.tiempo_uso_anios`, { min: 0, max: 99 })}
                              className={`w-full text-sm bg-gray-50 p-2 rounded-lg border-2 outline-none transition-all ${
                                isAniosInvalid(currentTreatments[index]?.tiempo_uso_anios)
                                  ? 'border-red-500 shadow-[0_0_6px_rgba(239,68,68,0.6)]'
                                  : 'border-gray-200'
                              }`}
                            />
                            {isAniosInvalid(currentTreatments[index]?.tiempo_uso_anios) && (
                              <div className="text-red-100 text-xs mt-0.5 flex items-center bg-red-600/80 px-1.5 py-0.5 rounded font-medium animate-pulse">
                                <AlertTriangle size={10} className="mr-1 flex-shrink-0" />
                                Máx. 99
                              </div>
                            )}
                            <span className="text-xs text-gray-400">Años</span>
                          </div>
                          <div className="flex-1">
                            <input
                              type="number" min="0" max="11"
                              placeholder="Mes"
                              {...register(`treatments.${index}.tiempo_uso_meses`, { min: 0, max: 11 })}
                              className={`w-full text-sm bg-gray-50 p-2 rounded-lg border-2 outline-none transition-all ${
                                isMesesInvalid(currentTreatments[index]?.tiempo_uso_meses)
                                  ? 'border-red-500 shadow-[0_0_6px_rgba(239,68,68,0.6)]'
                                  : 'border-gray-200'
                              }`}
                            />
                            {isMesesInvalid(currentTreatments[index]?.tiempo_uso_meses) && (
                              <div className="text-red-100 text-xs mt-0.5 flex items-center bg-red-600/80 px-1.5 py-0.5 rounded font-medium animate-pulse">
                                <AlertTriangle size={10} className="mr-1 flex-shrink-0" />
                                Máx. 11
                              </div>
                            )}
                            <span className="text-xs text-gray-400">Meses</span>
                          </div>
                        </div>
                      </div>
                      <div className="flex items-end h-full pb-1">
                        {index > 0 && (
                          <button type="button" onClick={() => remove(index)} className="text-red-400 hover:text-red-600 p-1"><Trash2 size={18} /></button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="bg-gray-50 p-6 rounded-2xl">
                <h4 className="font-bold text-gray-700 mb-4">Complicaciones de la diabetes y/o Enf. Concomitantes</h4>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                  {COMPLICATION_OPTIONS.map((opt) => (
                    <label key={opt.code} className="flex items-center gap-3 cursor-pointer p-2 hover:bg-white rounded-lg transition-colors select-none">
                      <input type="checkbox" value={opt.code} {...register('complications_selected')} className="w-5 h-5 text-vida-main rounded focus:ring-vida-main accent-vida-main" />
                      <span className="text-gray-700">{opt.label}</span>
                    </label>
                  ))}
                </div>

                {selectedComplications?.includes('OTRAS') && (
                  <div className="mt-4 animate-fadeIn">
                    <Input
                      label={<LabelRequired text="Especifique la complicación" />}
                      placeholder="Describa la otra complicación..."
                      {...register('otra_complicacion_detalle', { required: "Si marca 'Otras', debe especificar cuál." })}
                      error={errors.otra_complicacion_detalle}
                    />
                  </div>
                )}
              </section>
            </div>
          )}

          {/* PASO 3: VERIFICACIÓN */}
          {step === 3 && (
            <div className="text-center space-y-6 animate-fadeIn max-w-2xl mx-auto">
              <div className="w-20 h-20 rounded-full flex items-center justify-center mx-auto mb-6 shadow-lg bg-green-100 text-green-600 shadow-green-100">
                <CheckCircle size={40} />
              </div>

              <h3 className="text-2xl font-bold text-gray-800">Confirma tus datos</h3>

              {serverError && (
                <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-lg text-left text-sm font-medium">
                  🚨 {serverError}
                </div>
              )}

              <div className="bg-white border border-gray-100 text-left p-6 rounded-2xl shadow-xl space-y-4 text-sm">
                <div className="flex justify-between border-b border-gray-100 pb-2">
                  <span className="text-gray-500">Beneficiario:</span>
                  <span className="font-bold text-lg">{watch('nombres')} {watch('ap_paterno')}</span>
                </div>
                <div className="flex justify-between border-b border-gray-100 pb-2">
                  <span className="text-gray-500">Correo de acceso:</span>
                  <span className="font-bold">{watch('email')}</span>
                </div>
                <div className="flex justify-between border-b border-gray-100 pb-2">
                  <span className="text-gray-500">Ubicación:</span>
                  <span className="font-bold">{watch('municipio')}, {watch('zona')}</span>
                </div>
                <div className="flex justify-between border-b border-gray-100 pb-2">
                  <span className="text-gray-500">Diagnóstico:</span>
                  <span className="font-bold text-vida-main">{watch('medical.tipo_diabetes')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Insulinas registradas:</span>
                  <span className="font-bold">{treatmentFields.length}</span>
                </div>
              </div>

              <p className="text-xs text-gray-500">
                Al finalizar, tu registro quedará pendiente de la carga de documentos y de la validación de la Fundación.
              </p>
            </div>
          )}

          {/* BOTONES DE NAVEGACIÓN */}
          <div className="flex justify-between mt-10 pt-6 border-t border-gray-100">
            {step > 0 ? (
              <Button type="button" variant="secondary" onClick={prevStep} className="px-8">
                Atrás
              </Button>
            ) : (
              <Button
                type="button"
                variant="secondary"
                onClick={() => navigate('/login')}
                className="px-8 text-gray-500 hover:text-gray-700 bg-transparent border-transparent shadow-none hover:bg-gray-100"
              >
                Cancelar
              </Button>
            )}

            {step === 0 && (
              <Button
                type="button"
                onClick={nextFromStep0}
                disabled={matchStatus !== 'match'}
                className="px-8 bg-vida-main hover:bg-vida-hover text-white shadow-lg shadow-vida-main/20 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Siguiente Paso
              </Button>
            )}

            {step > 0 && step < 3 && (
              <Button type="button" onClick={nextStep} className="px-8 bg-vida-main hover:bg-vida-hover text-white shadow-lg shadow-vida-main/20">
                Siguiente Paso
              </Button>
            )}

            {step === 3 && (
              <Button
                type="button"
                onClick={handleSubmit(onSubmit)}
                disabled={isSubmitting || submitting}
                className="px-8 text-white shadow-lg w-full md:w-auto bg-green-600 hover:bg-green-700 shadow-green-200"
              >
                {(isSubmitting || submitting) ? 'Procesando...' : 'Finalizar Registro'}
              </Button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
