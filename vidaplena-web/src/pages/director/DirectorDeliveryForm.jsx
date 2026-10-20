import React, { useEffect, useState } from 'react';
import { AlertCircle, CheckCircle, Loader2, Plus, Search, UserCheck, X } from 'lucide-react';
import toast from 'react-hot-toast';
import {
  createDeliveryBatch,
  searchBeneficiaries,
  searchLastDelivery,
} from '../../api/directorDeliveries';
import {
  INSULIN_OPTIONS,
  PRESENTACION_OPTIONS,
  brandOptions,
  guessBrand,
} from '../../constants/insulins';

// Custom hook para debounce
function useDebounce(value, delay) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handler = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(handler);
  }, [value, delay]);
  return debounced;
}

const getLocalDateString = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

let rowSeq = 0;
const newRow = (extra = {}) => ({
  key: `row-${(rowSeq += 1)}`,
  insulinType: '',
  fichaNombre: '',
  dosis: null,
  presentacion: '',
  marca: '',
  cantidad: '',
  ...extra,
});

// Una fila por cada insulina anotada en la ficha del beneficiario.
const rowsFromTreatments = (tratamientos = []) => {
  const seen = new Set();
  const rows = [];
  tratamientos.forEach((t) => {
    const tipo = t.insulina || t.nombre;
    if (seen.has(tipo)) return;
    seen.add(tipo);
    rows.push(
      newRow({
        insulinType: tipo,
        fichaNombre: t.nombre,
        dosis: t.dosis_diaria,
        marca: guessBrand(t.insulina, t.nombre),
      }),
    );
  });
  return rows;
};

const fullName = (p) => [p.nombres, p.ap_paterno, p.ap_materno].filter(Boolean).join(' ');

