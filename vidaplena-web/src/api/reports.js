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

/**
 * Reporte de distribución de insulina: sube el Excel de la donación y recibe el
 * reparto calculado (no guarda nada en el servidor).
 * @param {File} file - Excel .xlsx de la donación
 */
export const generateInsulinDistributionReport = async (file) => {
  try {
    const formData = new FormData();
    formData.append('file', file);
    const response = await client.post('/reports/insulin-distribution', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  } catch (error) {
    console.error('Error al generar la distribución de insulina:', error);
    throw error.response?.data?.detail || 'Error al generar el reporte de distribución';
  }
};

/**
 * Beneficiarios ACTIVOS sin aporte aceptado en un periodo. Sin `periodo`, el
 * backend usa el mes anterior. Mismo cálculo que la tarjeta "Morosos" del
 * resumen operativo.
 * @param {string} [periodo] - Formato "YYYY-MM"
 * @param {string} [depto] - Departamento (opcional)
 */
export const getMorososReport = async (periodo, depto) => {
  try {
    const response = await client.get('/reports/morosos', {
      params: { periodo: periodo || undefined, depto: depto || undefined },
    });
    return response.data;
  } catch (error) {
    console.error('Error al cargar morosos:', error);
    throw error.response?.data?.detail || 'Error al cargar el reporte de morosos';
  }
};
