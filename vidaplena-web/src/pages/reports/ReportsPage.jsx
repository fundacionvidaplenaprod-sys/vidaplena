import { useEffect, useMemo, useState } from 'react';
import { BarChart3, AlertTriangle, ClipboardList, RefreshCcw } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { getAuditLogsReport, getInventoryReport, getPopulationReport } from '../../api/reports';
import { toast } from 'react-hot-toast';

export default function ReportsPage() {
  const [loading, setLoading] = useState(true);
  const [population, setPopulation] = useState(null);
  const [inventory, setInventory] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);

  const criticalProducts = useMemo(
    () => inventory.filter((item) => (item.estado || '').toUpperCase().includes('CRÍTICO')),
    [inventory]
  );

  const lowProducts = useMemo(
    () => inventory.filter((item) => (item.estado || '').toUpperCase().includes('BAJO')),
    [inventory]
  );

  const loadReports = async () => {
    try {
      setLoading(true);
      const [populationData, inventoryData] = await Promise.all([
        getPopulationReport(),
        getInventoryReport(),
      ]);
      setPopulation(populationData || null);
      setInventory(Array.isArray(inventoryData) ? inventoryData : []);

      try {
        const auditData = await getAuditLogsReport(50);
        setAuditLogs(Array.isArray(auditData) ? auditData : []);
      } catch {
        setAuditLogs([]);
      }
    } catch (error) {
      toast.error(error || 'No se pudieron cargar los reportes');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadReports();
  }, []);

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto animate-fadeIn">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-800">Reportes Operativos</h1>
          <p className="text-gray-500">Control ejecutivo de beneficiarios, stock y auditoría.</p>
        </div>
        <Button
          type="button"
          className="bg-vida-main hover:bg-vida-hover text-white shadow-lg shadow-vida-main/20"
          onClick={loadReports}
          disabled={loading}
        >
          <RefreshCcw size={18} />
          {loading ? 'Actualizando...' : 'Actualizar'}
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
          <p className="text-xs text-gray-500 uppercase font-semibold">Beneficiarios totales</p>
          <p className="text-2xl font-bold text-gray-800 mt-1">{population?.total_beneficiarios ?? 0}</p>
        </div>
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
          <p className="text-xs text-gray-500 uppercase font-semibold">Activos</p>
          <p className="text-2xl font-bold text-green-700 mt-1">{population?.activos ?? 0}</p>
        </div>
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
          <p className="text-xs text-gray-500 uppercase font-semibold">Pendientes validación</p>
          <p className="text-2xl font-bold text-yellow-700 mt-1">{population?.pendientes_validacion ?? 0}</p>
        </div>
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
          <p className="text-xs text-gray-500 uppercase font-semibold">Inactivos / morosos</p>
          <p className="text-2xl font-bold text-red-700 mt-1">{population?.inactivos_morosos ?? 0}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <section className="bg-white rounded-2xl shadow-xl border border-gray-100 p-6">
          <h2 className="text-xl font-bold text-gray-800 mb-4 flex items-center gap-2">
            <BarChart3 size={20} /> Estado de inventario
          </h2>
          <div className="flex gap-3 mb-4">
            <span className="text-xs font-semibold px-2 py-1 rounded-full bg-red-100 text-red-700">
              Críticos: {criticalProducts.length}
            </span>
            <span className="text-xs font-semibold px-2 py-1 rounded-full bg-yellow-100 text-yellow-700">
              Bajos: {lowProducts.length}
            </span>
          </div>
          <div className="overflow-x-auto border border-gray-100 rounded-xl">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Producto</th>
                  <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Presentación</th>
                  <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Stock</th>
                  <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Estado</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {inventory.length ? (
                  inventory.map((item, index) => (
                    <tr key={`${item.producto || 'prod'}-${index}`}>
                      <td className="px-4 py-3 text-sm text-gray-800">{item.producto || 'Sin nombre'}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">{item.presentacion || '-'}</td>
                      <td className="px-4 py-3 text-sm text-right text-gray-700">{item.stock_total ?? 0}</td>
                      <td className="px-4 py-3 text-sm text-right">
                        <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-semibold ${
                          (item.estado || '').includes('CRÍTICO')
                            ? 'bg-red-100 text-red-700'
                            : item.estado === 'BAJO'
                            ? 'bg-yellow-100 text-yellow-700'
                            : 'bg-green-100 text-green-700'
                        }`}>
                          {item.estado || 'OK'}
                        </span>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan="4" className="px-4 py-6 text-center text-gray-400">
                      Sin datos de inventario.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="bg-white rounded-2xl shadow-xl border border-gray-100 p-6">
          <h2 className="text-xl font-bold text-gray-800 mb-4 flex items-center gap-2">
            <ClipboardList size={20} /> Auditoría reciente
          </h2>
          {auditLogs.length === 0 ? (
            <div className="bg-yellow-50 border border-yellow-100 rounded-xl p-4 text-sm text-yellow-800 flex items-start gap-2">
              <AlertTriangle size={16} className="mt-0.5" />
              <span>
                No hay eventos de auditoría visibles o el usuario actual no tiene permisos de SUPER_ADMIN.
              </span>
            </div>
          ) : (
            <div className="space-y-2 max-h-[420px] overflow-auto pr-1">
              {auditLogs.map((log, index) => (
                <div key={`${log.usuario_id || 'u'}-${index}`} className="border border-gray-100 rounded-xl p-3">
                  <p className="text-sm font-semibold text-gray-800">{log.accion}</p>
                  <p className="text-xs text-gray-500">
                    Usuario #{log.usuario_id || '-'} | {new Date(log.fecha).toLocaleString()}
                  </p>
                  <p className="text-xs text-gray-600 mt-1 break-all">
                    Detalle: {log.detalle ? JSON.stringify(log.detalle) : 'Sin payload'}
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
