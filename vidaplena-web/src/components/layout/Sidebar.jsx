import { Link, useLocation, useNavigate } from 'react-router-dom';
import { 
  Users, 
  LogOut, 
  LayoutDashboard, 
  X, 
  UserPlus,
  Package,
  BarChart3,
  Wallet
} from 'lucide-react';

export default function Sidebar({ isOpen, onClose }) {
  const location = useLocation();
  const navigate = useNavigate();
  
  // 1. OBTENER ROL
  const user = JSON.parse(localStorage.getItem('user') || '{}');
  const isSuperAdmin = user.role === 'SUPER_ADMIN';

  const handleLogout = () => {
    if (confirm("¿Estás seguro de que deseas salir?")) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      navigate('/login');
    }
  };

  // 2. CONSTRUIR MENÚ DINÁMICO
  const menuItems = [
    // Opción común para todos (Registrador y Admin)
    { 
      path: '/dashboard/lista-pacientes', // Apuntamos directo a la lista
      label: 'Beneficiarios', 
      icon: <Users size={20} /> 
    },
    {
      path: '/dashboard/reportes',
      label: 'Reportes',
      icon: <BarChart3 size={20} />
    },
    {
      path: '/dashboard/revision-aportes',
      label: 'Revisión Aportes',
      icon: <Wallet size={20} />
    },
  ];

  // 👇 AQUÍ ESTÁ EL FILTRO DE SEGURIDAD VISUAL
  if (isSuperAdmin) {
    menuItems.push({
      path: '/dashboard/almacen-donaciones',
      label: 'Almacén / Donaciones',
      icon: <Package size={20} />
    });
    menuItems.push({
      path: '/dashboard/usuarios',
      label: 'Gestión Usuarios',
      icon: <UserPlus size={20} />
    });
  }

  const isActive = (path) => {
     // Lógica simple: si la URL actual empieza con el path del item, está activo
     return location.pathname.startsWith(path);
  };

  return (
    <>
      <aside 
        className={`
          fixed inset-y-0 left-0 z-30 w-64 transform transition-transform duration-300 ease-in-out md:static md:translate-x-0
          bg-vida-primary text-white shadow-2xl flex flex-col
          ${isOpen ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        {/* HEADER */}
        <div className="h-20 flex items-center justify-between px-6 border-b border-white/10">
          <div className="flex items-center gap-3 font-bold text-xl tracking-wide">
            <div className="w-8 h-8 bg-vida-main text-white rounded-lg flex items-center justify-center shadow-lg shadow-black/20">
              <LayoutDashboard size={18} />
            </div>
            <span>Vida Plena</span>
          </div>
          <button onClick={onClose} className="md:hidden text-gray-400 hover:text-white">
            <X size={24} />
          </button>
        </div>

        {/* NAVEGACIÓN */}
        <nav className="flex-1 px-3 py-6 space-y-2 overflow-y-auto">
          <p className="px-4 text-xs font-bold text-gray-400 uppercase mb-3 tracking-widest">
            Principal
          </p>
          
          {menuItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              onClick={() => onClose && onClose()} 
              className={`
                flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 font-medium text-sm
                ${isActive(item.path) 
                  ? 'bg-vida-main text-white shadow-lg shadow-black/20 translate-x-1' 
                  : 'text-gray-300 hover:bg-white/10 hover:text-white'
                }
              `}
            >
              <span>{item.icon}</span>
              <span>{item.label}</span>
            </Link>
          ))}
        </nav>

        {/* FOOTER USUARIO */}
        <div className="p-4 border-t border-white/10 bg-black/10">
            {/* Info del Usuario Logueado */}
            <div className="flex items-center gap-3 mb-4 px-2">
                <div className="w-8 h-8 rounded-full bg-vida-main/20 flex items-center justify-center text-vida-main font-bold border border-vida-main/30">
                    {user.email?.charAt(0).toUpperCase() || 'U'}
                </div>
                <div className="overflow-hidden">
                    <p className="text-xs font-bold text-white truncate">{user.email}</p>
                    <p className="text-[10px] text-gray-400 font-mono tracking-wider">{user.role}</p>
                </div>
            </div>

            <button
                onClick={handleLogout}
                className="flex w-full items-center gap-3 px-4 py-3 text-gray-400 hover:bg-red-500/10 hover:text-red-400 rounded-xl transition-colors font-medium text-sm"
            >
                <LogOut size={20} />
                <span>Cerrar Sesión</span>
            </button>
        </div>
      </aside>
    </>
  );
}