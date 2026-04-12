import { useForm } from 'react-hook-form';
// 👇 AQUÍ ESTÁ LA CLAVE: Subimos 2 niveles (../../)
import { useAuth } from '../../context/AuthContext';
import { useNavigate } from 'react-router-dom';
import { Input } from '../../components/ui/Input';
import { Button } from '../../components/ui/Button';
import { Mail, Lock, LogIn } from 'lucide-react';
import logoVidaPlena from '../../assets/logo.png'; // Asegúrate que esta ruta sea real

export default function LoginPage() {
    const { register, handleSubmit, formState: { errors } } = useForm();
    const { login } = useAuth();
    const navigate = useNavigate();

    const onSubmit = async (data) => {
        try {
            // 1. Login (Tu AuthContext ya maneja la lógica de pedir usuario si falta)
            await login(data);
            
            // 2. Redirección directa al Dashboard
            // (Ahí el DashboardHome se encargará de repartir a Admins o Pacientes)
            console.log("✅ Login exitoso. Entrando al dashboard...");
            navigate('/dashboard', { replace: true });

        } catch (error) {
            console.error("Error en Login:", error);
            // No es necesario alert si ya tienes toast, pero por seguridad:
            // alert("Error al iniciar sesión."); 
        }
    };

    return (
        <div className="min-h-screen w-full flex font-sans bg-white">
            {/* SECCIÓN IZQUIERDA (Branding) */}
            <div className="hidden md:flex md:w-1/2 bg-vida-primary relative overflow-hidden items-center justify-center p-12 text-white">
                <div className="absolute top-0 left-0 w-full h-full bg-gradient-to-br from-vida-primary to-vida-900 opacity-90 z-10"></div>
                <div className="relative z-20 text-center">
                    <div className="bg-white p-2 rounded-full w-72 h-72 mx-auto flex items-center justify-center mb-8 shadow-2xl overflow-hidden">
                        <img src={logoVidaPlena} alt="Logo" className="w-full h-full object-contain rounded-full" />
                    </div>
                    <h1 className="text-4xl font-bold mb-4">Fundación Vida Plena</h1>
                    <p className="text-vida-light text-lg">Comprometidos con la salud y el bienestar.</p>
                </div>
            </div>

            {/* SECCIÓN DERECHA (Formulario) */}
            <div className="w-full md:w-1/2 flex items-center justify-center p-8 bg-white">
                <div className="w-full max-w-md">
                    <div className="md:hidden text-center mb-8">
                         <img src={logoVidaPlena} alt="Logo" className="h-16 w-auto mx-auto mb-4" />
                         <h2 className="text-2xl font-bold text-vida-primary">Bienvenido</h2>
                    </div>

                    <h2 className="hidden md:block text-3xl font-bold text-vida-primary mb-2">Iniciar Sesión</h2>
                    <p className="hidden md:block text-gray-500 mb-8">Ingresa tus credenciales para acceder.</p>

                    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-6">
                        <Input
                            label="Correo Electrónico"
                            type="email"
                            icon={<Mail size={20} />}
                            {...register("email", { required: "Requerido" })}
                            error={errors.email}
                        />

                        <Input
                            label="Contraseña"
                            type="password"
                            icon={<Lock size={20} />}
                            {...register("password", { required: "Requerido" })}
                            error={errors.password}
                        />

                        <Button type="submit" className="mt-4 py-4 text-lg shadow-xl bg-vida-main text-white hover:bg-vida-hover">
                            Entrar al Sistema <LogIn size={20} className="ml-2" />
                        </Button>
                    </form>
                </div>
            </div>
        </div>
    );
}