// src/api/patients.js
import client from './axios';

export const createPatient = async (patientData) => {
  try {
    // El backend espera POST /pacientes/ (o donde hayas montado el router)
    // Asumo que el router de pacientes está en /pacientes según tu estructura
    const response = await client.post('/patients/', patientData);
    return response.data;
  } catch (error) {
    console.error("Error al registrar paciente:", error);
    throw error.response?.data?.detail || "Error desconocido al guardar";
  }
};

export const getPatients = async () => {
    try {
      const response = await client.get('/patients/');
      return response.data;
    } catch (error) {
      console.error("Error al obtener pacientes:", error);
      throw error;
    }
};

// 1. Obtener un paciente por ID
export const getPatientById = async (id) => {
    const response = await client.get(`/patients/${id}`);
    return response.data;
  };
  
  // 2. Activar paciente (Generar Usuario)
  export const activatePatient = async (id) => {
    // Cambiamos 'post' por 'put' para coincidir con el backend
    const response = await client.put(`/patients/${id}/activate`);
    return response.data;
  };

export const updatePatient = async (id, data) => {
    const response = await client.put(`/patients/${id}`, data);
    return response.data;
};

export const changePatientStatus = async (id, newStatus) => {
  const response = await client.put(`/patients/${id}/change-status`, { estado: newStatus });
  return response.data;
};

export const uploadDocument = async (docType, file) => {
  const formData = new FormData();
  formData.append('doc_type', docType);
  formData.append('file', file);

  const response = await client.post('/patients/me/upload-document', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};