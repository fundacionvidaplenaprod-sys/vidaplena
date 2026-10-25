import { useState } from 'react';
import { Plus, Trash2, ShieldCheck } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { DEPARTAMENTOS } from '../../constants/departamentos';
import { INSULIN_OPTIONS } from '../../constants/insulins';
import { ENTIDAD_TIPOS, RANGOS_EDAD, REFERENTE_VINCULOS } from '../../constants/assisted';

const inputClass = 'w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-vida-main';

const fromRegistration = (reg = {}) => ({
  nombre: reg.nombre || '',
  rango_edad: reg.rango_edad || '',
  edad_aproximada: reg.edad_aproximada ?? '',
  depto: reg.depto || '',
  ciudad_localidad: reg.ciudad_localidad || '',
  entidad_nombre: reg.entidad_nombre || '',
  entidad_tipo: reg.entidad_tipo || '',
  referente_nombre: reg.referente_nombre || '',
  referente_vinculo: reg.referente_vinculo || '',
  referente_contacto: reg.referente_contacto || '',
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
 * Formulario del Registro Asistido. NINGÚN campo es obligatorio (Art. 9 del reglamento): se puede
 * guardar vacío y completar después. No hay campos para documentos, tutor, ni causas del acogimiento
 * o de la privación de libertad, porque no se deben pedir ni registrar.
 */
export default function AssistedRegistrationForm({ initial, onSubmit, submitting = false, submitLabel = 'Guardar registro' }) {
  const [form, setForm] = useState(() => fromRegistration(initial));
  const set = (field) => (event) =>
    setForm((prev) => ({ ...prev, [field]: event.target.type === 'checkbox' ? event.target.checked : event.target.value }));

  const setTreatment = (index, field, value) =>
    setForm((prev) => ({
      ...prev,
      treatments: prev.treatments.map((t, i) => (i === index ? { ...t, [field]: value } : t)),
    }));

  const submit = (event) => {
    event.preventDefault();
    onSubmit({
      ...form,
      edad_aproximada: form.edad_aproximada === '' ? null : Number(form.edad_aproximada),
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
          <p className="font-semibold">Ningún dato es obligatorio y no se piden documentos.</p>
          <p className="text-blue-700">
            Anote solo lo que conozca, sin insistir. No registre las causas del acogimiento o de la privación de libertad,
            antecedentes ni la situación jurídica de la persona. El sistema le asigna su Código Interno de Registro.
          </p>
        </div>
      </div>

      <section className="space-y-3">
        <h3 className="font-bold text-gray-800">La persona</h3>
        <div className="grid md:grid-cols-2 gap-3">
          <Field label="Nombre, apodo o iniciales" htmlFor="as-nombre">
            <input id="as-nombre" className={inputClass} value={form.nombre} onChange={set('nombre')} maxLength={160} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Rango de edad" htmlFor="as-rango">
              <select id="as-rango" className={inputClass} value={form.rango_edad} onChange={set('rango_edad')}>
                <option value="">No se sabe</option>
                {RANGOS_EDAD.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </Field>
            <Field label="Edad aproximada" htmlFor="as-edad">
              <input id="as-edad" type="number" min="0" max="120" className={inputClass} value={form.edad_aproximada} onChange={set('edad_aproximada')} />
            </Field>
          </div>
          <Field label="Departamento" htmlFor="as-depto">
            <select id="as-depto" className={inputClass} value={form.depto} onChange={set('depto')}>
              <option value="">No se sabe</option>
              {DEPARTAMENTOS.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </Field>
          <Field label="Ciudad o localidad" htmlFor="as-ciudad">
            <input id="as-ciudad" className={inputClass} value={form.ciudad_localidad} onChange={set('ciudad_localidad')} maxLength={120} />
          </Field>
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="font-bold text-gray-800">Entidad y persona referente</h3>
        <div className="grid md:grid-cols-2 gap-3">
          <Field label="Entidad referente (institución, centro, recinto, comunidad)" htmlFor="as-entidad">
            <input id="as-entidad" className={inputClass} value={form.entidad_nombre} onChange={set('entidad_nombre')} maxLength={200} />
          </Field>
          <Field label="Tipo de entidad" htmlFor="as-entidad-tipo">
            <select id="as-entidad-tipo" className={inputClass} value={form.entidad_tipo} onChange={set('entidad_tipo')}>
              <option value="">No se sabe</option>
              {ENTIDAD_TIPOS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </Field>
          <Field label="Persona referente (enlace para la entrega)" htmlFor="as-ref-nombre">
            <input id="as-ref-nombre" className={inputClass} value={form.referente_nombre} onChange={set('referente_nombre')} maxLength={160} />
          </Field>
          <Field label="Vínculo de la persona referente" htmlFor="as-ref-vinculo">
            <select id="as-ref-vinculo" className={inputClass} value={form.referente_vinculo} onChange={set('referente_vinculo')}>
              <option value="">No se sabe</option>
              {REFERENTE_VINCULOS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </Field>
          <Field label="Contacto de la persona referente (teléfono, mensajería, correo)" htmlFor="as-ref-contacto">
            <input id="as-ref-contacto" className={inputClass} value={form.referente_contacto} onChange={set('referente_contacto')} maxLength={160} />
          </Field>
        </div>
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
          Necesidad médica inmediata (se puede entregar desde el primer contacto y completar el registro después)
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
