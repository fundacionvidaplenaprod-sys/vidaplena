import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getPatients, deletePatient, validateCommitmentCode } from '../../api/patients';
import { useAuth } from '../../context/AuthContext';
import {
    UserPlus, Search, Eye, Edit2,
    Key,
    FileCheck,
    CheckCircle,
    LayoutDashboard,
    Trash2,
    AlertTriangle
} from 'lucide-react';
import { Button } from '../../components/ui/Button';

export default function PatientsListPage() {
    const navigate = useNavigate();
    const { user } = useAuth();
    const isSuperAdmin = user?.role === 'SUPER_ADMIN';
    const [patients, setPatients] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [patientToDelete, setPatientToDelete] = useState(null);
    const [isDeleting, setIsDeleting] = useState(false);

    // Estado para la validación de código
    const [showValidationModal, setShowValidationModal] = useState(false);
    const [validationCode, setValidationCode] = useState('');
    const [validationResult, setValidationResult] = useState(null);
    const [isValidating, setIsValidating] = useState(false);


    useEffect(() => {
        loadPatients();
    }, []);

    const loadPatients = async () => {
        try {
            setLoading(true);
            const data = await getPatients();
            setPatients(data);
        } catch (error) {
            console.error("Error cargando pacientes", error);
        } finally {
            setLoading(false);
        }
    };

    const handleDeleteConfirm = async () => {
        if (!patientToDelete) return;
        try {
            setIsDeleting(true);
            await deletePatient(patientToDelete.id);
            setPatients(prev => prev.filter(p => p.id !== patientToDelete.id));
            setPatientToDelete(null);
        } catch (error) {
            console.error('Error al eliminar beneficiario:', error);
            alert('Error al eliminar el beneficiario. Por favor, intente nuevamente.');
        } finally {
            setIsDeleting(false);
        }
    };

    const handleValidateCode = async (e) => {
        e.preventDefault();
        if (!validationCode.trim()) return;
        try {
            setIsValidating(true);
            setValidationResult(null);
            const result = await validateCommitmentCode(validationCode.trim());
            setValidationResult({ success: true, data: result });
        } catch (error) {
            setValidationResult({ 
                success: false, 
                error: typeof error === 'string' ? error : error.response?.data?.detail || "Error desconocido al validar"
            });
        } finally {
            setIsValidating(false);
        }
    };

    // Filtrado simple
    const filteredPatients = patients.filter(p =>
        p.nombres.toLowerCase().includes(searchTerm.toLowerCase()) ||
        p.ap_paterno.toLowerCase().includes(searchTerm.toLowerCase()) ||
        p.ci.includes(searchTerm)
    );

    const getStatusBadge = (status) => {
        const styles = {
            'ACTIVO': 'bg-green-100 text-green-700 border-green-200',
            'HABILITADO': 'bg-blue-100 text-blue-700 border-blue-200',     // Listo para subir docs
            'PENDIENTE_DOC': 'bg-orange-100 text-orange-700 border-orange-200', // Le faltan papeles
            'PENDIENTE_APORTE': 'bg-yellow-100 text-yellow-800 border-yellow-200', // Alerta de pago ⚠️
            'INACTIVO': 'bg-red-100 text-red-600 border-red-200',
        };
        return (
            <span className={`px-3 py-1 rounded-full text-xs font-bold border ${styles[status] || 'bg-gray-100 text-gray-600'}`}>
                {status || 'DESCONOCIDO'}
            </span>
        );
    };

    return (
        <>
        <div className="p-8 max-w-7xl mx-auto animate-fadeIn">

            {/* HEADER */}
            <div className="flex flex-col md:flex-row justify-between items-center mb-8 gap-4">
                <div>
                    <h1 className="text-3xl font-bold text-gray-800">Beneficiarios</h1>
                    <p className="text-gray-500">Gestión y control de pacientes registrados.</p>
                </div>

                <div className="flex items-center justify-end gap-3 w-full md:w-auto mt-4 md:mt-0">
                    <Link to="/dashboard/registro-paciente" className="flex-1 md:flex-none">
                        <Button className="bg-vida-main hover:bg-vida-hover text-white shadow-lg shadow-vida-main/20 flex items-center justify-center gap-2 w-full">
                            <UserPlus size={18} />
                            Nuevo Registro
                        </Button>
                    </Link>
                    {isSuperAdmin && (
                        <Button 
                            onClick={() => {
                                setValidationCode('');
                                setValidationResult(null);
                                setShowValidationModal(true);
                            }}
                            className="bg-blue-600 hover:bg-blue-700 text-white shadow-lg shadow-blue-200 flex items-center justify-center gap-2 flex-1 md:flex-none"
                        >
                            <FileCheck size={18} className="flex-shrink-0" />
                            <span className="hidden sm:inline">Verificar Carta de Compromiso</span>
                            <span className="sm:hidden">Verificar Carta</span>
                        </Button>
                    )}
                </div>
            </div>

            {/* BARRA DE BÚSQUEDA */}
            <div className="bg-white p-4 rounded-xl shadow-sm border border-gray-100 mb-6 flex items-center gap-4">
                <div className="relative flex-1 max-w-md">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={20} />
                    <input
                        type="text"
                        placeholder="Buscar por nombre o carnet..."
                        className="w-full pl-10 pr-4 py-2 rounded-lg bg-gray-50 border-transparent focus:bg-white focus:ring-2 focus:ring-vida-light/30 outline-none transition-all"
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                    />
                </div>
            </div>

            {/* TABLA */}
            <div className="bg-white rounded-2xl shadow-xl overflow-hidden border border-gray-100">
                <div className="overflow-x-auto">
                    <table className="w-full">
                        <thead className="bg-gray-50 border-b border-gray-100">
                            <tr>
                                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Beneficiario</th>
                                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">C.I.</th>
                                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Diagnóstico</th>
                                <th className="px-6 py-4 text-center text-xs font-bold text-gray-500 uppercase tracking-wider">Estado</th>
                                <th className="px-6 py-4 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Acciones</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                            {loading ? (
                                <tr><td colSpan="5" className="px-6 py-10 text-center text-gray-400">Cargando...</td></tr>
                            ) : filteredPatients.length === 0 ? (
                                <tr><td colSpan="5" className="px-6 py-10 text-center text-gray-400">No se encontraron registros.</td></tr>
                            ) : (
                                filteredPatients.map((patient) => (
                                    <tr key={patient.id} className="hover:bg-gray-50/80 transition-colors">
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <div className="flex items-center">
                                                <div className="h-10 w-10 rounded-full bg-vida-light/20 flex items-center justify-center text-vida-primary font-bold text-sm">
                                                    {patient.nombres.charAt(0)}{patient.ap_paterno.charAt(0)}
                                                </div>
                                                <div className="ml-4">
                                                    <div className="text-sm font-bold text-gray-900">{patient.nombres} {patient.ap_paterno}</div>
                                                    <div className="text-xs text-gray-500">{patient.ap_materno}</div>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600 font-mono">{patient.ci}</td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <span className="text-sm text-gray-700 bg-blue-50 px-2 py-1 rounded-md border border-blue-100">
                                                {patient.medical?.tipo_diabetes || '-'}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-center">
                                            {getStatusBadge(patient.estado)}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                                            <div className="flex items-center justify-end gap-1">

                                                {/* BOTÓN REVISAR DOCUMENTOS (Solo si está HABILITADO) */}
                                                {patient.estado === 'HABILITADO' && (
                                                    <button
                                                        onClick={() => navigate(`/dashboard/pacientes/${patient.id}/review`)}
                                                        className="p-1.5 rounded-full bg-orange-100 text-orange-600 hover:bg-orange-500 hover:text-white transition-all animate-pulse"
                                                        title="Revisar Documentos del Beneficiario"
                                                    >
                                                        <FileCheck size={16} />
                                                    </button>
                                                )}

                                                {/* BOTÓN REVISAR (Solo si está ACTIVO) */}
                                                {patient.estado === 'ACTIVO' && (
                                                    <>
                                                        <button
                                                            onClick={() => navigate(`/dashboard/pacientes/${patient.id}/review`)}
                                                            className="p-1.5 rounded-full bg-yellow-100 text-yellow-700 hover:bg-yellow-200 transition-colors"
                                                            title="Revisar / Reabrir compromiso"
                                                        >
                                                            <FileCheck size={16} />
                                                        </button>
                                                        {/* Indicador de estado activo — no es un botón */}
                                                        <span
                                                            className="inline-flex text-green-500 mx-0.5"
                                                            title="Beneficiario Activo"
                                                        >
                                                            <CheckCircle size={16} />
                                                        </span>
                                                    </>
                                                )}

                                                {/* BOTÓN EDITAR */}
                                                <Link to={`/dashboard/editar-paciente/${patient.id}`}>
                                                    <button
                                                        className="p-1.5 rounded-full text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
                                                        title="Editar Expediente"
                                                    >
                                                        <Edit2 size={16} />
                                                    </button>
                                                </Link>

                                                {/* BOTÓN VER DETALLE */}
                                                <Link to={`/dashboard/pacientes/${patient.id}`}>
                                                    <button
                                                        className="p-1.5 rounded-full text-gray-400 hover:text-vida-main hover:bg-green-50 transition-colors"
                                                        title="Ver Expediente del Beneficiario"
                                                    >
                                                        <Eye size={16} />
                                                    </button>
                                                </Link>

                                                {/* BOTÓN ELIMINAR (SOLO SUPER_ADMIN) */}
                                                {isSuperAdmin ? (
                                                    <button
                                                        onClick={() => setPatientToDelete(patient)}
                                                        className="p-1.5 rounded-full text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                                                        title="Eliminar Beneficiario"
                                                    >
                                                        <Trash2 size={16} />
                                                    </button>
                                                ) : (
                                                    <button
                                                        disabled
                                                        className="p-1.5 rounded-full text-gray-200 cursor-not-allowed"
                                                        title="Solo el Super Administrador puede eliminar beneficiarios"
                                                    >
                                                        <Trash2 size={16} />
                                                    </button>
                                                )}

                                            </div>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        {/* MODAL DE CONFIRMACIÓN DE ELIMINACIÓN */}
        {patientToDelete && (
            <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
                <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 animate-fadeIn">
                    <div className="flex items-center gap-4 mb-4">
                        <div className="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center flex-shrink-0">
                            <AlertTriangle className="text-red-600" size={24} />
                        </div>
                        <div>
                            <h3 className="text-lg font-bold text-gray-800">Eliminar Beneficiario</h3>
                            <p className="text-sm text-gray-500">Esta acción no se puede deshacer.</p>
                        </div>
                    </div>
                    <p className="text-gray-700 mb-6 bg-red-50 p-3 rounded-lg border border-red-100 text-sm">
                        ¿Está seguro que desea eliminar a <strong>{patientToDelete.nombres} {patientToDelete.ap_paterno}</strong> (C.I. {patientToDelete.ci})? Se eliminarán todos sus datos, tratamientos y documentos asociados.
                    </p>
                    <div className="flex gap-3 justify-end">
                        <Button
                            type="button"
                            variant="secondary"
                            onClick={() => setPatientToDelete(null)}
                            disabled={isDeleting}
                            className="px-5"
                        >
                            Cancelar
                        </Button>
                        <Button
                            type="button"
                            onClick={handleDeleteConfirm}
                            disabled={isDeleting}
                            className="bg-red-600 hover:bg-red-700 text-white px-5 shadow-lg shadow-red-200"
                        >
                            {isDeleting ? 'Eliminando...' : 'Sí, eliminar'}
                        </Button>
                    </div>
                </div>
            </div>
        )}

        {/* MODAL DE VALIDACIÓN DE CÓDIGO (SUPER_ADMIN) */}
        {showValidationModal && (
            <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
                <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 animate-fadeIn">
                    <div className="flex items-center gap-3 mb-4 border-b border-gray-100 pb-4">
                        <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center flex-shrink-0">
                            <Key className="text-blue-600" size={20} />
                        </div>
                        <div>
                            <h3 className="text-lg font-bold text-gray-800">Validar Carta de Compromiso</h3>
                        </div>
                    </div>
                    
                    <form onSubmit={handleValidateCode} className="space-y-4">
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">Código de Seguridad Impreso</label>
                            <input
                                type="text"
                                placeholder="Ej: P5-150-A8F2"
                                value={validationCode}
                                onChange={(e) => setValidationCode(e.target.value.toUpperCase())}
                                className="w-full p-3 rounded-lg bg-gray-50 border border-gray-200 text-center font-mono text-xl tracking-widest focus:ring-2 focus:ring-blue-500 outline-none"
                                autoFocus
                            />
                            <p className="text-xs text-gray-500 mt-1">Busque el código en la esquina inferior del documento PDF.</p>
                        </div>

                        {/* RESULTADOS DE VALIDACIÓN */}
                        {validationResult?.success && (
                            <div className="bg-green-50 border border-green-200 p-4 rounded-xl animate-slideDown">
                                <div className="flex items-center gap-2 text-green-700 font-bold mb-2">
                                    <CheckCircle size={18} /> Documento Auténtico
                                </div>
                                <div className="text-sm space-y-1 text-green-900">
                                    <p><span className="font-semibold">Beneficiario/Tutor:</span> {validationResult.data.patient_name}</p>
                                    <p><span className="font-semibold">C.I.:</span> {validationResult.data.ci}</p>
                                    <p><span className="font-semibold">Monto Acordado:</span> {validationResult.data.monto} Bs.</p>
                                </div>
                            </div>
                        )}

                        {validationResult?.error && (
                            <div className="bg-red-50 border border-red-200 p-4 rounded-xl animate-shake">
                                <div className="flex gap-2 text-red-700 font-bold mb-1">
                                    <AlertTriangle size={18} className="flex-shrink-0" /> 
                                    Documento Inválido
                                </div>
                                <p className="text-sm text-red-600 font-medium">
                                    {validationResult.error}
                                </p>
                            </div>
                        )}

                        <div className="flex gap-3 pt-2">
                            <Button
                                type="button"
                                variant="secondary"
                                onClick={() => setShowValidationModal(false)}
                                className="flex-1"
                            >
                                Cerrar
                            </Button>
                            <Button
                                type="submit"
                                disabled={isValidating || !validationCode.trim()}
                                className="flex-1 bg-blue-600 hover:bg-blue-700 text-white shadow-lg shadow-blue-200"
                            >
                                {isValidating ? 'Verificando...' : 'Verificar'}
                            </Button>
                        </div>
                    </form>
                </div>
            </div>
        )}
        </>
    );
}