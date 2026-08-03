import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'react-hot-toast';
import { Phone, Save } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { getContactInfo, updateContactInfo } from '../../api/siteSettings';

const EMPTY_FORM = {
  phone: '',
  email: '',
  facebook_url: '',
  instagram_url: '',
  whatsapp_number: '',
};

export default function ContactInfoManagementPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState(EMPTY_FORM);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || '{}');
    if (user.role !== 'SUPER_ADMIN') {
      toast.error('Solo SUPER_ADMIN puede editar la información de contacto.');
      navigate('/dashboard/lista-pacientes', { replace: true });
    }
  }, [navigate]);

  const loadInfo = async () => {
    try {
      setLoading(true);
      const data = await getContactInfo();
      setForm({
        phone: data.phone || '',
        email: data.email || '',
        facebook_url: data.facebook_url || '',
        instagram_url: data.instagram_url || '',
        whatsapp_number: data.whatsapp_number || '',
      });
    } catch (error) {
      toast.error('No se pudo cargar la información de contacto.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadInfo(); }, []);

  const setField = (field) => (e) => setForm((prev) => ({ ...prev, [field]: e.target.value }));

  const handleSave = async () => {
    try {
      setSaving(true);
      await updateContactInfo(form);
      toast.success('Información de contacto actualizada.');
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo guardar la información de contacto.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="p-10 text-center text-gray-500 font-bold animate-pulse">Cargando...</div>;

  return (
    <div className="p-6 md:p-8 max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-vida-primary mb-2 flex items-center gap-2">
        <Phone /> Información de Contacto
      </h1>
      <p className="text-sm text-gray-500 mb-6">
        Edita el teléfono, correo y redes sociales que se muestran en la sección "Contacto" de la
        página principal.
      </p>

      <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
        <Input label="Teléfono (se muestra en pantalla)" value={form.phone} onChange={setField('phone')} placeholder="+591 70000000" />
        <Input label="Correo electrónico" type="email" value={form.email} onChange={setField('email')} placeholder="contacto@vidaplena.org" />
        <Input
          label="WhatsApp (solo número, con código de país, sin espacios ni +)"
          value={form.whatsapp_number}
          onChange={setField('whatsapp_number')}
          placeholder="59170000000"
        />
        <Input label="Enlace de Facebook" value={form.facebook_url} onChange={setField('facebook_url')} placeholder="https://facebook.com/..." />
        <Input label="Enlace de Instagram" value={form.instagram_url} onChange={setField('instagram_url')} placeholder="https://instagram.com/..." />

        <div className="flex justify-end pt-2">
          <Button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="w-auto px-6 inline-flex items-center gap-2"
          >
            <Save size={16} /> {saving ? 'Guardando...' : 'Guardar cambios'}
          </Button>
        </div>
      </div>
    </div>
  );
}
