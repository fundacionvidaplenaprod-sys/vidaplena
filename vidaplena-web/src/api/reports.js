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
 * Historial de aportes solidarios de un mes o de un rango de meses: cuántos
 * vouchers hay (aceptados/declarados/observados) y el listado completo, con una
 * fila por voucher, su periodo y el departamento del beneficiario.
 * @param {string|{periodo?: string, desde?: string, hasta?: string, depto?: string}} filters
 *   Un mes "YYYY-MM" o un objeto con `desde` / `hasta` (formato "YYYY-MM") y `depto` opcional.
 */
export const getContributionsReport = async (filters) => {
  const { periodo, desde, hasta, depto } = typeof filters === 'string' ? { periodo: filters } : filters || {};
  try {
    const response = await client.get('/reports/contributions', {
      params: {
        periodo: periodo || undefined,
        periodo_desde: desde || undefined,
        periodo_hasta: hasta || undefined,
        depto: depto || undefined,
      },
    });
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

/**
 * Cantidades de insulina requeridas para 60 días de tratamiento (todos los beneficiarios
 * registrados) y perfil de la población. Solo SUPER_ADMIN.
 */
export const getDonationRequestReport = async (reparto = null) => {
  try {
    // `reparto`: porcentajes por presentación {'3ml_U100', '3ml_U200', '3ml_U300', '10ml_U100'}; sin él, solo escenarios.
    const params = reparto
      ? {
          pct_3ml_u100: reparto['3ml_U100'],
          pct_3ml_u200: reparto['3ml_U200'],
          pct_3ml_u300: reparto['3ml_U300'],
          pct_10ml_u100: reparto['10ml_U100'],
        }
      : undefined;
    const response = await client.get('/reports/donation-request', { params });
    return response.data;
  } catch (error) {
    console.error('Error al cargar la solicitud de donación:', error);
    throw error.response?.data?.detail || 'Error al cargar la solicitud de donación';
  }
};

/**
 * Cuántos beneficiarios activos pagan cada aporte mensual (Bs. 25, 50, 100…) y cuántos están exonerados.
 * @param {string} [depto] Filtra por departamento.
 */
export const getContributionAmountsReport = async (depto = '') => {
  try {
    const response = await client.get('/reports/contribution-amounts', { params: { depto: depto || undefined } });
    return response.data;
  } catch (error) {
    console.error('Error al cargar los aportes por monto:', error);
    throw error.response?.data?.detail || 'Error al cargar los aportes por monto';
  }
};
