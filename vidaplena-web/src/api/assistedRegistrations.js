// src/api/assistedRegistrations.js — Registro Asistido por Situación Excepcional
import client from './axios';

const BASE = '/assisted-registrations';

/** Lista los registros. Filtros: estado (ACTIVO|DENEGADO|CESADO), depto, q, revision_vencida. */
export const listAssistedRegistrations = async (filters = {}) => {
  const params = {};
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) params[key] = value;
  });
  const response = await client.get(`${BASE}/`, { params });
  return response.data;
};

export const getAssistedRegistration = async (id) => (await client.get(`${BASE}/${id}`)).data;

/** Todos los campos son opcionales: con `{}` igual se registra y se asigna el Código Interno. */
export const createAssistedRegistration = async (payload) => (await client.post(`${BASE}/`, payload)).data;

export const updateAssistedRegistration = async (id, payload) => (await client.put(`${BASE}/${id}`, payload)).data;

export const addAssistedDelivery = async (id, payload) => (await client.post(`${BASE}/${id}/entregas`, payload)).data;

export const registerAssistedReview = async (id) => (await client.post(`${BASE}/${id}/revision`)).data;

export const denyAssistedRegistration = async (id, motivo) => (await client.post(`${BASE}/${id}/denegar`, { motivo })).data;

export const endAssistedRegistration = async (id, payload) => (await client.post(`${BASE}/${id}/cese`, payload)).data;

// --- Personas referentes: quienes reciben la insulina para entregarla. Pueden serlo de varios beneficiarios. ---

/** Busca por nombre o C.I.; devuelve cuántos registros activos tiene cada persona referente. */
export const searchReferents = async (q) => (await client.get(`${BASE}/referentes`, { params: { q } })).data;

export const getReferent = async (id) => (await client.get(`${BASE}/referentes/${id}`)).data;

const referentForm = ({ nombre_completo, ci, telefono, foto }) => {
  const form = new FormData();
  if (nombre_completo !== undefined) form.append('nombre_completo', nombre_completo);
  if (ci !== undefined) form.append('ci', ci);
  if (telefono !== undefined) form.append('telefono', telefono);
  if (foto) form.append('foto', foto);
  return form;
};

/** Nombre completo, C.I., teléfono y foto personal (archivo JPG/PNG de hasta 2 MB) son obligatorios. */
const MULTIPART = { headers: { 'Content-Type': 'multipart/form-data' } };

export const createReferent = async (fields) =>
  (await client.post(`${BASE}/referentes`, referentForm(fields), MULTIPART)).data;

/** Corrige o completa a la persona referente; lo que no se envía queda igual. */
export const updateReferent = async (id, fields) =>
  (await client.put(`${BASE}/referentes/${id}`, referentForm(fields), MULTIPART)).data;
