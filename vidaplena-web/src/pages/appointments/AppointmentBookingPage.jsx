import { useState, useEffect, useRef } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import { toast } from 'react-hot-toast';
import {
  MapPin, Clock, PhoneCall, ShieldCheck, User, Calendar, QrCode,
  Upload, Download, CheckCircle, AlertTriangle, Loader2, Timer, Info,
} from 'lucide-react';
import { Input } from '../../components/ui/Input';
import { Button } from '../../components/ui/Button';
import { getAvailability, bookAppointment, getFichaUrl } from '../../api/appointments';
import { getSiteAssets } from '../../api/siteAssets';

const WHATSAPP_CONTACT = '59172966106';
const WHATSAPP_DISPLAY = '+591 72966106';
const DONATION_AMOUNT = 70;
const MIN_DAYS_AHEAD = 1;
const MAX_DAYS_AHEAD = 15;
const COUNTDOWN_SECONDS = 5 * 60;

const STEP_LABELS = ['Bienvenida', 'Registro', 'Agendamiento', 'Donación', 'Confirmación'];

const TERMS_TEXT = [
  ['Primera. Objeto', 'El presente documento establece los términos y condiciones aplicables al procedimiento de solicitud de agendamiento de fichas para atención médica especializada en diabetes, administrado por la Fundación V.I.D.A. Plena, institución privada sin fines de lucro constituida conforme a la legislación vigente del Estado Plurinacional de Bolivia. La aceptación de estos términos constituye una declaración expresa de conocimiento y conformidad por parte del solicitante.'],
  ['Segunda. Naturaleza de la Fundación', 'La Fundación V.I.D.A. Plena es una entidad privada sin fines de lucro cuyo objeto es desarrollar programas, proyectos y actividades de carácter social, educativo, preventivo y asistencial dirigidos a personas con diabetes y otras enfermedades crónicas, conforme a su Estatuto, la Constitución Política del Estado, la Ley N.° 351 de Otorgación de Personalidades Jurídicas, el Decreto Supremo N.° 1597, el Código Civil y demás normativa aplicable. No comercializa servicios médicos ni persigue fines de lucro.'],
  ['Tercera. Donación institucional', 'El solicitante declara conocer y aceptar que la Fundación V.I.D.A. Plena no comercializa servicios médicos, no percibe honorarios médicos y no obtiene lucro alguno por la gestión administrativa del agendamiento. Con la finalidad de fortalecer la sostenibilidad institucional, el solicitante manifiesta libremente su voluntad de efectuar una donación institucional de apoyo por el monto de Bs. 70 (Setenta 00/100 Bolivianos) por cada solicitud de agendamiento de ficha. Esta donación no constituye el pago del acto médico, de honorarios profesionales, consulta médica, tratamiento, diagnóstico ni de ningún servicio de salud.'],
  ['Cuarta. Destino de la donación', 'Las donaciones serán destinadas al funcionamiento institucional, programas sociales, educación en diabetes, material, comunicaciones, alquileres, servicios básicos y demás gastos necesarios para el cumplimiento del objeto fundacional. En ningún caso estos recursos serán distribuidos entre directivos, fundadores o terceros con fines de lucro.'],
  ['Quinta. Agendamiento', 'La aceptación del presente documento habilita a la Fundación V.I.D.A. Plena a gestionar administrativamente la solicitud de una ficha para atención médica especializada, de acuerdo con la disponibilidad existente. La asignación dependerá exclusivamente de la disponibilidad existente y de la programación correspondiente. No garantiza fechas, horarios ni profesionales determinados.'],
  ['Sexta. Registro y tratamiento de información médica', 'El solicitante autoriza a la Fundación V.I.D.A. Plena a recopilar, almacenar y utilizar la información personal estrictamente necesaria para gestionar el agendamiento, realizar comunicaciones relacionadas con la consulta, elaborar estadísticas institucionales, control, seguimiento médico y tratamiento, y cumplir obligaciones legales. La información tendrá carácter confidencial y solo será accesible al personal autorizado y a los profesionales que intervengan en su atención.'],
  ['Séptima. Carácter de la donación', 'El solicitante declara conocer el destino de la donación, comprender que la Fundación es una organización sin fines de lucro, realizar la donación de manera libre, consciente e informada, y entender que tiene naturaleza institucional y no constituye contraprestación por servicios médicos.'],
  ['Octava. Cancelaciones y reprogramaciones', 'Cuando por causas ajenas a la Fundación la ficha no pueda ser utilizada por el solicitante, éste deberá comunicar oportunamente dicha circunstancia. La Fundación podrá gestionar una reprogramación conforme a la disponibilidad existente. La donación institucional efectuada continuará destinada al sostenimiento de las actividades fundacionales, por tratarse de una contribución institucional y no del pago de un servicio.'],
  ['Novena. Declaración', 'El solicitante declara haber leído y comprendido íntegramente estos términos y condiciones, conocer el destino de la donación institucional y aceptar expresamente su contenido.'],
  ['Décima. Legislación aplicable', 'Este documento se rige por la Constitución Política del Estado, el Código Civil, la Ley N° 351, el Decreto Supremo N° 1597 y demás normativa boliviana aplicable.'],
  ['Décima Primera. Aceptación', 'Al aceptar electrónicamente el presente documento, el solicitante expresa su consentimiento libre, expreso e informado.'],
];

