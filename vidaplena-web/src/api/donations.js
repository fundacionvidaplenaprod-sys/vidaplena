import client from './axios';

// --- Almacén: ingreso por el Excel de la donación y reparto con el motor del reporte -----------------------
const detail = (error, fallback) => {
  const d = error.response?.data?.detail;
  return typeof d === 'string' ? d : fallback;
};

const excelForm = (file) => {
  const formData = new FormData();
  formData.append('file', file);
  return formData;
};

/** Lee el Excel de la donación y muestra lo que se ingresaría, sin guardar nada. */
export const previewDonationIntake = async (file) => {
  try {
    const response = await client.post('/donations/intake/preview', excelForm(file), {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  } catch (error) {
    console.error('Error al revisar el Excel de la donación:', error);
    throw detail(error, 'No se pudo leer el Excel de la donación');
  }
};

/** Ingresa al almacén todas las filas del Excel (o ninguna si alguna tiene error). */
export const createDonationIntake = async (file) => {
  try {
    const response = await client.post('/donations/intake', excelForm(file), {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  } catch (error) {
    console.error('Error al ingresar la donación:', error);
    throw detail(error, 'No se pudo ingresar la donación');
  }
};

export const listDonationIntakes = async () => {
  try {
    const response = await client.get('/donations/intakes');
    return response.data;
  } catch (error) {
    console.error('Error al cargar los ingresos:', error);
    throw detail(error, 'No se pudieron cargar los ingresos');
  }
};

export const listWarehouseStock = async (soloDisponibles = false) => {
  try {
    const response = await client.get('/donations/stock', { params: { solo_disponibles: soloDisponibles } });
    return response.data;
  } catch (error) {
    console.error('Error al cargar el stock:', error);
    throw detail(error, 'No se pudo cargar el stock');
  }
};

/** Calcula el reparto con el stock del almacén (queda en borrador; descarta el borrador anterior). */
export const calculateWarehouseDistribution = async () => {
  try {
    // El optimizador puede tardar: más margen que el resto de las llamadas.
    const response = await client.post('/donations/distributions', null, { timeout: 180000 });
    return response.data;
  } catch (error) {
    console.error('Error al calcular el reparto:', error);
    throw detail(error, 'No se pudo calcular el reparto');
  }
};

export const listWarehouseDistributions = async () => {
  try {
    const response = await client.get('/donations/distributions');
    return response.data;
  } catch (error) {
    console.error('Error al cargar los repartos:', error);
    throw detail(error, 'No se pudo cargar el historial de repartos');
  }
};

export const getWarehouseDistribution = async (id) => {
  try {
    const response = await client.get(`/donations/distributions/${id}`);
    return response.data;
  } catch (error) {
    console.error('Error al cargar el reparto:', error);
    throw detail(error, 'No se pudo cargar el reparto');
  }
};

/** Beneficiarios que aparecen en los repartos guardados, por nombre o CI (sin tildes ni mayúsculas). */
export const searchDistributionBeneficiaries = async (q, incluirDescartados = false) => {
  try {
    const response = await client.get('/donations/distributions/beneficiarios', {
      params: { q, incluir_descartados: incluirDescartados },
    });
    return response.data;
  } catch (error) {
    console.error('Error al buscar el beneficiario:', error);
    throw detail(error, 'No se pudo buscar el beneficiario');
  }
};

/** Lo que recibió un beneficiario en cada reparto guardado, del más reciente al más antiguo. */
export const getBeneficiaryDistributions = async (beneficiarioId, incluirDescartados = false) => {
  try {
    const response = await client.get(`/donations/distributions/beneficiarios/${beneficiarioId}`, {
      params: { incluir_descartados: incluirDescartados },
    });
    return response.data;
  } catch (error) {
    console.error('Error al cargar los repartos del beneficiario:', error);
    throw detail(error, 'No se pudieron cargar los repartos del beneficiario');
  }
};

/** Con quién se pueden intercambiar `envases` del lote `lot_id` del tratamiento de un beneficiario. */
export const getDistributionSwapOptions = async (id, { beneficiarioId, insulina, lotId, envases }) => {
  try {
    const response = await client.get(`/donations/distributions/${id}/swap-options`, {
      params: { beneficiario_id: beneficiarioId, insulina, lot_id: lotId, envases },
    });
    return response.data;
  } catch (error) {
    console.error('Error al buscar intercambios:', error);
    throw detail(error, 'No se pudieron buscar intercambios');
  }
};

export const createDistributionSwap = async (id, payload) => {
  try {
    const response = await client.post(`/donations/distributions/${id}/swaps`, payload);
    return response.data;
  } catch (error) {
    console.error('Error al intercambiar:', error);
    throw detail(error, 'No se pudo hacer el intercambio');
  }
};

const distributionAction = (action, fallback) => async (id) => {
  try {
    const response = await client.post(`/donations/distributions/${id}/${action}`);
    return response.data;
  } catch (error) {
    console.error(`Error en ${action} del reparto:`, error);
    throw detail(error, fallback);
  }
};

export const resetWarehouseDistribution = distributionAction('reset', 'No se pudo restablecer la propuesta');
export const discardWarehouseDistribution = distributionAction('discard', 'No se pudo descartar el reparto');

/**
 * Consolida el reparto. El aviso que ve cada beneficiario en su portal dice del `entregaDesde` al `entregaHasta`
 * (fechas YYYY-MM-DD; sin ellas, del 1 al 10 del mes siguiente) y lleva las indicaciones opcionales `mensaje`.
 */
export const consolidateWarehouseDistribution = async (id, { mensaje = '', entregaDesde, entregaHasta } = {}) => {
  try {
    const response = await client.post(`/donations/distributions/${id}/consolidate`, {
      mensaje: mensaje.trim() || null,
      entrega_desde: entregaDesde || null,
      entrega_hasta: entregaHasta || null,
    });
    return response.data;
  } catch (error) {
    console.error('Error en consolidate del reparto:', error);
    throw detail(error, 'No se pudo consolidar el reparto');
  }
};

/** Portal del beneficiario: la insulina que le corresponde en cada reparto consolidado (más reciente primero). */
export const listMyInsulinNotices = async () => {
  try {
    const response = await client.get('/donations/insulin-notices/me');
    return response.data;
  } catch (error) {
    console.error('Error al cargar los avisos de insulina:', error);
    throw detail(error, 'No se pudieron cargar los avisos de insulina');
  }
};

/**
 * Sube la foto del aviso: `tipo` 'envases' (sus insulinas ya usadas) o 'hba1c' (su hemoglobina glucosilada, foto o
 * PDF). Reemplaza a la anterior (salvo que ya esté aprobada), queda por revisar y devuelve la foto.
 */
export const uploadInsulinNoticePhoto = async (noticeId, tipo, file) => {
  try {
    const formData = new FormData();
    formData.append('foto', file);
    const response = await client.post(`/donations/insulin-notices/me/${noticeId}/fotos/${tipo}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000, // con datos móviles una foto puede tardar
    });
    return response.data;
  } catch (error) {
    console.error('Error al subir la foto del aviso:', error);
    throw detail(error, 'No se pudo subir la foto');
  }
};

/** SUPER_ADMIN: aprueba (`estado` 'APROBADA') u observa ('OBSERVADA', con `observacion`) una foto del aviso. */
export const reviewInsulinNoticePhoto = async (noticeId, tipo, { estado, observacion = null }) => {
  try {
    const response = await client.post(`/donations/insulin-notices/${noticeId}/fotos/${tipo}/revision`, {
      estado,
      observacion,
    });
    return response.data;
  } catch (error) {
    console.error('Error al revisar la foto del aviso:', error);
    throw detail(error, 'No se pudo guardar la revisión');
  }
};

export const markInsulinNoticeSeen = async (noticeId) => {
  try {
    const response = await client.post(`/donations/insulin-notices/me/${noticeId}/visto`);
    return response.data;
  } catch (error) {
    console.error('Error al confirmar el aviso:', error);
    throw detail(error, 'No se pudo confirmar el aviso');
  }
};

/** Entradas y salidas de un lote (pestaña Stock del almacén). */
export const listLotMovements = async (lotId) => {
  try {
    const response = await client.get(`/donations/lots/${lotId}/movements`);
    return response.data;
  } catch (error) {
    console.error('Error al obtener movimientos de lote:', error);
    throw error.response?.data?.detail || 'Error al obtener movimientos';
  }
};

// --- Portal del beneficiario: boletas de las entregas registradas con el almacén anterior -----------------
export const listMyInsulinDeliveries = async () => {
  try {
    const response = await client.get('/donations/deliveries/me');
    return response.data;
  } catch (error) {
    console.error('Error al obtener mis entregas:', error);
    throw error.response?.data?.detail || 'Error al obtener entregas de insulina';
  }
};

export const getMyDeliveryReceipt = async (deliveryId) => {
  try {
    const response = await client.get(`/donations/deliveries/me/${deliveryId}/receipt`, {
      responseType: 'blob',
    });
    return response.data;
  } catch (error) {
    console.error('Error al descargar mi boleta:', error);
    throw error.response?.data?.detail || 'Error al descargar boleta';
  }
};