// Cuaderno de entrega de insulina: se busca a la persona, se despliegan sus insulinas anotadas y
// por cada una se elige la presentación y la marca; la cantidad la llena la Directora a su criterio.
export default function DirectorDeliveryForm() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState(null);
  const [manual, setManual] = useState(false);

  const [nombres, setNombres] = useState('');
  const [apPaterno, setApPaterno] = useState('');
  const [apMaterno, setApMaterno] = useState('');

  const [rows, setRows] = useState([]);
  const [deliveryDate, setDeliveryDate] = useState(getLocalDateString());
  const [lastDelivery, setLastDelivery] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const debouncedQuery = useDebounce(query, 400);
  const debouncedNombres = useDebounce(nombres, 500);
  const debouncedApPaterno = useDebounce(apPaterno, 500);
  const debouncedApMaterno = useDebounce(apMaterno, 500);

  // Búsqueda de beneficiarios mientras escribe
  useEffect(() => {
    if (selected || manual || debouncedQuery.trim().length < 2) {
      setResults([]);
      return undefined;
    }
    let cancelled = false;
    (async () => {
      try {
        setSearching(true);
        const data = await searchBeneficiaries(debouncedQuery.trim());
        if (!cancelled) setResults(data || []);
      } catch {
        if (!cancelled) toast.error('No se pudo buscar al beneficiario');
      } finally {
        if (!cancelled) setSearching(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery, selected, manual]);

  // Persona fuera del padrón: aviso de entrega previa por nombre
  useEffect(() => {
    if (!manual || !debouncedNombres.trim() || !debouncedApPaterno.trim()) {
      if (manual) setLastDelivery(null);
      return;
    }
    searchLastDelivery({ nombres: debouncedNombres, apPaterno: debouncedApPaterno, apMaterno: debouncedApMaterno })
      .then((data) => setLastDelivery(data || null))
      .catch(() => setLastDelivery(null));
  }, [manual, debouncedNombres, debouncedApPaterno, debouncedApMaterno]);

  const pickBeneficiary = (beneficiary) => {
    setSelected(beneficiary);
    setManual(false);
    setQuery('');
    setResults([]);
    setLastDelivery(beneficiary.ultima_entrega || null);
    setRows(rowsFromTreatments(beneficiary.tratamientos));
  };

  const clearPerson = () => {
    setSelected(null);
    setManual(false);
    setLastDelivery(null);
    setRows([]);
    setNombres('');
    setApPaterno('');
    setApMaterno('');
  };

  const startManual = () => {
    setSelected(null);
    setManual(true);
    setResults([]);
    setLastDelivery(null);
    setRows([newRow()]);
  };

  const updateRow = (key, changes) =>
    setRows((prev) => prev.map((row) => (row.key === key ? { ...row, ...changes } : row)));
  const removeRow = (key) => setRows((prev) => prev.filter((row) => row.key !== key));
  const addRow = () => setRows((prev) => [...prev, newRow()]);

  const diffDays = lastDelivery
    ? Math.ceil(Math.abs(new Date() - new Date(lastDelivery.delivery_date)) / (1000 * 60 * 60 * 24))
    : null;
  const alertWarning = diffDays !== null && diffDays < 25;

  const personReady = selected || (manual && nombres.trim() && apPaterno.trim());

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!personReady) {
      toast.error('Busque y elija al beneficiario, o ingrese sus nombres.');
      return;
    }
    const filled = rows.filter((row) => row.cantidad.trim());
    if (filled.length === 0) {
      toast.error('Escriba la cantidad de al menos una insulina entregada.');
      return;
    }
    const incomplete = filled.find((row) => !row.insulinType || !row.presentacion);
    if (incomplete) {
      toast.error(
        incomplete.insulinType
          ? `Elija la presentación de ${incomplete.insulinType}.`
          : 'Elija el tipo de insulina de cada fila con cantidad.',
      );
      return;
    }

    const items = filled.map((row) => ({
      insulin_type: row.insulinType,
      presentacion: row.presentacion,
      marca: row.marca || null,
      quantity: row.cantidad.trim(),
    }));
    const payload = selected
      ? { patient_id: selected.id, delivery_date: deliveryDate, items }
      : {
          patient_nombres: nombres.trim(),
          patient_ap_paterno: apPaterno.trim(),
          patient_ap_materno: apMaterno.trim() || null,
          delivery_date: deliveryDate,
          items,
        };

    try {
      setSubmitting(true);
      await createDeliveryBatch(payload);
      toast.success(items.length > 1 ? 'Entregas registradas exitosamente' : 'Entrega registrada exitosamente');
      clearPerson();
      setQuery('');
      setDeliveryDate(getLocalDateString());
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Error al registrar la entrega');
    } finally {
      setSubmitting(false);
    }
  };

  const inputClass = 'w-full p-3 border-2 border-gray-300 rounded-xl text-lg focus:border-green-500';

  return (
    <form onSubmit={handleSubmit} className="space-y-8">
      {/* 1. PERSONA */}
      <div className="bg-gray-50 p-6 rounded-2xl border border-gray-200">
        <h2 className="text-2xl font-bold text-gray-700 mb-4 flex items-center justify-between">
          1. Beneficiario
          {searching && <Loader2 className="w-5 h-5 text-gray-400 animate-spin" />}
        </h2>

        {selected ? (
          <div className="flex items-start justify-between gap-4 bg-white border-2 border-green-300 rounded-2xl p-4">
            <div className="flex items-start gap-3">
              <UserCheck className="w-7 h-7 text-green-600 mt-1" />
              <div>
                <p className="text-xl font-bold text-gray-800">{fullName(selected)}</p>
                <p className="text-sm text-gray-500">
                  C.I.: <strong>{selected.ci || 'Sin C.I.'}</strong>
                  {selected.depto ? ` · ${selected.depto}` : ''}
                  {selected.edad != null ? ` · ${selected.edad} años` : ''} · {selected.estado}
                </p>
              </div>
            </div>
            <button type="button" onClick={clearPerson} className="text-sm font-semibold text-gray-500 hover:text-gray-800">
              Cambiar
            </button>
          </div>
        ) : manual ? (
          <div className="space-y-4">
            <div className="grid md:grid-cols-3 gap-4">
              <div>
                <label className="block text-lg font-bold text-gray-700 mb-2">Nombres *</label>
                <input type="text" placeholder="Ej. Juan Carlos" className={inputClass} value={nombres} onChange={(e) => setNombres(e.target.value)} />
              </div>
              <div>
                <label className="block text-lg font-bold text-gray-700 mb-2">Apellido Paterno *</label>
                <input type="text" placeholder="Ej. Perez" className={inputClass} value={apPaterno} onChange={(e) => setApPaterno(e.target.value)} />
              </div>
              <div>
                <label className="block text-lg font-bold text-gray-700 mb-2">Apellido Materno</label>
                <input type="text" placeholder="Ej. Arce" className={inputClass} value={apMaterno} onChange={(e) => setApMaterno(e.target.value)} />
              </div>
            </div>
            <button type="button" onClick={clearPerson} className="text-sm font-semibold text-green-700 hover:underline">
              ← Volver a buscar en la lista de beneficiarios
            </button>
          </div>
        ) : (
          <div>
            <label className="block text-lg font-bold text-gray-700 mb-2" htmlFor="buscar-beneficiario">
              Buscar por nombre, apellido o C.I.
            </label>
            <div className="relative">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
              <input
                id="buscar-beneficiario"
                type="text"
                autoComplete="off"
                placeholder="Ej. Quispe, o 4503853"
                className={`${inputClass} pl-12`}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>

            {results.length > 0 && (
              <ul className="mt-3 bg-white border-2 border-gray-200 rounded-2xl divide-y divide-gray-100 overflow-hidden">
                {results.map((b) => (
                  <li key={b.id}>
                    <button
                      type="button"
                      onClick={() => pickBeneficiary(b)}
                      className="w-full text-left px-4 py-3 hover:bg-green-50 flex items-center justify-between gap-3"
                    >
                      <span>
                        <span className="block text-lg font-semibold text-gray-800">{fullName(b)}</span>
                        <span className="block text-sm text-gray-500">
                          C.I.: {b.ci || 'Sin C.I.'}
                          {b.depto ? ` · ${b.depto}` : ''}
                        </span>
                      </span>
                      <span className="text-xs text-gray-400 text-right">
                        {b.tratamientos.length
                          ? b.tratamientos.map((t) => t.nombre).join(', ')
                          : 'Sin insulina anotada'}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {!searching && debouncedQuery.trim().length >= 2 && results.length === 0 && (
              <p className="mt-3 text-sm text-gray-500">No hay beneficiarios con ese dato.</p>
            )}

            <button type="button" onClick={startManual} className="mt-4 text-sm font-semibold text-green-700 hover:underline">
              La persona no está en la lista: ingresar sus nombres
            </button>
          </div>
        )}
      </div>

      {/* ALERTA VISUAL DINÁMICA */}
      {lastDelivery && (
        <div className={`p-6 rounded-2xl border-2 flex items-start space-x-4 ${alertWarning ? 'bg-red-50 border-red-400 text-red-900' : 'bg-blue-50 border-blue-200 text-blue-900'}`}>
          {alertWarning ? <AlertCircle className="w-8 h-8 text-red-600 flex-shrink-0 mt-1" /> : <CheckCircle className="w-8 h-8 text-blue-500 flex-shrink-0 mt-1" />}
          <div>
            <h4 className={`text-xl font-bold mb-2 ${alertWarning ? 'text-red-700' : 'text-blue-800'}`}>
              {alertWarning ? '¡ATENCIÓN! Posible entrega duplicada adelantada' : 'Información de última entrega'}
            </h4>
            <p className="text-lg">
              Paciente: <strong>{lastDelivery.patient_nombres} {lastDelivery.patient_ap_paterno} {lastDelivery.patient_ap_materno}</strong><br />
              Última entrega: <strong>{lastDelivery.delivery_date}</strong><br />
              Recibió: <strong>{lastDelivery.quantity}</strong> de <strong>{lastDelivery.insulin_type}</strong>
              {lastDelivery.marca ? <> ({lastDelivery.marca}{lastDelivery.presentacion ? `, ${lastDelivery.presentacion}` : ''})</> : null}
            </p>
            {alertWarning && <p className="mt-3 font-bold bg-red-200 inline-block px-3 py-1 rounded text-red-800">Han pasado menos de 25 días.</p>}
          </div>
        </div>
      )}

      {/* 2. INSULINAS */}
      {(selected || manual) && (
        <div className="bg-gray-50 p-6 rounded-2xl border border-gray-200">
          <h2 className="text-2xl font-bold text-gray-700 mb-1">2. Insulinas</h2>
          <p className="text-sm text-gray-500 mb-5">
            {selected && rows.length > 0
              ? 'Estas son las insulinas anotadas en su ficha. Elija la presentación y la marca, y escriba la cantidad que entrega; deje en blanco la cantidad de la que no entrega.'
              : 'Elija la insulina, la presentación y la marca, y escriba la cantidad que entrega.'}
          </p>
          {selected && rows.length === 0 && (
            <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mb-4">
              Esta persona no tiene insulina anotada en su ficha. Agregue la que entrega.
            </p>
          )}

          <div className="space-y-4">
            {rows.map((row) => {
              const fromFicha = Boolean(row.fichaNombre);
              const brands = brandOptions(row.insulinType);
              return (
                <div key={row.key} className="bg-white border-2 border-gray-200 rounded-2xl p-4" data-testid="fila-insulina">
                  <div className="flex items-start justify-between gap-3 mb-3">
                    {fromFicha ? (
                      <div>
                        <p className="text-lg font-bold text-gray-800">{row.insulinType}</p>
                        <p className="text-xs text-gray-500">
                          En su ficha: {row.fichaNombre}
                          {row.dosis ? ` · ${row.dosis} UI/día` : ''}
                        </p>
                      </div>
                    ) : (
                      <div className="flex-1">
                        <label className="block text-sm font-bold text-gray-700 mb-1">Insulina</label>
                        <select
                          aria-label="Insulina"
                          value={row.insulinType}
                          onChange={(e) => updateRow(row.key, { insulinType: e.target.value, marca: '' })}
                          className="w-full p-3 border-2 border-gray-300 rounded-xl text-lg bg-white"
                        >
                          <option value="">Elegir insulina…</option>
                          {INSULIN_OPTIONS.map((opt) => (
                            <option key={opt.value} value={opt.value}>{opt.label}</option>
                          ))}
                        </select>
                      </div>
                    )}
                    {!fromFicha && (
                      <button type="button" onClick={() => removeRow(row.key)} aria-label="Quitar esta insulina" className="text-gray-400 hover:text-red-600 mt-1">
                        <X className="w-5 h-5" />
                      </button>
                    )}
                  </div>

                  <div className="grid md:grid-cols-3 gap-4">
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-1">Presentación</label>
                      <select
                        aria-label={`Presentación de ${row.insulinType || 'la insulina'}`}
                        value={row.presentacion}
                        onChange={(e) => updateRow(row.key, { presentacion: e.target.value })}
                        className="w-full p-3 border-2 border-gray-300 rounded-xl text-lg bg-white"
                      >
                        <option value="">Elegir…</option>
                        {PRESENTACION_OPTIONS.map((opt) => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-1">Marca</label>
                      <select
                        aria-label={`Marca de ${row.insulinType || 'la insulina'}`}
                        value={row.marca}
                        onChange={(e) => updateRow(row.key, { marca: e.target.value })}
                        disabled={!row.insulinType}
                        className="w-full p-3 border-2 border-gray-300 rounded-xl text-lg bg-white disabled:bg-gray-100"
                      >
                        <option value="">Sin especificar</option>
                        {brands.map((brand) => (
                          <option key={brand} value={brand}>{brand}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-1">Cantidad</label>
                      <input
                        type="text"
                        aria-label={`Cantidad de ${row.insulinType || 'la insulina'}`}
                        placeholder="Ej. 4 pens, 1 frasco"
                        value={row.cantidad}
                        onChange={(e) => updateRow(row.key, { cantidad: e.target.value })}
                        className="w-full p-3 border-2 border-gray-300 rounded-xl text-lg focus:border-green-500"
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          <button type="button" onClick={addRow} className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-green-700 hover:underline">
            <Plus className="w-4 h-4" /> Agregar otra insulina
          </button>

          <div className="mt-6">
            <label className="block text-lg font-bold text-gray-700 mb-2">Fecha de Entrega *</label>
            <input
              type="date"
              required
              value={deliveryDate}
              onChange={(e) => setDeliveryDate(e.target.value)}
              className="w-full md:w-1/2 p-4 border-2 border-gray-300 rounded-xl text-lg focus:border-green-500"
            />
          </div>
        </div>
      )}

      <button
        type="submit"
        disabled={submitting || !personReady}
        className={`w-full text-white font-bold py-5 rounded-2xl text-2xl mt-4 transition-colors shadow-lg ${
          submitting || !personReady ? 'bg-gray-400' : 'bg-green-600 hover:bg-green-700'
        }`}
      >
        {submitting ? 'Registrando...' : 'Confirmar Registro'}
      </button>
    </form>
  );
}
