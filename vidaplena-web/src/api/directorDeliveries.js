// src/api/directorDeliveries.js — cuaderno de la Directora
import client from './axios';

const BASE = '/api/director-deliveries';

/** Busca beneficiarios por nombre, apellido o C.I.; trae sus insulinas anotadas y su última entrega. */
export const searchBeneficiaries = async (q) => {
  const response = await client.get(`${BASE}/beneficiaries`, { params: { q } });
  return response.data;
};

/** Última entrega anotada de una persona por nombre (personas fuera del padrón). */
export const searchLastDelivery = async ({ nombres, apPaterno, apMaterno }) => {
  const response = await client.get(`${BASE}/search`, {
    params: { nombres, ap_paterno: apPaterno, ap_materno: apMaterno || null },
  });
  return response.data;
};

/**
 * Registra la visita de una persona con una o varias insulinas, todo o nada.
 * @param {{patient_id?: number, patient_nombres?: string, patient_ap_paterno?: string,
 *          patient_ap_materno?: string, delivery_date?: string,
 *          items: {insulin_type: string, presentacion?: string, marca?: string, quantity: string}[]}} payload
 */
export const createDeliveryBatch = async (payload) => {
  const response = await client.post(`${BASE}/batch`, payload);
  return response.data;
};

/** Reporte del cuaderno: entregas anotadas entre dos fechas, con búsqueda por texto. */
export const getDirectorDeliveries = async ({ desde, hasta, q } = {}) => {
  const response = await client.get(`${BASE}/`, {
    params: { desde: desde || undefined, hasta: hasta || undefined, q: q || undefined },
  });
  return response.data;
};
