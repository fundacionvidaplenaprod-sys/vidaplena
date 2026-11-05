import { useCallback, useEffect, useState } from 'react';
import { Wallet } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { DEPARTAMENTOS } from '../../constants/departamentos';
import { getContributionAmountsReport } from '../../api/reports';

const fmtBs = (value) => `Bs. ${Number(value).toLocaleString('es-BO', { maximumFractionDigits: 2 })}`;
const fmtPct = (cantidad, total) =>
  total ? `${((cantidad * 100) / total).toLocaleString('es-BO', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %` : '-';

/**
 * Cuántos beneficiarios activos pagan cada aporte mensual (Bs. 25, 50, 100…) y cuántos están exonerados.
 * Cada beneficiario cuenta en un solo grupo. Las personas del Registro Asistido no pagan y van aparte.
 */
export default function ContributionAmountsCard() {
  const [depto, setDepto] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setData(await getContributionAmountsReport(depto));
    } catch (error) {
      toast.error(typeof error === 'string' ? error : 'No se pudo cargar el reporte de aportes.');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [depto]);

  useEffect(() => {
    const timer = setTimeout(load, 0);
    return () => clearTimeout(timer);
  }, [load]);

  const filas = data
    ? [
        { clave: 'vulnerabilidad', etiqueta: 'Exonerados por vulnerabilidad (evaluación socioeconómica)', cantidad: data.exonerados_vulnerabilidad, exonerado: true },
        { clave: 'cargo', etiqueta: 'Exonerados por cargo (responsable departamental)', cantidad: data.exonerados_cargo, exonerado: true },
        ...data.montos.map((m) => ({
          clave: `monto-${m.monto}`,
          etiqueta: `Pagan ${fmtBs(m.monto)} al mes${m.reducido ? ' (aporte reducido)' : ''}`,
          cantidad: m.cantidad,
          total_bs: m.total_bs,
        })),
        { clave: 'sin-monto', etiqueta: 'Sin monto definido (aún no descargan su compromiso)', cantidad: data.sin_monto },
      ]
    : [];

  return (
    <section className="bg-white rounded-2xl shadow-xl border border-gray-100 p-6 mb-8">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-4">
        <div>
          <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2">
            <Wallet size={20} /> Beneficiarios activos según su aporte mensual
          </h2>
          <p className="text-sm text-gray-500">Cuántos están exonerados y cuántos pagan Bs. 25, Bs. 50, Bs. 100… Cada uno cuenta en un solo grupo.</p>
        </div>
        <select
          aria-label="Departamento"
          value={depto}
          onChange={(e) => setDepto(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white"
        >
          <option value="">Todos los departamentos</option>
          {DEPARTAMENTOS.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      </div>

      {loading ? (
        <p className="text-sm text-gray-500">Cargando…</p>
      ) : !data ? (
        <p className="text-sm text-gray-500">No se pudo cargar el reporte.</p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="border-b border-gray-100">
                <tr>
                  <th className="py-2 pr-4 text-xs font-bold text-gray-500 uppercase tracking-wider">Grupo</th>
                  <th className="py-2 px-4 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Beneficiarios</th>
                  <th className="py-2 px-4 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">%</th>
                  <th className="py-2 pl-4 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Aporte mensual</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filas.map((fila) => (
                  <tr key={fila.clave}>
                    <td className={`py-2 pr-4 text-sm ${fila.exonerado ? 'text-blue-700' : 'text-gray-800'}`}>{fila.etiqueta}</td>
                    <td className="py-2 px-4 text-sm text-right font-semibold text-gray-800">{fila.cantidad}</td>
                    <td className="py-2 px-4 text-sm text-right text-gray-500">{fmtPct(fila.cantidad, data.total_activos)}</td>
                    <td className="py-2 pl-4 text-sm text-right text-gray-600">{fila.total_bs != null ? fmtBs(fila.total_bs) : '-'}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="border-t border-gray-200">
                <tr>
                  <td className="py-2 pr-4 text-sm font-bold text-gray-900">Total de beneficiarios activos</td>
                  <td className="py-2 px-4 text-sm text-right font-bold text-gray-900">{data.total_activos}</td>
                  <td className="py-2 px-4" />
                  <td className="py-2 pl-4 text-sm text-right font-bold text-gray-900" title="Suma de los aportes comprometidos de quienes pagan">
                    {fmtBs(data.ingreso_mensual_comprometido_bs)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="text-xs text-gray-500 mt-3">
            Exonerados en total: <b>{data.exonerados_total}</b> · Pagan: <b>{data.pagan}</b>. Además, hay <b>{data.registro_asistido}</b> persona(s) activa(s) del
            Registro Asistido, que no pagan (gratuito) y no están incluidas en el total de arriba.
          </p>
        </>
      )}
    </section>
  );
}
