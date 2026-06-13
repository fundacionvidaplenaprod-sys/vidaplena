import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import client from '../../api/axios';
import { Loader2, AlertCircle, CheckCircle } from 'lucide-react';
import toast from 'react-hot-toast';

// Custom hook para debounce
function useDebounce(value, delay) {
  const [debouncedValue, setDebouncedValue] = useState(value);
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);
    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);
  return debouncedValue;
}

export default function DirectorDeliveryPage() {
  const { user, isAuthenticated, login, logout, loading } = useAuth();
  const navigate = useNavigate();

  const [isUnlocked, setIsUnlocked] = useState(false);
  const [pinInput, setPinInput] = useState("");
  const [step, setStep] = useState("LOCK"); // LOCK, FORM

  // Campos de formulario libre
  const [nombres, setNombres] = useState("");
  const [apPaterno, setApPaterno] = useState("");
  const [apMaterno, setApMaterno] = useState("");
  
  const [insulinType, setInsulinType] = useState("");
  const [quantity, setQuantity] = useState("");
  const [deliveryDate, setDeliveryDate] = useState(new Date().toISOString().split('T')[0]);

  const [lastDelivery, setLastDelivery] = useState(null);
  const [alertWarning, setAlertWarning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [authenticating, setAuthenticating] = useState(false);

  // Valores debounced
  const debouncedNombres = useDebounce(nombres, 500);
  const debouncedApPaterno = useDebounce(apPaterno, 500);
  const debouncedApMaterno = useDebounce(apMaterno, 500);

  const handleLock = () => {
      logout();
      setStep("LOCK");
  };

  useEffect(() => {
    if (!loading && isAuthenticated && user?.email === "directora@vidaplena.org") {
        setStep("FORM");
        setIsUnlocked(true);
    }
  }, [loading, isAuthenticated, user]);

  // Timeout de inactividad
  useEffect(() => {
    let timeoutId;
    const resetTimer = () => {
      clearTimeout(timeoutId);
      if (step === "FORM") {
        timeoutId = setTimeout(() => {
          handleLock();
          toast("Sesión bloqueada por inactividad", { icon: "🔒" });
        }, 3 * 60 * 1000); // 3 minutos de inactividad
      }
    };

    if (step === "FORM") {
      window.addEventListener("mousemove", resetTimer);
      window.addEventListener("keydown", resetTimer);
      window.addEventListener("click", resetTimer);
      window.addEventListener("scroll", resetTimer);
      resetTimer();
    }

    return () => {
      clearTimeout(timeoutId);
      window.removeEventListener("mousemove", resetTimer);
      window.removeEventListener("keydown", resetTimer);
      window.removeEventListener("click", resetTimer);
      window.removeEventListener("scroll", resetTimer);
    };
  }, [step]);

  // Efecto para buscar duplicados mientras escribe
  useEffect(() => {
    if (step === "FORM" && debouncedNombres && debouncedApPaterno) {
      searchDuplicate(debouncedNombres, debouncedApPaterno, debouncedApMaterno);
    } else {
      setLastDelivery(null);
      setAlertWarning(false);
    }
  }, [debouncedNombres, debouncedApPaterno, debouncedApMaterno, step]);

  const searchDuplicate = async (n, p, m) => {
    try {
      setIsSearching(true);
      const res = await client.get(`/api/director-deliveries/search`, {
        params: {
          nombres: n,
          ap_paterno: p,
          ap_materno: m || null
        }
      });

      if (res.data) {
        setLastDelivery(res.data);
        const lastDate = new Date(res.data.delivery_date);
        const today = new Date();
        const diffTime = Math.abs(today - lastDate);
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        if (diffDays < 25) {
          setAlertWarning(true);
        } else {
          setAlertWarning(false);
        }
      } else {
        setLastDelivery(null);
        setAlertWarning(false);
      }
    } catch (error) {
      console.error(error);
    } finally {
      setIsSearching(false);
    }
  };

  const handleKeypadClick = (num) => {
    if (pinInput.length < 4) {
      setPinInput(prev => prev + num);
    }
  };

  useEffect(() => {
    const authenticatePin = async () => {
        if (pinInput.length === 4) {
            setAuthenticating(true);
            try {
                // Hacemos login invisible con la cuenta técnica
                await login({ email: 'directora@vidaplena.org', password: pinInput });
                setIsUnlocked(true);
                setStep("FORM");
                setPinInput("");
                toast.success("Acceso concedido");
            } catch (error) {
                toast.error("PIN Incorrecto");
                setPinInput("");
            } finally {
                setAuthenticating(false);
            }
        }
    };
    authenticatePin();
  }, [pinInput, login]);

  const handleSubmitDelivery = async (e) => {
    e.preventDefault();
    if (!nombres || !apPaterno || !insulinType || !quantity) {
      toast.error("Complete los campos obligatorios");
      return;
    }
    
    try {
      setSubmitting(true);
      await client.post('/api/director-deliveries/', {
        patient_nombres: nombres,
        patient_ap_paterno: apPaterno,
        patient_ap_materno: apMaterno || null,
        insulin_type: insulinType,
        quantity: quantity,
        delivery_date: deliveryDate
      });
      toast.success("Entrega registrada exitosamente");
      // Limpiar formulario
      setNombres("");
      setApPaterno("");
      setApMaterno("");
      setInsulinType("");
      setQuantity("");
      setAlertWarning(false);
      setLastDelivery(null);
    } catch (error) {
      toast.error("Error al registrar la entrega");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <div className="flex h-screen items-center justify-center"><Loader2 className="animate-spin w-10 h-10 text-green-600"/></div>;

  if (step === "LOCK") {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center p-4">
        <div className="max-w-sm w-full">
          <h2 className="text-3xl font-bold text-center text-white mb-8">Acceso Directora</h2>
          
          <div className="flex justify-center space-x-4 mb-10">
            {[...Array(4)].map((_, i) => (
              <div key={i} className={`w-6 h-6 rounded-full border-2 border-white ${i < pinInput.length ? 'bg-white' : 'bg-transparent'}`}></div>
            ))}
          </div>

          <div className="grid grid-cols-3 gap-4">
            {[1, 2, 3, 4, 5, 6, 7, 8, 9].map(num => (
              <button 
                key={num} 
                onClick={() => handleKeypadClick(num.toString())}
                className="w-20 h-20 mx-auto rounded-full bg-gray-800 text-white text-3xl font-light hover:bg-gray-700 focus:outline-none focus:ring-4 focus:ring-gray-500 transition-colors"
                disabled={authenticating}
              >
                {num}
              </button>
            ))}
            <div className="col-start-2">
              <button 
                onClick={() => handleKeypadClick('0')}
                className="w-20 h-20 mx-auto rounded-full bg-gray-800 text-white text-3xl font-light hover:bg-gray-700 focus:outline-none focus:ring-4 focus:ring-gray-500 transition-colors"
                disabled={authenticating}
              >
                0
              </button>
            </div>
            <div className="flex items-center justify-center">
              <button 
                onClick={() => setPinInput(prev => prev.slice(0, -1))}
                className="w-16 h-16 rounded-full bg-red-900 text-white text-xl hover:bg-red-800 transition-colors"
                disabled={authenticating}
              >
                X
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6 md:p-12 font-sans">
      <div className="max-w-4xl mx-auto">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-4xl font-bold text-gray-800">Registro Rápido de Entrega</h1>
          <button onClick={handleLock} className="bg-gray-800 text-white px-6 py-2 rounded-full font-semibold hover:bg-gray-700">
            Bloquear Pantalla
          </button>
        </div>

        <div className="bg-white rounded-3xl shadow-lg p-8">
          
          <form onSubmit={handleSubmitDelivery} className="space-y-8">
            
            {/* DATOS DEL PACIENTE */}
            <div className="bg-gray-50 p-6 rounded-2xl border border-gray-200">
              <h2 className="text-2xl font-bold text-gray-700 mb-6 flex items-center justify-between">
                1. Datos del Paciente
                {isSearching && <Loader2 className="w-5 h-5 text-gray-400 animate-spin" />}
              </h2>
              
              <div className="grid md:grid-cols-3 gap-6">
                <div>
                  <label className="block text-lg font-bold text-gray-700 mb-2">Nombres *</label>
                  <input
                    type="text"
                    required
                    placeholder="Ej. Juan Carlos"
                    className="w-full p-4 border-2 border-gray-300 rounded-xl text-lg focus:border-green-500"
                    value={nombres}
                    onChange={(e) => setNombres(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-lg font-bold text-gray-700 mb-2">Apellido Paterno *</label>
                  <input
                    type="text"
                    required
                    placeholder="Ej. Perez"
                    className="w-full p-4 border-2 border-gray-300 rounded-xl text-lg focus:border-green-500"
                    value={apPaterno}
                    onChange={(e) => setApPaterno(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-lg font-bold text-gray-700 mb-2">Apellido Materno</label>
                  <input
                    type="text"
                    placeholder="Ej. Arce"
                    className="w-full p-4 border-2 border-gray-300 rounded-xl text-lg focus:border-green-500"
                    value={apMaterno}
                    onChange={(e) => setApMaterno(e.target.value)}
                  />
                </div>
              </div>
            </div>

            {/* ALERTA VISUAL DINÁMICA */}
            {lastDelivery && (
              <div className={`p-6 rounded-2xl border-2 flex items-start space-x-4 ${alertWarning ? 'bg-red-50 border-red-400 text-red-900' : 'bg-blue-50 border-blue-200 text-blue-900'}`}>
                {alertWarning ? <AlertCircle className="w-8 h-8 text-red-600 flex-shrink-0 mt-1" /> : <CheckCircle className="w-8 h-8 text-blue-500 flex-shrink-0 mt-1" />}
                <div>
                  <h4 className={`text-xl font-bold mb-2 ${alertWarning ? 'text-red-700' : 'text-blue-800'}`}>
                    {alertWarning ? '¡ATENCIÓN! Posible entrega duplicada adelantada' : 'Información de última entrega'}
                  </h4>
                  <p className="text-lg">
                    Paciente: <strong>{lastDelivery.patient_nombres} {lastDelivery.patient_ap_paterno} {lastDelivery.patient_ap_materno}</strong><br/>
                    Última entrega: <strong>{lastDelivery.delivery_date}</strong><br/>
                    Recibió: <strong>{lastDelivery.quantity}</strong> de <strong>{lastDelivery.insulin_type}</strong>
                  </p>
                  {alertWarning && <p className="mt-3 font-bold bg-red-200 inline-block px-3 py-1 rounded text-red-800">Han pasado menos de 25 días.</p>}
                </div>
              </div>
            )}

            {/* DATOS DE LA ENTREGA */}
            <div className="bg-gray-50 p-6 rounded-2xl border border-gray-200">
              <h2 className="text-2xl font-bold text-gray-700 mb-6">2. Datos de la Entrega</h2>
              
              <div className="grid md:grid-cols-2 gap-6">
                <div>
                  <label className="block text-lg font-bold text-gray-700 mb-2">Tipo de Insulina / Insumo *</label>
                  <input 
                    type="text"
                    required
                    placeholder="Ej. NPH, Glargina, Jeringas..."
                    value={insulinType}
                    onChange={e => setInsulinType(e.target.value)}
                    className="w-full p-4 border-2 border-gray-300 rounded-xl text-lg focus:border-green-500"
                  />
                </div>

                <div>
                  <label className="block text-lg font-bold text-gray-700 mb-2">Cantidad *</label>
                  <input 
                    type="text"
                    required
                    placeholder="Ej. 2 frascos, 1 pluma..."
                    value={quantity}
                    onChange={e => setQuantity(e.target.value)}
                    className="w-full p-4 border-2 border-gray-300 rounded-xl text-lg focus:border-green-500"
                  />
                </div>
              </div>

              <div className="mt-6">
                <label className="block text-lg font-bold text-gray-700 mb-2">Fecha de Entrega *</label>
                <input 
                  type="date" 
                  required
                  value={deliveryDate}
                  onChange={e => setDeliveryDate(e.target.value)}
                  className="w-full md:w-1/2 p-4 border-2 border-gray-300 rounded-xl text-lg focus:border-green-500"
                />
              </div>
            </div>

            <button 
              type="submit" 
              disabled={submitting}
              className={`w-full text-white font-bold py-5 rounded-2xl text-2xl mt-4 transition-colors shadow-lg ${submitting ? 'bg-gray-400' : 'bg-green-600 hover:bg-green-700'}`}
            >
              {submitting ? 'Registrando...' : 'Confirmar Registro'}
            </button>
          </form>

        </div>
      </div>
    </div>
  );
}
