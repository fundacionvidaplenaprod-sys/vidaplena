// src/api/siteSettings.js
import client from './axios';

export const getContactInfo = async () => {
  const response = await client.get('/site-settings/contact');
  return response.data;
};

export const updateContactInfo = async (payload) => {
  const response = await client.put('/site-settings/contact', payload);
  return response.data;
};
