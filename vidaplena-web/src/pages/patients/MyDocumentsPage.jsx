import { useState, useEffect } from 'react';
import { LogOut, UploadCloud, CheckCircle, FileText, Lock, Clock, Camera, Users, Download, AlertTriangle, Pill, Wallet, CalendarDays } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../../components/ui/Button';
import { toast } from 'react-hot-toast';
import { uploadDocument } from '../../api/patients';
import { getMyDeliveryReceipt, listMyInsulinDeliveries } from '../../api/donations';
import client from '../../api/axios';

export default function MyDocumentsPage() {
    const navigate = useNavigate();
    const [docs, setDocs] = useState([]); // Iniciamos vacío, se llena al cargar
    const [patientStatus, setPatientStatus] = useState('PENDIENTE_DOC');
    const [patientProfile, setPatientProfile] = useState(null);
    const [loading, setLoading] = useState(true);
    const [observations, setObservations] = useState([]);
    const [contributions, setContributions] = useState([]);
    const [voucherUploading, setVoucherUploading] = useState(false);
    const [voucherForm, setVoucherForm] = useState({
        monto: '50',
        periodo: new Date().toISOString().slice(0, 7),
        fechaPago: new Date().toISOString().slice(0, 10),
        comprobante: null,
    });


    const [montoAporte, setMontoAporte] = useState(50); // Mínimo por defecto
    const [showConfirmModal, setShowConfirmModal] = useState(false);
    const [downloading, setDownloading] = useState(false);
    const [insulinDeliveries, setInsulinDeliveries] = useState([]);
    const [downloadingDeliveryId, setDownloadingDeliveryId] = useState(null);

    const normalizeObservations = (items) => {
        if (!Array.isArray(items)) return [];
        return items
            .filter((item) => item && typeof item.doc_key === 'string' && typeof item.motivo === 'string')
            .map((item) => ({
                doc_key: item.doc_key.trim(),
                motivo: item.motivo.trim(),
            }))
            .filter((item) => item.doc_key && item.motivo);
    };

    const parseCommittedAmount = (value) => {
        const parsed = Number(value);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    };

    const loadContributions = async () => {
        try {
            const { data } = await client.get('/contributions/me');
            setContributions(Array.isArray(data) ? data : []);
        } catch (error) {
            console.error('Error cargando aportes:', error);
            toast.error('No se pudo cargar el historial de aportes');
        }
    };

    const loadInsulinDeliveries = async () => {
        try {
            const data = await listMyInsulinDeliveries();
            setInsulinDeliveries(Array.isArray(data) ? data : []);
        } catch (error) {
            console.error('Error cargando entregas de insulina:', error);
        }
    };

    const handleDownloadInsulinReceipt = async (deliveryId) => {
        try {
            setDownloadingDeliveryId(deliveryId);
            const blob = await getMyDeliveryReceipt(deliveryId);
            const url = window.URL.createObjectURL(new Blob([blob]));
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', `Boleta_Entrega_${deliveryId}.pdf`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);
            toast.success('Boleta descargada');
        } catch (error) {
            console.error(error);
            toast.error('No se pudo descargar la boleta.');
        } finally {
            setDownloadingDeliveryId(null);
        }
    };
    // 1. CARGA INTELIGENTE DEL PERFIL
    useEffect(() => {
        const fetchPatientData = async () => {
            try {
                const { data } = await client.get('/patients/me');
                setPatientStatus(data.estado);
                setObservations(normalizeObservations(data.observaciones_doc));
                setPatientProfile(data);
                let resolvedCommittedAmount = parseCommittedAmount(data?.monto_aporte_comprometido);

                if (data?.id) {
                    try {
                        const detailRes = await client.get(`/patients/${data.id}`);
                        setPatientProfile(detailRes.data);
                        resolvedCommittedAmount = parseCommittedAmount(detailRes.data?.monto_aporte_comprometido) ?? resolvedCommittedAmount;
                    } catch (error) {
                        console.warn('No se pudo cargar perfil extendido del paciente:', error);
                    }
                }

                if (resolvedCommittedAmount) {
                    setMontoAporte(resolvedCommittedAmount);
                    setVoucherForm((prev) => ({ ...prev, monto: String(resolvedCommittedAmount) }));
                }

                const getDocUrl = (shortKey, urlKey) => {
                    const urlValue = data?.[urlKey];
                    if (urlValue) return urlValue;
                    const shortValue = data?.[shortKey];
                    if (typeof shortValue === 'string' && shortValue.startsWith('http')) {
                        return shortValue;
                    }
                    return null;
                };

                // --- CONFIGURACIÓN DE DOCUMENTOS BASE ---
                const baseDocs = [
                    { id: 'ci', label: 'Cédula de Identidad (Paciente)', url: getDocUrl('ci', 'url_ci_paciente'), icon: 'file' },
                    { id: 'medico', label: 'Certificado Médico', url: getDocUrl('medico', 'url_certificado_medico'), icon: 'file' },
                    { id: 'foto', label: 'Foto Actual (Paciente)', url: getDocUrl('foto', 'url_foto_paciente'), icon: 'camera' },
                    { id: 'compromiso', label: 'Compromiso Firmado', url: getDocUrl('compromiso', 'url_declaracion_aporte'), icon: 'file' },
                ];

                // --- SI TIENE TUTOR, AGREGAMOS LOS EXTRAS ---
                const hasTutor = data.has_tutor ?? Boolean(data.tutor);
                if (hasTutor) {
                    baseDocs.push(
                        { id: 'ci_tutor', label: 'Cédula de Identidad (Tutor)', url: getDocUrl('ci_tutor', 'url_ci_tutor'), icon: 'users' },
                        { id: 'foto_tutor', label: 'Foto del Tutor', url: getDocUrl('foto_tutor', 'url_foto_tutor'), icon: 'camera' }
                    );
                }

                // Mapeamos al formato que usa la vista (status SUBIDO/PENDIENTE)
                const finalDocs = baseDocs.map(d => ({
                    ...d,
                    status: d.url ? 'SUBIDO' : 'PENDIENTE',
                    file: null
                }));

                setDocs(finalDocs);

                if (data.estado === 'ACTIVO' || data.estado === 'HABILITADO') {
                    await loadContributions();
                    await loadInsulinDeliveries();
                }

            } catch (error) {
                console.error("Error cargando perfil:", error);
                toast.error("Error al cargar datos del paciente");
            } finally {
                setLoading(false);
            }
        };

        fetchPatientData();
    }, []);

    // Lógica de Bloqueo
    const isReadOnly = patientStatus !== 'PENDIENTE_DOC';
    const allUploaded = docs.length > 0 && docs.every(doc => doc.status === 'SUBIDO');


    const handleOpenConfirm = () => {
        if (hasCommittedAmount) {
            setMontoAporte(committedAmount);
            setShowConfirmModal(true);
            return;
        }
        if (montoAporte < 50) {
            toast.error("El aporte mínimo es de 50 Bs.");
            return;
        }
        setShowConfirmModal(true);
    };

    const handleDownloadCommitment = async () => {
        try {
            setDownloading(true);
            const response = await client.get('/patients/me/commitment-template', {
                params: { monto_compromiso: montoAporte },
                responseType: 'blob' // Importante para PDF
            });

            // Crear link de descarga invisible
            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', `Compromiso_Aporte_${montoAporte}Bs.pdf`);
            document.body.appendChild(link);
            link.click();
            link.remove();

            toast.success("Formulario descargado. Fírmalo y súbelo.");
            setShowConfirmModal(false);
        } catch (error) {
            console.error(error);
            toast.error("Error al generar el PDF.");
        } finally {
            setDownloading(false);
        }
    };

    const handleLogout = () => {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        navigate('/login');
    };

    const handleUpload = async (id, file) => {
        if (isReadOnly) return;
        try {
            const toastId = toast.loading('Subiendo archivo...');
            await uploadDocument(id, file);

            setDocs(prev => prev.map(d =>
                d.id === id ? { ...d, status: 'SUBIDO', file: file, url: 'temp' } : d
            ));
            toast.success('Cargado correctamente', { id: toastId });
        } catch (error) {
            console.error(error);
            toast.dismiss();
            toast.error('Error al subir.');
        }
    };

    const handleSubmit = async () => {
        if (!allUploaded || isReadOnly) return;
        try {
            const toastId = toast.loading('Enviando carpeta...');
            await client.put('/patients/me/complete-registration');
            toast.success('¡Enviado con éxito!', { id: toastId });

            setPatientStatus('HABILITADO');
            // Recargamos para que se active el bloqueo visualmente
            setTimeout(() => window.location.reload(), 1500);
        } catch (error) {
            console.error(error);
            toast.error('Error al enviar solicitud.');
        }
    };

    const handleVoucherChange = (field, value) => {
        setVoucherForm((prev) => ({ ...prev, [field]: value }));
    };

    const handleVoucherUpload = async (event) => {
        event.preventDefault();
        if (!voucherForm.comprobante) {
            toast.error('Adjunte un comprobante antes de enviar.');
            return;
        }
        if (!voucherForm.periodo || !voucherForm.fechaPago) {
            toast.error('Complete periodo y fecha de pago.');
            return;
        }

        const montoNum = Number(voucherForm.monto);
        if (!Number.isFinite(montoNum) || montoNum <= 0) {
            toast.error('Ingrese un monto válido.');
            return;
        }
        const effectiveAmount = hasCommittedAmount ? committedAmount : montoNum;
        if (hasCommittedAmount && Math.abs(montoNum - committedAmount) > 0.001) {
            toast.error(`El monto debe coincidir con su compromiso: Bs. ${committedAmount.toFixed(2)}.`);
            return;
        }
        if (isDuplicateVoucherPeriod) {
            toast.error(`El aporte del periodo ${voucherForm.periodo} ya fue validado y no puede reemplazarse.`);
            return;
        }

        try {
            setVoucherUploading(true);
            const formData = new FormData();
            formData.append('monto', String(effectiveAmount));
            formData.append('periodo', voucherForm.periodo);
            formData.append('fecha_pago', voucherForm.fechaPago);
            formData.append('comprobante', voucherForm.comprobante);

            await client.post('/contributions/me', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });

            toast.success('Voucher enviado. Quedó en estado DECLARADO.');
            setVoucherForm((prev) => ({ ...prev, comprobante: null }));
            await loadContributions();
        } catch (error) {
            console.error(error);
            const detail = error?.response?.data?.detail;
            toast.error(typeof detail === 'string' ? detail : 'No se pudo subir el voucher.');
        } finally {
            setVoucherUploading(false);
        }
    };

    // Helper para iconos
    const renderIcon = (type) => {
        if (type === 'camera') return <Camera size={24} />;
        if (type === 'users') return <Users size={24} />;
        return <UploadCloud size={24} />; // Default
    };

    if (loading) return <div className="p-10 text-center font-bold text-gray-500">Cargando expediente...</div>;

    const docLabelById = docs.reduce((acc, doc) => {
        acc[doc.id] = doc.label;
        return acc;
    }, {});
    const observedReasonByDocId = observations.reduce((acc, item) => {
        acc[item.doc_key] = item.motivo;
        return acc;
    }, {});
    const currentPeriod = new Date().toISOString().slice(0, 7);
    const committedAmount = parseCommittedAmount(patientProfile?.monto_aporte_comprometido) || 0;
    const hasCommittedAmount = committedAmount > 0;
    const currentPeriodContribution = contributions.find((item) => item.periodo === currentPeriod);
    const selectedPeriodContribution = contributions.find((item) => item.periodo === voucherForm.periodo);
    const isDuplicateVoucherPeriod = selectedPeriodContribution?.estado === 'ACEPTADO';
    const todayDoseTotal = (patientProfile?.treatments || []).reduce((acc, treatment) => {
        return acc + Number(treatment.dosis_diaria || 0);
    }, 0);

    const insulinDeliveriesSection = (
        <div className="bg-white rounded-2xl shadow-xl p-8 border border-gray-100 mb-6">
            <h2 className="text-2xl font-bold text-gray-800 mb-2">Boletas de entrega de insulina</h2>
            <p className="text-gray-500 mb-6">
                Descargue la boleta de cada entrega para presentarla en la fundación cuando corresponda.
            </p>
            <div className="space-y-3">
                {insulinDeliveries.length > 0 ? (
                    insulinDeliveries.map((delivery) => (
                        <div key={delivery.id} className="border border-gray-100 rounded-lg p-4 flex items-center justify-between gap-4">
                            <div>
                                <p className="text-sm font-semibold text-gray-800">
                                    Entrega #{delivery.id} - {delivery.fecha_entrega}
                                </p>
                                <p className="text-xs text-gray-500">
                                    Cantidad: {delivery.cantidad_entregada} | Estado: {delivery.estado}
                                </p>
                            </div>
                            <Button
                                type="button"
                                className="bg-vida-main hover:bg-vida-hover text-white"
                                onClick={() => handleDownloadInsulinReceipt(delivery.id)}
                                disabled={downloadingDeliveryId === delivery.id}
                            >
                                <Download size={16} className="mr-2" />
                                {downloadingDeliveryId === delivery.id ? 'Descargando...' : 'Descargar boleta'}
                            </Button>
                        </div>
                    ))
                ) : (
                    <p className="text-sm text-gray-500 italic">Aún no tiene entregas de insulina registradas.</p>
                )}
            </div>
        </div>
    );

    return (
        <div className="min-h-screen bg-gray-50 font-sans">
            <nav className="bg-vida-primary text-white p-4 shadow-md flex justify-between items-center">
                <div className="flex items-center gap-3">
                    <div className="bg-white/20 p-2 rounded-lg"><FileText size={24} /></div>
                    <div>
                        <h1 className="font-bold text-lg leading-tight">Portal del Beneficiario</h1>
                        <p className="text-xs text-white/80">
                            Estado: <span className="font-bold text-yellow-300">{patientStatus}</span>
                        </p>
                    </div>
                </div>
                <button onClick={handleLogout} className="text-white/80 hover:text-white flex items-center gap-2 text-sm font-medium">
                    <LogOut size={18} /> Salir
                </button>
            </nav>

            <main className="max-w-3xl mx-auto p-6 mt-8">
                {patientStatus === 'HABILITADO' && (
                    <>
                        <div className="grid md:grid-cols-3 gap-4 mb-6">
                            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
                                <p className="text-xs text-gray-500 font-semibold uppercase">Estado actual</p>
                                <p className="text-xl font-bold text-yellow-700 mt-1">{patientStatus}</p>
                                <p className="text-xs text-gray-500 mt-1">Expediente enviado y en validacion administrativa.</p>
                            </div>
                            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
                                <p className="text-xs text-gray-500 font-semibold uppercase">Documentos base</p>
                                <p className="text-xl font-bold text-vida-primary mt-1">
                                    {docs.filter((d) => d.status === 'SUBIDO').length}/{docs.length}
                                </p>
                                <p className="text-xs text-gray-500 mt-1">Documentacion cargada por el paciente.</p>
                            </div>
                            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
                                <p className="text-xs text-gray-500 font-semibold uppercase">Aporte {currentPeriod}</p>
                                <p className={`text-xl font-bold mt-1 ${currentPeriodContribution?.estado === 'ACEPTADO' ? 'text-green-700' : 'text-orange-600'}`}>
                                    {currentPeriodContribution?.estado || 'SIN REGISTRO'}
                                </p>
                                <p className="text-xs text-gray-500 mt-1">
                                    {currentPeriodContribution?.estado === 'ACEPTADO'
                                        ? 'Su aporte del periodo ya fue validado.'
                                        : 'Puede adelantar el voucher para agilizar su activacion.'}
                                </p>
                            </div>
                        </div>

                        <div className="bg-white rounded-2xl shadow-xl p-8 border border-gray-100 mb-6">
                            <h2 className="text-2xl font-bold text-gray-800 mb-2">Expediente en revision</h2>
                            <p className="text-gray-500 mb-6">
                                Su carpeta esta en proceso de validacion. En esta fase no se puede editar documentacion.
                            </p>

                            <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 mb-4">
                                <h3 className="font-bold text-blue-800 mb-2">Checklist de avance</h3>
                                <ul className="text-sm text-blue-700 space-y-1">
                                    <li>{docs.every((d) => d.status === 'SUBIDO') ? '✅' : '🟡'} Documentacion principal registrada.</li>
                                    <li>{currentPeriodContribution ? '✅' : '🟡'} Aporte mensual reportado en el sistema.</li>
                                    <li>🟡 Validacion final por equipo administrativo.</li>
                                </ul>
                            </div>

                            {currentPeriodContribution?.estado !== 'ACEPTADO' && (
                                <div className="bg-yellow-50 border-l-4 border-yellow-500 p-4 rounded-r">
                                    <p className="text-sm text-yellow-800">
                                        Recomendacion: cargue o regularice su aporte mensual para evitar bloqueos en la dotacion una vez activado.
                                    </p>
                                </div>
                            )}
                        </div>

                        {insulinDeliveriesSection}

                        <div className="bg-white rounded-2xl shadow-xl p-8 border border-gray-100">
                            <h2 className="text-2xl font-bold text-gray-800 mb-2">Cargar voucher de aporte</h2>
                            <p className="text-gray-500 mb-6">
                                Aunque su expediente aun este en revision, puede registrar su aporte mensual para evitar bloqueos en la distribucion.
                            </p>

                            <form onSubmit={handleVoucherUpload} className="grid md:grid-cols-2 gap-4 mb-6">
                                <div>
                                    <label className="text-sm font-semibold text-gray-700 block mb-1">Periodo (YYYY-MM)</label>
                                    <input
                                        type="month"
                                        value={voucherForm.periodo}
                                        onChange={(e) => handleVoucherChange('periodo', e.target.value)}
                                        className="w-full border rounded-lg px-3 py-2 text-sm"
                                        required
                                    />
                                </div>
                                <div>
                                    <label className="text-sm font-semibold text-gray-700 block mb-1">Fecha de pago</label>
                                    <input
                                        type="date"
                                        value={voucherForm.fechaPago}
                                        onChange={(e) => handleVoucherChange('fechaPago', e.target.value)}
                                        className="w-full border rounded-lg px-3 py-2 text-sm"
                                        required
                                    />
                                </div>
                                <div>
                                    <label className="text-sm font-semibold text-gray-700 block mb-1">Monto (Bs)</label>
                                    <input
                                        type="number"
                                        min="1"
                                        step="0.01"
                                        value={hasCommittedAmount ? String(committedAmount) : voucherForm.monto}
                                        onChange={(e) => handleVoucherChange('monto', e.target.value)}
                                        readOnly={hasCommittedAmount}
                                        className="w-full border rounded-lg px-3 py-2 text-sm"
                                        required
                                    />
                                    {hasCommittedAmount && (
                                        <p className="text-xs text-gray-500 mt-1">Monto fijo según compromiso firmado.</p>
                                    )}
                                </div>
                                <div>
                                    <label className="text-sm font-semibold text-gray-700 block mb-1">Comprobante</label>
                                    <input
                                        type="file"
                                        accept=".pdf,.jpg,.jpeg,.png"
                                        onChange={(e) => handleVoucherChange('comprobante', e.target.files?.[0] || null)}
                                        className="w-full border rounded-lg px-3 py-2 text-sm"
                                        required
                                    />
                                </div>
                                <div className="md:col-span-2 flex justify-end">
                                    <Button
                                        type="submit"
                                        disabled={voucherUploading || isDuplicateVoucherPeriod}
                                        className="bg-vida-main hover:bg-vida-hover text-white"
                                    >
                                        {voucherUploading ? 'Subiendo...' : isDuplicateVoucherPeriod ? 'Periodo validado' : 'Subir voucher'}
                                    </Button>
                                </div>
                            </form>
                            {isDuplicateVoucherPeriod && (
                                <p className="text-xs text-amber-700 mb-4">
                                    El periodo {voucherForm.periodo} ya fue validado. Para corregir, contacte a administración.
                                </p>
                            )}

                            <h3 className="font-bold text-gray-800 mb-3">Historial de aportes</h3>
                            <div className="space-y-2">
                                {contributions.length > 0 ? (
                                    contributions.map((item) => (
                                        <div key={item.id} className="border border-gray-100 rounded-lg p-3 flex items-start justify-between gap-4">
                                            <div>
                                                <p className="text-sm font-semibold text-gray-800">
                                                    Periodo {item.periodo} - Bs. {item.monto}
                                                </p>
                                                <p className="text-xs text-gray-500">
                                                    Pago: {item.fecha_pago} | Registro: {new Date(item.created_at).toLocaleDateString()}
                                                </p>
                                                {item.observacion_admin && (
                                                    <p className="text-xs text-red-600 mt-1">Observacion: {item.observacion_admin}</p>
                                                )}
                                            </div>
                                            <span className={`text-xs font-bold px-2 py-1 rounded-full border ${
                                                item.estado === 'ACEPTADO'
                                                    ? 'bg-green-100 text-green-700 border-green-200'
                                                    : item.estado === 'OBSERVADO'
                                                        ? 'bg-red-100 text-red-700 border-red-200'
                                                        : 'bg-yellow-100 text-yellow-700 border-yellow-200'
                                            }`}>
                                                {item.estado}
                                            </span>
                                        </div>
                                    ))
                                ) : (
                                    <p className="text-sm text-gray-500 italic">Aun no registra aportes.</p>
                                )}
                            </div>
                        </div>
                    </>
                )}

                {patientStatus === 'ACTIVO' && (
                    <>
                        <div className="grid md:grid-cols-3 gap-4 mb-6">
                            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
                                <p className="text-xs text-gray-500 font-semibold uppercase">Estado actual</p>
                                <p className="text-xl font-bold text-green-700 mt-1">{patientStatus}</p>
                                <p className="text-xs text-gray-500 mt-1">Expediente aprobado por administración.</p>
                            </div>
                            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
                                <p className="text-xs text-gray-500 font-semibold uppercase flex items-center gap-2">
                                    <Pill size={14} /> Tratamientos activos
                                </p>
                                <p className="text-xl font-bold text-vida-primary mt-1">
                                    {(patientProfile?.treatments || []).length}
                                </p>
                                <p className="text-xs text-gray-500 mt-1">Dosis diaria registrada: {todayDoseTotal}</p>
                            </div>
                            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
                                <p className="text-xs text-gray-500 font-semibold uppercase flex items-center gap-2">
                                    <Wallet size={14} /> Aporte {currentPeriod}
                                </p>
                                <p className={`text-xl font-bold mt-1 ${currentPeriodContribution?.estado === 'ACEPTADO' ? 'text-green-700' : 'text-orange-600'}`}>
                                    {currentPeriodContribution?.estado || 'PENDIENTE'}
                                </p>
                                <p className="text-xs text-gray-500 mt-1">
                                    {currentPeriodContribution?.estado === 'ACEPTADO'
                                        ? 'Apto para distribución del periodo.'
                                        : 'Suba su voucher para habilitar su beneficio.'}
                                </p>
                            </div>
                        </div>

                        <div className="bg-white rounded-2xl shadow-xl p-8 border border-gray-100 mb-6">
                            <h2 className="text-2xl font-bold text-gray-800 mb-2">Mi tratamiento y seguimiento</h2>
                            <p className="text-gray-500 mb-6">
                                Revise su información registrada y mantenga su aporte voluntario al día para no afectar su dotación.
                            </p>

                            <div className="space-y-3 mb-6">
                                {(patientProfile?.treatments || []).length > 0 ? (
                                    patientProfile.treatments.map((tx, index) => (
                                        <div key={`${tx.id || tx.nombre}-${index}`} className="rounded-lg border border-gray-100 p-4 bg-gray-50">
                                            {(() => {
                                                const dailyUnits = Number(tx.dosis_diaria || 0);
                                                return (
                                                    <>
                                            <p className="text-sm font-bold text-gray-800">{tx.nombre || 'Tratamiento sin nombre'}</p>
                                            <p className="text-xs text-gray-600 mt-1">
                                                UI por día: {dailyUnits > 0 ? dailyUnits : 'No especificada'}
                                            </p>
                                                    </>
                                                );
                                            })()}
                                        </div>
                                    ))
                                ) : (
                                    <p className="text-sm text-gray-500 italic">Aun no hay tratamientos visibles en su perfil.</p>
                                )}
                            </div>

                            <div className="bg-blue-50 border border-blue-100 rounded-xl p-4">
                                <h3 className="font-bold text-blue-800 mb-2 flex items-center gap-2">
                                    <CalendarDays size={16} /> Recomendaciones de seguimiento
                                </h3>
                                <ul className="text-sm text-blue-700 space-y-1">
                                    <li>Mantenga sus datos de tratamiento actualizados con su médico.</li>
                                    <li>Suba su voucher mensual en cuanto realice el aporte.</li>
                                    <li>Si su aporte queda observado, revise la observación administrativa en el historial.</li>
                                </ul>
                            </div>
                        </div>

                        {insulinDeliveriesSection}

                        <div className="bg-white rounded-2xl shadow-xl p-8 border border-gray-100">
                            <h2 className="text-2xl font-bold text-gray-800 mb-2">Aporte voluntario mensual</h2>
                            <p className="text-gray-500 mb-6">
                                Suba el voucher para validacion. Sin aporte aceptado del periodo, la distribucion puede bloquearse.
                            </p>

                            <form onSubmit={handleVoucherUpload} className="grid md:grid-cols-2 gap-4 mb-6">
                                <div>
                                    <label className="text-sm font-semibold text-gray-700 block mb-1">Periodo (YYYY-MM)</label>
                                    <input
                                        type="month"
                                        value={voucherForm.periodo}
                                        onChange={(e) => handleVoucherChange('periodo', e.target.value)}
                                        className="w-full border rounded-lg px-3 py-2 text-sm"
                                        required
                                    />
                                </div>
                                <div>
                                    <label className="text-sm font-semibold text-gray-700 block mb-1">Fecha de pago</label>
                                    <input
                                        type="date"
                                        value={voucherForm.fechaPago}
                                        onChange={(e) => handleVoucherChange('fechaPago', e.target.value)}
                                        className="w-full border rounded-lg px-3 py-2 text-sm"
                                        required
                                    />
                                </div>
                                <div>
                                    <label className="text-sm font-semibold text-gray-700 block mb-1">Monto (Bs)</label>
                                    <input
                                        type="number"
                                        min="1"
                                        step="0.01"
                                        value={hasCommittedAmount ? String(committedAmount) : voucherForm.monto}
                                        onChange={(e) => handleVoucherChange('monto', e.target.value)}
                                        readOnly={hasCommittedAmount}
                                        className="w-full border rounded-lg px-3 py-2 text-sm"
                                        required
                                    />
                                    {hasCommittedAmount && (
                                        <p className="text-xs text-gray-500 mt-1">Monto fijo según compromiso firmado.</p>
                                    )}
                                </div>
                                <div>
                                    <label className="text-sm font-semibold text-gray-700 block mb-1">Comprobante</label>
                                    <input
                                        type="file"
                                        accept=".pdf,.jpg,.jpeg,.png"
                                        onChange={(e) => handleVoucherChange('comprobante', e.target.files?.[0] || null)}
                                        className="w-full border rounded-lg px-3 py-2 text-sm"
                                        required
                                    />
                                </div>
                                <div className="md:col-span-2 flex justify-end">
                                    <Button
                                        type="submit"
                                        disabled={voucherUploading || isDuplicateVoucherPeriod}
                                        className="bg-vida-main hover:bg-vida-hover text-white"
                                    >
                                        {voucherUploading ? 'Subiendo...' : isDuplicateVoucherPeriod ? 'Periodo validado' : 'Subir voucher'}
                                    </Button>
                                </div>
                            </form>
                            {isDuplicateVoucherPeriod && (
                                <p className="text-xs text-amber-700 mb-4">
                                    El periodo {voucherForm.periodo} ya fue validado. Para corregir, contacte a administración.
                                </p>
                            )}

                            <h3 className="font-bold text-gray-800 mb-3">Historial de aportes</h3>
                            <div className="space-y-2">
                                {contributions.length > 0 ? (
                                    contributions.map((item) => (
                                        <div key={item.id} className="border border-gray-100 rounded-lg p-3 flex items-start justify-between gap-4">
                                            <div>
                                                <p className="text-sm font-semibold text-gray-800">
                                                    Periodo {item.periodo} - Bs. {item.monto}
                                                </p>
                                                <p className="text-xs text-gray-500">
                                                    Pago: {item.fecha_pago} | Registro: {new Date(item.created_at).toLocaleDateString()}
                                                </p>
                                                {item.observacion_admin && (
                                                    <p className="text-xs text-red-600 mt-1">Observacion: {item.observacion_admin}</p>
                                                )}
                                            </div>
                                            <span className={`text-xs font-bold px-2 py-1 rounded-full border ${
                                                item.estado === 'ACEPTADO'
                                                    ? 'bg-green-100 text-green-700 border-green-200'
                                                    : item.estado === 'OBSERVADO'
                                                        ? 'bg-red-100 text-red-700 border-red-200'
                                                        : 'bg-yellow-100 text-yellow-700 border-yellow-200'
                                            }`}>
                                                {item.estado}
                                            </span>
                                        </div>
                                    ))
                                ) : (
                                    <p className="text-sm text-gray-500 italic">Aun no registra aportes.</p>
                                )}
                            </div>
                        </div>
                    </>
                )}

                {isReadOnly && patientStatus !== 'ACTIVO' && patientStatus !== 'HABILITADO' && (
                    <div className="bg-blue-50 border-l-4 border-blue-500 p-4 mb-6 rounded-r shadow-sm animate-fade-in">
                        <div className="flex items-center">
                            <Clock className="text-blue-500 mr-3" size={24} />
                            <div>
                                <h3 className="font-bold text-blue-800">Expediente en Revisión</h3>
                                <p className="text-sm text-blue-600">
                                    Sus documentos han sido enviados. No puede realizar cambios durante la validación.
                                </p>
                            </div>
                        </div>
                    </div>
                )}

                {patientStatus !== 'ACTIVO' && patientStatus !== 'HABILITADO' && (
                <div className="bg-white rounded-2xl shadow-xl p-8 border border-gray-100">
                    <h2 className="text-2xl font-bold text-gray-800 mb-2">Expediente Digital</h2>
                    
                    {!isReadOnly && (
                        <div className="bg-gradient-to-r from-vida-main to-vida-primary rounded-2xl shadow-lg p-6 mb-8 text-white">
                            <h3 className="font-bold text-lg mb-2 flex items-center gap-2">
                                <FileText /> Paso 1: Generar Compromiso de Aporte
                            </h3>
                            <p className="text-sm text-white/80 mb-4">
                                Defina su aporte voluntario mensual (Mínimo 50 Bs) para descargar, imprimir y firmar su declaración jurada.
                            </p>

                            <div className="flex flex-col sm:flex-row items-end gap-4">
                                <div className="w-full sm:w-1/3">
                                    <label className="block text-xs font-bold mb-1 ml-1">Monto Mensual (Bs)</label>
                                    <input
                                        type="number"
                                        min="50"
                                        value={montoAporte}
                                        onChange={(e) => setMontoAporte(e.target.value)}
                                        readOnly={hasCommittedAmount}
                                        className="w-full p-2 rounded-lg text-gray-800 font-bold text-center text-xl outline-none border-2 border-white/30 focus:border-white"
                                    />
                                </div>
                                <Button
                                    onClick={handleOpenConfirm}
                                    className="bg-green-600 hover:bg-green-700 text-white shadow-lg shadow-green-200 font-bold shadow-lg w-full sm:w-auto"
                                >
                                    
                                    <Download size={18} className="mr-2" /> Descargar Formulario
                                </Button>
                            </div>
                        </div>
                    )}
                    <p className="text-gray-500 mb-8">
                        {isReadOnly
                            ? "Documentación resguardada."
                            : "Cargue los documentos solicitados. Los campos de Tutor aparecen automáticamente si aplica."}
                    </p>

                    {patientStatus === 'PENDIENTE_DOC' && observations.length > 0 && (
                        <div className="bg-yellow-50 border-l-4 border-yellow-500 p-4 mb-6 rounded-r shadow-sm">
                            <div className="flex items-start">
                                <AlertTriangle className="text-yellow-600 mr-3 mt-0.5" size={22} />
                                <div>
                                    <h3 className="font-bold text-yellow-800">Documentos observados</h3>
                                    <p className="text-sm text-yellow-700 mb-3">
                                        Revise los motivos y vuelva a subir los documentos observados.
                                    </p>
                                    <ul className="space-y-2 text-sm text-yellow-800">
                                        {observations.map((item, index) => (
                                            <li key={`${item.doc_key}-${index}`} className="border border-yellow-100 rounded-md p-2 bg-white/60">
                                                <span className="font-semibold">
                                                    {docLabelById[item.doc_key] || item.doc_key}
                                                </span>
                                                : {item.motivo}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            </div>
                        </div>
                    )}

                    <div className="space-y-4">
                        {docs.map((doc) => (
                            <div key={doc.id} className={`border rounded-xl p-4 flex items-center justify-between transition-all ${isReadOnly ? 'bg-gray-50 opacity-90' : 'bg-white hover:shadow-md'}`}>
                                <div className="flex items-center gap-4">
                                    <div className={`p-3 rounded-full ${doc.status === 'SUBIDO' ? 'bg-green-100 text-green-600' : 'bg-gray-200 text-gray-500'}`}>
                                        {doc.status === 'SUBIDO' ? <CheckCircle size={24} /> : renderIcon(doc.icon)}
                                    </div>
                                    <div>
                                        <h3 className="font-bold text-gray-800">{doc.label}</h3>
                                        <p className={`text-xs font-bold ${doc.status === 'SUBIDO' ? 'text-green-600' : 'text-orange-500'}`}>
                                            {doc.status === 'SUBIDO' ? 'Cargado' : 'Pendiente'}
                                        </p>
                                        {patientStatus === 'PENDIENTE_DOC' && observedReasonByDocId[doc.id] && (
                                            <p className="text-xs text-red-600 mt-1">
                                                Observado: {observedReasonByDocId[doc.id]}
                                            </p>
                                        )}
                                        {doc.url && isReadOnly && (
                                            <a href={doc.url} target="_blank" rel="noreferrer" className="text-xs text-blue-500 underline mt-1 block">
                                                Ver archivo
                                            </a>
                                        )}
                                    </div>
                                </div>

                                <div>
                                    {isReadOnly ? (
                                        <div className="text-gray-400 px-4"> <Lock size={20} /> </div>
                                    ) : (
                                        <>
                                            <input
                                                type="file"
                                                id={`file-${doc.id}`}
                                                className="hidden"
                                                accept={doc.icon === 'camera' ? "image/*" : ".pdf,.jpg,.jpeg,.png"}
                                                onChange={(e) => e.target.files[0] && handleUpload(doc.id, e.target.files[0])}
                                            />
                                            <label
                                                htmlFor={`file-${doc.id}`}
                                                className={`cursor-pointer px-4 py-2 rounded-lg text-sm font-bold transition-colors inline-block
                                                    ${doc.status === 'SUBIDO'
                                                        ? 'bg-gray-100 text-gray-500 border border-gray-300'
                                                        : 'bg-vida-main text-white hover:bg-vida-hover shadow-lg shadow-vida-main/20'
                                                    }`}
                                            >
                                                {doc.status === 'SUBIDO' ? 'Cambiar' : 'Subir'}
                                            </label>
                                        </>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>

                

                    {!isReadOnly && (
                        <div className="mt-8 pt-6 border-t border-gray-100 flex justify-end">
                            <Button
                                onClick={handleSubmit}
                                disabled={!allUploaded}
                                className={`w-full md:w-auto transition-all duration-300 ${allUploaded
                                    ? 'bg-green-600 hover:bg-green-700 text-white shadow-lg shadow-green-200'
                                    : 'bg-gray-300 text-gray-500 cursor-not-allowed'
                                    }`}
                            >
                                Enviar a Revisión
                            </Button>
                        </div>
                    )}
                </div>
                )}
            </main>

            {showConfirmModal && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4 animate-fadeIn">
                    <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
                        <div className="text-center mb-6">
                            <div className="bg-vida-light/30 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4 text-vida-primary">
                                <FileText size={32} />
                            </div>
                            <h3 className="text-xl font-bold text-gray-800">Confirmar Aporte Mensual</h3>
                            <p className="text-gray-500 mt-2">
                                Se generará su declaración jurada con el siguiente monto. <br />
                                <span className="text-xs text-red-500">Verifique bien, este documento es legal.</span>
                            </p>
                            <div className="mt-4 text-3xl font-bold text-vida-primary">
                                {montoAporte} Bs.
                            </div>
                        </div>
                        <div className="flex gap-3">
                            <Button
                                variant="secondary"
                                className="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-700"
                                onClick={() => setShowConfirmModal(false)}
                            >
                                Cancelar
                            </Button>
                            <Button
                                className="flex-1 bg-vida-main hover:bg-vida-hover text-white"
                                onClick={handleDownloadCommitment}
                                disabled={downloading}
                            >
                                {downloading ? 'Generando...' : 'Sí, Generar PDF'}
                            </Button>
                        </div>
                    </div>
                </div>
            )}

        </div>
    );
}