import { useNavigate } from 'react-router-dom';
import { CalendarOff, LogIn, Home } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import logoVidaPlena from '../../assets/logo.png';

// Aviso que reemplaza al formulario de autoregistro mientras el registro de
// beneficiarios está cerrado (ver AUTOREGISTRO_HABILITADO en constants/features).
// Se muestra en lugar de redirigir en silencio porque quien llega acá suele
// traer el enlace guardado o compartido, y merece saber por qué no puede
// registrarse y qué hacer.
export default function RegistroCerradoPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-vida-bg flex items-center justify-center py-10 px-4">
      <div className="w-full max-w-lg bg-white rounded-2xl shadow-xl p-8 text-center">
        <img src={logoVidaPlena} alt="Fundación V.I.D.A. Plena" className="h-16 w-auto mx-auto mb-6" />

        <div className="w-16 h-16 rounded-full bg-amber-100 text-amber-600 flex items-center justify-center mx-auto mb-5">
          <CalendarOff size={32} />
        </div>

        <h1 className="text-2xl font-bold text-vida-primary mb-3">
          Registro de beneficiarios cerrado
        </h1>

        <p className="text-gray-600 mb-3">
          Por el momento la Fundación V.I.D.A. Plena no está recibiendo nuevos
          registros de beneficiarios.
        </p>
        <p className="text-gray-500 text-sm mb-8">
          Si ya te registraste, puedes ingresar con tu correo y contraseña. Para
          cualquier consulta, comunícate directamente con la Fundación.
        </p>

        <div className="flex flex-col sm:flex-row gap-3">
          <Button
            type="button"
            variant="secondary"
            className="flex-1 flex items-center justify-center gap-2"
            onClick={() => navigate('/')}
          >
            <Home size={18} /> Ir al inicio
          </Button>
          <Button
            type="button"
            className="flex-1 flex items-center justify-center gap-2 bg-vida-main text-white hover:bg-vida-hover"
            onClick={() => navigate('/login')}
          >
            <LogIn size={18} /> Iniciar sesión
          </Button>
        </div>
      </div>
    </div>
  );
}
