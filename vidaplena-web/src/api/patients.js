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

export const getPatients = async (skip = 0, limit = 10000, search = '') => {
    try {
      const response = await client.get('/patients/', { params: { skip, limit, search } });
      return response.data;
    } catch (error) {
      console.error("Error al obtener pacientes:", error);
      throw error;
    }
};

export const getPaginatedPatients = async (skip = 0, limit = 20, search = '', estado = '') => {
    try {
      const params = { skip, limit, search };
      if (estado) params.estado = estado;
      const response = await client.get('/patients/paginated', { params });
      return response.data;
    } catch (error) {
      console.error("Error al obtener pacientes paginados:", error);
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

export const deletePatient = async (id) => {
  const response = await client.delete(`/patients/${id}`);
  return response.data;
};

export const validateCommitmentCode = async (code) => {
  const response = await client.get(`/patients/validate-commitment-code/${code}`);
  return response.data;
};

// --- AUTOREGISTRO PÚBLICO DE BENEFICIARIOS ---
export const checkBeneficiary = async ({ nombres, ap_paterno, ap_materno }) => {
  const response = await client.post('/patients/check-beneficiary', {
    nombres,
    ap_paterno: ap_paterno || null,
    ap_materno: ap_materno || null,
  });
  return response.data;
};

export const selfRegisterPatient = async (payload) => {
  try {
    const response = await client.post('/patients/self-register', payload);
    return response.data;
  } catch (error) {
    console.error('Error en autoregistro:', error);
    throw error.response?.data?.detail || 'Error desconocido al registrarse';
  }
};

// --- Corrección administrativa del padrón (SUPER_ADMIN, herramienta temporal) ---
export const searchBeneficiariesAdmin = async (q) => {
  const response = await client.get('/patients/admin/beneficiaries', { params: { q } });
  return response.data;
};

export const getPaginatedBeneficiariesAdmin = async ({ skip = 0, limit = 20, search = '' } = {}) => {
  const response = await client.get('/patients/admin/beneficiaries/paginated', {
    params: { skip, limit, search: search || undefined },
  });
  return response.data;
};

export const deleteBeneficiaryAdmin = async (id) => {
  await client.delete(`/patients/admin/beneficiaries/${id}`);
};

export const createBeneficiaryAdmin = async ({ nombres, ap_paterno, ap_materno, depto }) => {
  const response = await client.post('/patients/admin/beneficiaries', {
    nombres,
    ap_paterno: ap_paterno || null,
    ap_materno: ap_materno || null,
    depto: depto || null,
  });
  return response.data;
};

export const updateBeneficiaryAdmin = async (id, { nombres, ap_paterno, ap_materno, depto }) => {
  const response = await client.put(`/patients/admin/beneficiaries/${id}`, {
    nombres,
    ap_paterno: ap_paterno || null,
    ap_materno: ap_materno || null,
    depto: depto || null,
  });
  return response.data;
};

export const resetBeneficiaryRegistration = async (id) => {
  const response = await client.post(`/patients/admin/beneficiaries/${id}/reset-registration`);
  return response.data;
};