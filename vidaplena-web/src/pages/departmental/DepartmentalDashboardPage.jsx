import { useEffect, useState } from 'react';
import {
    MapPin, Search, CheckCircle, AlertTriangle, Syringe, Phone, X, Send, Plus, Trash2,
    MessageSquare, Pencil, ShieldCheck, FileWarning,
} from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '../../components/ui/Button';
import { DEPARTAMENTOS } from '../../constants/departamentos';
import { INSULIN_OPTIONS, PRESENTACION_OPTIONS } from '../../constants/insulins';
import {
    getActiveDepartmentalBeneficiaries,
    getPendingDocDepartmentalBeneficiaries,
    getDepartmentalInsulinDeliveries,
    createDepartmentalInsulinDelivery,
    updateDeliveryObservaciones,
    getDepartmentalResponsables,
    createInsulinShipment,
    getInsulinShipments,
} from '../../api/departmental';

const LIMIT = 20;

// El RESPONSABLE_DEPARTAMENTAL solo ve beneficiarios activos y pendientes de
// documentos de SU departamento; el historial de entregas y los envíos a
// responsables son solo para Coordinador Nacional / Super Admin.
const TABS_RESPONSABLE = [
    { key: 'activos', label: 'Beneficiarios Activos' },
    { key: 'pendientes', label: 'Documentos Pendientes' },
];
const TABS_NACIONAL = [
    ...TABS_RESPONSABLE,
    { key: 'historial', label: 'Historial de Entregas' },
    { key: 'envios', label: 'Envíos a Responsables' },
];

