// src/api/contributions.js
import client from './axios';

export const getMyContributions = async () => {
  const response = await client.get('/contributions/me');
  return response.data;
};

export const getContributionsReview = async ({ estado, periodo } = {}) => {
  const params = { estado: estado || undefined, periodo: periodo || undefined };
  const response = await client.get('/contributions/review', { params });
  return response.data;
};

/**
 * Descarga el PDF de "Control de Vouchers" (Reportes): lista general de
 * TODOS los beneficiarios con la captura del comprobante, nombre y fecha de
 * pago. `periodo` (YYYY-MM) es opcional — sin él trae todos los periodos.
 */
export const downloadVouchersControlPdf = async (periodo) => {
  const params = periodo ? { periodo } : {};
  const response = await client.get('/contributions/vouchers/export.pdf', {
    params,
    responseType: 'blob',
  });
  const url = window.URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }));
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', `Control_Vouchers_${periodo || 'TODOS'}.pdf`);
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
