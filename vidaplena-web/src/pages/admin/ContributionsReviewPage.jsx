import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ExternalLink, FileDown, FilePlus, RefreshCcw, Search } from 'lucide-react';
import { toast } from 'react-hot-toast';
import client from '../../api/axios';
import { Button } from '../../components/ui/Button';
import { getPaginatedPatients } from '../../api/patients';
import { createContributionAdmin } from '../../api/contributions';

const emptyRegisterForm = { periodo: '', monto: '', fechaPago: '' };

export default function ContributionsReviewPage() {
    const isSuperAdmin = JSON.parse(localStorage.getItem('user') || '{}').role === 'SUPER_ADMIN';
    const [loading, setLoading] = useState(true);
    const [items, setItems] = useState([]);
    const [statusFilter, setStatusFilter] = useState('DECLARADO');
    const [submittingId, setSubmittingId] = useState(null);
    const [exporting, setExporting] = useState(false);
    const [observationModal, setObservationModal] = useState({ open: false, contributionId: null });
    const [observationText, setObservationText] = useState('');

    const [registerModalOpen, setRegisterModalOpen] = useState(false);
    const [patientSearch, setPatientSearch] = useState('');
    const [patientResults, setPatientResults] = useState([]);
    const [searchingPatients, setSearchingPatients] = useState(false);
    const [selectedPatient, setSelectedPatient] = useState(null);
    const [registerForm, setRegisterForm] = useState(emptyRegisterForm);
    const [comprobanteFile, setComprobanteFile] = useState(null);
    const [registering, setRegistering] = useState(false);

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

    const handleExportPdf = async () => {
        try {
            setExporting(true);
            const params = statusFilter ? { estado: statusFilter } : undefined;
            const response = await client.get('/contributions/review/export.pdf', {
                params,
                responseType: 'blob',
            });
            const url = window.URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }));
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', `Reporte_Vouchers_${statusFilter || 'TODOS'}.pdf`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);
        } catch (error) {
            console.error(error);
            toast.error('No se pudo generar el reporte en PDF.');
        } finally {
            setExporting(false);
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

    // --- Registro manual de un aporte que el beneficiario pagó pero nunca declaró en la app ---
    useEffect(() => {
        if (!registerModalOpen || selectedPatient || patientSearch.trim().length < 2) {
            setPatientResults([]);
            return;
        }
        let cancelled = false;
        setSearchingPatients(true);
        const timer = setTimeout(async () => {
            try {
                const data = await getPaginatedPatients(0, 8, patientSearch.trim());
                if (!cancelled) setPatientResults(Array.isArray(data?.items) ? data.items : []);
            } catch (error) {
                console.error(error);
            } finally {
                if (!cancelled) setSearchingPatients(false);
            }
        }, 350);
        return () => {
            cancelled = true;
            clearTimeout(timer);
        };
    }, [patientSearch, registerModalOpen, selectedPatient]);

    const openRegisterModal = () => {
        setRegisterModalOpen(true);
        setPatientSearch('');
        setPatientResults([]);
        setSelectedPatient(null);
        setRegisterForm(emptyRegisterForm);
        setComprobanteFile(null);
    };

    const closeRegisterModal = () => {
        setRegisterModalOpen(false);
        setPatientSearch('');
        setPatientResults([]);
        setSelectedPatient(null);
        setRegisterForm(emptyRegisterForm);
        setComprobanteFile(null);
    };

    const submitRegisterContribution = async () => {
        if (!selectedPatient) {
            toast.error('Seleccione al beneficiario.');
            return;
        }
        if (!/^\d{4}-\d{2}$/.test(registerForm.periodo)) {
            toast.error('Indique el periodo en formato AAAA-MM.');
            return;
        }
        if (!(Number(registerForm.monto) > 0)) {
            toast.error('Indique un monto válido.');
            return;
        }
        if (!registerForm.fechaPago) {
            toast.error('Indique la fecha de pago.');
            return;
        }
        if (!comprobanteFile) {
            toast.error('Suba una foto o escaneo del comprobante.');
            return;
        }
        try {
            setRegistering(true);
            await createContributionAdmin(selectedPatient.id, {
                monto: Number(registerForm.monto),
                periodo: registerForm.periodo,
                fechaPago: registerForm.fechaPago,
                comprobante: comprobanteFile,
            });
            toast.success('Aporte registrado y aceptado.');
            closeRegisterModal();
            await fetchContributions();
        } catch (error) {
            console.error(error);
            const detail = error?.response?.data?.detail;
            toast.error(typeof detail === 'string' ? detail : 'No se pudo registrar el aporte.');
        } finally {
            setRegistering(false);
        }
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
                    <Button
                        type="button"
                        variant="secondary"
                        className="border border-gray-200 text-gray-700"
                        onClick={handleExportPdf}
                        disabled={exporting}
                    >
                        <FileDown size={16} className="mr-2" />
                        {exporting ? 'Generando...' : 'Exportar a PDF'}
                    </Button>
                    {isSuperAdmin && (
                        <Button
                            type="button"
                            className="bg-vida-main hover:bg-vida-hover text-white"
                            onClick={openRegisterModal}
                        >
                            <FilePlus size={16} className="mr-2" />
                            Registrar aporte
                        </Button>
                    )}
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

            {registerModalOpen && (
                <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4 overflow-y-auto">
                    <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6 my-8">
                        <h3 className="text-lg font-bold text-gray-800 mb-2">Registrar aporte</h3>
                        <p className="text-sm text-gray-500 mb-4">
                            Para cuando el beneficiario pagó (p. ej. depósito bancario) pero nunca declaró su
                            voucher en la app. Queda registrado como <span className="font-semibold">ACEPTADO</span> de
                            inmediato, ya que usted mismo lo está verificando al registrarlo.
                        </p>

                        {!selectedPatient ? (
                            <div>
                                <label className="block text-sm font-semibold text-gray-700 mb-1">
                                    Buscar beneficiario (nombre o CI)
                                </label>
                                <div className="relative">
                                    <Search size={16} className="absolute left-3 top-3 text-gray-400" />
                                    <input
                                        type="text"
                                        value={patientSearch}
                                        onChange={(event) => setPatientSearch(event.target.value)}
                                        className="w-full pl-9 pr-3 py-2 border rounded-lg text-sm"
                                        placeholder="Ej: María Quispe o CI-1234567"
                                        autoFocus
                                    />
                                </div>
                                <div className="mt-2 max-h-56 overflow-auto border rounded-lg divide-y">
                                    {searchingPatients && (
                                        <p className="p-3 text-sm text-gray-400">Buscando...</p>
                                    )}
                                    {!searchingPatients && patientSearch.trim().length >= 2 && patientResults.length === 0 && (
                                        <p className="p-3 text-sm text-gray-400">Sin resultados.</p>
                                    )}
                                    {patientResults.map((patient) => (
                                        <button
                                            key={patient.id}
                                            type="button"
                                            onClick={() => setSelectedPatient(patient)}
                                            className="w-full text-left p-3 text-sm hover:bg-vida-bg"
                                        >
                                            <span className="font-semibold text-gray-800">
                                                {patient.nombres} {patient.ap_paterno} {patient.ap_materno || ''}
                                            </span>
                                            <span className="text-gray-500"> — CI {patient.ci}</span>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        ) : (
                            <div className="space-y-4">
                                <div className="flex items-center justify-between bg-vida-bg rounded-lg p-3">
                                    <div>
                                        <p className="font-semibold text-gray-800">
                                            {selectedPatient.nombres} {selectedPatient.ap_paterno} {selectedPatient.ap_materno || ''}
                                        </p>
                                        <p className="text-xs text-gray-500">CI {selectedPatient.ci}</p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => { setSelectedPatient(null); setPatientSearch(''); }}
                                        className="text-xs text-vida-primary underline"
                                    >
                                        Cambiar
                                    </button>
                                </div>

                                <div className="grid grid-cols-2 gap-3">
                                    <div>
                                        <label className="block text-xs font-semibold text-gray-700 mb-1">Periodo (AAAA-MM) *</label>
                                        <input
                                            type="month"
                                            value={registerForm.periodo}
                                            onChange={(event) => setRegisterForm((prev) => ({ ...prev, periodo: event.target.value }))}
                                            className="w-full border rounded-lg px-3 py-2 text-sm"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-xs font-semibold text-gray-700 mb-1">Monto (Bs.) *</label>
                                        <input
                                            type="number"
                                            min="0.01"
                                            step="0.01"
                                            value={registerForm.monto}
                                            onChange={(event) => setRegisterForm((prev) => ({ ...prev, monto: event.target.value }))}
                                            className="w-full border rounded-lg px-3 py-2 text-sm"
                                        />
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-xs font-semibold text-gray-700 mb-1">Fecha de pago *</label>
                                    <input
                                        type="date"
                                        value={registerForm.fechaPago}
                                        onChange={(event) => setRegisterForm((prev) => ({ ...prev, fechaPago: event.target.value }))}
                                        className="w-full border rounded-lg px-3 py-2 text-sm"
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs font-semibold text-gray-700 mb-1">
                                        Comprobante (foto/escaneo del depósito) *
                                    </label>
                                    <input
                                        type="file"
                                        accept="application/pdf,image/jpeg,image/png,image/jpg"
                                        onChange={(event) => setComprobanteFile(event.target.files?.[0] || null)}
                                        className="w-full text-sm"
                                    />
                                </div>
                            </div>
                        )}

                        <div className="mt-6 flex justify-end gap-3">
                            <button
                                type="button"
                                onClick={closeRegisterModal}
                                className="px-4 py-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
                            >
                                Cancelar
                            </button>
                            {selectedPatient && (
                                <button
                                    type="button"
                                    onClick={submitRegisterContribution}
                                    disabled={registering}
                                    className="px-4 py-2 rounded-lg bg-green-600 hover:bg-green-700 text-white font-bold disabled:opacity-50"
                                >
                                    {registering ? 'Registrando...' : 'Registrar y aceptar'}
                                </button>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
