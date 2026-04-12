import axios from 'axios';

// 1. Crear la instancia BÁSICA (sin token aún)
const client = axios.create({
  baseURL: 'http://localhost:8000', // Asegúrate de que este puerto sea el correcto
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