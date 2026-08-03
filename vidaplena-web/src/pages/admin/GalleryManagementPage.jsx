import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'react-hot-toast';
import { Images, UploadCloud, Trash2, Save } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { getGalleryPhotos, createGalleryPhoto, updateGalleryPhoto, deleteGalleryPhoto } from '../../api/gallery';

export default function GalleryManagementPage() {
  const navigate = useNavigate();
  const [photos, setPhotos] = useState([]);
  const [loading, setLoading] = useState(false);

  const [foto, setFoto] = useState(null);
  const [preview, setPreview] = useState(null);
  const [caption, setCaption] = useState('');
  const [orden, setOrden] = useState(0);
  const [uploading, setUploading] = useState(false);

  const [drafts, setDrafts] = useState({});
  const [savingId, setSavingId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || '{}');
    if (user.role !== 'SUPER_ADMIN') {
      toast.error('Solo SUPER_ADMIN puede administrar la Galería.');
      navigate('/dashboard/lista-pacientes', { replace: true });
    }
  }, [navigate]);

  const loadPhotos = async () => {
    try {
      setLoading(true);
      const data = await getGalleryPhotos();
      setPhotos(data);
      const nextDrafts = {};
      data.forEach((p) => { nextDrafts[p.id] = { caption: p.caption || '', orden: p.orden }; });
      setDrafts(nextDrafts);
    } catch (error) {
      toast.error('No se pudieron cargar las fotos de la galería.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadPhotos(); }, []);

  const handleFileChange = (file) => {
    setFoto(file);
    setPreview(file ? URL.createObjectURL(file) : null);
  };

  const resetForm = () => {
    setFoto(null);
    setPreview(null);
    setCaption('');
    setOrden(0);
  };

  const handleUpload = async () => {
    if (!foto) {
      toast.error('Selecciona una foto para subir.');
      return;
    }
    try {
      setUploading(true);
      await createGalleryPhoto({ foto, caption, orden });
      toast.success('Foto agregada a la galería.');
      resetForm();
      loadPhotos();
    } catch (error) {
      toast.error(error.message || 'No se pudo subir la foto.');
    } finally {
      setUploading(false);
    }
  };

  const handleSaveDraft = async (photoId) => {
    const draft = drafts[photoId];
    try {
      setSavingId(photoId);
      await updateGalleryPhoto(photoId, { caption: draft.caption, orden: Number(draft.orden) || 0 });
      toast.success('Foto actualizada.');
      loadPhotos();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'No se pudo actualizar la foto.');
    } finally {
      setSavingId(null);
    }
  };

  const handleDelete = async (photo) => {
    const confirmado = window.confirm(`¿Eliminar esta foto de la galería permanentemente?`);
    if (!confirmado) return;
    try {
      setDeletingId(photo.id);
      await deleteGalleryPhoto(photo.id);
      toast.success('Foto eliminada.');
      loadPhotos();
    } catch (error) {
      toast.error('No se pudo eliminar la foto.');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="p-6 md:p-8 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold text-vida-primary mb-2 flex items-center gap-2">
        <Images /> Galería de la Página Principal
      </h1>
      <p className="text-sm text-gray-500 mb-6">
        Administra las fotos que se muestran en la sección "Galería" de la página pública. El número de
        orden determina la posición (menor primero).
      </p>

      <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 mb-8 space-y-4">
        <div className="flex flex-col md:flex-row gap-4 md:items-start">
          <div className="flex-1">
            <label
              htmlFor="gallery-photo-file"
              className="w-full border-2 border-dashed border-gray-300 rounded-xl p-4 flex items-center gap-3 cursor-pointer hover:border-vida-main hover:bg-vida-bg/50 transition-colors"
            >
              {preview ? (
                <img src={preview} alt="Vista previa" className="h-16 w-16 object-cover rounded-lg flex-shrink-0" />
              ) : (
                <UploadCloud size={22} className="text-vida-main flex-shrink-0" />
              )}
              <span className="text-sm text-gray-600 truncate">
                {foto ? foto.name : 'Subir foto (JPG, PNG o WEBP)'}
              </span>
            </label>
            <input
              id="gallery-photo-file"
              type="file"
              accept=".jpg,.jpeg,.png,.webp"
              className="hidden"
              onChange={(e) => handleFileChange(e.target.files?.[0] || null)}
            />
          </div>
          <Input label="Descripción (opcional)" value={caption} onChange={(e) => setCaption(e.target.value)} className="flex-1" />
          <Input type="number" label="Orden" value={orden} onChange={(e) => setOrden(e.target.value)} className="w-full md:w-24" />
        </div>
        <Button
          type="button"
          onClick={handleUpload}
          disabled={uploading}
          className="w-auto px-4 inline-flex items-center gap-2"
        >
          <UploadCloud size={16} /> {uploading ? 'Subiendo...' : 'Agregar foto'}
        </Button>
      </div>

      {loading && <p className="text-sm text-gray-500">Cargando...</p>}
      {!loading && photos.length === 0 && (
        <p className="text-sm text-gray-500">No hay fotos en la galería todavía.</p>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {photos.map((photo) => (
          <div key={photo.id} className="bg-white border border-gray-200 rounded-xl p-3 shadow-sm flex gap-3">
            <img src={photo.url} alt={photo.caption || 'Foto galería'} className="h-24 w-24 object-cover rounded-lg flex-shrink-0" />
            <div className="flex-1 space-y-2">
              <Input
                label="Descripción"
                value={drafts[photo.id]?.caption ?? ''}
                onChange={(e) => setDrafts((prev) => ({ ...prev, [photo.id]: { ...prev[photo.id], caption: e.target.value } }))}
              />
              <div className="flex items-end gap-2">
                <Input
                  type="number"
                  label="Orden"
                  value={drafts[photo.id]?.orden ?? 0}
                  onChange={(e) => setDrafts((prev) => ({ ...prev, [photo.id]: { ...prev[photo.id], orden: e.target.value } }))}
                  className="w-20"
                />
                <Button
                  type="button"
                  onClick={() => handleSaveDraft(photo.id)}
                  disabled={savingId === photo.id}
                  className="w-auto px-3 py-2 text-sm inline-flex items-center gap-1"
                >
                  <Save size={14} /> {savingId === photo.id ? 'Guardando...' : 'Guardar'}
                </Button>
                <button
                  onClick={() => handleDelete(photo)}
                  disabled={deletingId === photo.id}
                  className="text-red-400 hover:text-red-600 p-2"
                  title="Eliminar foto"
                >
                  <Trash2 size={18} />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