function getDateOffset(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().split('T')[0];
}

function formatCountdown(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = Math.floor(seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

const LabelRequired = ({ text }) => (
  <span className="flex items-center gap-1 font-semibold text-gray-700 text-sm">
    {text} <span className="text-red-500">*</span>
  </span>
);

export default function AppointmentBookingPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [termsAccepted, setTermsAccepted] = useState(false);

  const { register, trigger, watch, formState: { errors } } = useForm({
    defaultValues: { nombres: '', ap_paterno: '', ap_materno: '', ci: '', fecha_nac: '' },
  });

  // --- Paso 2: agendamiento ---
  const [selectedDate, setSelectedDate] = useState('');
  const [availability, setAvailability] = useState(null);
  const [loadingAvailability, setLoadingAvailability] = useState(false);
  const [selectedHora, setSelectedHora] = useState(null);

  // --- Paso 3: donación ---
  const [comprobante, setComprobante] = useState(null);
  const [countdown, setCountdown] = useState(COUNTDOWN_SECONDS);
  const timerRef = useRef(null);
  const [submitting, setSubmitting] = useState(false);
  const [bookingError, setBookingError] = useState(null);

  // --- Paso 4: confirmación ---
  const [bookingResult, setBookingResult] = useState(null);

  // --- QR de donación (configurable por SUPER_ADMIN) ---
  const [qrConsultas, setQrConsultas] = useState(null);

  useEffect(() => {
    getSiteAssets()
      .then((assets) => setQrConsultas(assets.find((a) => a.key === 'qr_consultas')?.url || null))
      .catch(() => setQrConsultas(null));
  }, []);

  useEffect(() => {
    if (step === 3) {
      setCountdown(COUNTDOWN_SECONDS);
      timerRef.current = setInterval(() => {
        setCountdown((prev) => (prev > 0 ? prev - 1 : 0));
      }, 1000);
      return () => clearInterval(timerRef.current);
    }
  }, [step]);

  const handleDateChange = async (fecha) => {
    setSelectedDate(fecha);
    setSelectedHora(null);
    setAvailability(null);
    if (!fecha) return;
    try {
      setLoadingAvailability(true);
      const data = await getAvailability(fecha);
      setAvailability(data);
    } catch (err) {
      toast.error('No se pudo consultar la disponibilidad. Intenta nuevamente.');
    } finally {
      setLoadingAvailability(false);
    }
  };

  const nextFromStep1 = async () => {
    const isValid = await trigger(['nombres', 'ap_paterno', 'ci', 'fecha_nac']);
    if (!isValid) {
      toast.error('Completa los campos obligatorios.');
      return;
    }
    setStep(2);
  };

  const nextFromStep2 = () => {
    if (!selectedDate || !selectedHora) {
      toast.error('Selecciona una fecha y un horario disponible.');
      return;
    }
    setBookingError(null);
    setStep(3);
  };

  const handleSubmitBooking = async () => {
    if (!comprobante) {
      toast.error('Sube la captura o PDF del comprobante de tu donación.');
      return;
    }
    try {
      setSubmitting(true);
      setBookingError(null);

      const formData = new FormData();
      formData.append('nombres', watch('nombres'));
      formData.append('ap_paterno', watch('ap_paterno'));
      if (watch('ap_materno')) formData.append('ap_materno', watch('ap_materno'));
      formData.append('ci', watch('ci'));
      formData.append('fecha_nac', watch('fecha_nac'));
      formData.append('fecha_cita', selectedDate);
      formData.append('hora_cita', selectedHora);
      formData.append('comprobante', comprobante);

      const result = await bookAppointment(formData);
      setBookingResult(result);
      setStep(4);
    } catch (err) {
      if (err?.status === 409) {
        toast.error('Ese horario acaba de ser tomado. Elige otro.');
        setStep(2);
        handleDateChange(selectedDate);
      } else {
        setBookingError(err?.message || 'No se pudo procesar la donación.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-vida-bg py-10 px-4">
      <div className="max-w-3xl mx-auto p-8 bg-white rounded-2xl shadow-xl relative">

        <div className="mb-8 pb-4 border-b border-gray-100">
          <h2 className="text-2xl md:text-3xl font-bold text-vida-primary">
            Sistema de Agendamiento para Atención Médica (SAPAM)
          </h2>
          <div className="flex gap-2 mt-4">
            {[0, 1, 2, 3, 4].map((num) => (
              <div key={num} className={`h-2 flex-1 rounded-full transition-all duration-300 ${step >= num ? 'bg-vida-main' : 'bg-gray-200'}`} />
            ))}
          </div>
          <p className="text-sm text-right text-gray-500 mt-2 font-medium">
            Paso {step + 1} de 5 — {STEP_LABELS[step]}
          </p>
        </div>

        {/* PASO 0: BIENVENIDA + TÉRMINOS */}
        {step === 0 && (
          <div className="space-y-6 animate-fadeIn">
            <p className="text-gray-700">
              Bienvenidos al Sistema de Agendamiento para Atención Médica (SAPAM) de la Fundación V.I.D.A. Plena.
            </p>

            <div className="bg-amber-50 border-l-4 border-amber-500 p-4 rounded-r-xl flex gap-3">
              <MapPin className="text-amber-600 flex-shrink-0 mt-0.5" size={22} />
              <p className="text-sm text-amber-800">
                <b>ATENCIÓN:</b> Este servicio está disponible solamente en la ciudad de Cochabamba, en las
                instalaciones de la Fundación V.I.D.A. Plena (Calle Juan Capriles N°346 entre Santa Cruz y
                Villarroel, zona Norte). Tome sus previsiones antes de agendar una cita de atención médica.
              </p>
            </div>

            <div className="bg-blue-50 border-l-4 border-blue-500 p-4 rounded-r-xl flex gap-3">
              <Clock className="text-blue-600 flex-shrink-0 mt-0.5" size={22} />
              <div className="text-sm text-blue-800">
                <p className="font-bold mb-1">Horarios de atención:</p>
                <p>Lunes a viernes: 08:30 a 12:30 y 14:30 a 19:30</p>
                <p>Sábados: 08:30 a 13:30</p>
                <p>Domingos y feriados: no hay atención</p>
              </div>
            </div>

            <p className="text-sm text-gray-600 flex items-center gap-2">
              <PhoneCall size={16} />
              Cualquier consulta puede comunicarse al WhatsApp{' '}
              <a href={`https://wa.me/${WHATSAPP_CONTACT}`} target="_blank" rel="noreferrer" className="font-bold underline">
                {WHATSAPP_DISPLAY}
              </a>
            </p>

            <div>
              <p className="font-bold text-gray-700 mb-2 flex items-center gap-2">
                <ShieldCheck size={18} /> Términos y condiciones del servicio
              </p>
              <div className="max-h-64 overflow-y-auto border border-gray-200 rounded-xl p-4 space-y-3 bg-gray-50 text-sm text-gray-600">
                {TERMS_TEXT.map(([title, body]) => (
                  <div key={title}>
                    <p className="font-bold text-gray-700">{title}</p>
                    <p>{body}</p>
                  </div>
                ))}
              </div>
            </div>

            <label className="flex items-start gap-3 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={termsAccepted}
                onChange={(e) => setTermsAccepted(e.target.checked)}
                className="w-5 h-5 mt-0.5 accent-vida-main cursor-pointer flex-shrink-0"
              />
              <span className="text-sm text-gray-700">
                Acepto los términos y condiciones del servicio.
              </span>
            </label>

            <div className="bg-blue-50 border border-blue-200 p-4 rounded-xl flex gap-3">
              <Info className="text-blue-800 flex-shrink-0 mt-0.5" size={20} />
              <div className="text-sm text-blue-800">
                <p className="font-bold mb-1">Atención de Trabajo Social</p>
                <p>
                  Si por motivos de vulnerabilidad económica no le es posible realizar la donación
                  institucional de Bs. 70 descrita en la cláusula tercera, por favor no marque la
                  casilla de aceptación y comuníquese directamente a nuestro WhatsApp oficial para
                  solicitar una Evaluación Socioeconómica.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* PASO 1: REGISTRO */}
        {step === 1 && (
          <div className="space-y-6 animate-fadeIn">
            <h3 className="text-xl font-bold flex items-center gap-2 text-vida-primary mb-2">
              <User /> Registro de Cita de Atención Médica
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <Input label={<LabelRequired text="Nombre(s)" />} {...register('nombres', { required: 'Requerido' })} error={errors.nombres} />
              <Input label={<LabelRequired text="Apellido Paterno" />} {...register('ap_paterno', { required: 'Requerido' })} error={errors.ap_paterno} />
              <Input label="Apellido Materno" {...register('ap_materno')} />
              <Input label={<LabelRequired text="N° de Cédula de Identidad" />} {...register('ci', { required: 'Requerido' })} error={errors.ci} />
              <Input type="date" label={<LabelRequired text="Fecha de nacimiento" />} {...register('fecha_nac', { required: 'Requerido' })} error={errors.fecha_nac} />
            </div>
          </div>
        )}

        {/* PASO 2: AGENDAMIENTO */}
        {step === 2 && (
          <div className="space-y-6 animate-fadeIn">
            <h3 className="text-xl font-bold flex items-center gap-2 text-vida-primary mb-2">
              <Calendar /> Agendamiento de Cita de Atención Médica
            </h3>
            <p className="text-sm text-gray-500">
              Solo se puede agendar desde mañana hasta 15 días continuos en adelante.
            </p>
            <Input
              type="date"
              label={<LabelRequired text="Día" />}
              min={getDateOffset(MIN_DAYS_AHEAD)}
              max={getDateOffset(MAX_DAYS_AHEAD)}
              value={selectedDate}
              onChange={(e) => handleDateChange(e.target.value)}
            />

            {loadingAvailability && (
              <p className="text-sm text-gray-500 flex items-center gap-2"><Loader2 className="animate-spin" size={16} /> Consultando disponibilidad...</p>
            )}

            {availability && !availability.disponible && (
              <div className="bg-red-50 border-l-4 border-red-500 p-4 rounded-r-xl text-sm text-red-700 flex gap-2">
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
          </div>
        )}

        {/* PASO 3: DONACIÓN */}
        {step === 3 && (
          <div className="space-y-6 animate-fadeIn text-center">
            <h3 className="text-xl font-bold flex items-center justify-center gap-2 text-vida-primary mb-2">
              <QrCode /> Donación
            </h3>
            <p className="text-sm text-gray-600">
              Por favor realice su donación de <b>Bs. {DONATION_AMOUNT}</b> a través del QR en pantalla.
            </p>
            <div className="flex justify-center">
              {qrConsultas ? (
                <img src={qrConsultas} alt="QR Donación Cita" className="w-48 h-48 border p-2 bg-white rounded-xl" />
              ) : (
                <div className="w-48 h-48 border p-2 bg-white rounded-xl flex items-center justify-center text-gray-300 text-sm text-center">
                  QR no configurado
                </div>
              )}
            </div>
            <p className="text-sm text-gray-600">
              Realizada su donación, descargue su comprobante de depósito o realice una captura del mismo.
              Puede ser una imagen o un PDF.
            </p>

            <div className={`inline-flex items-center gap-2 px-4 py-2 rounded-full font-bold text-sm ${countdown === 0 ? 'bg-red-100 text-red-700' : 'bg-vida-bg text-vida-primary'}`}>
              <Timer size={16} /> Tiempo para realizar la transacción: {formatCountdown(countdown)}
            </div>
            {countdown === 0 && (
              <p className="text-xs text-red-600">
                El tiempo sugerido expiró. Si ya realizaste la donación, puedes continuar igualmente.
              </p>
            )}

            <div className="border-2 border-dashed border-gray-300 rounded-xl p-6">
              <label className="cursor-pointer flex flex-col items-center gap-2 text-gray-500">
                <Upload size={28} />
                <span className="text-sm font-semibold">
                  {comprobante ? comprobante.name : 'Subir comprobante (imagen o PDF)'}
                </span>
                <input
                  type="file"
                  accept="image/*,application/pdf"
                  className="hidden"
                  onChange={(e) => setComprobante(e.target.files?.[0] || null)}
                />
              </label>
            </div>

            {bookingError && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm text-left">
                {bookingError}
              </div>
            )}
          </div>
        )}

        {/* PASO 4: CONFIRMACIÓN */}
        {step === 4 && bookingResult && (
          <div className="text-center space-y-6 animate-fadeIn">
            <div className="w-20 h-20 rounded-full flex items-center justify-center mx-auto shadow-lg bg-green-100 text-green-600">
              <CheckCircle size={40} />
            </div>
            <h3 className="text-2xl font-bold text-gray-800">¡Cita confirmada!</h3>
            <div className="bg-white border border-gray-100 text-left p-6 rounded-2xl shadow-xl space-y-3 text-sm max-w-md mx-auto">
              <div className="flex justify-between border-b border-gray-100 pb-2">
                <span className="text-gray-500">Paciente:</span>
                <span className="font-bold">{bookingResult.nombre_completo}</span>
              </div>
              <div className="flex justify-between border-b border-gray-100 pb-2">
                <span className="text-gray-500">Fecha:</span>
                <span className="font-bold">{bookingResult.fecha_cita}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Hora:</span>
                <span className="font-bold">{bookingResult.hora_cita}</span>
              </div>
            </div>
            <Button
              type="button"
              onClick={() => window.open(getFichaUrl(bookingResult.id, bookingResult.security_code), '_blank')}
              className="px-8 bg-vida-main hover:bg-vida-hover text-white shadow-lg shadow-vida-main/20 inline-flex items-center gap-2"
            >
              <Download size={18} /> Descargar Ficha
            </Button>
          </div>
        )}

        {/* NAVEGACIÓN */}
        {step < 4 && (
          <div className="flex justify-between mt-10 pt-6 border-t border-gray-100">
            {step > 0 ? (
              <Button type="button" variant="secondary" onClick={() => setStep((s) => s - 1)} className="px-8">
                Atrás
              </Button>
            ) : (
              <Button
                type="button"
                variant="secondary"
                onClick={() => navigate('/')}
                className="px-8 text-gray-500 hover:text-gray-700 bg-transparent border-transparent shadow-none hover:bg-gray-100"
              >
                Cancelar
              </Button>
            )}

            {step === 0 && (
              <Button
                type="button"
                onClick={() => (termsAccepted ? setStep(1) : toast.error('Debes aceptar los términos y condiciones.'))}
                disabled={!termsAccepted}
                className="px-8 bg-vida-main hover:bg-vida-hover text-white shadow-lg shadow-vida-main/20 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Siguiente
              </Button>
            )}
            {step === 1 && (
              <Button type="button" onClick={nextFromStep1} className="px-8 bg-vida-main hover:bg-vida-hover text-white shadow-lg shadow-vida-main/20">
                Siguiente
              </Button>
            )}
            {step === 2 && (
              <Button type="button" onClick={nextFromStep2} className="px-8 bg-vida-main hover:bg-vida-hover text-white shadow-lg shadow-vida-main/20">
                Siguiente
              </Button>
            )}
            {step === 3 && (
              <Button
                type="button"
                onClick={handleSubmitBooking}
                disabled={submitting}
                className="px-8 text-white shadow-lg bg-green-600 hover:bg-green-700 shadow-green-200"
              >
                {submitting ? 'Verificando...' : 'Siguiente'}
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
