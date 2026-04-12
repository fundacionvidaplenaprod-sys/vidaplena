import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ExternalLink, RefreshCcw } from 'lucide-react';
import { toast } from 'react-hot-toast';
import client from '../../api/axios';
import { Button } from '../../components/ui/Button';

export default function ContributionsReviewPage() {
    const [loading, setLoading] = useState(true);
    const [items, setItems] = useState([]);
    const [statusFilter, setStatusFilter] = useState('DECLARADO');
    const [submittingId, setSubmittingId] = useState(null);
    const [observationModal, setObservationModal] = useState({ open: false, contributionId: null });
    const [observationText, setObservationText] = useState('');

    const fetchContributions = async () => {
        try {
            setLoading(true);
            const params = statusFilter ? { estado: statusFilter } : undefined;
            const { data } = await client.get('/contributions/review', { params });
            setItems(Array.isArray(data) ? data : []);
        } catch (error) {
            console.error(error);
            toast.error('No se pudo cargar la revisión de aportes.');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchContributions();
    }, [statusFilter]);

    const handleValidate = async (contributionId, targetState) => {
        const observation = targetState === 'OBSERVADO' ? observationText.trim() : null;

        try {
            setSubmittingId(contributionId);
            await client.put(`/contributions/${contributionId}/validate`, {
                estado: targetState,
                observacion_admin: observation || null,
            });
            if (statusFilter && statusFilter !== targetState) {
                toast.success(`Aporte marcado como ${targetState}. Dejó de verse por el filtro actual.`);
            } else {
                toast.success(`Aporte marcado como ${targetState}.`);
            }
            await fetchContributions();
        } catch (error) {
            console.error(error);
            const detail = error?.response?.data?.detail;
            toast.error(typeof detail === 'string' ? detail : 'No se pudo actualizar el aporte.');
        } finally {
            setSubmittingId(null);
            if (targetState === 'OBSERVADO') {
                setObservationModal({ open: false, contributionId: null });
                setObservationText('');
            }
        }
    };

    const openObservationModal = (contributionId) => {
        setObservationModal({ open: true, contributionId });
        setObservationText('');
    };

    const closeObservationModal = () => {
        setObservationModal({ open: false, contributionId: null });
        setObservationText('');
    };

    const submitObservation = () => {
        if (!observationText.trim()) {
            toast.error('Debe registrar una observación.');
            return;
        }
        handleValidate(observationModal.contributionId, 'OBSERVADO');
    };

    return (
        <div className="max-w-6xl mx-auto">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-6">
                <div>
                    <h1 className="text-2xl font-bold text-gray-800">Revision de vouchers de aporte</h1>
                    <p className="text-sm text-gray-500">Aprobar u observar comprobantes de aportes voluntarios.</p>
                </div>
                <div className="flex items-center gap-2">
                    <select
                        value={statusFilter}
                        onChange={(event) => setStatusFilter(event.target.value)}
                        className="border rounded-lg px-3 py-2 text-sm bg-white"
                    >
                        <option value="">Todos</option>
                        <option value="DECLARADO">DECLARADO</option>
                        <option value="OBSERVADO">OBSERVADO</option>
                        <option value="ACEPTADO">ACEPTADO</option>
                    </select>
                    <Button
                        type="button"
                        variant="secondary"
                        className="border border-gray-200 text-gray-700"
                        onClick={fetchContributions}
                    >
                        <RefreshCcw size={16} className="mr-2" />
                        Recargar
                    </Button>
                </div>
            </div>

            {loading ? (
                <div className="p-10 text-center text-gray-500 font-semibold">Cargando vouchers...</div>
            ) : items.length === 0 ? (
                <div className="bg-white border border-gray-100 rounded-xl p-6 text-sm text-gray-500">
                    No hay vouchers para el filtro seleccionado.
                </div>
            ) : (
                <div className="space-y-3">
                    {items.map((item) => (
                        <div key={item.id} className="bg-white border border-gray-100 rounded-xl p-4 shadow-sm">
                            <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
                                <div>
                                    <p className="font-semibold text-gray-800">
                                        {item.patient_nombre} - CI {item.patient_ci}
                                    </p>
                                    <p className="text-sm text-gray-500 mt-1">
                                        Periodo {item.periodo} | Pago {item.fecha_pago} | Monto Bs. {item.monto}
                                    </p>
                                    {item.observacion_admin && (
                                        <p className="text-xs text-red-600 mt-2">
                                            Ultima observacion: {item.observacion_admin}
                                        </p>
                                    )}
                                    <div className="flex items-center gap-3 mt-3">
                                        <a
                                            href={item.url_comprobante}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="text-sm text-blue-600 hover:text-blue-700 underline inline-flex items-center gap-1"
                                        >
                                            Ver voucher <ExternalLink size={14} />
                                        </a>
                                        <Link
                                            to={`/dashboard/pacientes/${item.patient_id}`}
                                            className="text-sm text-vida-primary hover:underline"
                                        >
                                            Ver ficha
                                        </Link>
                                    </div>
                                </div>

                                <div className="flex items-center gap-2">
                                    <span className={`text-xs font-bold px-2 py-1 rounded-full border ${
                                        item.estado === 'ACEPTADO'
                                            ? 'bg-green-100 text-green-700 border-green-200'
                                            : item.estado === 'OBSERVADO'
                                                ? 'bg-red-100 text-red-700 border-red-200'
                                                : 'bg-yellow-100 text-yellow-700 border-yellow-200'
                                    }`}>
                                        {item.estado}
                                    </span>

                                    <button
                                        type="button"
                                        className="px-4 py-2 rounded-xl font-bold text-sm bg-green-600 hover:bg-green-700 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                                        disabled={submittingId === item.id || item.estado === 'ACEPTADO'}
                                        onClick={() => handleValidate(item.id, 'ACEPTADO')}
                                    >
                                        Aprobar
                                    </button>
                                    <button
                                        type="button"
                                        className="px-4 py-2 rounded-xl font-bold text-sm bg-red-600 hover:bg-red-700 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                                        disabled={submittingId === item.id}
                                        onClick={() => openObservationModal(item.id)}
                                    >
                                        Observar
                                    </button>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {observationModal.open && (
                <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6">
                        <h3 className="text-lg font-bold text-gray-800 mb-2">Observar voucher</h3>
                        <p className="text-sm text-gray-500 mb-4">
                            Registre el motivo para que el paciente lo vea en su historial de aportes.
                        </p>
                        <textarea
                            value={observationText}
                            onChange={(event) => setObservationText(event.target.value)}
                            className="w-full border rounded-lg px-3 py-2 text-sm min-h-[110px]"
                            placeholder="Ej: El comprobante no es legible o el monto no coincide."
                        />
                        <div className="mt-4 flex justify-end gap-2">
                            <button
                                type="button"
                                onClick={closeObservationModal}
                                className="px-4 py-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
                            >
                                Cancelar
                            </button>
                            <button
                                type="button"
                                onClick={submitObservation}
                                disabled={submittingId === observationModal.contributionId}
                                className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white disabled:opacity-50"
                            >
                                Confirmar observación
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
