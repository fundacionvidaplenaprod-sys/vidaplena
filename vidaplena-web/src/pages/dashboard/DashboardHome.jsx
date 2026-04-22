import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LayoutDashboard } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

export default function DashboardHome() {
    const navigate = useNavigate();
    const [status, setStatus] = useState("Verificando acceso...");

    const { user, isAuthenticated, loading } = useAuth();
 
    useEffect(() => {
        if (loading) return;

        if (!isAuthenticated || !user) {
            console.log("❌ No hay sesión, volviendo al login");
            navigate('/login');
            return;
        }

        setStatus(`Hola ${user.email}, redirigiendo...`);
        
        // Usamos setTimeout para dar un respiro a React y evitar parpadeos
        setTimeout(() => {
            if (['SUPER_ADMIN', 'REGISTRADOR'].includes(user.role)) {
                // Admin -> Lista
                navigate('/dashboard/lista-pacientes', { replace: true });
            } else if (user.role === 'PACIENTE') {
                // Paciente -> Su Portal
                navigate('/mi-portal', { replace: true });
            } else {
                // Rol raro -> Login
                navigate('/login');
            }
        }, 500);

    }, [navigate, user, isAuthenticated, loading]);

    return (
        <div className="flex flex-col items-center justify-center h-full min-h-[50vh] text-gray-500">
            <LayoutDashboard size={64} className="text-vida-main animate-bounce mb-4"/>
            <p className="font-bold text-xl">{status}</p>
        </div>
    );
}