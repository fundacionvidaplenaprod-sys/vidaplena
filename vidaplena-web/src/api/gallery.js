// src/api/gallery.js
import client from './axios';

export const getGalleryPhotos = async () => {
  const response = await client.get('/gallery/');
  return response.data;
};

export const createGalleryPhoto = async ({ foto, caption, orden }) => {
  const formData = new FormData();
  formData.append('foto', foto);
  if (caption) formData.append('caption', caption);
  formData.append('orden', orden ?? 0);

  try {
    const response = await client.post('/gallery/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  } catch (error) {
    console.error('Error al subir la foto:', error);
    throw {
      status: error.response?.status,
      message: error.response?.data?.detail || 'Error desconocido al subir la foto',
    };
  }
};

export const updateGalleryPhoto = async (photoId, { caption, orden }) => {
  const response = await client.put(`/gallery/${photoId}`, { caption, orden });
  return response.data;
};

export const deleteGalleryPhoto = async (photoId) => {
  await client.delete(`/gallery/${photoId}`);
};
