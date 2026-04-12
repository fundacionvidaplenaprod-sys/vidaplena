import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getPatients } from '../../api/patients';
import {
    UserPlus, Search, Eye, Edit2,
    Key,
    FileCheck,
    CheckCircle,
    LayoutDashboard
} from 'lucide-react';
import { Button } from '../../components/ui/Button';

export default function PatientsListPage() {
    const navigate = useNavigate();
    const [patients, setPatients] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');


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
        <div className="p-8 max-w-7xl mx-auto animate-fadeIn">

            {/* HEADER */}
            <div className="flex flex-col md:flex-row justify-between items-center mb-8 gap-4">
                <div>
                    <h1 className="text-3xl font-bold text-gray-800">Beneficiarios</h1>
                    <p className="text-gray-500">Gestión y control de pacientes registrados.</p>
                </div>

                <Link to="/dashboard/registro-paciente">
                    <Button className="bg-vida-main hover:bg-vida-hover text-white shadow-lg shadow-vida-main/20 flex items-center gap-2">
                        <UserPlus size={18} />
                        Nuevo Registro
                    </Button>
                </Link>
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
                                            {/* 2. BOTÓN REVISAR DOCUMENTOS (Si está HABILITADO) */}
                                            {patient.estado === 'HABILITADO' && (
                                                <button
                                                    onClick={() => navigate(`/dashboard/pacientes/${patient.id}/review`)}
                                                    className="bg-orange-500 text-white p-2 rounded-lg hover:bg-orange-600 shadow-lg shadow-orange-200 animate-pulse transition-all"
                                                    title="Revisar Documentos Subidos"
                                                >
                                                    <FileCheck size={16} />
                                                </button>
                                            )}

                                            {/* 3. ACTIVO: Badge + acceso a revisión administrativa */}
                                            {patient.estado === 'ACTIVO' && (
                                                <>
                                                    <button
                                                        onClick={() => navigate(`/dashboard/pacientes/${patient.id}/review`)}
                                                        className="bg-yellow-100 text-yellow-700 p-2 rounded-lg hover:bg-yellow-200 border border-yellow-200 mx-1"
                                                        title="Revisar / Reabrir compromiso"
                                                    >
                                                        <FileCheck size={16} />
                                                    </button>
                                                    <span className="text-green-600 bg-green-50 p-2 rounded-lg border border-green-200" title="Paciente Activo">
                                                        <CheckCircle size={16} />
                                                    </span>
                                                </>
                                            )}

                                            {/* --- BOTÓN EDITAR (LÁPIZ) --- */}
                                            <Link to={`/dashboard/editar-paciente/${patient.id}`}>
                                                <button
                                                    className="text-gray-400 hover:text-blue-600 transition-colors mx-1 p-1 hover:bg-blue-50 rounded-full"
                                                    title="Editar Expediente Completo"
                                                >
                                                    <Edit2 size={18} />
                                                </button>
                                            </Link>

                                            {/* --- BOTÓN VER DETALLE (OJO) --- */}
                                            <Link to={`/dashboard/pacientes/${patient.id}`}>
                                                <button
                                                    className="text-gray-400 hover:text-vida-main transition-colors mx-1 p-1 hover:bg-green-50 rounded-full"
                                                    title="Ver Expediente"
                                                >
                                                    <Eye size={18} />
                                                </button>
                                            </Link>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}