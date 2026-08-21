// src/api/contributions.js
import client from './axios';

export const getMyContributions = async () => {
  const response = await client.get('/contributions/me');
  return response.data;
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

// SUPER_ADMIN registra un aporte que el beneficiario pagó (p. ej. depósito
// bancario) pero nunca declaró por su cuenta en la app. Queda ACEPTADO.
export const createContributionAdmin = async (patientId, { monto, periodo, fechaPago, comprobante }) => {
  const formData = new FormData();
  formData.append('monto', String(monto));
  formData.append('periodo', periodo);
  formData.append('fecha_pago', fechaPago);
  formData.append('comprobante', comprobante);
  const response = await client.post(`/contributions/${patientId}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};
