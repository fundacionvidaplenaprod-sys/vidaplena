import { useState } from 'react';
import { toast } from 'react-hot-toast';
import { Plus, Trash2, ShieldCheck } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { DEPARTAMENTOS } from '../../constants/departamentos';
import { INSULIN_OPTIONS } from '../../constants/insulins';
import { ENTIDAD_TIPOS, RANGOS_EDAD, REFERENTE_VINCULOS, TIPOS_DIABETES } from '../../constants/assisted';
import ReferentPicker from './ReferentPicker';

const inputClass = 'w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-vida-main';

const fromRegistration = (reg = {}) => ({
  nombre: reg.nombre || '',
  ci: reg.ci || '',
  fecha_nacimiento: reg.fecha_nacimiento || '',
  rango_edad: reg.rango_edad || '',
  edad_aproximada: reg.edad_aproximada ?? '',
  depto: reg.depto || '',
  municipio: reg.municipio || '',
  ciudad_localidad: reg.ciudad_localidad || '',
  tipo_diabetes: reg.tipo_diabetes || '',
  anios_diabetes: reg.anios_diabetes ?? '',
  complicaciones_otras: reg.complicaciones_otras || '',
  entidad_nombre: reg.entidad_nombre || '',
  entidad_tipo: reg.entidad_tipo || '',
  referente_vinculo: reg.referente_vinculo || '',
  insumos_requeridos: reg.insumos_requeridos || '',
  urgente: Boolean(reg.urgente),
  buen_uso_comunicado: Boolean(reg.buen_uso_comunicado_at),
  treatments: (reg.treatments || []).map((t) => ({ insulina: t.insulina, dosis_diaria: t.dosis_diaria ?? '' })),
});

function Field({ label, htmlFor, children }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="block text-xs font-semibold text-gray-700 mb-1">{label}</label>
      {children}
    </div>
  );
}

/**
 * Formulario del Registro Asistido.
 *  - Los datos de la persona asistida son OPCIONALES (Art. 9): se puede guardar sin llenarlos y completar
 *    después. No hay campos para documentos, tutor, ni causas del acogimiento o de la privación de libertad.
 *  - La persona referente y su vínculo SÍ son obligatorios: es quien recibe la insulina para entregarla.
 */
