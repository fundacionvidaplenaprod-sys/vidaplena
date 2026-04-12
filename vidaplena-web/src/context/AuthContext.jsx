import React, { createContext, useState, useContext, useEffect } from 'react';
import client from '../api/axios';
import { toast } from 'react-hot-toast'; // Para alertas bonitas

const AuthContext = createContext();

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth debe usarse dentro de un AuthProvider');
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);

  // 1. Verificar si ya hay sesión al abrir la app
  useEffect(() => {
    const checkLogin = async () => {
      const token = localStorage.getItem('token');
      if (token) {
        try {
          // Intentamos obtener los datos del usuario usando el token guardado
          const { data } = await client.get('/users/me');
          setUser(data);
          setIsAuthenticated(true);
        } catch (error) {
          // Si el token expiró o es inválido
          console.error("Sesión expirada");
          logout();
        }
      }
      setLoading(false);
    };
    checkLogin();
  }, []);

// 2. Función de Login CORREGIDA
const login = async (data) => { // 👈 CAMBIO AQUÍ: Recibimos un objeto 'data'
  try {
    // Desestructuramos para sacar email y password del objeto
    const { email, password } = data; 

    const formData = new URLSearchParams();
    formData.append('username', email); // FastAPI usa 'username'
    formData.append('password', password);

    const res = await client.post('/login/access-token', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    });

    const { access_token, user } = res.data; // A veces el backend ya devuelve el user aquí
    
    // Guardamos token
    localStorage.setItem('token', access_token);
    
    // Si el backend NO devuelve el usuario en el login, lo pedimos aparte:
    // (Si tu backend ya devuelve 'user' junto con el token, usa ese. Si no, deja esta línea)
    let userData = user;
    if (!userData) {
       const userRes = await client.get('/users/me');
       userData = userRes.data;
    }
    
    // Guardamos usuario en Storage y Estado
    localStorage.setItem('user', JSON.stringify(userData));
    setUser(userData);
    setIsAuthenticated(true);
    
    return userData; // Devolvemos el usuario para que el LoginPage sepa qué hacer

  } catch (error) {
    console.error("Error Login:", error);
    // No usamos toast aquí para dejar que LoginPage decida si mostrar error o no,
    // pero lanzamos el error para que LoginPage sepa que falló.
    throw error;
  }
};

  // 3. Función de Logout
  const logout = () => {
    localStorage.removeItem('token');
    setUser(null);
    setIsAuthenticated(false);
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, isAuthenticated, loading }}>
      {children}
    </AuthContext.Provider>
  );
};