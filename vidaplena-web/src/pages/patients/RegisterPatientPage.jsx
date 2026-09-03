import { useState, useEffect } from 'react';
import { useForm, useFieldArray } from 'react-hook-form';
import { useNavigate, useParams } from 'react-router-dom';
// IMPORTANTE: Agregamos getPatientById y updatePatient
import { createPatient, getPatientById, updatePatient } from '../../api/patients';
import { Input } from '../../components/ui/Input';
import { Button } from '../../components/ui/Button';
import { INSULIN_OPTIONS, normalizeInsulinName } from '../../constants/insulins';
import {
  User, MapPin, Phone, Mail,
  HeartPulse, Activity, AlertTriangle, Plus, Trash2, CheckCircle, Lock, Unlock
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
const toDailyUnitsFromTreatment = (tx) => {
  return Number(tx?.dosis_diaria || 0);
};

// El backend guarda "tiempo_enfermedad" como un solo string armado al
// enviar (ej. "3 años 2 meses"); al editar hay que descomponerlo de nuevo
// en los dos campos separados del formulario (medical.tiempo_enfermedad_anios/meses).
const parseTiempoEnfermedad = (str) => {
  const anioMatch = String(str || '').match(/(\d+)\s*años?/i);
  const mesMatch = String(str || '').match(/(\d+)\s*mes(?:es)?/i);
  return {
    tiempo_enfermedad_anios: anioMatch ? anioMatch[1] : '',
    tiempo_enfermedad_meses: mesMatch ? mesMatch[1] : '',
  };
};

const LabelRequired = ({ text }) => (
  <span className="flex items-center gap-1 font-semibold text-gray-700 text-sm">
    {text} <span className="text-red-500">*</span>
  </span>
);

export default function RegisterPatientPage() {
  const { id } = useParams(); // Capturamos el ID si estamos editando
  const isEditMode = !!id;    // True si hay ID

  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [isMinor, setIsMinor] = useState(false);
  const [serverError, setServerError] = useState(null);
  const [loadingData, setLoadingData] = useState(false); // Estado de carga para edición
  const [hasInitialCi, setHasInitialCi] = useState(false);
  const [ciUnlocked, setCiUnlocked] = useState(false);

  const currentUser = JSON.parse(localStorage.getItem('user') || '{}');
  const isSuperAdmin = currentUser.role === 'SUPER_ADMIN';

  const handleUnlockCi = () => {
    const confirmado = window.confirm(
      'El C.I. es un dato de identidad único. ¿Confirmas que quieres desbloquearlo para corregirlo? ' +
        'Verifica que el nuevo número sea correcto antes de guardar.'
    );
    if (confirmado) setCiUnlocked(true);
  };

  const { register, control, handleSubmit, watch, trigger, reset, setValue, formState: { errors, isSubmitting } } = useForm({
    defaultValues: {
      // 3.1 Datos Generales
      nombres: '', ap_paterno: '', ap_materno: '', ci: '',
      fecha_nac: '', peso: '', altura: '', imc: '', tipo_sangre: '',
      departamento: 'La Paz', municipio: '', zona: '', direccion: '',
      email: '', tel_contacto: '', tel_referencia: '',

      // Discapacidad/limitación con tutor legal (habilita el bloque de Tutor también para mayores de edad)
      tiene_discapacidad_tutor: false,

      // 3.3 Tutor (Menores, o mayores con discapacidad y tutor legal)
      tutor: { nombres: '', apellidos: '', ci: '', direccion: '', telefonos: '', email: '' },

      // 3.2 Información Médica
      medical: { tipo_diabetes: '', tiempo_enfermedad_anios: '', tiempo_enfermedad_meses: '' },

      // Arrays
      treatments: [{ nombre: 'Glargina', dosis_diaria: 0 }],
      complications_selected: []
    },
    mode: "onChange"
  });

  const { fields: treatmentFields, append, remove } = useFieldArray({
    control, name: "treatments"
  });

  // VIGILANTES (Watches)
  const fechaNacimiento = watch('fecha_nac');
  const tieneDiscapacidadTutor = watch('tiene_discapacidad_tutor');
  const requiereTutor = isMinor || tieneDiscapacidadTutor;
  const selectedComplications = watch('complications_selected');
  const currentTreatments = watch('treatments') || [];
  const tiempoEnfAnios = watch('medical.tiempo_enfermedad_anios');
  const tiempoEnfMeses = watch('medical.tiempo_enfermedad_meses');

  // Helpers de validación inline
  const isAniosInvalid = (v) => v !== '' && v !== null && v !== undefined && (Number(v) < 0 || Number(v) > 99);
  const isMesesInvalid = (v) => v !== '' && v !== null && v !== undefined && (Number(v) < 0 || Number(v) > 11);

  // --- LÓGICA DE CARGA DE DATOS (MODO EDICIÓN) ---
  useEffect(() => {
    if (isEditMode) {
      loadPatientData();
    }
  }, [id]);

  const loadPatientData = async () => {
    try {
      setLoadingData(true);
      const data = await getPatientById(id);


      let fechaFormat = '';
      if (data.fecha_nac) {
        fechaFormat = data.fecha_nac.includes('T')
          ? data.fecha_nac.split('T')[0]
          : data.fecha_nac;
      }

      // Preparar complicaciones para el formulario (Array de Strings)
      let complicationsCodes = [];
      let otraDetalle = '';

      if (data.complications && Array.isArray(data.complications)) {
        complicationsCodes = data.complications.map(c => c.complication_code);
        const otras = data.complications.find(c => c.complication_code === 'OTRAS');
        if (otras) otraDetalle = otras.detalle;
      }

      // Preparar tratamientos
      const treatmentsList = (data.treatments && data.treatments.length > 0)
        ? data.treatments.map((tx) => ({
            nombre: normalizeInsulinName(tx.nombre),
            dosis_diaria: toDailyUnitsFromTreatment(tx),
            tiempo_uso_anios: tx.tiempo_uso_anios ?? '',
            tiempo_uso_meses: tx.tiempo_uso_meses ?? '',
          }))
        : [{ nombre: 'Glargina', dosis_diaria: 0 }];

      // El IMC se recalcula desde peso/altura en vez de confiar en el valor
      // guardado: el useEffect de cálculo automático (más abajo) solo
      // reacciona a cambios del usuario en peso/altura, no a un reset()
      // programático — sin esto, el campo IMC quedaba en blanco al editar
      // un registro cuyo IMC nunca se calculó o quedó desactualizado.
      const pesoNum = parseFloat(data.peso);
      const alturaNum = parseFloat(data.altura);
      const imcRecalculado = pesoNum > 0 && alturaNum > 0
        ? (pesoNum / (alturaNum * alturaNum)).toFixed(2)
        : (data.imc || '');

      // RESETEAR EL FORMULARIO CON LOS DATOS DEL BACKEND
      reset({
        nombres: data.nombres,
        ap_paterno: data.ap_paterno,
        ap_materno: data.ap_materno || '',
        ci: data.ci || '',
        // --- AQUÍ ESTÁ LA CORRECCIÓN DE TUS CAMPOS ---
        fecha_nac: fechaFormat,         // Asignamos la fecha formateada
        peso: data.peso || '',          // Evitamos undefined
        altura: data.altura || '',      // Evitamos undefined
        imc: imcRecalculado,
        tipo_sangre: data.tipo_sangre || '', // Asegura que coincida con las opciones del <select>
        // ---------------------------------------------
        
        // Registrar si tenía CI inicialmente
        ...(() => { setHasInitialCi(!!data.ci); return {}; })(),

        departamento: data.depto || data.departamento || 'La Paz',
        municipio: data.municipio,
        zona: data.zona,
        direccion: data.direccion,
        email: data.email || '',
        tel_contacto: data.tel_contacto || data.celular || '', // Soporte para ambos nombres de campo
        tel_referencia: data.tel_referencia || '',

        // Datos del Tutor (si existen)
        tutor: data.tutor || { nombres: '', apellidos: '', ci: '', direccion: '', telefonos: '', email: '' },
        tiene_discapacidad_tutor: !!(data.tutor && (data.tutor.nombres || data.tutor.ci)),

        // Datos Médicos
        medical: {
          tipo_diabetes: data.medical?.tipo_diabetes || '',
          ...parseTiempoEnfermedad(data.medical?.tiempo_enfermedad),
        },

        // Arrays y Especiales
        treatments: treatmentsList,
        complications_selected: complicationsCodes,
        otra_complicacion_detalle: otraDetalle
      });

    } catch (error) {

      alert("Error cargando expediente del paciente.");
      navigate('/dashboard');
    } finally {
      setLoadingData(false);
    }
  };

  // Cálculo de Edad
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

  // Cálculo automático de IMC
  const peso = watch('peso');
  const altura = watch('altura');

  useEffect(() => {
    if (peso && altura) {
      const p = parseFloat(peso);
      const a = parseFloat(altura);
      if (p > 0 && a > 0) {
        const calculatedImc = (p / (a * a)).toFixed(2);
        // Solo actualizamos si es un número válido
        if (!isNaN(calculatedImc)) {
          setValue('imc', calculatedImc);
        }
      }
    }
  }, [peso, altura, setValue]);

  // Navegación entre Pasos
  const nextStep = async () => {
    let isValid = false;
    if (step === 1) {
      const fields = [
        'nombres', 'ap_paterno', 'fecha_nac', 'peso', 'altura', 'imc', 'tipo_sangre',
        'departamento', 'municipio', 'zona', 'direccion', 'tel_contacto'
      ];
      // CI es obligatorio solo para mayores de edad
      if (!isMinor) fields.push('ci');
      if (requiereTutor) fields.push('tutor.nombres', 'tutor.apellidos', 'tutor.ci', 'tutor.direccion', 'tutor.telefonos');
      isValid = await trigger(fields);
    } else if (step === 2) {
      const fields = ['medical.tipo_diabetes', 'medical.tiempo_enfermedad'];
      if (selectedComplications?.includes('OTRAS')) {
        fields.push('otra_complicacion_detalle');
      }
      isValid = await trigger(fields);
    }

    if (isValid) {
      setServerError(null);
      setStep(prev => prev + 1);
    } else {
      toast.error("Por favor complete los campos obligatorios marcados en rojo.");
    }
  };

  const prevStep = () => setStep(prev => prev - 1);

  // ENVÍO FINAL (CREAR O EDITAR)
  const onSubmit = async (data) => {
    try {
      setServerError(null);

      const formattedComplications = data.complications_selected.map(code => ({
        complication_code: code,
        detalle: code === 'OTRAS' ? (data.otra_complicacion_detalle || 'Sin especificar') : null
      }));

      const normalizedTreatments = (data.treatments || []).map((tx) => {
        const dailyUnits = Number(tx.dosis_diaria || 0);
        return {
          nombre: (tx.nombre || '').trim(),
          dosis_diaria: dailyUnits,
          tiempo_uso_anios: tx.tiempo_uso_anios ? Number(tx.tiempo_uso_anios) : null,
          tiempo_uso_meses: tx.tiempo_uso_meses ? Number(tx.tiempo_uso_meses) : null,
        };
      });

      const invalidInsulin = normalizedTreatments.find((tx) => !tx.nombre || Number(tx.dosis_diaria || 0) <= 0);
      if (invalidInsulin) {
        setServerError('Cada tratamiento debe tener tipo de insulina y UI por día mayores a 0.');
        return;
      }
      
      const insulinsSet = new Set(normalizedTreatments.map(t => t.nombre));
      if (insulinsSet.size !== normalizedTreatments.length) {
        setServerError('No puede asignar el mismo tipo de insulina más de una vez.');
        return;
      }

      const capitalizeWords = (str) => {
        if (!str) return str;
        return str
          .trim()
          .toLowerCase()
          .split(' ')
          .filter(word => word.length > 0)
          .map(word => word.charAt(0).toUpperCase() + word.slice(1))
          .join(' ');
      };

      const parsedPeso = Number(data.peso);
      const parsedAltura = Number(data.altura);

      // Payload explícito para evitar desalineación con el backend (422).
      const payload = {
        ci: data.ci,
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
        email: data.email || null,
        tel_contacto: data.tel_contacto || null,
        tel_referencia: data.tel_referencia || null,
        medical: {
          tipo_diabetes: data.medical?.tipo_diabetes,
          tiempo_enfermedad: [
            data.medical?.tiempo_enfermedad_anios ? `${data.medical.tiempo_enfermedad_anios} años` : '',
            data.medical?.tiempo_enfermedad_meses ? `${data.medical.tiempo_enfermedad_meses} meses` : '',
          ].filter(Boolean).join(' ') || null,
        },
        medical_info: data.medical,
        tutor: requiereTutor ? {
          ...data.tutor,
          nombres: capitalizeWords(data.tutor?.nombres),
          apellidos: capitalizeWords(data.tutor?.apellidos),
        } : null,
        treatments: normalizedTreatments,
        complications: formattedComplications,
      };

      if (isEditMode) {
        // --- MODO ACTUALIZACIÓN ---
        await updatePatient(id, payload);
        toast.success("✅ Expediente actualizado correctamente");
      } else {
        // --- MODO CREACIÓN ---
        await createPatient(payload);
        toast.success("✅ Paciente registrado correctamente");
      }

      navigate('/dashboard');

    } catch (err) {

      // Mostrar el error exacto si viene del backend
      if (err.response && err.response.data && err.response.data.detail) {
        if (Array.isArray(err.response.data.detail)) {
          setServerError(`Error: ${err.response.data.detail[0].msg} en ${err.response.data.detail[0].loc.join(' -> ')}`);
        } else {
          setServerError(err.response.data.detail);
        }
      } else {
        setServerError(typeof err === 'string' ? err : "Error al procesar. Verifique los datos.");
      }
    }
  };

  if (loadingData) return <div className="p-10 text-center text-gray-500 font-bold animate-pulse">Cargando expediente...</div>;

  return (
    <div className="max-w-5xl mx-auto p-8 bg-white rounded-2xl shadow-xl my-10 relative">

      {/* HEADER DINÁMICO */}
      <div className="mb-8 pb-4 border-b border-gray-100">
        <h2 className="text-3xl font-bold text-vida-primary">
          {isEditMode ? 'Editar Beneficiario' : 'Registro de Beneficiario'}
        </h2>
        <p className="text-gray-500 mt-1">
          {isEditMode ? 'Modifica los datos del expediente.' : 'Complete la información para dar de alta.'}
        </p>

        <div className="flex gap-2 mt-4">
          {[1, 2, 3].map(num => (
            <div key={num} className={`h-2 flex-1 rounded-full transition-all duration-300 ${step >= num ? 'bg-vida-main' : 'bg-gray-200'}`} />
          ))}
        </div>
        <p className="text-sm text-right text-gray-500 mt-2 font-medium">Paso {step} de 3</p>
      </div>

      <form onSubmit={(e) => e.preventDefault()}>

        {/* PASO 1: DATOS GENERALES */}
        {step === 1 && (
          <div className="space-y-8 animate-fadeIn">
            <section>
              <h3 className="text-xl font-bold flex items-center gap-2 text-vida-primary mb-4 border-b pb-2">
                <User /> 3.1 Datos Generales
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                <Input label={<LabelRequired text="Nombres" />} {...register('nombres', { required: "Requerido" })} error={errors.nombres} />
                <Input label={<LabelRequired text="Ap. Paterno" />} {...register('ap_paterno', { required: "Requerido" })} error={errors.ap_paterno} />
                <Input label="Ap. Materno" {...register('ap_materno')} />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-5 mt-4">
                <div className="relative">
                  <Input
                    label={isMinor
                      ? <span className="flex items-center gap-1 font-semibold text-gray-700 text-sm">C.I. <span className="text-gray-400 font-normal text-xs">(opcional para menores)</span></span>
                      : <LabelRequired text="C.I." />
                    }
                    {...register('ci', { required: isMinor ? false : "Requerido" })}
                    error={errors.ci}
                    disabled={isEditMode && hasInitialCi && !ciUnlocked}
                    className={(isEditMode && hasInitialCi && !ciUnlocked) ? "bg-gray-100 pr-9" : "pr-9"}
                  />
                  {isEditMode && hasInitialCi && isSuperAdmin && (
                    <button
                      type="button"
                      onClick={handleUnlockCi}
                      disabled={ciUnlocked}
                      title={ciUnlocked ? 'C.I. desbloqueado para edición' : 'Desbloquear C.I. (Solo Super Admin)'}
                      className={`absolute right-2 top-[38px] p-1 rounded-full transition-colors ${
                        ciUnlocked ? 'text-vida-main cursor-default' : 'text-gray-400 hover:text-vida-main hover:bg-vida-bg'
                      }`}
                    >
                      {ciUnlocked ? <Unlock size={16} /> : <Lock size={16} />}
                    </button>
                  )}
                </div>
                <Input type="date" label={<LabelRequired text="Nacimiento" />} {...register('fecha_nac', { required: "Requerido" })} error={errors.fecha_nac} />
                <div className="flex flex-col gap-1">
                  <label htmlFor="tipo_sangre" className="text-sm font-bold text-gray-700 ml-1">Tipo Sangre</label>
                  <select id="tipo_sangre" {...register('tipo_sangre')} className="w-full bg-vida-bg p-3 rounded-xl border border-transparent focus:bg-white outline-none">
                    <option value="">--</option>
                    {TIPOS_SANGRE.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-5 mt-4">
                <Input type="number" step="0.1" label={<LabelRequired text="Peso (Kg)" />} {...register('peso', { required: "Requerido" })} error={errors.peso} />
                <Input type="number" step="0.01" label={<LabelRequired text="Altura (m)" />} {...register('altura', { required: "Requerido" })} error={errors.altura} />
                <Input type="number" step="0.01" label="IMC" {...register('imc')} />
              </div>
              <div className="mt-4">
                <label className="flex items-start sm:items-center gap-3 cursor-pointer p-3 bg-orange-50 border border-orange-200 rounded-xl select-none">
                  <input
                    type="checkbox"
                    {...register('tiene_discapacidad_tutor')}
                    className="w-5 h-5 mt-0.5 sm:mt-0 text-vida-main rounded focus:ring-vida-main accent-vida-main flex-shrink-0"
                  />
                  <span className="text-sm text-gray-700">
                    Si la persona registrada tiene una discapacidad o limitación y cuenta con un tutor/a legal marque aquí.
                  </span>
                </label>
              </div>
            </section>

            <section className="bg-gray-50 p-6 rounded-2xl border border-gray-100">
              <h4 className="font-bold text-lg text-gray-700 mb-4 flex items-center gap-2"><MapPin size={20} /> Ubicación y Contacto</h4>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                <div className="flex flex-col gap-1">
                  <label htmlFor="departamento" className="text-sm font-bold text-gray-700 ml-1">Departamento <span className="text-red-500">*</span></label>
                  <select id="departamento" {...register('departamento', { required: "Requerido" })} className="w-full bg-white p-3 rounded-xl border border-gray-200 outline-none">
                    {DEPARTAMENTOS.map(d => <option key={d} value={d}>{d}</option>)}
                  </select>
                </div>
                <Input label={<LabelRequired text="Municipio" />} {...register('municipio', { required: "Requerido" })} error={errors.municipio} />
                <Input label={<LabelRequired text="Zona" />} {...register('zona', { required: "Requerido" })} error={errors.zona} />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mt-4">
                <Input label={<LabelRequired text="Dirección Detallada" />} className="w-full" {...register('direccion', { required: "Requerido" })} error={errors.direccion} />
                <div className="grid grid-cols-2 gap-2">
                  <Input label={<LabelRequired text="Tel. Contacto" />} icon={<Phone size={16} />} {...register('tel_contacto', { required: "Requerido" })} error={errors.tel_contacto} />
                  <Input label="Tel. Referencia" icon={<Phone size={16} />} {...register('tel_referencia')} />
                </div>
              </div>
              <div className="mt-4">
                <Input type="email" label={<LabelRequired text="Correo Electrónico" />} icon={<Mail size={16} />} {...register('email',{required: "Requerido"})} error={errors.email}/>
              </div>
            </section>

            {requiereTutor && (
              <section className="bg-orange-50 p-6 rounded-2xl border border-orange-200 animate-slideDown">
                <div className="flex items-center gap-2 text-orange-800 font-bold mb-4 border-b border-orange-200 pb-2">
                  <AlertTriangle className="h-5 w-5" />
                  <span>3.3 Tutor Legal (Obligatorio){!isMinor && ' — Discapacidad/Limitación'}</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                  <Input label={<LabelRequired text="Nombre Tutor" />} {...register('tutor.nombres', { required: "Requerido" })} error={errors.tutor?.nombres} />
                  <Input label={<LabelRequired text="Apellidos Tutor" />} {...register('tutor.apellidos', { required: "Requerido" })} error={errors.tutor?.apellidos} />
                  <Input label={<LabelRequired text="C.I. Tutor" />} {...register('tutor.ci', { required: "Requerido" })} error={errors.tutor?.ci} />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mt-4">
                  <Input label={<LabelRequired text="Dirección Tutor" />} {...register('tutor.direccion', { required: "Requerido" })} error={errors.tutor?.direccion} />
                  <div className="flex gap-2">
                    <Input label={<LabelRequired text="Teléfonos" />} {...register('tutor.telefonos', { required: "Requerido" })} error={errors.tutor?.telefonos} />
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
                <HeartPulse /> 3.2 Información Médica
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label htmlFor="tipo_diabetes" className="text-sm font-bold text-gray-700 ml-1 block mb-1">Tipo de Diabetes <span className="text-red-500">*</span></label>
                  <select id="tipo_diabetes" {...register('medical.tipo_diabetes', { required: "Requerido" })} className="w-full bg-vida-bg p-3 rounded-xl border border-transparent focus:bg-white outline-none">
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
                      toast.error("El paciente ya tiene asignados todos los tipos de insulina disponibles.");
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
                        {...register(`treatments.${index}.nombre`, { required: "Requerido" })}
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
                        {...register(`treatments.${index}.dosis_diaria`, {
                          valueAsNumber: true,
                          required: true,
                          min: 0.1,
                        })}
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
            <div className={`w-20 h-20 rounded-full flex items-center justify-center mx-auto mb-6 shadow-lg 
              ${isEditMode ? 'bg-blue-100 text-blue-600 shadow-blue-100' : 'bg-green-100 text-green-600 shadow-green-100'}`}>
              <CheckCircle size={40} />
            </div>

            <h3 className="text-2xl font-bold text-gray-800">
              {isEditMode ? 'Confirmar Cambios' : 'Verificar Datos'}
            </h3>

            {serverError && (
              <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-lg text-left text-sm font-medium animate-pulse">
                🚨 {serverError}
              </div>
            )}

            <div className="bg-white border border-gray-100 text-left p-6 rounded-2xl shadow-xl space-y-4 text-sm">
              <div className="flex justify-between border-b border-gray-100 pb-2">
                <span className="text-gray-500">Beneficiario:</span>
                <span className="font-bold text-lg">{watch('nombres')} {watch('ap_paterno')}</span>
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
          </div>
        )}

        {/* BOTONES DE NAVEGACIÓN */}
        <div className="flex justify-between mt-10 pt-6 border-t border-gray-100">

          {step > 1 ? (
            <Button type="button" variant="secondary" onClick={prevStep} className="px-8">
              Atrás
            </Button>
          ) : (
            <Button
              type="button"
              variant="secondary"
              onClick={() => navigate('/dashboard')}
              className="px-8 text-gray-500 hover:text-gray-700 bg-transparent border-transparent shadow-none hover:bg-gray-100"
            >
              Cancelar
            </Button>
          )}

          {step < 3 ? (
            <Button type="button" onClick={nextStep} className="px-8 bg-vida-main hover:bg-vida-hover text-white shadow-lg shadow-vida-main/20">
              Siguiente Paso
            </Button>
          ) : (
            <Button
              type="button"
              onClick={handleSubmit(onSubmit)}
              disabled={isSubmitting}
              className={`px-8 text-white shadow-lg w-full md:w-auto
                ${isEditMode
                  ? 'bg-blue-600 hover:bg-blue-700 shadow-blue-200'
                  : 'bg-green-600 hover:bg-green-700 shadow-green-200'
                }`}
            >
              {isSubmitting
                ? 'Procesando...'
                : (isEditMode ? 'Guardar Cambios' : 'Finalizar Registro')
              }
            </Button>
          )}
        </div>
      </form>
    </div>
  );
}