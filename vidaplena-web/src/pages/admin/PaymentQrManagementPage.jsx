import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'react-hot-toast';
import { QrCode, UploadCloud } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { getSiteAssets, updateSiteAsset } from '../../api/siteAssets';

const SLOTS = [
  {
    key: 'qr_donaciones',
    title: 'QR de Donaciones',
    description: 'Se muestra en la página principal, sección "Apoya Nuestra Causa", para donaciones libres.',
  },
  {
    key: 'qr_compromisos',
    title: 'QR de Compromisos (Aporte Solidario)',
    description: 'Se muestra al registrar un aporte solidario mensual. El monto es variable, mínimo Bs. 100.',
  },
  {
    key: 'qr_consultas',
    title: 'QR de Consultas (Cita SAPAM)',
    description: 'Se muestra al agendar una cita, para la donación institucional de Bs. 70 de la consulta.',
  },
];

function QrSlotCard({ slot, asset, onUploaded }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [uploading, setUploading] = useState(false);

  const handleFileChange = (f) => {
    setFile(f);
    setPreview(f ? URL.createObjectURL(f) : null);
  };

  const handleUpload = async () => {
    if (!file) {
      toast.error('Selecciona una imagen de QR para subir.');
      return;
    }
    try {
      setUploading(true);
      const updated = await updateSiteAsset(slot.key, file);
      toast.success(`${slot.title} actualizado.`);
      setFile(null);
      setPreview(null);
      onUploaded(updated);
    } catch (error) {
      toast.error(error.message || 'No se pudo subir el QR.');
    } finally {
      setUploading(false);
    }
  };

  const displayImage = preview || asset?.url;

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm flex flex-col sm:flex-row gap-4">
      <div className="flex-shrink-0 flex justify-center">
        {displayImage ? (
          <img src={displayImage} alt={slot.title} className="w-32 h-32 object-cover rounded-lg border bg-white" />
        ) : (
          <div className="w-32 h-32 rounded-lg border-2 border-dashed border-gray-300 flex items-center justify-center text-gray-300">
            <QrCode size={32} />
          </div>
        )}
      </div>
      <div className="flex-1 space-y-2">
        <h3 className="font-bold text-gray-800">{slot.title}</h3>
        <p className="text-xs text-gray-500">{slot.description}</p>
        {asset?.updated_at && (
          <p className="text-xs text-gray-400">
            Última actualización: {new Date(asset.updated_at).toLocaleString('es-BO')}
          </p>
        )}
        <div className="flex flex-col sm:flex-row gap-2 pt-1">
          <label
            htmlFor={`qr-file-${slot.key}`}
            className="flex-1 border-2 border-dashed border-gray-300 rounded-xl px-3 py-2 flex items-center gap-2 cursor-pointer hover:border-vida-main hover:bg-vida-bg/50 transition-colors"
          >
            <UploadCloud size={18} className="text-vida-main flex-shrink-0" />
            <span className="text-sm text-gray-600 truncate">
              {file ? file.name : 'Elegir imagen (JPG, PNG o WEBP)'}
            </span>
          </label>
          <input
            id={`qr-file-${slot.key}`}
            type="file"
            accept=".jpg,.jpeg,.png,.webp"
            className="hidden"
            onChange={(e) => handleFileChange(e.target.files?.[0] || null)}
          />
          <Button
            type="button"
            onClick={handleUpload}
            disabled={uploading || !file}
            className="w-auto px-4 text-sm inline-flex items-center gap-1"
          >
            {uploading ? 'Subiendo...' : asset ? 'Reemplazar' : 'Subir'}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function PaymentQrManagementPage() {
  const navigate = useNavigate();
  const [assets, setAssets] = useState({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || '{}');
    if (user.role !== 'SUPER_ADMIN') {
      toast.error('Solo SUPER_ADMIN puede administrar los QR de pago.');
      navigate('/dashboard/lista-pacientes', { replace: true });
    }
  }, [navigate]);

  const loadAssets = async () => {
    try {
      setLoading(true);
      const data = await getSiteAssets();
      const byKey = {};
      data.forEach((a) => { byKey[a.key] = a; });
      setAssets(byKey);
    } catch (error) {
      toast.error('No se pudieron cargar los QR configurados.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAssets(); }, []);

  const handleUploaded = (updated) => {
    setAssets((prev) => ({ ...prev, [updated.key]: updated }));
  };

  return (
    <div className="p-6 md:p-8 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold text-vida-primary mb-2 flex items-center gap-2">
        <QrCode /> QR de Pagos
      </h1>
      <p className="text-sm text-gray-500 mb-6">
        Administra los códigos QR de pago que se muestran en la página pública y en el flujo de
        agendamiento de citas. El monto que codifica cada QR se define al generarlo (fuera del
        sistema); aquí solo se administra la imagen.
      </p>

      {loading ? (
        <p className="text-sm text-gray-500">Cargando...</p>
      ) : (
        <div className="space-y-4">
          {SLOTS.map((slot) => (
            <QrSlotCard key={slot.key} slot={slot} asset={assets[slot.key]} onUploaded={handleUploaded} />
          ))}
        </div>
      )}
    </div>
  );
}
