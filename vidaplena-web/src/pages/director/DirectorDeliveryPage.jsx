import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { Loader2, Calendar, Package, Save, Clock, User, FileText, CheckCircle2, BookOpen } from 'lucide-react';
import toast from 'react-hot-toast';
import { getAgenda, updateClinicalNote } from '../../api/appointments';
import DirectorDeliveryForm from './DirectorDeliveryForm';
import DirectorNotebookReport from '../reports/DirectorNotebookReport';

export default function DirectorDeliveryPage() {
  const { user, isAuthenticated, login, logout, loading } = useAuth();
  const navigate = useNavigate();

  const [isUnlocked, setIsUnlocked] = useState(false);
  const [pinInput, setPinInput] = useState("");
  const [step, setStep] = useState("LOCK"); // LOCK, FORM

  const getLocalDateString = () => {
    const d = new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };
  const [authenticating, setAuthenticating] = useState(false);

  // Navegación de pestañas en módulo directora
  const [activeTab, setActiveTab] = useState("ENTREGA"); // "ENTREGA" | "REGISTROS" | "CITAS"
  const [agendaDate, setAgendaDate] = useState(getLocalDateString());
  const [agendaList, setAgendaList] = useState([]);
  const [loadingAgenda, setLoadingAgenda] = useState(false);
  const [notesState, setNotesState] = useState({}); // { [id]: string }
  const [savingNoteId, setSavingNoteId] = useState(null);

  const loadDirectorAgenda = async (fechaStr) => {
    try {
      setLoadingAgenda(true);
      const data = await getAgenda(fechaStr);
      setAgendaList(data || []);
      const initialNotes = {};
      (data || []).forEach(item => {
        initialNotes[item.id] = item.nota_consulta || "";
      });
      setNotesState(initialNotes);
    } catch (error) {
      toast.error('No se pudo cargar la agenda del día');
    } finally {
      setLoadingAgenda(false);
    }
  };

  useEffect(() => {
    if (isUnlocked && activeTab === "CITAS") {
      loadDirectorAgenda(agendaDate);
    }
  }, [isUnlocked, activeTab, agendaDate]);

  const handleSaveClinicalNote = async (appointmentId) => {
    try {
      setSavingNoteId(appointmentId);
      const notaText = notesState[appointmentId] || "";
      await updateClinicalNote(appointmentId, notaText);
      toast.success('Nota clínica guardada correctamente');
    } catch (error) {
      toast.error('Error al guardar la nota clínica');
    } finally {
      setSavingNoteId(null);
    }
  };

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
      <div className="max-w-6xl mx-auto">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
          <div>
            <h1 className="text-4xl font-bold text-gray-800">Módulo de Atención — Directora</h1>
            <p className="text-gray-500 mt-1">Gestión rápida de entrega de insulinas y atención de citas del día</p>
          </div>
          <button onClick={handleLock} className="bg-gray-800 text-white px-6 py-2 rounded-full font-semibold hover:bg-gray-700">
            Bloquear Pantalla
          </button>
        </div>

        {/* PESTAÑAS DE NAVEGACIÓN RÁPIDA */}
        <div className="flex flex-wrap gap-3 mb-6">
          <button
            type="button"
            onClick={() => setActiveTab("ENTREGA")}
            className={`flex items-center gap-2 px-6 py-3 rounded-2xl font-bold text-lg transition-all ${
              activeTab === "ENTREGA"
                ? "bg-green-600 text-white shadow-lg"
                : "bg-white text-gray-700 hover:bg-gray-100 shadow"
            }`}
          >
            <Package className="w-5 h-5" />
            Entrega Rápida de Insulina
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("REGISTROS")}
            className={`flex items-center gap-2 px-6 py-3 rounded-2xl font-bold text-lg transition-all ${
              activeTab === "REGISTROS"
                ? "bg-amber-600 text-white shadow-lg"
                : "bg-white text-gray-700 hover:bg-gray-100 shadow"
            }`}
          >
            <BookOpen className="w-5 h-5" />
            Mis registros
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("CITAS")}
            className={`flex items-center gap-2 px-6 py-3 rounded-2xl font-bold text-lg transition-all ${
              activeTab === "CITAS"
                ? "bg-blue-600 text-white shadow-lg"
                : "bg-white text-gray-700 hover:bg-gray-100 shadow"
            }`}
          >
            <Calendar className="w-5 h-5" />
            Agenda de Citas del Día
          </button>
        </div>

        <div className="bg-white rounded-3xl shadow-lg p-8">
          
          {activeTab === "ENTREGA" && <DirectorDeliveryForm />}

          {activeTab === "REGISTROS" && <DirectorNotebookReport />}

          {activeTab === "CITAS" && (
            <div className="space-y-6">
              <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-gray-50 p-6 rounded-2xl border border-gray-200">
                <div>
                  <h2 className="text-2xl font-bold text-gray-800 flex items-center gap-2">
                    <Calendar className="w-6 h-6 text-blue-600" />
                    Atención de Citas Programadas
                  </h2>
                  <p className="text-sm text-gray-500 mt-1">
                    Vista de atención médica para consulta y registro de evolución de pacientes con cita confirmada.
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <label className="font-bold text-gray-700">Fecha:</label>
                  <input
                    type="date"
                    value={agendaDate}
                    onChange={(e) => setAgendaDate(e.target.value)}
                    className="p-3 border-2 border-gray-300 rounded-xl font-semibold text-gray-800 bg-white"
                  />
                </div>
              </div>

              {loadingAgenda && (
                <div className="text-center py-12 text-gray-500 flex flex-col items-center gap-2">
                  <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
                  <span>Cargando agenda médica...</span>
                </div>
              )}

              {!loadingAgenda && agendaList.length === 0 && (
                <div className="text-center py-12 bg-gray-50 rounded-2xl border border-gray-200 text-gray-500">
                  <Clock className="w-12 h-12 mx-auto mb-3 text-gray-400" />
                  <p className="text-lg font-semibold">No hay citas confirmadas para esta fecha ({agendaDate}).</p>
                </div>
              )}

              {!loadingAgenda && agendaList.length > 0 && (
                <div className="space-y-4">
                  {agendaList.map((item) => (
                    <div key={item.id} className="bg-gray-50 border-2 border-gray-200 rounded-2xl p-6 transition hover:border-blue-300">
                      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-gray-200 pb-4 mb-4">
                        <div className="flex items-center gap-3">
                          <div className="bg-blue-600 text-white font-bold px-4 py-2 rounded-xl text-lg flex items-center gap-2">
                            <Clock className="w-5 h-5" />
                            {item.hora_cita}
                          </div>
                          <div>
                            <h3 className="text-xl font-bold text-gray-800 flex items-center gap-2">
                              <User className="w-5 h-5 text-blue-600" />
                              {item.nombres} {item.ap_paterno} {item.ap_materno || ''}
                            </h3>
                            <p className="text-sm text-gray-500">
                              C.I.: <strong>{item.ci}</strong> | Nacimiento: <strong>{item.fecha_nac}</strong>
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="bg-green-100 text-green-800 px-3 py-1 rounded-full text-xs font-bold flex items-center gap-1">
                            <CheckCircle2 className="w-4 h-4" /> Confirmada
                          </span>
                        </div>
                      </div>

                      {/* NOTA DE EVOLUCIÓN / CONSULTA */}
                      <div className="space-y-2">
                        <label className="text-sm font-bold text-gray-700 flex items-center gap-1">
                          <FileText className="w-4 h-4 text-blue-600" />
                          Nota Clínica / Evolución de la Consulta:
                        </label>
                        <textarea
                          rows="3"
                          placeholder="Escriba aquí los detalles de la consulta, diagnóstico, indicaciones o tratamiento recomendado..."
                          value={notesState[item.id] || ""}
                          onChange={(e) => setNotesState((prev) => ({ ...prev, [item.id]: e.target.value }))}
                          className="w-full p-3 border-2 border-gray-300 rounded-xl text-gray-800 focus:border-blue-500 outline-none"
                        />
                        <div className="flex justify-end">
                          <button
                            type="button"
                            onClick={() => handleSaveClinicalNote(item.id)}
                            disabled={savingNoteId === item.id}
                            className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded-xl font-bold flex items-center gap-2 transition disabled:opacity-50"
                          >
                            {savingNoteId === item.id ? (
                              <>
                                <Loader2 className="w-4 h-4 animate-spin" /> Guardando...
                              </>
                            ) : (
                              <>
                                <Save className="w-4 h-4" /> Guardar Nota Clínica
                              </>
                            )}
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
