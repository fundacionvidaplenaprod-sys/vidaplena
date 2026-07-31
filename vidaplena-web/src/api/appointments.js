// src/api/appointments.js
import client from './axios';

export const getAppointmentConfig = async () => {
  const response = await client.get('/appointments/config');
  return response.data;
};

export const getAvailability = async (fecha) => {
  const response = await client.get('/appointments/availability', { params: { fecha } });
  return response.data;
};

export const bookAppointment = async (formData) => {
  try {
    const response = await client.post('/appointments/book', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  } catch (error) {
    console.error('Error al agendar cita:', error);
    throw {
      status: error.response?.status,
      message: error.response?.data?.detail || 'Error desconocido al agendar la cita',
    };
  }
};

export const getFichaUrl = (id, code) => {
  const baseURL = client.defaults.baseURL || '';
  return `${baseURL}/appointments/${id}/ficha.pdf?code=${encodeURIComponent(code)}`;
};

// --- Panel doctora (SUPER_ADMIN) ---

export const getBlockedDays = async () => {
  const response = await client.get('/appointments/blocked-days');
  return response.data;
};

export const createBlockedDay = async ({ fecha, motivo }) => {
  const response = await client.post('/appointments/blocked-days', { fecha, motivo });
  return response.data;
};

export const deleteBlockedDay = async (fecha) => {
  await client.delete(`/appointments/blocked-days/${fecha}`);
};

export const getAgenda = async (fecha) => {
  const response = await client.get('/appointments/agenda', { params: { fecha } });
  return response.data;
};

export const updateClinicalNote = async (appointmentId, nota) => {
  const response = await client.put(`/appointments/${appointmentId}/clinical-note`, { nota });
  return response.data;
};

export const getHistoryByCi = async (ci) => {
  const response = await client.get('/appointments/history', { params: { ci } });
  return response.data;
};
