import axios from 'axios';

// 1. Crear la instancia BÁSICA (sin token aún)
const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000', // Usa la variable de entorno
  headers: {
    'Content-Type': 'application/json',
  },
});

// 2. AGREGAR INTERCEPTOR (La Magia ✨)
// Esto se ejecuta JUSTO ANTES de enviar cualquier petición
client.interceptors.request.use(
  (config) => {
    // Leemos el token FRESCO del localStorage cada vez
    const token = localStorage.getItem('token');
    
    if (token) {
      // Si existe, lo inyectamos en la cabecera
      config.headers.Authorization = `Bearer ${token}`;
    }
    
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

export default client;