export default function AssistedRegistrationForm({ initial, onSubmit, submitting = false, submitLabel = 'Guardar registro' }) {
  const [form, setForm] = useState(() => fromRegistration(initial));
  const [referente, setReferente] = useState(initial?.referente || null);
  const set = (field) => (event) =>
    setForm((prev) => ({ ...prev, [field]: event.target.type === 'checkbox' ? event.target.checked : event.target.value }));

  const setTreatment = (index, field, value) =>
    setForm((prev) => ({
      ...prev,
      treatments: prev.treatments.map((t, i) => (i === index ? { ...t, [field]: value } : t)),
    }));

  const submit = (event) => {
    event.preventDefault();
    if (!referente) {
      toast.error('Indique la persona referente: es quien recibirá la insulina.');
      return;
    }
    if (!form.referente_vinculo) {
      toast.error('Indique el vínculo de la persona referente con el beneficiario.');
      return;
    }
    onSubmit({
      ...form,
      referente_id: referente.id,
      edad_aproximada: form.edad_aproximada === '' ? null : Number(form.edad_aproximada),
      anios_diabetes: form.anios_diabetes === '' ? null : Number(form.anios_diabetes),
      treatments: form.treatments
        .filter((t) => t.insulina)
        .map((t) => ({ insulina: t.insulina, dosis_diaria: t.dosis_diaria === '' ? null : Number(t.dosis_diaria) })),
    });
  };

  return (
    <form onSubmit={submit} className="space-y-6">
      <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-sm text-blue-800 flex gap-3">
        <ShieldCheck className="flex-shrink-0 mt-0.5" size={18} />
        <div>
          <p className="font-semibold">Los datos de la persona son opcionales; la persona referente es obligatoria.</p>
          <p className="text-blue-700">
            Anote de la persona solo lo que conozca, sin insistir, y no registre las causas del acogimiento o de la privación
            de libertad, antecedentes ni su situación jurídica. El sistema le asigna su Código Interno de Registro.
          </p>
        </div>
      </div>

      <section className="space-y-3">
        <h3 className="font-bold text-gray-800">La persona (todo opcional)</h3>
        <div className="grid md:grid-cols-3 gap-3">
          <Field label="Nombre, apodo o iniciales" htmlFor="as-nombre">
            <input id="as-nombre" className={inputClass} value={form.nombre} onChange={set('nombre')} maxLength={160} />
          </Field>
          <Field label="N.° de carnet de identidad (C.I.)" htmlFor="as-ci">
            <input id="as-ci" className={inputClass} value={form.ci} onChange={set('ci')} maxLength={32} />
          </Field>
          <Field label="Fecha de nacimiento" htmlFor="as-nacimiento">
            <input id="as-nacimiento" type="date" min="1900-01-01" max={new Date().toISOString().split('T')[0]} className={inputClass} value={form.fecha_nacimiento} onChange={set('fecha_nacimiento')} />
          </Field>
          <Field label="Rango de edad" htmlFor="as-rango">
            <select id="as-rango" className={inputClass} value={form.rango_edad} onChange={set('rango_edad')}>
              <option value="">No se sabe</option>
              {RANGOS_EDAD.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </Field>
          <Field label="Edad aproximada" htmlFor="as-edad">
            <input id="as-edad" type="number" min="0" max="120" className={inputClass} value={form.edad_aproximada} onChange={set('edad_aproximada')} />
          </Field>
          <Field label="Departamento" htmlFor="as-depto">
            <select id="as-depto" className={inputClass} value={form.depto} onChange={set('depto')}>
              <option value="">No se sabe</option>
              {DEPARTAMENTOS.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </Field>
          <Field label="Municipio" htmlFor="as-municipio">
            <input id="as-municipio" className={inputClass} value={form.municipio} onChange={set('municipio')} maxLength={120} />
          </Field>
          <Field label="Ciudad o localidad" htmlFor="as-ciudad">
            <input id="as-ciudad" className={inputClass} value={form.ciudad_localidad} onChange={set('ciudad_localidad')} maxLength={120} />
          </Field>
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="font-bold text-gray-800">Salud (todo opcional)</h3>
        <div className="grid md:grid-cols-3 gap-3">
          <Field label="Tipo de diabetes" htmlFor="as-tipo-diabetes">
            <select id="as-tipo-diabetes" className={inputClass} value={form.tipo_diabetes} onChange={set('tipo_diabetes')}>
              <option value="">No se sabe</option>
              {TIPOS_DIABETES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
          <Field label="Años con la diabetes" htmlFor="as-anios">
            <input id="as-anios" type="number" min="0" max="99" className={inputClass} value={form.anios_diabetes} onChange={set('anios_diabetes')} />
          </Field>
          <div className="md:col-span-3">
            <Field label="Complicaciones u otras enfermedades (separadas por coma)" htmlFor="as-complicaciones">
              <input id="as-complicaciones" className={inputClass} value={form.complicaciones_otras} onChange={set('complicaciones_otras')} maxLength={500} placeholder="Ej: Hipertensión, neuropatía" />
            </Field>
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="font-bold text-gray-800">Entidad referente (opcional)</h3>
        <div className="grid md:grid-cols-2 gap-3">
          <Field label="Institución, centro, recinto o comunidad" htmlFor="as-entidad">
            <input id="as-entidad" className={inputClass} value={form.entidad_nombre} onChange={set('entidad_nombre')} maxLength={200} />
          </Field>
          <Field label="Tipo de entidad" htmlFor="as-entidad-tipo">
            <select id="as-entidad-tipo" className={inputClass} value={form.entidad_tipo} onChange={set('entidad_tipo')}>
              <option value="">No se sabe</option>
              {ENTIDAD_TIPOS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </Field>
        </div>
      </section>

      <section className="space-y-3 border-2 border-vida-main/20 rounded-xl p-4">
        <h3 className="font-bold text-gray-800">Persona referente (obligatoria)</h3>
        <p className="text-sm text-gray-500">
          Es quien recibe la insulina para entregarla. Debe tener nombre completo, C.I., número de contacto y una foto personal
          para identificarse. Una misma persona puede ser referente de varios beneficiarios: búsquela antes de registrarla.
        </p>
        <ReferentPicker value={referente} onChange={setReferente} />
        <Field label="Vínculo de la persona referente con el beneficiario *" htmlFor="as-ref-vinculo">
          <select id="as-ref-vinculo" className={inputClass} value={form.referente_vinculo} onChange={set('referente_vinculo')}>
            <option value="">Elegir el vínculo…</option>
            {REFERENTE_VINCULOS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </Field>
      </section>

      <section className="space-y-3">
        <h3 className="font-bold text-gray-800">Tratamiento (según lo informado por quien lo administra)</h3>
        {form.treatments.map((t, index) => (
          <div key={index} className="grid grid-cols-[1fr_9rem_2.5rem] gap-3 items-end">
            <Field label="Insulina" htmlFor={`as-ins-${index}`}>
              <select id={`as-ins-${index}`} className={inputClass} value={t.insulina} onChange={(e) => setTreatment(index, 'insulina', e.target.value)}>
                <option value="">Elegir…</option>
                {INSULIN_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                <option value="Otra">Otra / no identificada</option>
              </select>
            </Field>
            <Field label="Dosis diaria (UI)" htmlFor={`as-dosis-${index}`}>
              <input id={`as-dosis-${index}`} type="number" min="0" step="0.5" className={inputClass} value={t.dosis_diaria} onChange={(e) => setTreatment(index, 'dosis_diaria', e.target.value)} />
            </Field>
            <button
              type="button"
              aria-label="Quitar insulina"
              onClick={() => setForm((prev) => ({ ...prev, treatments: prev.treatments.filter((_, i) => i !== index) }))}
              className="p-2 text-red-500 hover:bg-red-50 rounded-lg"
            >
              <Trash2 size={18} />
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => setForm((prev) => ({ ...prev, treatments: [...prev.treatments, { insulina: '', dosis_diaria: '' }] }))}
          className="text-sm font-semibold text-vida-main inline-flex items-center gap-1 hover:underline"
        >
          <Plus size={16} /> Agregar insulina
        </button>
        <Field label="Otros insumos que requiere (jeringas, tiras reactivas, glucómetro…)" htmlFor="as-insumos">
          <input id="as-insumos" className={inputClass} value={form.insumos_requeridos} onChange={set('insumos_requeridos')} maxLength={500} />
        </Field>
      </section>

      <section className="space-y-2">
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.urgente} onChange={set('urgente')} />
          Necesidad médica inmediata
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.buen_uso_comunicado} onChange={set('buen_uso_comunicado')} />
          Se comunicó a la persona referente que los insumos son de uso personal e intransferible y que su venta o desvío está prohibido
        </label>
      </section>

      <div className="flex justify-end">
        <Button type="submit" disabled={submitting} className="w-auto px-8">
          {submitting ? 'Guardando…' : submitLabel}
        </Button>
      </div>
    </form>
  );
}