export default function DepartmentalDashboardPage() {
    const user = JSON.parse(localStorage.getItem('user') || '{}');
    const isCoordinadorNacional = user.role === 'COORDINADOR_NACIONAL';
    const esResponsableDepartamental = user.role === 'RESPONSABLE_DEPARTAMENTAL';
    const puedeRegistrarEntrega = user.role === 'RESPONSABLE_DEPARTAMENTAL' || user.role === 'SUPER_ADMIN';
    const puedeEnviarInsulina = user.role === 'COORDINADOR_NACIONAL' || user.role === 'SUPER_ADMIN';
    // Una vez consolidada la entrega, solo Coordinador Nacional/Super Admin
    // pueden corregir la observación (el responsable departamental solo la
    // fija al crearla — evita que quien registró pueda alterarla en silencio).
    const puedeEditarObservaciones = user.role === 'COORDINADOR_NACIONAL' || user.role === 'SUPER_ADMIN';
    const TABS = esResponsableDepartamental ? TABS_RESPONSABLE : TABS_NACIONAL;

    const [tab, setTab] = useState('activos');
    const [depto, setDepto] = useState(''); // Solo aplica para Coordinador Nacional ("" = todos)
    const [search, setSearch] = useState('');
    const [page, setPage] = useState(1);
    const [loading, setLoading] = useState(true);
    const [items, setItems] = useState([]);
    const [total, setTotal] = useState(0);

    const [deliveryModal, setDeliveryModal] = useState({ open: false, patient: null });
    const [deliveryForm, setDeliveryForm] = useState({
        items: [{ insulinType: INSULIN_OPTIONS[0]?.value || '', presentacion: PRESENTACION_OPTIONS[0]?.value || '', quantity: '' }],
        deliveryDate: '',
        observaciones: '',
    });
    const [submittingDelivery, setSubmittingDelivery] = useState(false);

    // Edición de observaciones de una entrega ya consolidada (solo
    // Coordinador Nacional / Super Admin).
    const [observationEdit, setObservationEdit] = useState({ open: false, delivery: null, value: '' });
    const [savingObservation, setSavingObservation] = useState(false);

    const [responsables, setResponsables] = useState([]);
    const [shipmentModalOpen, setShipmentModalOpen] = useState(false);
    const [shipmentForm, setShipmentForm] = useState({
        recipientUserId: '',
        items: [{ insulinType: INSULIN_OPTIONS[0]?.value || '', presentacion: PRESENTACION_OPTIONS[0]?.value || '', quantity: '' }],
        shipmentDate: '',
    });
    const [submittingShipment, setSubmittingShipment] = useState(false);

    const totalPages = Math.ceil(total / LIMIT) || 1;

    const load = async () => {
        try {
            setLoading(true);
            const params = { skip: (page - 1) * LIMIT, limit: LIMIT, search, depto };
            let data;
            if (tab === 'activos') {
                data = await getActiveDepartmentalBeneficiaries(params);
            } else if (tab === 'pendientes') {
                data = await getPendingDocDepartmentalBeneficiaries(params);
            } else if (tab === 'envios') {
                data = await getInsulinShipments({ skip: params.skip, limit: params.limit, depto });
            } else {
                data = await getDepartmentalInsulinDeliveries({ skip: params.skip, limit: params.limit, depto });
            }
            setItems(data.items || []);
            setTotal(data.total || 0);
        } catch (error) {
            console.error(error);
            toast.error('No se pudo cargar la información.');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tab, depto, page]);

    const handleTabChange = (key) => {
        setTab(key);
        setPage(1);
        setSearch('');
    };

    const handleSearchSubmit = (e) => {
        e.preventDefault();
        setPage(1);
        load();
    };

    const openDeliveryModal = (patient) => {
        setDeliveryForm({
            items: [{ insulinType: INSULIN_OPTIONS[0]?.value || '', presentacion: PRESENTACION_OPTIONS[0]?.value || '', quantity: '' }],
            deliveryDate: new Date().toISOString().slice(0, 10),
            observaciones: '',
        });
        setDeliveryModal({ open: true, patient });
    };

    const closeDeliveryModal = () => setDeliveryModal({ open: false, patient: null });

    const addDeliveryItem = () => {
        setDeliveryForm((prev) => {
            const usados = new Set(prev.items.map((it) => it.insulinType));
            const disponible = INSULIN_OPTIONS.find((opt) => !usados.has(opt.value));
            if (!disponible) {
                toast.error('Ya agregó todos los tipos de insulina disponibles.');
                return prev;
            }
            return {
                ...prev,
                items: [...prev.items, { insulinType: disponible.value, presentacion: PRESENTACION_OPTIONS[0]?.value || '', quantity: '' }],
            };
        });
    };

    const removeDeliveryItem = (index) => {
        setDeliveryForm((prev) => ({ ...prev, items: prev.items.filter((_, i) => i !== index) }));
    };

    const updateDeliveryItem = (index, field, value) => {
        setDeliveryForm((prev) => ({
            ...prev,
            items: prev.items.map((it, i) => (i === index ? { ...it, [field]: value } : it)),
        }));
    };

    const submitDelivery = async () => {
        const itemIncompleto = deliveryForm.items.some((it) => !it.insulinType || !it.quantity.trim());
        if (itemIncompleto) {
            toast.error('Indique el tipo de insulina y la cantidad entregada en cada fila.');
            return;
        }
        const tipos = deliveryForm.items.map((it) => it.insulinType);
        if (new Set(tipos).size !== tipos.length) {
            toast.error('No puede repetir el mismo tipo de insulina.');
            return;
        }
        try {
            setSubmittingDelivery(true);
            await createDepartmentalInsulinDelivery({
                patientId: deliveryModal.patient.id,
                items: deliveryForm.items.map((it) => ({
                    insulinType: it.insulinType,
                    presentacion: it.presentacion,
                    quantity: it.quantity.trim(),
                })),
                deliveryDate: deliveryForm.deliveryDate,
                observaciones: deliveryForm.observaciones.trim(),
            });
            toast.success(deliveryForm.items.length > 1 ? 'Entregas registradas.' : 'Entrega registrada.');
            closeDeliveryModal();
            if (tab === 'historial') load();
        } catch (error) {
            console.error(error);
            const detail = error?.response?.data?.detail;
            toast.error(typeof detail === 'string' ? detail : 'No se pudo registrar la entrega.');
        } finally {
            setSubmittingDelivery(false);
        }
    };

    const openObservationEdit = (delivery) => {
        setObservationEdit({ open: true, delivery, value: delivery.observaciones || '' });
    };

    const closeObservationEdit = () => setObservationEdit({ open: false, delivery: null, value: '' });

    const submitObservationEdit = async () => {
        try {
            setSavingObservation(true);
            await updateDeliveryObservaciones(observationEdit.delivery.id, observationEdit.value.trim());
            toast.success('Observación actualizada.');
            closeObservationEdit();
            load();
        } catch (error) {
            console.error(error);
            const detail = error?.response?.data?.detail;
            toast.error(typeof detail === 'string' ? detail : 'No se pudo actualizar la observación.');
        } finally {
            setSavingObservation(false);
        }
    };

    const openShipmentModal = async () => {
        setShipmentForm({
            recipientUserId: '',
            items: [{ insulinType: INSULIN_OPTIONS[0]?.value || '', presentacion: PRESENTACION_OPTIONS[0]?.value || '', quantity: '' }],
            shipmentDate: new Date().toISOString().slice(0, 10),
        });
        setShipmentModalOpen(true);
        try {
            const data = await getDepartmentalResponsables();
            setResponsables(Array.isArray(data) ? data : []);
        } catch (error) {
            console.error(error);
            toast.error('No se pudo cargar la lista de responsables de departamento.');
        }
    };

    const closeShipmentModal = () => setShipmentModalOpen(false);

    const addShipmentItem = () => {
        setShipmentForm((prev) => {
            const usados = new Set(prev.items.map((it) => it.insulinType));
            const disponible = INSULIN_OPTIONS.find((opt) => !usados.has(opt.value));
            if (!disponible) {
                toast.error('Ya agregó todos los tipos de insulina disponibles.');
                return prev;
            }
            return {
                ...prev,
                items: [...prev.items, { insulinType: disponible.value, presentacion: PRESENTACION_OPTIONS[0]?.value || '', quantity: '' }],
            };
        });
    };

    const removeShipmentItem = (index) => {
        setShipmentForm((prev) => ({ ...prev, items: prev.items.filter((_, i) => i !== index) }));
    };

    const updateShipmentItem = (index, field, value) => {
        setShipmentForm((prev) => ({
            ...prev,
            items: prev.items.map((it, i) => (i === index ? { ...it, [field]: value } : it)),
        }));
    };

    const submitShipment = async () => {
        if (!shipmentForm.recipientUserId) {
            toast.error('Seleccione al responsable de departamento destinatario.');
            return;
        }
        const itemIncompleto = shipmentForm.items.some((it) => !it.insulinType || !it.quantity.trim());
        if (itemIncompleto) {
            toast.error('Indique el tipo de insulina y la cantidad enviada en cada fila.');
            return;
        }
        const tipos = shipmentForm.items.map((it) => it.insulinType);
        if (new Set(tipos).size !== tipos.length) {
            toast.error('No puede repetir el mismo tipo de insulina.');
            return;
        }
        try {
            setSubmittingShipment(true);
            await createInsulinShipment({
                recipientUserId: Number(shipmentForm.recipientUserId),
                items: shipmentForm.items.map((it) => ({
                    insulinType: it.insulinType,
                    presentacion: it.presentacion,
                    quantity: it.quantity.trim(),
                })),
                shipmentDate: shipmentForm.shipmentDate,
            });
            toast.success(shipmentForm.items.length > 1 ? 'Envíos registrados.' : 'Envío registrado.');
            closeShipmentModal();
            if (tab === 'envios') load();
        } catch (error) {
            console.error(error);
            const detail = error?.response?.data?.detail;
            toast.error(typeof detail === 'string' ? detail : 'No se pudo registrar el envío.');
        } finally {
            setSubmittingShipment(false);
        }
    };

    return (
        <div className="max-w-6xl mx-auto">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-6">
                <div>
                    <h1 className="text-2xl font-bold text-gray-800 flex items-center gap-2">
                        <MapPin size={24} className="text-vida-main" />
                        {isCoordinadorNacional ? 'Panel Nacional' : `Mi Departamento — ${user.depto_asignado || ''}`}
                    </h1>
                    <p className="text-sm text-gray-500">
                        {isCoordinadorNacional
                            ? 'Seguimiento y control a nivel nacional (solo lectura).'
                            : 'Beneficiarios de su departamento asignado.'}
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    {isCoordinadorNacional && (
                        <select
                            value={depto}
                            onChange={(e) => { setDepto(e.target.value); setPage(1); }}
                            className="border rounded-lg px-3 py-2 text-sm bg-white"
                        >
                            <option value="">Todos los departamentos</option>
                            {DEPARTAMENTOS.map((d) => <option key={d} value={d}>{d}</option>)}
                        </select>
                    )}
                    {tab === 'envios' && puedeEnviarInsulina && (
                        <Button
                            type="button"
                            className="bg-vida-main hover:bg-vida-hover text-white w-auto px-4"
                            onClick={openShipmentModal}
                        >
                            <Send size={16} className="mr-2" />
                            Registrar envío
                        </Button>
                    )}
                </div>
            </div>

            {/* TABS */}
            <div className="flex gap-2 border-b border-gray-200 mb-6 overflow-x-auto">
                {TABS.map((t) => (
                    <button
                        key={t.key}
                        onClick={() => handleTabChange(t.key)}
                        className={`px-4 py-2 text-sm font-semibold whitespace-nowrap border-b-2 transition-colors ${
                            tab === t.key
                                ? 'border-vida-main text-vida-main'
                                : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                    >
                        {t.label}
                    </button>
                ))}
            </div>

            {/* BUSCADOR (no aplica al historial ni a envíos) */}
            {tab !== 'historial' && tab !== 'envios' && (
                <form onSubmit={handleSearchSubmit} className="flex gap-2 mb-4">
                    <div className="relative flex-1 max-w-md">
                        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                        <input
                            type="text"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Buscar por nombre o CI..."
                            className="w-full pl-9 pr-3 py-2 border rounded-lg text-sm"
                        />
                    </div>
                    <Button type="submit" variant="secondary" className="border border-gray-200 text-gray-700 w-auto px-4">
                        Buscar
                    </Button>
                </form>
            )}

            {loading ? (
                <div className="p-10 text-center text-gray-500 font-semibold">Cargando...</div>
            ) : items.length === 0 ? (
                <div className="bg-white border border-gray-100 rounded-xl p-6 text-sm text-gray-500">
                    No hay resultados.
                </div>
            ) : tab === 'activos' ? (
                <div className="space-y-3">
                    {items.map((p) => (
                        <div key={p.id} className="bg-white border border-gray-100 rounded-xl p-4 shadow-sm flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                            <div>
                                <p className="font-semibold text-gray-800">
                                    {p.nombres} {p.ap_paterno} {p.ap_materno || ''} — CI {p.ci || 'Sin CI'}
                                </p>
                                <p className="text-sm text-gray-500 mt-1 flex items-center gap-3 flex-wrap">
                                    {isCoordinadorNacional && <span className="inline-flex items-center gap-1"><MapPin size={12} /> {p.depto || 'Sin depto'}</span>}
                                    {p.tel_contacto && <span className="inline-flex items-center gap-1"><Phone size={12} /> {p.tel_contacto}</span>}
                                </p>
                            </div>
                            <div className="flex items-center gap-2 flex-wrap justify-end">
                                {p.exonerado_aporte ? (
                                    <span className="text-xs font-bold px-3 py-1 rounded-full border inline-flex items-center gap-1 bg-blue-100 text-blue-700 border-blue-200">
                                        <ShieldCheck size={14} /> Exonerado
                                    </span>
                                ) : (
                                    <>
                                        <span className={`text-xs font-bold px-3 py-1 rounded-full border inline-flex items-center gap-1 ${
                                            p.al_dia_aporte
                                                ? 'bg-green-100 text-green-700 border-green-200'
                                                : 'bg-red-100 text-red-700 border-red-200'
                                        }`}>
                                            {p.al_dia_aporte ? <CheckCircle size={14} /> : <AlertTriangle size={14} />}
                                            {p.al_dia_aporte ? `Al día (${p.periodo_actual})` : `Sin aporte (${p.periodo_actual})`}
                                        </span>
                                        <span className={`text-xs font-bold px-3 py-1 rounded-full border inline-flex items-center gap-1 ${
                                            p.al_dia_mes_anterior
                                                ? 'bg-green-50 text-green-600 border-green-200'
                                                : 'bg-red-50 text-red-600 border-red-200'
                                        }`}>
                                            {p.al_dia_mes_anterior ? <CheckCircle size={14} /> : <AlertTriangle size={14} />}
                                            {p.al_dia_mes_anterior ? `Al día (${p.periodo_anterior})` : `Sin aporte (${p.periodo_anterior})`}
                                        </span>
                                    </>
                                )}
                                {puedeRegistrarEntrega && (
                                    <button
                                        type="button"
                                        onClick={() => openDeliveryModal(p)}
                                        className="px-3 py-2 rounded-xl font-bold text-sm bg-vida-main hover:bg-vida-hover text-white inline-flex items-center gap-1"
                                    >
                                        <Syringe size={16} /> Registrar entrega
                                    </button>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            ) : tab === 'pendientes' ? (
                <div className="space-y-3">
                    {items.map((p) => (
                        <div key={p.id} className="bg-white border border-gray-100 rounded-xl p-4 shadow-sm">
                            <p className="font-semibold text-gray-800">
                                {p.nombres} {p.ap_paterno} {p.ap_materno || ''} — CI {p.ci || 'Sin CI'}
                            </p>
                            <p className="text-sm text-gray-500 mt-1 flex items-center gap-3 flex-wrap">
                                {isCoordinadorNacional && <span className="inline-flex items-center gap-1"><MapPin size={12} /> {p.depto || 'Sin depto'}</span>}
                                {p.tel_contacto && <span className="inline-flex items-center gap-1"><Phone size={12} /> {p.tel_contacto}</span>}
                                <span className="text-xs font-bold px-2 py-1 rounded-full bg-yellow-100 text-yellow-700 border border-yellow-200">
                                    {p.estado}
                                </span>
                            </p>
                            {p.documentos_pendientes && p.documentos_pendientes.length > 0 && (
                                <div className="mt-2 flex items-start gap-1.5 bg-orange-50 border border-orange-100 rounded-lg px-3 py-2">
                                    <FileWarning size={14} className="text-orange-500 mt-0.5 flex-shrink-0" />
                                    <p className="text-xs text-orange-700">
                                        <span className="font-bold">Le falta subir:</span>{' '}
                                        {p.documentos_pendientes.join(', ')}
                                    </p>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            ) : tab === 'historial' ? (
                <div className="space-y-3">
                    {items.map((d) => (
                        <div key={d.id} className="bg-white border border-gray-100 rounded-xl p-4 shadow-sm flex flex-col md:flex-row md:items-start md:justify-between gap-2">
                            <div>
                                <p className="font-semibold text-gray-800">{d.patient_nombre}</p>
                                <p className="text-sm text-gray-500 mt-1">
                                    {d.insulin_type} ({d.presentacion}) — {d.quantity} | Entrega: {d.delivery_date}
                                    {isCoordinadorNacional && ` | ${d.depto}`}
                                </p>
                                {d.observaciones && (
                                    <div className="mt-2 flex items-start gap-1.5 bg-purple-50 border border-purple-100 rounded-lg px-3 py-2 max-w-xl">
                                        <MessageSquare size={14} className="text-purple-500 mt-0.5 flex-shrink-0" />
                                        <p className="text-xs text-purple-800 whitespace-pre-wrap">{d.observaciones}</p>
                                    </div>
                                )}
                            </div>
                            <div className="flex flex-col items-end gap-1 flex-shrink-0">
                                <p className="text-xs text-gray-400">Registrado por {d.recorded_by_email || 'desconocido'}</p>
                                {puedeEditarObservaciones && (
                                    <button
                                        type="button"
                                        onClick={() => openObservationEdit(d)}
                                        className="text-xs font-bold text-vida-primary hover:underline inline-flex items-center gap-1"
                                    >
                                        <Pencil size={12} /> {d.observaciones ? 'Editar observación' : 'Agregar observación'}
                                    </button>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            ) : (
                <div className="space-y-3">
                    {items.map((s) => (
                        <div key={s.id} className="bg-white border border-gray-100 rounded-xl p-4 shadow-sm flex flex-col md:flex-row md:items-center md:justify-between gap-2">
                            <div>
                                <p className="font-semibold text-gray-800">
                                    {s.recipient_email} <span className="text-gray-400 font-normal">— {s.depto}</span>
                                </p>
                                <p className="text-sm text-gray-500 mt-1">
                                    {s.insulin_type} ({s.presentacion}) — {s.quantity} | Envío: {s.shipment_date}
                                </p>
                            </div>
                            <p className="text-xs text-gray-400">Registrado por {s.recorded_by_email || 'desconocido'}</p>
                        </div>
                    ))}
                </div>
            )}

            {!loading && totalPages > 1 && (
                <div className="flex items-center justify-between px-2 py-4">
                    <div className="text-sm text-gray-500">
                        Página <span className="font-medium text-gray-900">{page}</span> de <span className="font-medium text-gray-900">{totalPages}</span>
                    </div>
                    <div className="flex gap-2">
                        <button
                            onClick={() => setPage((p) => Math.max(1, p - 1))}
                            disabled={page === 1}
                            className="px-4 py-2 border border-gray-200 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                            Anterior
                        </button>
                        <button
                            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                            disabled={page === totalPages}
                            className="px-4 py-2 border border-gray-200 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                            Siguiente
                        </button>
                    </div>
                </div>
            )}

            {deliveryModal.open && (
                <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
                        <div className="flex justify-between items-center mb-4">
                            <h3 className="text-lg font-bold text-gray-800">Registrar entrega de insulina</h3>
                            <button onClick={closeDeliveryModal} className="text-gray-400 hover:text-gray-600">
                                <X size={22} />
                            </button>
                        </div>
                        <p className="text-sm text-gray-500 mb-4">
                            Beneficiario: <span className="font-semibold text-gray-800">
                                {deliveryModal.patient?.nombres} {deliveryModal.patient?.ap_paterno} {deliveryModal.patient?.ap_materno || ''}
                            </span>
                            <br />
                            Este registro es solo un control interno (fecha/tipo/presentación/cantidad) — no afecta el stock de almacén.
                        </p>

                        <div className="space-y-3">
                            <div className="flex items-center justify-between">
                                <label className="block text-xs font-semibold text-gray-700">Insulina(s) entregada(s) *</label>
                                <button
                                    type="button"
                                    onClick={addDeliveryItem}
                                    className="text-xs font-bold text-vida-main hover:text-vida-hover inline-flex items-center gap-1"
                                >
                                    <Plus size={14} /> Agregar otro tipo
                                </button>
                            </div>
                            {deliveryForm.items.map((item, index) => (
                                <div key={index} className="bg-gray-50 p-2 rounded-lg space-y-2">
                                    <div className="flex gap-2 items-start">
                                        <select
                                            value={item.insulinType}
                                            onChange={(e) => updateDeliveryItem(index, 'insulinType', e.target.value)}
                                            className="flex-1 border rounded-lg px-3 py-2 text-sm bg-white"
                                        >
                                            {INSULIN_OPTIONS.map((opt) => (
                                                <option key={opt.value} value={opt.value}>{opt.label}</option>
                                            ))}
                                        </select>
                                        {deliveryForm.items.length > 1 && (
                                            <button
                                                type="button"
                                                onClick={() => removeDeliveryItem(index)}
                                                className="text-red-400 hover:text-red-600 p-2"
                                            >
                                                <Trash2 size={16} />
                                            </button>
                                        )}
                                    </div>
                                    <div className="flex gap-2 items-start">
                                        <select
                                            value={item.presentacion}
                                            onChange={(e) => updateDeliveryItem(index, 'presentacion', e.target.value)}
                                            className="flex-1 border rounded-lg px-3 py-2 text-sm bg-white"
                                        >
                                            {PRESENTACION_OPTIONS.map((opt) => (
                                                <option key={opt.value} value={opt.value}>{opt.label}</option>
                                            ))}
                                        </select>
                                        <input
                                            type="text"
                                            value={item.quantity}
                                            onChange={(e) => updateDeliveryItem(index, 'quantity', e.target.value)}
                                            placeholder="Cantidad"
                                            className="w-28 border rounded-lg px-3 py-2 text-sm"
                                        />
                                    </div>
                                </div>
                            ))}
                            <div>
                                <label className="block text-xs font-semibold text-gray-700 mb-1">Fecha de entrega *</label>
                                <input
                                    type="date"
                                    value={deliveryForm.deliveryDate}
                                    onChange={(e) => setDeliveryForm((prev) => ({ ...prev, deliveryDate: e.target.value }))}
                                    className="w-full border rounded-lg px-3 py-2 text-sm"
                                />
                            </div>
                            <div>
                                <label className="block text-xs font-semibold text-gray-700 mb-1">Observaciones</label>
                                <p className="text-xs text-gray-400 mb-1">
                                    Ej: solicitó cambio de insulina, no podrá recoger por viaje, sospecha de reventa,
                                    falleció, etc. Una vez guardada la entrega, solo el Coordinador Nacional o
                                    SUPER_ADMIN podrán corregir esta nota.
                                </p>
                                <textarea
                                    value={deliveryForm.observaciones}
                                    onChange={(e) => setDeliveryForm((prev) => ({ ...prev, observaciones: e.target.value }))}
                                    className="w-full border rounded-lg px-3 py-2 text-sm min-h-[90px]"
                                    placeholder="Observaciones sobre el beneficiario en esta visita (opcional)"
                                />
                            </div>
                        </div>

                        <div className="mt-6 flex justify-end gap-3">
                            <button
                                type="button"
                                onClick={closeDeliveryModal}
                                className="px-4 py-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
                            >
                                Cancelar
                            </button>
                            <button
                                type="button"
                                onClick={submitDelivery}
                                disabled={submittingDelivery}
                                className="px-4 py-2 rounded-lg bg-vida-main hover:bg-vida-hover text-white font-bold disabled:opacity-50"
                            >
                                {submittingDelivery ? 'Registrando...' : 'Registrar entrega'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {shipmentModalOpen && (
                <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
                        <div className="flex justify-between items-center mb-4">
                            <h3 className="text-lg font-bold text-gray-800">Registrar envío de insulina</h3>
                            <button onClick={closeShipmentModal} className="text-gray-400 hover:text-gray-600">
                                <X size={22} />
                            </button>
                        </div>
                        <p className="text-sm text-gray-500 mb-4">
                            Registra la insulina que usted (Coordinador Nacional) envió a un responsable de
                            departamento para su distribución. Es solo un control interno — no afecta el
                            stock de almacén.
                        </p>

                        <div className="space-y-3">
                            <div>
                                <label className="block text-xs font-semibold text-gray-700 mb-1">Responsable de departamento *</label>
                                <select
                                    value={shipmentForm.recipientUserId}
                                    onChange={(e) => setShipmentForm((prev) => ({ ...prev, recipientUserId: e.target.value }))}
                                    className="w-full border rounded-lg px-3 py-2 text-sm bg-white"
                                >
                                    <option value="">Seleccione...</option>
                                    {responsables.map((r) => (
                                        <option key={r.id} value={r.id}>
                                            {r.email} — {r.depto_asignado || 'Sin depto'}
                                        </option>
                                    ))}
                                </select>
                            </div>
                            <div className="flex items-center justify-between">
                                <label className="block text-xs font-semibold text-gray-700">Insulina(s) enviada(s) *</label>
                                <button
                                    type="button"
                                    onClick={addShipmentItem}
                                    className="text-xs font-bold text-vida-main hover:text-vida-hover inline-flex items-center gap-1"
                                >
                                    <Plus size={14} /> Agregar otro tipo
                                </button>
                            </div>
                            {shipmentForm.items.map((item, index) => (
                                <div key={index} className="bg-gray-50 p-2 rounded-lg space-y-2">
                                    <div className="flex gap-2 items-start">
                                        <select
                                            value={item.insulinType}
                                            onChange={(e) => updateShipmentItem(index, 'insulinType', e.target.value)}
                                            className="flex-1 border rounded-lg px-3 py-2 text-sm bg-white"
                                        >
                                            {INSULIN_OPTIONS.map((opt) => (
                                                <option key={opt.value} value={opt.value}>{opt.label}</option>
                                            ))}
                                        </select>
                                        {shipmentForm.items.length > 1 && (
                                            <button
                                                type="button"
                                                onClick={() => removeShipmentItem(index)}
                                                className="text-red-400 hover:text-red-600 p-2"
                                            >
                                                <Trash2 size={16} />
                                            </button>
                                        )}
                                    </div>
                                    <div className="flex gap-2 items-start">
                                        <select
                                            value={item.presentacion}
                                            onChange={(e) => updateShipmentItem(index, 'presentacion', e.target.value)}
                                            className="flex-1 border rounded-lg px-3 py-2 text-sm bg-white"
                                        >
                                            {PRESENTACION_OPTIONS.map((opt) => (
                                                <option key={opt.value} value={opt.value}>{opt.label}</option>
                                            ))}
                                        </select>
                                        <input
                                            type="text"
                                            value={item.quantity}
                                            onChange={(e) => updateShipmentItem(index, 'quantity', e.target.value)}
                                            placeholder="Cantidad"
                                            className="w-28 border rounded-lg px-3 py-2 text-sm"
                                        />
                                    </div>
                                </div>
                            ))}
                            <div>
                                <label className="block text-xs font-semibold text-gray-700 mb-1">Fecha de envío *</label>
                                <input
                                    type="date"
                                    value={shipmentForm.shipmentDate}
                                    onChange={(e) => setShipmentForm((prev) => ({ ...prev, shipmentDate: e.target.value }))}
                                    className="w-full border rounded-lg px-3 py-2 text-sm"
                                />
                            </div>
                        </div>

                        <div className="mt-6 flex justify-end gap-3">
                            <button
                                type="button"
                                onClick={closeShipmentModal}
                                className="px-4 py-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
                            >
                                Cancelar
                            </button>
                            <button
                                type="button"
                                onClick={submitShipment}
                                disabled={submittingShipment}
                                className="px-4 py-2 rounded-lg bg-vida-main hover:bg-vida-hover text-white font-bold disabled:opacity-50"
                            >
                                {submittingShipment ? 'Registrando...' : 'Registrar envío'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {observationEdit.open && (
                <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
                        <div className="flex justify-between items-center mb-4">
                            <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
                                <MessageSquare size={18} className="text-purple-600" /> Observación de la entrega
                            </h3>
                            <button onClick={closeObservationEdit} className="text-gray-400 hover:text-gray-600">
                                <X size={22} />
                            </button>
                        </div>
                        <p className="text-sm text-gray-500 mb-3">
                            Beneficiario: <span className="font-semibold text-gray-800">{observationEdit.delivery?.patient_nombre}</span>
                            <br />
                            Entrega del {observationEdit.delivery?.delivery_date}.
                        </p>
                        <textarea
                            value={observationEdit.value}
                            onChange={(e) => setObservationEdit((prev) => ({ ...prev, value: e.target.value }))}
                            className="w-full border rounded-lg px-3 py-2 text-sm min-h-[120px]"
                            placeholder="Observaciones sobre el beneficiario en esta entrega"
                        />
                        <div className="mt-4 flex justify-end gap-3">
                            <button
                                type="button"
                                onClick={closeObservationEdit}
                                className="px-4 py-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
                            >
                                Cancelar
                            </button>
                            <button
                                type="button"
                                onClick={submitObservationEdit}
                                disabled={savingObservation}
                                className="px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-700 text-white font-bold disabled:opacity-50"
                            >
                                {savingObservation ? 'Guardando...' : 'Guardar'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
