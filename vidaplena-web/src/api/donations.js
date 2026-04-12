import client from './axios';

export const listDonationProducts = async () => {
  try {
    const response = await client.get('/donations/products');
    return response.data;
  } catch (error) {
    console.error('Error al obtener productos:', error);
    throw error.response?.data?.detail || 'Error al cargar productos';
  }
};

export const createDonationProduct = async (payload) => {
  try {
    const response = await client.post('/donations/products/', payload);
    return response.data;
  } catch (error) {
    console.error('Error al registrar producto:', error);
    throw error.response?.data?.detail || 'Error al registrar producto';
  }
};

export const listDonationLots = async () => {
  try {
    const response = await client.get('/donations/lots');
    return response.data;
  } catch (error) {
    console.error('Error al obtener lotes:', error);
    throw error.response?.data?.detail || 'Error al cargar lotes';
  }
};

export const createDonationLot = async (payload) => {
  try {
    const response = await client.post('/donations/lots/', payload);
    return response.data;
  } catch (error) {
    console.error('Error al registrar lote:', error);
    throw error.response?.data?.detail || 'Error al registrar lote';
  }
};

export const getDonationLotDetail = async (lotId) => {
  try {
    const response = await client.get(`/donations/lots/${lotId}`);
    return response.data;
  } catch (error) {
    console.error('Error al obtener detalle del lote:', error);
    throw error.response?.data?.detail || 'Error al obtener detalle del lote';
  }
};

export const calculateDonationDistribution = async (lotId) => {
  try {
    const response = await client.post(`/donations/calculate-distribution/${lotId}`);
    return response.data;
  } catch (error) {
    console.error('Error al calcular distribución:', error);
    throw error.response?.data?.detail || 'Error al calcular distribución';
  }
};

export const updateDonationAllocation = async (allocationId, payload) => {
  try {
    const response = await client.put(`/donations/allocations/${allocationId}`, payload);
    return response.data;
  } catch (error) {
    console.error('Error al actualizar asignación:', error);
    throw error.response?.data?.detail || 'Error al actualizar asignación';
  }
};

export const consolidateDonationLot = async (lotId) => {
  try {
    const response = await client.post(`/donations/lots/${lotId}/consolidate`);
    return response.data;
  } catch (error) {
    console.error('Error al consolidar lote:', error);
    throw error.response?.data?.detail || 'Error al consolidar lote';
  }
};

export const listLotMovements = async (lotId) => {
  try {
    const response = await client.get(`/donations/lots/${lotId}/movements`);
    return response.data;
  } catch (error) {
    console.error('Error al obtener movimientos de lote:', error);
    throw error.response?.data?.detail || 'Error al obtener movimientos';
  }
};

export const importDonationLotsCsv = async (file) => {
  try {
    const formData = new FormData();
    formData.append('file', file);
    const response = await client.post('/donations/lots/import-csv', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  } catch (error) {
    console.error('Error al importar CSV:', error);
    throw error.response?.data?.detail || 'Error al importar CSV';
  }
};

export const getDeliveryByAllocation = async (allocationId) => {
  try {
    const response = await client.get(`/donations/deliveries/by-allocation/${allocationId}`);
    return response.data;
  } catch (error) {
    if (error?.response?.status === 404) return null;
    console.error('Error al obtener entrega de asignación:', error);
    throw error.response?.data?.detail || 'Error al obtener entrega';
  }
};

export const createDelivery = async (payload) => {
  try {
    const response = await client.post('/donations/deliveries/', payload);
    return response.data;
  } catch (error) {
    console.error('Error al registrar entrega:', error);
    throw error.response?.data?.detail || 'Error al registrar entrega';
  }
};

export const getDeliveryReceipt = async (deliveryId) => {
  try {
    const response = await client.get(`/donations/deliveries/${deliveryId}/receipt`, {
      responseType: 'blob',
    });
    return response.data;
  } catch (error) {
    console.error('Error al descargar boleta:', error);
    throw error.response?.data?.detail || 'Error al descargar boleta';
  }
};

export const uploadDeliveryReceipt = async (deliveryId, file) => {
  try {
    const formData = new FormData();
    formData.append('receipt', file);
    const response = await client.put(`/donations/deliveries/${deliveryId}/upload-receipt`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  } catch (error) {
    console.error('Error al subir boleta firmada:', error);
    throw error.response?.data?.detail || 'Error al subir boleta firmada';
  }
};

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
