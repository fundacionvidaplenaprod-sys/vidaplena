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
  HeartPulse, Activity, AlertTriangle, Plus, Trash2, CheckCircle
} from 'lucide-react';

// --- OPCIONES FIJAS ---
const DEPARTAMENTOS = ["La Paz", "Cochabamba", "Santa Cruz", "Oruro", "Potosí", "Chuquisaca", "Tarija", "Beni", "Pando"];
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

  const { register, control, handleSubmit, watch, trigger, reset, formState: { errors, isSubmitting } } = useForm({
    defaultValues: {
      // 3.1 Datos Generales
      nombres: '', ap_paterno: '', ap_materno: '', ci: '',
      fecha_nac: '', peso: '', altura: '', tipo_sangre: '',
      departamento: 'La Paz', municipio: '', zona: '', direccion: '',
      email: '', tel_contacto: '', tel_referencia: '',

      // 3.3 Tutor (Solo menores)
      tutor: { nombres: '', apellidos: '', ci: '', direccion: '', telefonos: '', email: '' },

      // 3.2 Información Médica
      medical: { tipo_diabetes: '', tiempo_enfermedad: '' },

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
  const selectedComplications = watch('complications_selected');

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

      console.log("🔍 DATOS RECIBIDOS DEL BACKEND:", data); // ¡Mira la consola (F12) para ver qué llega!
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
          }))
        : [{ nombre: 'Glargina', dosis_diaria: 0 }];

      // RESETEAR EL FORMULARIO CON LOS DATOS DEL BACKEND
      reset({
        nombres: data.nombres,
        ap_paterno: data.ap_paterno,
        ap_materno: data.ap_materno || '',
        ci: data.ci,
        // --- AQUÍ ESTÁ LA CORRECCIÓN DE TUS CAMPOS ---
        fecha_nac: fechaFormat,         // Asignamos la fecha formateada
        peso: data.peso || '',          // Evitamos undefined
        altura: data.altura || '',      // Evitamos undefined
        tipo_sangre: data.tipo_sangre || '', // Asegura que coincida con las opciones del <select>
        // ---------------------------------------------

        departamento: data.depto || data.departamento || 'La Paz',
        municipio: data.municipio,
        zona: data.zona,
        direccion: data.direccion,
        email: data.email || '',
        tel_contacto: data.tel_contacto || data.celular || '', // Soporte para ambos nombres de campo
        tel_referencia: data.tel_referencia || '',

        // Datos del Tutor (si existen)
        tutor: data.tutor || { nombres: '', apellidos: '', ci: '', direccion: '', telefonos: '', email: '' },

        // Datos Médicos
        medical: {
          tipo_diabetes: data.medical?.tipo_diabetes || '',
          tiempo_enfermedad: data.medical?.tiempo_enfermedad || ''
        },

        // Arrays y Especiales
        treatments: treatmentsList,
        complications_selected: complicationsCodes,
        otra_complicacion_detalle: otraDetalle
      });

    } catch (error) {
      console.error(error);
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

  // Navegación entre Pasos
  const nextStep = async () => {
    let isValid = false;
    if (step === 1) {
      const fields = [
        'nombres', 'ap_paterno', 'ci', 'fecha_nac', 'peso', 'altura', 'tipo_sangre',
        'departamento', 'municipio', 'zona', 'direccion', 'tel_contacto'
      ];
      if (isMinor) fields.push('tutor.nombres', 'tutor.apellidos', 'tutor.ci', 'tutor.direccion', 'tutor.telefonos');
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
      alert("Por favor complete los campos obligatorios marcados en rojo.");
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
        };
      });

      const invalidInsulin = normalizedTreatments.find((tx) => !tx.nombre || Number(tx.dosis_diaria || 0) <= 0);
      if (invalidInsulin) {
        setServerError('Cada tratamiento debe tener tipo de insulina y UI por día mayores a 0.');
        return;
      }

      const parsedPeso = Number(data.peso);
      const parsedAltura = Number(data.altura);

      // Payload explícito para evitar desalineación con el backend (422).
      const payload = {
        ci: data.ci,
        nombres: data.nombres,
        ap_paterno: data.ap_paterno,
        ap_materno: data.ap_materno || null,
        fecha_nac: data.fecha_nac,
        peso: Number.isFinite(parsedPeso) ? parsedPeso : null,
        altura: Number.isFinite(parsedAltura) ? parsedAltura : null,
        tipo_sangre: data.tipo_sangre || null,
        depto: data.departamento || null,
        municipio: data.municipio || null,
        zona: data.zona || null,
        direccion: data.direccion || null,
        email: data.email || null,
        tel_contacto: data.tel_contacto || null,
        tel_referencia: data.tel_referencia || null,
        medical: data.medical,
        medical_info: data.medical,
        tutor: isMinor ? data.tutor : null,
        treatments: normalizedTreatments,
        complications: formattedComplications,
      };

      if (isEditMode) {
        // --- MODO ACTUALIZACIÓN ---
        await updatePatient(id, payload);
        alert("✅ Expediente actualizado correctamente");
      } else {
        // --- MODO CREACIÓN ---
        await createPatient(payload);
        alert("✅ Paciente registrado correctamente");
      }

      navigate('/dashboard');

    } catch (err) {
      console.error(err);
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
                <Input label={<LabelRequired text="C.I." />} {...register('ci', { required: "Requerido" })} error={errors.ci} disabled={isEditMode} className={isEditMode ? "bg-gray-100" : ""} />
                <Input type="date" label={<LabelRequired text="Nacimiento" />} {...register('fecha_nac', { required: "Requerido" })} error={errors.fecha_nac} />
                <div className="flex flex-col gap-1">
                  <label className="text-sm font-bold text-gray-700 ml-1">Tipo Sangre <span className="text-red-500">*</span></label>
                  <select {...register('tipo_sangre', { required: "Requerido" })} className="w-full bg-vida-bg p-3 rounded-xl border border-transparent focus:bg-white outline-none">
                    <option value="">--</option>
                    {TIPOS_SANGRE.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                  {errors.tipo_sangre && <span className="text-red-500 text-xs font-bold">{errors.tipo_sangre.message}</span>}
                </div>
                <div className="flex gap-2">
                  <Input type="number" step="0.1" label={<LabelRequired text="Peso (Kg)" />} {...register('peso', { required: "Requerido" })} error={errors.peso} />
                  <Input type="number" step="0.01" label={<LabelRequired text="Altura (m)" />} {...register('altura', { required: "Requerido" })} error={errors.altura} />
                </div>
              </div>
            </section>

            <section className="bg-gray-50 p-6 rounded-2xl border border-gray-100">
              <h4 className="font-bold text-lg text-gray-700 mb-4 flex items-center gap-2"><MapPin size={20} /> Ubicación y Contacto</h4>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                <div className="flex flex-col gap-1">
                  <label className="text-sm font-bold text-gray-700 ml-1">Departamento <span className="text-red-500">*</span></label>
                  <select {...register('departamento', { required: "Requerido" })} className="w-full bg-white p-3 rounded-xl border border-gray-200 outline-none">
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

            {isMinor && (
              <section className="bg-orange-50 p-6 rounded-2xl border border-orange-200 animate-slideDown">
                <div className="flex items-center gap-2 text-orange-800 font-bold mb-4 border-b border-orange-200 pb-2">
                  <AlertTriangle className="h-5 w-5" />
                  <span>3.3 Tutor Legal (Obligatorio)</span>
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
                  <label className="text-sm font-bold text-gray-700 ml-1 block mb-1">Tipo de Diabetes <span className="text-red-500">*</span></label>
                  <select {...register('medical.tipo_diabetes', { required: "Requerido" })} className="w-full bg-vida-bg p-3 rounded-xl border border-transparent focus:bg-white outline-none">
                    <option value="">-- Seleccionar --</option>
                    <option value="Tipo 1">Tipo 1</option>
                    <option value="Tipo 2">Tipo 2</option>
                    <option value="Gestacional">Gestacional</option>
                    <option value="Otra">Otra</option>
                  </select>
                  {errors.medical?.tipo_diabetes && <span className="text-red-500 text-xs font-bold">{errors.medical.tipo_diabetes.message}</span>}
                </div>
                <Input label={<LabelRequired text="Tiempo con la enfermedad" />} placeholder="Ej: 2 años" {...register('medical.tiempo_enfermedad', { required: "Requerido" })} error={errors.medical?.tiempo_enfermedad} />
              </div>
            </section>

            <section className="p-6 bg-blue-50/50 rounded-2xl border border-blue-100">
              <div className="flex justify-between items-center mb-4">
                <h4 className="font-bold text-lg text-blue-800 flex items-center gap-2"><Activity size={20} /> Tratamiento de Insulina</h4>
                <button type="button" onClick={() => append({ nombre: 'Glargina', dosis_diaria: 0 })} className="text-sm bg-white border border-blue-200 text-blue-600 px-3 py-1 rounded-lg hover:bg-blue-50 font-bold flex items-center gap-1 shadow-sm">
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
                        {INSULIN_OPTIONS.map((opt) => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
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
              <h4 className="font-bold text-gray-700 mb-4">Complicaciones</h4>
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