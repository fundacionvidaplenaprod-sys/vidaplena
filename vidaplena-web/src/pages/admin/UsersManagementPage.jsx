import { useEffect, useState } from 'react';
import { 
    Users, Search, UserPlus, Edit2, Trash2, 
    Shield, Mail, Lock, Power, RefreshCw, X
} from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { toast } from 'react-hot-toast';
import client from '../../api/axios';

export default function UsersManagementPage() {
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    
    // ESTADOS PARA EL MODAL (Crear/Editar)
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingUser, setEditingUser] = useState(null); // null = Modo Crear
    const [formData, setFormData] = useState({ email: '', password: '', role: 'REGISTRADOR' });
    const [processing, setProcessing] = useState(false);

    // Obtener el ID del usuario actual para no auto-eliminarse
    const currentUser = JSON.parse(localStorage.getItem('user') || '{}');

    // 1. CARGAR USUARIOS
    const loadUsers = async () => {
        try {
            setLoading(true);
            const { data } = await client.get('/users/');
            setUsers(data);
        } catch (error) {
            console.error("Error cargando usuarios:", error);
            toast.error("Error al cargar la lista de usuarios");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadUsers();
    }, []);

    // 2. ABRIR MODAL (Crear o Editar)
    const openModal = (user = null) => {
        if (user) {
            // MODO EDITAR
            setEditingUser(user);
            setFormData({ 
                email: user.email, 
                password: '', // Password vacío por seguridad (si escribe, se cambia)
                role: user.role 
            });
        } else {
            // MODO CREAR
            setEditingUser(null);
            setFormData({ email: '', password: '', role: 'REGISTRADOR' });
        }
        setIsModalOpen(true);
    };

    // 3. GUARDAR (Create / Update)
    const handleSubmit = async (e) => {
        e.preventDefault();
        setProcessing(true);

        try {
            if (editingUser) {
                // UPDATE
                await client.put(`/users/${editingUser.id}`, formData);
                toast.success("Usuario actualizado correctamente");
            } else {
                // CREATE
                await client.post('/users/', formData);
                toast.success("Usuario creado exitosamente");
            }
            setIsModalOpen(false);
            loadUsers();
        } catch (error) {
            console.error(error);
            const msg = error.response?.data?.detail || "Error al guardar";
            toast.error(msg);
        } finally {
            setProcessing(false);
        }
    };

    // 4. DAR DE BAJA / REACTIVAR (Toggle)
    const handleToggleStatus = async (user) => {
        const action = user.estado === 'ACTIVO' ? 'desactivar' : 'activar';
        if (!confirm(`¿Estás seguro de ${action} a ${user.email}?`)) return;

        try {
            await client.put(`/users/${user.id}/toggle-status`);
            toast.success(`Usuario ${user.estado === 'ACTIVO' ? 'desactivado' : 'activado'}`);
            loadUsers();
        } catch (error) {
            toast.error("Error al cambiar estado");
        }
    };

    // 5. ELIMINAR (Hard Delete)
    const handleDelete = async (user) => {
        if (!confirm(`⚠️ ¡CUIDADO! ⚠️\n\nEstás a punto de ELIMINAR PERMANENTEMENTE a ${user.email}.\nEsto borrará sus logs y accesos.\n\n¿Confirmar eliminación?`)) return;

        try {
            await client.delete(`/users/${user.id}`);
            toast.success("Usuario eliminado");
            loadUsers();
        } catch (error) {
            const msg = error.response?.data?.detail || "Error al eliminar";
            toast.error(msg);
        }
    };

    // FILTRO
    const filteredUsers = users.filter(u => 
        u.email.toLowerCase().includes(searchTerm.toLowerCase())
    );

    return (
        <div className="p-8 max-w-7xl mx-auto animate-fadeIn min-h-screen pb-20">
            {/* HEADER */}
            <div className="flex flex-col md:flex-row justify-between items-center mb-8 gap-4">
                <div>
                    <h1 className="text-3xl font-bold text-gray-800 flex items-center gap-2">
                        <Users className="text-vida-primary" /> Gestión de Usuarios
                    </h1>
                    <p className="text-gray-500">Administre los accesos de Super Admins y Registradores.</p>
                </div>
                <Button onClick={() => openModal()} className="bg-vida-main hover:bg-vida-hover text-white shadow-lg flex items-center gap-2">
                    <UserPlus size={18} /> Nuevo Usuario
                </Button>
            </div>

            {/* BUSCADOR */}
            <div className="bg-white p-4 rounded-xl shadow-sm border border-gray-100 mb-6 flex items-center gap-4">
                <div className="relative flex-1 max-w-md">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={20} />
                    <input
                        type="text"
                        placeholder="Buscar por correo electrónico..."
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
                                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Usuario</th>
                                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Rol</th>
                                <th className="px-6 py-4 text-center text-xs font-bold text-gray-500 uppercase tracking-wider">Estado</th>
                                <th className="px-6 py-4 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Acciones</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                            {loading ? (
                                <tr><td colSpan="4" className="px-6 py-10 text-center text-gray-400">Cargando usuarios...</td></tr>
                            ) : filteredUsers.length === 0 ? (
                                <tr><td colSpan="4" className="px-6 py-10 text-center text-gray-400">No hay usuarios registrados.</td></tr>
                            ) : (
                                filteredUsers.map((user) => (
                                    <tr key={user.id} className="hover:bg-gray-50/80 transition-colors">
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <div className="flex items-center gap-3">
                                                <div className="w-8 h-8 rounded-full bg-vida-main/10 flex items-center justify-center text-vida-main font-bold">
                                                    {user.email.charAt(0).toUpperCase()}
                                                </div>
                                                <div className="text-sm font-medium text-gray-900">{user.email}</div>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <span className={`px-2 py-1 rounded text-xs font-bold border ${
                                                user.role === 'SUPER_ADMIN' 
                                                    ? 'bg-purple-100 text-purple-700 border-purple-200' 
                                                    : 'bg-blue-100 text-blue-700 border-blue-200'
                                            }`}>
                                                {user.role.replace('_', ' ')}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-center">
                                            <span className={`px-2 py-1 rounded-full text-xs font-bold ${
                                                user.estado === 'ACTIVO' 
                                                    ? 'bg-green-100 text-green-700' 
                                                    : 'bg-red-100 text-red-600'
                                            }`}>
                                                {user.estado}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                                            <div className="flex items-center justify-end gap-2">
                                                {/* No permitir editarse a sí mismo completamente, ni borrar */}
                                                
                                                <button 
                                                    onClick={() => openModal(user)}
                                                    className="p-2 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                                                    title="Editar"
                                                >
                                                    <Edit2 size={18} />
                                                </button>

                                                {user.id !== currentUser.id && ( // Prohibido desactivarse a uno mismo
                                                    <>
                                                        <button 
                                                            onClick={() => handleToggleStatus(user)}
                                                            className={`p-2 rounded-lg transition-colors ${
                                                                user.estado === 'ACTIVO' 
                                                                    ? 'text-green-500 hover:bg-red-50 hover:text-red-600' 
                                                                    : 'text-red-500 hover:bg-green-50 hover:text-green-600'
                                                            }`}
                                                            title={user.estado === 'ACTIVO' ? 'Desactivar' : 'Reactivar'}
                                                        >
                                                            <Power size={18} />
                                                        </button>

                                                        <button 
                                                            onClick={() => handleDelete(user)}
                                                            className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                                                            title="Eliminar permanentemente"
                                                        >
                                                            <Trash2 size={18} />
                                                        </button>
                                                    </>
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

            {/* MODAL DE CREACIÓN / EDICIÓN */}
            {isModalOpen && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4 animate-fadeIn">
                    <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
                        <div className="flex justify-between items-center mb-6 border-b pb-4">
                            <h3 className="text-xl font-bold text-gray-800 flex items-center gap-2">
                                {editingUser ? <Edit2 size={20}/> : <UserPlus size={20}/>}
                                {editingUser ? 'Editar Usuario' : 'Nuevo Usuario'}
                            </h3>
                            <button onClick={() => setIsModalOpen(false)} className="text-gray-400 hover:text-gray-600">
                                <X size={24} />
                            </button>
                        </div>
                        
                        <form onSubmit={handleSubmit} className="space-y-4">
                            <div>
                                <label className="block text-sm font-bold text-gray-700 mb-1">Email</label>
                                <div className="relative">
                                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
                                    <input
                                        type="email"
                                        required
                                        className="w-full pl-10 pr-4 py-2 border rounded-lg focus:ring-2 focus:ring-vida-primary outline-none"
                                        value={formData.email}
                                        onChange={(e) => setFormData({...formData, email: e.target.value})}
                                    />
                                </div>
                            </div>

                            <div>
                                <label className="block text-sm font-bold text-gray-700 mb-1">
                                    {editingUser ? 'Nueva Contraseña (Opcional)' : 'Contraseña'}
                                </label>
                                <div className="relative">
                                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
                                    <input
                                        type="password"
                                        required={!editingUser} // Solo obligatorio al crear
                                        placeholder={editingUser ? "Dejar vacío para mantener actual" : "••••••"}
                                        className="w-full pl-10 pr-4 py-2 border rounded-lg focus:ring-2 focus:ring-vida-primary outline-none"
                                        value={formData.password}
                                        onChange={(e) => setFormData({...formData, password: e.target.value})}
                                    />
                                </div>
                            </div>

                            <div>
                                <label className="block text-sm font-bold text-gray-700 mb-1">Rol</label>
                                <div className="relative">
                                    <Shield className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
                                    <select
                                        className="w-full pl-10 pr-4 py-2 border rounded-lg focus:ring-2 focus:ring-vida-primary outline-none bg-white"
                                        value={formData.role}
                                        onChange={(e) => setFormData({...formData, role: e.target.value})}
                                    >
                                        <option value="REGISTRADOR">REGISTRADOR (Operativo)</option>
                                        <option value="SUPER_ADMIN">SUPER ADMIN (Total)</option>
                                        {/* No permitimos crear pacientes aquí, eso es otro flujo */}
                                    </select>
                                </div>
                            </div>

                            <div className="pt-4 flex gap-3">
                                <Button 
                                    type="button" 
                                    variant="secondary" 
                                    className="flex-1 bg-gray-100 text-gray-700"
                                    onClick={() => setIsModalOpen(false)}
                                >
                                    Cancelar
                                </Button>
                                <Button 
                                    type="submit" 
                                    className="flex-1 bg-vida-main text-white"
                                    disabled={processing}
                                >
                                    {processing ? 'Guardando...' : 'Guardar'}
                                </Button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}