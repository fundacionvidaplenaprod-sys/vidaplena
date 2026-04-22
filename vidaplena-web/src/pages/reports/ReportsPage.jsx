import { useEffect, useMemo, useState } from 'react';
import { BarChart3, AlertTriangle, ClipboardList, RefreshCcw, ShieldCheck, Clock, User } from 'lucide-react';
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
          {/* Título */}
          <h2 className="text-xl font-bold text-gray-800 flex items-center gap-2 mb-3">
            <ClipboardList size={20} /> Auditoría reciente
          </h2>

          {/* Leyenda de colores */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 bg-gray-50 border border-gray-100 rounded-xl px-4 py-2.5 mb-4">
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wider w-full">Leyenda de colores:</p>
            {[
              { dot: 'bg-green-500',  badge: 'bg-green-100 text-green-700',   label: 'Creación',                    title: 'Registro de nuevo paciente, producto o lote' },
              { dot: 'bg-yellow-500', badge: 'bg-yellow-100 text-yellow-700',  label: 'Actualización',               title: 'Ajuste de asignación, importación CSV o cambio de estado manual' },
              { dot: 'bg-red-500',    badge: 'bg-red-100 text-red-700',        label: 'Eliminación',                 title: 'Eliminación de registros del sistema' },
              { dot: 'bg-purple-500', badge: 'bg-purple-100 text-purple-700',  label: 'Validación / Consolidación',  title: 'Validación de aporte o consolidación de lote de insulina' },
              { dot: 'bg-orange-500', badge: 'bg-orange-100 text-orange-700',  label: 'Distribución de insulina',    title: 'Cálculo y distribución equitativa de insulina entre beneficiarios según diagnóstico' },
              { dot: 'bg-blue-400',   badge: 'bg-blue-100 text-blue-700',      label: 'Otros eventos',               title: 'Entrega registrada, recibo subido u otras acciones del sistema' },
            ].map(({ dot, badge, label, title }) => (
              <span key={label} className="flex items-center gap-1.5" title={title}>
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dot}`} />
                <span className={`text-xs font-semibold px-1.5 py-0.5 rounded-full ${badge} cursor-help`}>{label}</span>
              </span>
            ))}
            <p className="text-[10px] text-gray-400 w-full mt-0.5">Pase el cursor sobre cada etiqueta para ver más detalles.</p>
          </div>
          {auditLogs.length === 0 ? (
            <div className="bg-yellow-50 border border-yellow-100 rounded-xl p-4 text-sm text-yellow-800 flex items-start gap-2">
              <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
              <span>
                No hay eventos de auditoría visibles o el usuario actual no tiene permisos de SUPER_ADMIN.
              </span>
            </div>
          ) : (
            <div className="space-y-2 max-h-[420px] overflow-auto pr-1 custom-scrollbar">
              {auditLogs.map((log, index) => {
                // Formateo de fecha legible
                const fecha = log.fecha ? new Date(log.fecha) : null;
                const fechaStr = fecha
                  ? fecha.toLocaleDateString('es-BO', { day: '2-digit', month: 'short', year: 'numeric' })
                  : '—';
                const horaStr = fecha
                  ? fecha.toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit' })
                  : '';

                // Color del badge según la acción
                const accion = (log.accion || '').toUpperCase();
                let badgeClass = 'bg-blue-100 text-blue-700';
                let dotClass = 'bg-blue-400';

                // Distribución de insulina (acción específica del sistema)
                if (accion.includes('CALCULATE') || accion.includes('DISTRIBUT') || accion.includes('DISTRIB')) {
                  badgeClass = 'bg-orange-100 text-orange-700';
                  dotClass = 'bg-orange-500';
                // Creación de nuevos registros
                } else if (accion.includes('CREA') || accion.includes('CREATE') || accion.includes('IMPORT') || accion.includes('ADD')) {
                  badgeClass = 'bg-green-100 text-green-700';
                  dotClass = 'bg-green-500';
                // Eliminación
                } else if (accion.includes('ELIMIN') || accion.includes('DELET') || accion.includes('REMOV')) {
                  badgeClass = 'bg-red-100 text-red-700';
                  dotClass = 'bg-red-500';
                // Actualización / modificación
                } else if (accion.includes('UPDATE') || accion.includes('ACTUAL') || accion.includes('MODIF') || accion.includes('RESET') || accion.includes('CAMBIAR')) {
                  badgeClass = 'bg-yellow-100 text-yellow-700';
                  dotClass = 'bg-yellow-500';
                // Validación / consolidación / activación
                } else if (accion.includes('VALID') || accion.includes('APROB') || accion.includes('ACTIV') || accion.includes('CONSOLID')) {
                  badgeClass = 'bg-purple-100 text-purple-700';
                  dotClass = 'bg-purple-500';
                }

                // Payload: mostrar de forma legible
                let detalleDisplay = null;
                if (log.detalle && typeof log.detalle === 'object') {
                  const entries = Object.entries(log.detalle).slice(0, 4);
                  if (entries.length > 0) {
                    detalleDisplay = (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {entries.map(([k, v]) => (
                          <span key={k} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-md font-mono">
                            <span className="text-gray-400">{k}:</span> {String(v).slice(0, 40)}
                          </span>
                        ))}
                      </div>
                    );
                  }
                } else if (log.detalle && typeof log.detalle === 'string') {
                  detalleDisplay = (
                    <p className="mt-1 text-xs text-gray-500 truncate">{log.detalle}</p>
                  );
                }

                return (
                  <div
                    key={`${log.usuario_id || 'u'}-${index}`}
                    className="flex gap-3 items-start border border-gray-100 rounded-xl p-3 hover:bg-gray-50/70 transition-colors"
                  >
                    {/* Dot indicador */}
                    <div className="mt-1.5 flex-shrink-0">
                      <span className={`block w-2.5 h-2.5 rounded-full ${dotClass}`} />
                    </div>

                    {/* Contenido */}
                    <div className="flex-1 min-w-0">
                      {/* Fila superior: acción + fecha */}
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${badgeClass}`}>
                          {log.accion || 'EVENTO'}
                        </span>
                        <span className="flex items-center gap-1 text-xs text-gray-400">
                          <Clock size={11} />
                          {fechaStr} {horaStr && `· ${horaStr}`}
                        </span>
                      </div>

                      {/* Actor */}
                      <div className="flex items-center gap-1 mt-1.5 text-xs text-gray-500">
                        <User size={11} />
                        <span>Usuario <span className="font-semibold text-gray-700">#{log.usuario_id ?? '—'}</span></span>
                      </div>

                      {/* Payload formateado */}
                      {detalleDisplay}
                    </div>

                    {/* Icono decorativo */}
                    <ShieldCheck size={14} className="text-gray-200 flex-shrink-0 mt-1" />
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
