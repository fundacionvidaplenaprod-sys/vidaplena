import { useState } from 'react';
import { CheckCircle2, ExternalLink, MessageSquareWarning, X } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { reviewInsulinNoticePhoto } from '../../api/donations';
import { FOTO_ESTADOS, FOTO_TITULOS, esPdf } from '../../utils/insulinDistribution';

const fechaHora = (iso) => (iso ? new Date(iso).toLocaleString('es-BO') : '');

// Revisión de una foto que subió el beneficiario en su aviso: se ve en grande y se aprueba, o se observa diciendo
// qué corregir (el beneficiario lo lee en su portal y sube otra). Al guardar, el reparto abre la siguiente por revisar.
export default function PhotoReviewDialog({ aviso, tipo, restantes = 0, onClose, onReviewed }) {
    const foto = aviso[`foto_${tipo}`];
    const [observando, setObservando] = useState(foto.estado === 'OBSERVADA');
    const [motivo, setMotivo] = useState(foto.observacion || '');
    const [guardando, setGuardando] = useState(false);
    const titulo = FOTO_TITULOS[tipo];
    const estado = FOTO_ESTADOS[foto.estado];

    const revisar = async (nuevoEstado) => {
        try {
            setGuardando(true);
            const revisada = await reviewInsulinNoticePhoto(aviso.notice_id, tipo, {
                estado: nuevoEstado,
                observacion: nuevoEstado === 'OBSERVADA' ? motivo.trim() : null,
            });
            toast.success(nuevoEstado === 'APROBADA' ? 'Foto aprobada' : 'Foto observada: el beneficiario verá el motivo en su portal');
            onReviewed(revisada);
        } catch (error) {
            toast.error(typeof error === 'string' ? error : 'No se pudo guardar la revisión');
        } finally {
            setGuardando(false);
        }
    };

    return (
        <div
            className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4"
            role="dialog"
            aria-label="Revisar foto"
        >
            <div className="bg-white rounded-2xl shadow-2xl max-w-3xl w-full max-h-[90vh] flex flex-col overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-100 flex justify-between items-center gap-3 bg-gray-50/50">
                    <h3 className="text-lg font-bold text-gray-800">
                        {titulo} · {aviso.nombre_completo}
                    </h3>
                    <button type="button" onClick={onClose} aria-label="Cerrar" className="p-1 rounded-full hover:bg-gray-200 text-gray-400">
                        <X size={20} />
                    </button>
                </div>

                <div className="p-6 overflow-y-auto">
                    {esPdf(foto.url) ? (
                        <iframe src={foto.url} title={`${titulo} de ${aviso.nombre_completo}`} className="w-full h-[55vh] rounded-lg border border-gray-200" />
                    ) : (
                        <img
                            src={foto.url}
                            alt={`${titulo} de ${aviso.nombre_completo}`}
                            className="max-h-[55vh] w-auto mx-auto rounded-lg object-contain border border-gray-200"
                        />
                    )}
                    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-600">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${estado.clase}`}>{estado.label}</span>
                        <span>CI {aviso.ci || '-'}</span>
                        <span>Subida el {fechaHora(foto.subida_at)}</span>
                        {foto.revisada_at && (
                            <span>
                                Revisada el {fechaHora(foto.revisada_at)}
                                {foto.revisada_por ? ` por ${foto.revisada_por}` : ''}
                            </span>
                        )}
                        <a href={foto.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-blue-700 underline">
                            <ExternalLink size={14} /> Abrir en otra pestaña
                        </a>
                    </div>
                    {observando && (
                        <label className="mt-4 block text-sm font-bold text-gray-700">
                            Qué debe corregir el beneficiario
                            <textarea
                                value={motivo}
                                onChange={(e) => setMotivo(e.target.value.slice(0, 300))}
                                rows={2}
                                placeholder="Ej.: la foto está borrosa y no se lee el resultado"
                                className="mt-1 w-full px-3 py-2 border rounded-lg text-sm font-normal text-gray-800 focus:ring-2 focus:ring-vida-primary outline-none"
                            />
                        </label>
                    )}
                </div>

                <div className="px-6 py-4 border-t border-gray-100 flex flex-wrap items-center justify-between gap-3">
                    <p className="text-xs text-gray-500">
                        {restantes > 0 ? `Quedan ${restantes} foto(s) más por revisar en este reparto.` : 'Es la última por revisar en este reparto.'}
                    </p>
                    <div className="flex flex-wrap gap-2">
                        {observando ? (
                            <button
                                type="button"
                                onClick={() => revisar('OBSERVADA')}
                                disabled={guardando || motivo.trim().length < 3}
                                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
                            >
                                <MessageSquareWarning size={16} /> Enviar observación
                            </button>
                        ) : (
                            <button
                                type="button"
                                onClick={() => setObservando(true)}
                                disabled={guardando}
                                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-gray-100 text-red-600 hover:bg-red-50"
                            >
                                <MessageSquareWarning size={16} /> Observar
                            </button>
                        )}
                        <button
                            type="button"
                            onClick={() => revisar('APROBADA')}
                            disabled={guardando || foto.estado === 'APROBADA'}
                            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
                        >
                            <CheckCircle2 size={16} /> Aprobar
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
