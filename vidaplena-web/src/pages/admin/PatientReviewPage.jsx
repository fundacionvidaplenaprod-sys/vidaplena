import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { FileText, CheckCircle, XCircle, User, ArrowLeft, ExternalLink, Users, UploadCloud, Wallet } from 'lucide-react';
import { Button } from '../../components/ui/Button'; // Ajusta la ruta a tu componente Button
import { toast } from 'react-hot-toast';
import client from '../../api/axios'; // Ajusta la ruta a tu cliente axios
import { uploadPatientDocumentAdmin } from '../../api/patients';
import { getSocialEvaluation } from '../../api/evaluations';

const APORTE_ESTADO_STYLES = {
    ACEPTADO: 'bg-green-100 text-green-700 border-green-200',
    OBSERVADO: 'bg-red-100 text-red-700 border-red-200',
    DECLARADO: 'bg-yellow-100 text-yellow-700 border-yellow-200',
};

const DOC_FIELD_BY_KEY = {
    ci: 'url_ci_paciente',
    medico: 'url_certificado_medico',
    foto: 'url_foto_paciente',
    compromiso: 'url_declaracion_aporte',
    ci_tutor: 'url_ci_tutor',
    foto_tutor: 'url_foto_tutor',
};

export default function PatientReviewPage() {
    const { id } = useParams(); // El ID del paciente viene de la URL
    const navigate = useNavigate();
    const [patient, setPatient] = useState(null);
    const [loading, setLoading] = useState(true);
    const [showObservations, setShowObservations] = useState(false);
    const [showResetCommitmentModal, setShowResetCommitmentModal] = useState(false);
    const [resetCommitmentReason, setResetCommitmentReason] = useState('');
    const [observedDocs, setObservedDocs] = useState({});
    const [observationNotes, setObservationNotes] = useState({});
    const [uploadingDoc, setUploadingDoc] = useState(null);
    const [contributions, setContributions] = useState([]);
    const [loadingContributions, setLoadingContributions] = useState(true);
    const [socialEvaluation, setSocialEvaluation] = useState(null);

    // 1. Cargar datos del paciente
    useEffect(() => {
        const fetchPatient = async () => {
            try {
                // Usamos el endpoint público o de admin que trae todo el objeto paciente
                const { data } = await client.get(`/patients/${id}`);
                setPatient(data);
            } catch (error) {
                console.error("Error cargando paciente:", error);
                toast.error("No se pudo cargar el expediente");
            } finally {
                setLoading(false);
            }
        };
        fetchPatient();
    }, [id]);

    // 1.b Cargar historial de aportes (vouchers) del beneficiario, para poder
    // verificar/certificar si realmente subió el de un mes puntual.
    useEffect(() => {
        const fetchContributions = async () => {
            try {
                setLoadingContributions(true);
                const { data } = await client.get(`/contributions/patient/${id}`);
                setContributions(Array.isArray(data) ? data : []);
            } catch (error) {
                console.error("Error cargando historial de aportes:", error);
            } finally {
                setLoadingContributions(false);
            }
        };
        fetchContributions();
    }, [id]);

    // 1.c Cargar la evaluación socioeconómica (si existe), para saber si el
    // beneficiario tiene exoneración total (categoría ALTA) y por lo tanto
    // no debe pedírsele el "Compromiso Firmado".
    useEffect(() => {
        const fetchEvaluation = async () => {
            try {
                const data = await getSocialEvaluation(id);
                setSocialEvaluation(data);
            } catch (error) {
                if (error?.response?.status !== 404) {
                    console.error("Error cargando evaluación socioeconómica:", error);
                }
                setSocialEvaluation(null);
            }
        };
        fetchEvaluation();
    }, [id]);

    // 2. Función para cambiar estado (Aprobar/Rechazar)
    const handleStatusChange = async (newStatus, observaciones = null) => {
        try {
            const toastId = toast.loading(`Cambiando estado a ${newStatus}...`);
            
            // Llamamos al endpoint que definimos en patients.py: /{id}/change-status
            await client.put(`/patients/${id}/change-status`, {
                estado: newStatus,
                observacion_admin: newStatus === 'ACTIVO' ? 'Documentación validada correctamente.' : 'Documentación ilegible o incompleta.',
                observaciones: observaciones || undefined,
            });

            toast.success(`Paciente actualizado a ${newStatus}`, { id: toastId });
            
            // Volver a la lista de pacientes
            // Redirigimos al dashboard para que decida según el rol
            setTimeout(() => navigate('/dashboard', { replace: true }), 1000);

        } catch (error) {
            console.error(error);
            toast.error("Error al actualizar el estado");
        }
    };

    const submitResetCommitment = async () => {
        const reason = resetCommitmentReason.trim();
        if (!reason) {
            toast.error('Ingrese el motivo de reapertura.');
            return;
        }
        try {
            const toastId = toast.loading('Reabriendo compromiso de aporte...');
            await client.post(`/patients/${id}/reset-commitment`, {
                observacion_admin: reason,
            });
            setShowResetCommitmentModal(false);
            setResetCommitmentReason('');
            toast.success('Compromiso reabierto correctamente', { id: toastId });
            setTimeout(() => navigate('/dashboard', { replace: true }), 1000);
        } catch (error) {
            console.error(error);
            toast.error('No se pudo reabrir el compromiso');
        }
    };

    const handleUploadDocument = async (docKey, file) => {
        if (!file) return;
        if (file.size > 2 * 1024 * 1024) {
            toast.error('El archivo supera el tamaño máximo permitido (2 MB).');
            return;
        }
        const field = DOC_FIELD_BY_KEY[docKey];
        try {
            setUploadingDoc(docKey);
            const toastId = toast.loading('Subiendo documento...');
            const { url } = await uploadPatientDocumentAdmin(id, docKey, file);
            setPatient((prev) => ({ ...prev, [field]: url }));
            toast.success('Documento actualizado.', { id: toastId });
        } catch (error) {
            console.error(error);
            const detail = error?.response?.data?.detail;
            toast.error(typeof detail === 'string' ? detail : 'No se pudo subir el documento.');
        } finally {
            setUploadingDoc(null);
        }
    };

    if (loading) return <div className="p-10 text-center">Cargando expediente...</div>;
    if (!patient) return <div className="p-10 text-center text-red-500">Paciente no encontrado</div>;

    // Igual criterio que el checklist del propio beneficiario (MyDocumentsPage):
    // sin CI registrada (menor sin carnet) no se exige subir su Cédula; con
    // evaluación aprobada en categoría ALTA (exoneración total) no se exige
    // el Compromiso Firmado.
    const exoneracionTotalAprobada = socialEvaluation?.estado_revision === 'APROBADO' && socialEvaluation?.categoria_final === 'ALTA';
    const documentsCatalog = [
        ...(patient.ci ? [{ key: 'ci', label: 'Cédula de Identidad', url: patient.url_ci_paciente }] : []),
        { key: 'medico', label: 'Certificado Médico', url: patient.url_certificado_medico },
        { key: 'foto', label: 'Foto Tipo Carnet', url: patient.url_foto_paciente },
        ...(exoneracionTotalAprobada ? [] : [{ key: 'compromiso', label: 'Compromiso Firmado', url: patient.url_declaracion_aporte }]),
    ];
    if (patient.tutor) {
        documentsCatalog.push(
            { key: 'ci_tutor', label: 'Cédula del Tutor', url: patient.url_ci_tutor },
            { key: 'foto_tutor', label: 'Foto del Tutor', url: patient.url_foto_tutor }
        );
    }

    const toggleObservedDoc = (docKey) => {
        setObservedDocs((prev) => ({ ...prev, [docKey]: !prev[docKey] }));
    };

    const updateObservationNote = (docKey, value) => {
        setObservationNotes((prev) => ({ ...prev, [docKey]: value }));
    };

    const submitObservations = () => {
        const selectedDocs = documentsCatalog.filter((doc) => observedDocs[doc.key]);
        if (selectedDocs.length === 0) {
            toast.error('Seleccione al menos un documento observado.');
            return;
        }

        const missingReason = selectedDocs.find((doc) => !observationNotes[doc.key]?.trim());
        if (missingReason) {
            toast.error(`Ingrese el motivo para: ${missingReason.label}.`);
            return;
        }

        const observaciones = selectedDocs.map((doc) => ({
            doc_key: doc.key,
            motivo: observationNotes[doc.key].trim(),
        }));

        setShowObservations(false);
        handleStatusChange('PENDIENTE_DOC', observaciones);
    };

    const resetObservations = () => {
        setObservedDocs({});
        setObservationNotes({});
        setShowObservations(false);
    };

    // Helper para mostrar tarjeta de documento
    const DocumentCard = ({ title, url, icon, docKey }) => {
        const IconComponent = icon;
        const isUploading = uploadingDoc === docKey;
        const inputId = `doc-upload-${docKey}`;
        return (
            <div className="border rounded-lg p-4 bg-white shadow-sm hover:shadow-md transition-shadow">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className={`p-2 rounded-full ${url ? 'bg-blue-100 text-blue-600' : 'bg-red-100 text-red-500'}`}>
                            <IconComponent size={20} />
                        </div>
                        <div>
                            <h4 className="font-bold text-sm text-gray-700">{title}</h4>
                            <p className={`text-xs font-bold ${url ? 'text-green-600' : 'text-red-500'}`}>
                                {url ? 'Cargado' : 'No cargado'}
                            </p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        {url && (
                            <a
                                href={url}
                                target="_blank"
                                rel="noreferrer"
                                className="flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 font-medium px-3 py-1 bg-blue-50 rounded-md"
                            >
                                Ver <ExternalLink size={14} />
                            </a>
                        )}
                        <label
                            htmlFor={inputId}
                            className={`flex items-center gap-1 text-sm font-medium px-3 py-1 rounded-md cursor-pointer ${
                                isUploading
                                    ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                                    : 'bg-vida-bg text-vida-primary hover:bg-vida-light/40'
                            }`}
                        >
                            <UploadCloud size={14} />
                            {isUploading ? 'Subiendo...' : url ? 'Reemplazar' : 'Subir'}
                        </label>
                        <input
                            id={inputId}
                            type="file"
                            accept="application/pdf,image/jpeg,image/png,image/jpg"
                            className="hidden"
                            disabled={isUploading}
                            onChange={(event) => {
                                const file = event.target.files?.[0];
                                event.target.value = '';
                                handleUploadDocument(docKey, file);
                            }}
                        />
                    </div>
                </div>
            </div>
        );
    };

    return (
        <div className="min-h-screen bg-gray-50 p-6">
            <div className="max-w-4xl mx-auto">
                {/* Header de Navegación */}
                <button onClick={() => navigate(-1)} className="flex items-center text-gray-500 hover:text-gray-800 mb-6">
                    <ArrowLeft size={18} className="mr-1" /> Volver al listado
                </button>

                {/* Encabezado del Paciente */}
                <div className="bg-white rounded-xl shadow-lg p-6 mb-6 border-l-4 border-vida-primary">
                    <div className="flex justify-between items-start">
                        <div>
                            <h1 className="text-2xl font-bold text-gray-800 flex items-center gap-2">
                                <User /> {patient.nombres} {patient.ap_paterno} {patient.ap_materno}
                            </h1>
                            <p className="text-gray-500 mt-1">CI: <span className="font-mono font-bold text-gray-700">{patient.ci}</span></p>
                        </div>
                        <div className="text-right">
                            <span className={`px-4 py-2 rounded-full text-sm font-bold border
                                ${patient.estado === 'HABILITADO' ? 'bg-yellow-100 text-yellow-700 border-yellow-200' : ''}
                                ${patient.estado === 'ACTIVO' ? 'bg-green-100 text-green-700 border-green-200' : ''}
                                ${patient.estado === 'PENDIENTE_DOC' ? 'bg-gray-100 text-gray-600 border-gray-200' : ''}
                            `}>
                                {patient.estado}
                            </span>
                            <p className="text-xs text-gray-400 mt-2">Registrado: {new Date(patient.created_at).toLocaleDateString()}</p>
                        </div>
                    </div>
                </div>

                {/* Grid de Documentos */}
                <div className="grid md:grid-cols-2 gap-6 mb-8">
                    {/* Columna Izquierda: Documentos del Paciente */}
                    <div className="space-y-4">
                        <h3 className="font-bold text-gray-700 flex items-center gap-2">
                            <FileText size={18} /> Documentación del Paciente
                        </h3>
                        {patient.ci && (
                            <DocumentCard title="Cédula de Identidad" url={patient.url_ci_paciente} icon={FileText} docKey="ci" />
                        )}
                        <DocumentCard title="Certificado Médico" url={patient.url_certificado_medico} icon={FileText} docKey="medico" />
                        <DocumentCard title="Foto Tipo Carnet" url={patient.url_foto_paciente} icon={User} docKey="foto" />
                        {!exoneracionTotalAprobada && (
                            <DocumentCard title="Compromiso Firmado" url={patient.url_declaracion_aporte} icon={FileText} docKey="compromiso" />
                        )}
                        {exoneracionTotalAprobada && (
                            <div className="text-xs text-green-700 bg-green-50 border border-green-100 rounded-lg p-3">
                                Exonerado del aporte solidario (evaluación socioeconómica aprobada, categoría ALTA) — no se exige Compromiso Firmado.
                            </div>
                        )}
                    </div>

                    {/* Columna Derecha: Documentos del Tutor (Si existen) */}
                    <div className="space-y-4">
                        <h3 className="font-bold text-gray-700 flex items-center gap-2">
                            <Users size={18} /> Documentación del Tutor
                        </h3>
                        {patient.tutor ? (
                            <>
                                <div className="bg-blue-50 p-3 rounded-lg text-sm text-blue-800 mb-2">
                                    <span className="font-bold">Tutor:</span> {patient.tutor.nombres} {patient.tutor.ap_paterno}
                                </div>
                                <DocumentCard title="Cédula del Tutor" url={patient.url_ci_tutor} icon={Users} docKey="ci_tutor" />
                                <DocumentCard title="Foto del Tutor" url={patient.url_foto_tutor} icon={User} docKey="foto_tutor" />
                            </>
                        ) : (
                            <div className="h-full flex items-center justify-center border-2 border-dashed border-gray-200 rounded-lg text-gray-400 p-8">
                                <p>Este paciente es mayor de edad o no registró tutor.</p>
                            </div>
                        )}
                    </div>
                </div>

                {/* Historial de Aportes (Vouchers) */}
                <div className="bg-white rounded-xl shadow-lg p-6 mb-8">
                    <h3 className="font-bold text-gray-700 flex items-center gap-2 mb-4">
                        <Wallet size={18} /> Historial de Aportes (Vouchers)
                    </h3>
                    {loadingContributions ? (
                        <p className="text-sm text-gray-400">Cargando historial...</p>
                    ) : contributions.length === 0 ? (
                        <p className="text-sm text-gray-400">
                            Este beneficiario no tiene ningún aporte declarado todavía.
                        </p>
                    ) : (
                        <div className="space-y-2">
                            {contributions.map((item) => (
                                <div
                                    key={item.id}
                                    className="border border-gray-100 rounded-lg p-3 flex items-center justify-between gap-3 flex-wrap"
                                >
                                    <div>
                                        <p className="text-sm font-semibold text-gray-800">
                                            Periodo {item.periodo} — Bs. {item.monto}
                                        </p>
                                        <p className="text-xs text-gray-500">
                                            Fecha de pago: {item.fecha_pago}
                                            {item.observacion_admin && (
                                                <span className="text-red-600"> · {item.observacion_admin}</span>
                                            )}
                                        </p>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <span className={`text-xs font-bold px-2 py-1 rounded-full border ${APORTE_ESTADO_STYLES[item.estado] || 'bg-gray-100 text-gray-600 border-gray-200'}`}>
                                            {item.estado}
                                        </span>
                                        <a
                                            href={item.url_comprobante}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 font-medium px-3 py-1 bg-blue-50 rounded-md"
                                        >
                                            Ver voucher <ExternalLink size={14} />
                                        </a>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Barra de Acciones */}
                <div className="bg-white p-6 rounded-xl shadow-lg border-t border-gray-100 flex justify-between items-center">
                    <div>
                        <p className="text-sm text-gray-500">Revise cuidadosamente los documentos antes de aprobar.</p>
                    </div>
                    <div className="flex gap-4">
                        {patient.estado === 'ACTIVO' && (
                            <Button
                                variant="secondary"
                                className="bg-yellow-100 text-yellow-700 hover:bg-yellow-200 border border-yellow-200"
                                onClick={() => setShowResetCommitmentModal(true)}
                            >
                                <FileText className="mr-2" size={18} /> Reabrir compromiso
                            </Button>
                        )}
                        <Button 
                            variant="danger" 
                            className="bg-red-100 text-red-600 hover:bg-red-200 border border-red-200"
                            onClick={() => setShowObservations(true)}
                        >
                            <XCircle className="mr-2" size={18} /> Rechazar / Observar
                        </Button>
                        
                        <Button 
                            className="bg-green-600 hover:bg-green-700 text-white shadow-lg shadow-green-200"
                            onClick={() => handleStatusChange('ACTIVO')}
                        >
                            <CheckCircle className="mr-2" size={18} /> Aprobar y Activar
                        </Button>
                    </div>
                </div>
            </div>

            {showObservations && (
                <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
                    <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl p-6">
                        <h3 className="text-lg font-bold text-gray-800 mb-2">Documentos observados</h3>
                        <p className="text-sm text-gray-500 mb-4">
                            Seleccione los documentos observados y agregue el motivo correspondiente.
                        </p>
                        <div className="space-y-4 max-h-[60vh] overflow-auto pr-2">
                            {documentsCatalog.map((doc) => (
                                <div key={doc.key} className="border rounded-lg p-4">
                                    <label className="flex items-center gap-2 text-sm font-semibold text-gray-700">
                                        <input
                                            type="checkbox"
                                            className="h-4 w-4"
                                            checked={!!observedDocs[doc.key]}
                                            onChange={() => toggleObservedDoc(doc.key)}
                                        />
                                        {doc.label}
                                    </label>
                                    {observedDocs[doc.key] && (
                                        <input
                                            type="text"
                                            className="mt-3 w-full border rounded-md px-3 py-2 text-sm"
                                            placeholder="Motivo de la observación"
                                            value={observationNotes[doc.key] || ''}
                                            onChange={(event) => updateObservationNote(doc.key, event.target.value)}
                                        />
                                    )}
                                </div>
                            ))}
                        </div>
                        <div className="mt-6 flex justify-end gap-3">
                            <Button
                                variant="secondary"
                                className="border border-gray-200 text-gray-600"
                                onClick={resetObservations}
                            >
                                Cancelar
                            </Button>
                            <Button
                                className="bg-red-600 hover:bg-red-700 text-white"
                                onClick={submitObservations}
                            >
                                Confirmar observaciones
                            </Button>
                        </div>
                    </div>
                </div>
            )}

            {showResetCommitmentModal && (
                <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
                    <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6">
                        <h3 className="text-lg font-bold text-gray-800 mb-2">Reabrir compromiso de aporte</h3>
                        <p className="text-sm text-gray-500 mb-4">
                            Esta acción regresará al paciente a <span className="font-semibold">PENDIENTE_DOC</span> para que registre un nuevo monto y vuelva a subir su compromiso firmado.
                        </p>
                        <label className="text-sm font-semibold text-gray-700 block mb-2">
                            Motivo de reapertura
                        </label>
                        <textarea
                            className="w-full border rounded-md px-3 py-2 text-sm min-h-[110px]"
                            placeholder="Ej: Actualización de monto de aporte solicitada por administración."
                            value={resetCommitmentReason}
                            onChange={(event) => setResetCommitmentReason(event.target.value)}
                        />
                        <div className="mt-6 flex justify-end gap-3">
                            <Button
                                variant="secondary"
                                className="border border-gray-200 text-gray-600"
                                onClick={() => {
                                    setShowResetCommitmentModal(false);
                                    setResetCommitmentReason('');
                                }}
                            >
                                Cancelar
                            </Button>
                            <Button
                                className="bg-yellow-600 hover:bg-yellow-700 text-white"
                                onClick={submitResetCommitment}
                            >
                                Confirmar reapertura
                            </Button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}