import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getPatientById, activatePatient, updatePatient, changePatientStatus } from '../../api/patients';
import { Button } from '../../components/ui/Button';
import { ArrowLeft, CheckCircle, User, Activity, Edit2, AlertTriangle, Pill } from 'lucide-react';

export default function PatientDetailsPage() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [patient, setPatient] = useState(null);
    const [loading, setLoading] = useState(true);
    const [activating, setActivating] = useState(false);
    const [isChangingStatus, setIsChangingStatus] = useState(false);

    useEffect(() => {
        loadData();
    }, [id]);

    const loadData = async () => {
        try {
            const data = await getPatientById(id);
            setPatient(data);
        } catch (error) {
            console.error(error);
            alert("Error cargando ficha del paciente");
            navigate('/dashboard');
        } finally {
            setLoading(false);
        }
    };

    const handleActivate = async () => {
        const confirmacion = window.confirm(
            `¿Estás seguro de activar a ${patient.nombres}?\n\nEsto habilitará su acceso al sistema.`
        );

        if (!confirmacion) return;

        try {
            setActivating(true);
            await activatePatient(id);

            alert(
                `✅ ¡PACIENTE ACTIVADO!\n\n` +
                `Usuario: ${patient.email || patient.ci}\n` +
                `Contraseña: ${patient.ci}\n\n` +
                `Informe al paciente para que inicie sesión.`
            );
            loadData();
        } catch (error) {
            alert("Error al activar: " + (error.response?.data?.detail || "Error desconocido"));
        } finally {
            setActivating(false);
        }
    };

    const handleManualStatusChange = async (newStatus) => {
        if (!confirm(`¿Forzar cambio de estado a ${newStatus}?`)) return;

        try {
            await changePatientStatus(id, newStatus);
            setIsChangingStatus(false);
            loadData(); // Recargar para ver cambios
        } catch (error) {
            alert("Error al cambiar estado");
        }
    };

    if (loading) return <div className="p-10 text-center text-gray-500">Cargando ficha...</div>;
    if (!patient) return <div className="p-10 text-center">No encontrado</div>;

    // --- 1. FUNCIÓN PARA FORMATEAR FECHA SIN ERRORES DE ZONA HORARIA ---
    const formatDate = (dateString) => {
        if (!dateString) return '-';
        // Cortamos la hora si viene (YYYY-MM-DDT00:00:00 -> YYYY-MM-DD)
        const rawDate = dateString.split('T')[0];
        const [year, month, day] = rawDate.split('-');
        return `${day}/${month}/${year}`; // Retorna DD/MM/YYYY
    };

    // --- 2. FUNCIÓN PARA CALCULAR EDAD (Fallback si el backend falla) ---
    const getAge = () => {
        if (patient.edad_calc) return patient.edad_calc; // Si el backend ya la calculó, úsala.

        if (patient.fecha_nacimiento) {
            const birth = new Date(patient.fecha_nacimiento);
            const today = new Date();
            let age = today.getFullYear() - birth.getFullYear();
            const m = today.getMonth() - birth.getMonth();
            if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) {
                age--;
            }
            return age;
        }
        return '?';
    };

    // Helpers para mostrar datos
    const getCelular = () => patient.tel_contacto || patient.celular || 'No registrado';
    const getMedicalInfo = () => patient.medical || {};

    return (
        <div className="p-8 max-w-6xl mx-auto animate-fadeIn pb-24">

            {/* HEADER */}
            <div className="flex items-center justify-between mb-8">
                <div className="flex items-center gap-4">
                    <button onClick={() => navigate('/dashboard')} className="p-2 hover:bg-gray-100 rounded-full transition-colors">
                        <ArrowLeft size={24} className="text-gray-500" />
                    </button>
                    <div>
                        <h1 className="text-2xl font-bold text-gray-800 flex items-center gap-3">
                            {patient.nombres} {patient.ap_paterno} {patient.ap_materno}

                            {/* BOTÓN EDITAR (Lleva al formulario completo) */}
                            <button
                                onClick={() => navigate(`/dashboard/editar-paciente/${patient.id}`)}
                                className="p-2 bg-gray-100 text-gray-600 rounded-lg hover:bg-vida-main hover:text-white transition-colors"
                                title="Editar Expediente Completo"
                            >
                                <Edit2 size={18} />
                            </button>
                        </h1>
                        <p className="text-gray-500 text-sm">C.I. {patient.ci} {patient.complemento_ci}</p>
                    </div>
                </div>

                <div className="relative group">
                    {isChangingStatus ? (
                        <select
                            className="bg-white text-gray-900 border border-gray-300 rounded-lg px-3 py-1 text-sm shadow-sm outline-none focus:ring-2 focus:ring-vida-main"
                            value={patient.estado}
                            onChange={(e) => handleManualStatusChange(e.target.value)}
                            onBlur={() => setIsChangingStatus(false)} // Si hace clic fuera, se cierra
                            autoFocus
                        >
                            <option value="PENDIENTE_DOC">PENDIENTE</option>
                            <option value="HABILITADO">HABILITADO</option>
                            <option value="ACTIVO">ACTIVO</option>
                            <option value="INACTIVO">INACTIVO</option>
                        </select>
                    ) : (
                        <div
                            onClick={() => setIsChangingStatus(true)}
                            className="cursor-pointer transition-transform hover:scale-105"
                            title="Clic para cambiar estado manualmente"
                        >
                            <span className={`px-4 py-2 rounded-full text-sm font-bold border 
                      ${patient.estado === 'ACTIVO' ? 'bg-green-100 text-green-700 border-green-200' :
                                    patient.estado === 'HABILITADO' ? 'bg-blue-100 text-blue-700 border-blue-200' :
                                        'bg-orange-100 text-orange-700 border-orange-200'
                                }`}>
                                {patient.estado}
                            </span>
                            {/* Icono pequeño de edición que aparece al pasar el mouse */}
                            <span className="absolute -top-1 -right-1 bg-gray-600 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity text-[10px]">
                                <Edit2 size={10} />
                            </span>
                        </div>
                    )}
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

                {/* COLUMNA IZQUIERDA: DATOS PERSONALES */}
                <div className="lg:col-span-1 space-y-6">
                    <div className="bg-white p-6 rounded-2xl shadow-sm border border-gray-100">
                        <h3 className="font-bold text-gray-800 mb-4 flex items-center gap-2 border-b pb-2">
                            <User size={18} className="text-vida-main" /> Datos Personales
                        </h3>
                        <div className="space-y-4 text-sm">
                            <div className="grid grid-cols-2 gap-2">
                                <div>
                                    <span className="block text-gray-400 text-xs uppercase font-bold">Fecha Nacimiento</span>
                                    <span className="font-medium text-gray-700">{formatDate(patient.fecha_nac)}</span>
                                </div>
                                <div>
                                    <span className="block text-gray-400 text-xs uppercase font-bold">Edad</span>
                                    <span className="font-medium text-gray-700">({getAge()} años)</span>
                                </div>
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                                <div>
                                    <span className="block text-gray-400 text-xs uppercase font-bold">Peso</span>
                                    <span className="font-medium text-gray-700">{patient.peso ? `${patient.peso} Kg` : '-'}</span>
                                </div>
                                <div>
                                    <span className="block text-gray-400 text-xs uppercase font-bold">Altura</span>
                                    <span className="font-medium text-gray-700">{patient.altura ? `${patient.altura} m` : '-'}</span>
                                </div>
                            </div>
                            <div>
                                <span className="block text-gray-400 text-xs uppercase font-bold">Tipo Sangre</span>
                                <span className="font-medium text-gray-700">{patient.tipo_sangre || '-'}</span>
                            </div>
                            <div>
                                <span className="block text-gray-400 text-xs uppercase font-bold">Celular / Contacto</span>
                                {/* CORRECCIÓN AQUÍ: Mostramos tel_contacto o celular */}
                                <span className="font-medium text-gray-800 text-lg">{getCelular()}</span>
                            </div>
                            <div>
                                <span className="block text-gray-400 text-xs uppercase font-bold">Dirección</span>
                                <span className="font-medium text-gray-700">
                                    {patient.departamento}, {patient.municipio}<br />
                                    {patient.zona} - {patient.direccion}
                                </span>
                            </div>
                        </div>
                    </div>

                    {/* TUTOR SI EXISTE */}
                    {patient.tutor && (
                        <div className="bg-orange-50 p-6 rounded-2xl shadow-sm border border-orange-100">
                            <h3 className="font-bold text-orange-800 mb-3 text-sm uppercase">Tutor Legal</h3>
                            <p className="font-bold text-gray-800">{patient.tutor.nombres} {patient.tutor.apellidos}</p>
                            <p className="text-sm text-gray-600">CI: {patient.tutor.ci}</p>
                            <p className="text-sm text-gray-600">Tel: {patient.tutor.telefonos}</p>
                        </div>
                    )}
                </div>

                {/* COLUMNA DERECHA: DATOS MÉDICOS (Expandida) */}
                <div className="lg:col-span-2 space-y-6">

                    {/* 1. RESUMEN CLÍNICO */}
                    <div className="bg-white p-6 rounded-2xl shadow-sm border border-gray-100">
                        <h3 className="font-bold text-gray-800 mb-4 flex items-center gap-2 border-b pb-2">
                            <Activity size={18} className="text-vida-main" /> Ficha Clínica
                        </h3>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                            <div className="bg-blue-50 p-4 rounded-xl border border-blue-100">
                                <span className="block text-blue-400 text-xs uppercase font-bold mb-1">Diagnóstico Principal (Diabetes)</span>
                                <span className="text-xl font-bold text-blue-700 block">
                                    {getMedicalInfo().tipo_diabetes || 'Sin diagnóstico'}
                                </span>
                            </div>
                            <div className="bg-gray-50 p-4 rounded-xl border border-gray-100">
                                <span className="block text-gray-400 text-xs uppercase font-bold mb-1">Tiempo con enfermedad</span>
                                <span className="text-lg font-medium text-gray-700">
                                    {getMedicalInfo().tiempo_enfermedad || 'No especificado'}
                                </span>
                            </div>
                        </div>

                        {/* 2. TRATAMIENTOS */}
                        <div className="mb-6">
                            <h4 className="font-bold text-gray-700 mb-3 flex items-center gap-2">
                                <Pill size={16} /> Tratamiento Actual
                            </h4>
                            {patient.treatments && patient.treatments.length > 0 ? (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                    {patient.treatments.map((t, idx) => (
                                        <div key={idx} className="flex items-start gap-3 p-3 rounded-lg border border-gray-100 bg-gray-50">
                                            <div className="bg-white p-2 rounded shadow-sm font-bold text-xs text-vida-main border border-gray-100">
                                                INSULINA
                                            </div>
                                            <div>
                                                <p className="font-bold text-gray-800 text-sm">{t.nombre}</p>
                                                <p className="text-xs text-gray-500">UI por día: {t.dosis_diaria ?? 0}</p>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <p className="text-sm text-gray-400 italic">No hay tratamientos registrados.</p>
                            )}
                        </div>

                        {/* 3. COMPLICACIONES */}
                        <div>
                            <h4 className="font-bold text-gray-700 mb-3 flex items-center gap-2">
                                <AlertTriangle size={16} /> Complicaciones Reportadas
                            </h4>
                            {patient.complications && patient.complications.length > 0 ? (
                                <div className="flex flex-wrap gap-2">
                                    {patient.complications.map((c, idx) => (
                                        <span key={idx} className="px-3 py-1 bg-red-50 text-red-700 border border-red-100 rounded-full text-sm font-medium">
                                            {c.complication_code === 'OTRAS' && c.detalle ? c.detalle : c.complication_code}
                                        </span>
                                    ))}
                                </div>
                            ) : (
                                <p className="text-sm text-gray-400 italic">Ninguna complicación reportada.</p>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            {/* FOOTER ACTION */}
            {patient.estado !== 'ACTIVO' && patient.estado !== 'HABILITADO' && (
                <div className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 p-4 md:pl-72 flex justify-end items-center gap-4 z-10 shadow-lg">
                    <p className="text-xs text-gray-400 mr-auto hidden md:block">
                        * Revise cuidadosamente los datos médicos antes de aprobar.
                    </p>
                    <Button variant="secondary" onClick={() => navigate('/dashboard')}>
                        Volver
                    </Button>
                    <Button
                        onClick={handleActivate}
                        disabled={activating}
                        className="bg-green-600 hover:bg-green-700 text-white shadow-lg shadow-green-200"
                    >
                        {activating ? 'Procesando...' : 'Aprobar y Crear Usuario'}
                        {!activating && <CheckCircle size={18} className="ml-2" />}
                    </Button>
                </div>
            )}
        </div>
    );
}