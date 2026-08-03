// src/api/siteAssets.js
import client from './axios';

export const getSiteAssets = async () => {
  const response = await client.get('/site-assets/');
  return response.data;
};

export const updateSiteAsset = async (key, foto) => {
  const formData = new FormData();
  formData.append('foto', foto);

  try {
    const response = await client.put(`/site-assets/${key}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  } catch (error) {
    console.error('Error al subir el QR:', error);
    throw {
      status: error.response?.status,
      message: error.response?.data?.detail || 'Error desconocido al subir el QR',
    };
  }
};
