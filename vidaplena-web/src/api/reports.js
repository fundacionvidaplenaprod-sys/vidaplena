import client from './axios';

export const getPopulationReport = async () => {
  try {
    const response = await client.get('/reports/population');
    return response.data;
  } catch (error) {
    console.error('Error al cargar reporte de población:', error);
    throw error.response?.data?.detail || 'Error al cargar reporte de población';
  }
};

export const getInventoryReport = async () => {
  try {
    const response = await client.get('/reports/inventory');
    return response.data;
  } catch (error) {
    console.error('Error al cargar reporte de inventario:', error);
    throw error.response?.data?.detail || 'Error al cargar reporte de inventario';
  }
};

export const getAuditLogsReport = async (limit = 50) => {
  try {
    const response = await client.get('/reports/audit-logs', { params: { limit } });
    return response.data;
  } catch (error) {
    console.error('Error al cargar bitácora:', error);
    throw error.response?.data?.detail || 'Error al cargar bitácora';
  }
};

/**
 * Historial de aportes solidarios de un periodo (mes) elegido: cuántos
 * beneficiarios hicieron su aporte ese mes (aceptados/declarados/observados)
 * y el listado completo.
 * @param {string} periodo - Formato "YYYY-MM"
 */
export const getContributionsReport = async (periodo) => {
  try {
    const response = await client.get('/reports/contributions', { params: { periodo } });
    return response.data;
  } catch (error) {
    console.error('Error al cargar historial de aportes:', error);
    throw error.response?.data?.detail || 'Error al cargar historial de aportes';
  }
};
