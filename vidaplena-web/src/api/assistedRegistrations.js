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
