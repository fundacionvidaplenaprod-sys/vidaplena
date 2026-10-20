// src/api/contributions.js
import client from './axios';

export const getMyContributions = async () => {
  const response = await client.get('/contributions/me');
  return response.data;
};

// Parámetros de filtro por periodo y departamento: un mes (`periodo`), un rango (`desde` / `hasta`,
// formato AAAA-MM) y/o un departamento.
const periodParams = ({ periodo, desde, hasta, depto } = {}) => ({
  periodo: periodo || undefined,
  periodo_desde: desde || undefined,
  periodo_hasta: hasta || undefined,
  depto: depto || undefined,
});

// Etiqueta corta del filtro para nombres de archivo: «2026-04_a_2026-10», «2026-04» o «TODOS».
export const periodLabel = ({ periodo, desde, hasta } = {}) => {
  if (periodo) return periodo;
  if (desde && hasta) return desde === hasta ? desde : `${desde}_a_${hasta}`;
  if (desde) return `desde_${desde}`;
  if (hasta) return `hasta_${hasta}`;
  return 'TODOS';
};

export const getContributionsReview = async ({ estado, ...filters } = {}) => {
  const params = { estado: estado || undefined, ...periodParams(filters) };
  const response = await client.get('/contributions/review', { params });
  return response.data;
};

/**
 * Descarga el PDF de "Control de Vouchers" (Reportes): lista general de
 * TODOS los beneficiarios con la captura del comprobante, nombre, departamento,
 * periodo y fecha de pago. Acepta un mes (`periodo`), un rango (`desde` / `hasta`,
 * AAAA-MM) y un `depto`; sin filtros trae todos los periodos. También se acepta el
 * mes suelto como texto, por compatibilidad.
 */
export const downloadVouchersControlPdf = async (filters = {}) => {
  const normalized = typeof filters === 'string' ? { periodo: filters } : filters || {};
  const response = await client.get('/contributions/vouchers/export.pdf', {
    params: periodParams(normalized),
    responseType: 'blob',
  });
  const url = window.URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }));
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', `Control_Vouchers_${periodLabel(normalized)}.pdf`);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

export const previewContributionOcr = async (file) => {
  const formData = new FormData();
  formData.append('comprobante', file);
  const response = await client.post('/contributions/ocr-preview', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

export const createMyContribution = async ({ monto, periodo, fechaPago, comprobante }) => {
  const formData = new FormData();
  formData.append('monto', String(monto));
  formData.append('periodo', periodo);
  formData.append('fecha_pago', fechaPago);
  formData.append('comprobante', comprobante);
  const response = await client.post('/contributions/me', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

// SUPER_ADMIN registra un aporte que el beneficiario pagó (por voucher/QR
// que nunca declaró en la app, o en EFECTIVO directamente en campo, sin
// ningún comprobante digital). Queda ACEPTADO de inmediato.
export const createContributionAdmin = async (patientId, { monto, periodo, fechaPago, metodoPago = 'VOUCHER', comprobante }) => {
  const formData = new FormData();
  formData.append('monto', String(monto));
  formData.append('periodo', periodo);
  formData.append('fecha_pago', fechaPago);
  formData.append('metodo_pago', metodoPago);
  if (comprobante) formData.append('comprobante', comprobante);
  const response = await client.post(`/contributions/${patientId}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

// SUPER_ADMIN corrige el periodo (gestión) de un aporte que el beneficiario
// declaró en un mes equivocado. `periodo` en formato AAAA-MM.
export const updateContributionPeriodo = async (contributionId, periodo) => {
  const response = await client.put(`/contributions/${contributionId}/periodo`, { periodo });
  return response.data;
};
