import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Calculator, History, Package, Syringe, Upload } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { ConfirmModal } from '../../components/ui/ConfirmModal';
import {
    calculateWarehouseDistribution,
    getWarehouseDistribution,
    listWarehouseDistributions,
    listWarehouseStock,
} from '../../api/donations';
import logoUrl from '../../assets/logo.png';
import { imageToBase64 } from '../../utils/imageToBase64';
import DistributionHistoryPanel from './DistributionHistoryPanel';
import DistributionWorkspace from './DistributionWorkspace';
import WarehouseIntakePanel from './WarehouseIntakePanel';
import WarehouseStockPanel from './WarehouseStockPanel';

const TABS = [
    { id: 'ingreso', label: 'Ingreso', icon: <Upload size={16} /> },
    { id: 'stock', label: 'Stock', icon: <Package size={16} /> },
    { id: 'reparto', label: 'Reparto', icon: <Syringe size={16} /> },
    { id: 'historial', label: 'Historial', icon: <History size={16} /> },
];

// Almacén de insulina: se ingresa el Excel de la donación, se calcula el reparto con el mismo motor y las mismas
// reglas que el reporte de distribución, se ajusta con intercambios equivalentes y se consolida (descuenta el stock).
// Cada reparto queda guardado y se puede volver a ver; en el historial se filtra y se busca a un beneficiario.
export default function DonationsWarehousePage() {
    const navigate = useNavigate();
    const [tab, setTab] = useState('reparto');
    const [stock, setStock] = useState([]);
    const [soloDisponibles, setSoloDisponibles] = useState(true);
    const [history, setHistory] = useState([]);
    const [detail, setDetail] = useState(null);
    // Al abrir un reparto desde la búsqueda de un beneficiario, la matriz se abre filtrada en esa persona.
    const [detailSearch, setDetailSearch] = useState('');
    const [loadingDetail, setLoadingDetail] = useState(false);
    const [calculating, setCalculating] = useState(false);
    const [confirmRecalc, setConfirmRecalc] = useState(false);
    const [logoBase64, setLogoBase64] = useState(null);

    const loadStock = useCallback(
        (solo = soloDisponibles) =>
            listWarehouseStock(solo)
                .then(setStock)
                .catch((error) => toast.error(typeof error === 'string' ? error : 'No se pudo cargar el stock')),
        [soloDisponibles]
    );

    const loadHistory = useCallback(async () => {
        try {
            const list = await listWarehouseDistributions();
            setHistory(list);
            return list;
        } catch (error) {
            toast.error(typeof error === 'string' ? error : 'No se pudo cargar el historial');
            return [];
        }
    }, []);

    const openDistribution = useCallback(async (id, search = '') => {
        try {
            setLoadingDetail(true);
            setDetail(await getWarehouseDistribution(id));
            setDetailSearch(search);
            setTab('reparto');
        } catch (error) {
            toast.error(typeof error === 'string' ? error : 'No se pudo abrir el reparto');
        } finally {
            setLoadingDetail(false);
        }
    }, []);

    useEffect(() => {
        const user = JSON.parse(localStorage.getItem('user') || '{}');
        if (user.role !== 'SUPER_ADMIN') {
            toast.error('Solo SUPER_ADMIN puede acceder al almacén.');
            navigate('/dashboard/lista-pacientes', { replace: true });
            return;
        }
        imageToBase64(logoUrl).then(setLogoBase64).catch(() => setLogoBase64(null));
        loadStock(true);
        // Al entrar se abre el borrador en curso, si lo hay.
        loadHistory().then((list) => {
            const borrador = list.find((d) => d.estado === 'BORRADOR');
            if (borrador) openDistribution(borrador.id);
        });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [navigate]);

    const borradorActual = history.find((d) => d.estado === 'BORRADOR');

    const calculate = async () => {
        try {
            setCalculating(true);
            setConfirmRecalc(false);
            const result = await calculateWarehouseDistribution();
            setDetail(result);
            setDetailSearch('');
            setTab('reparto');
            toast.success(`Reparto #${result.id} calculado: queda en borrador hasta consolidarlo`);
            loadHistory();
        } catch (error) {
            toast.error(typeof error === 'string' ? error : 'No se pudo calcular el reparto');
        } finally {
            setCalculating(false);
        }
    };

    const handleCalculate = () => (borradorActual ? setConfirmRecalc(true) : calculate());

    const handleChange = (updated) => {
        setDetail(updated);
        loadHistory();
        if (updated.estado === 'CONSOLIDADO') loadStock();
    };

    return (
        <div className="p-6 md:p-8 max-w-7xl mx-auto animate-fadeIn">
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
                <div>
                    <h1 className="text-3xl font-bold text-gray-800">Almacén de insulina</h1>
                    <p className="text-gray-500">
                        Ingreso de donaciones, stock por lote y reparto con el mismo motor y las mismas reglas del reporte de
                        distribución.
                    </p>
                </div>
                <button
                    type="button"
                    onClick={handleCalculate}
                    disabled={calculating}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-vida-main text-white hover:bg-vida-hover shadow-lg shadow-vida-main/20 disabled:opacity-50"
                >
                    <Calculator size={18} /> {calculating ? 'Calculando reparto...' : 'Calcular reparto'}
                </button>
            </div>

            <div className="flex flex-wrap gap-2 mb-6 border-b border-gray-100" role="tablist">
                {TABS.map(({ id, label, icon }) => (
                    <button
                        key={id}
                        type="button"
                        role="tab"
                        aria-selected={tab === id}
                        onClick={() => setTab(id)}
                        className={`inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold border-b-2 -mb-px ${
                            tab === id ? 'border-vida-main text-vida-primary' : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                    >
                        {icon} {label}
                    </button>
                ))}
            </div>

            {tab === 'ingreso' && <WarehouseIntakePanel onIngresado={() => loadStock()} />}

            {tab === 'stock' && (
                <WarehouseStockPanel
                    stock={stock}
                    soloDisponibles={soloDisponibles}
                    onToggleDisponibles={(value) => {
                        setSoloDisponibles(value);
                        loadStock(value);
                    }}
                />
            )}

            {tab === 'reparto' && (
                <>
                    {loadingDetail && <p className="text-sm text-gray-400 py-10 text-center">Cargando reparto...</p>}
                    {!loadingDetail && !detail && (
                        <p className="text-sm text-gray-400 py-10 text-center">
                            No hay un reparto en curso. Ingrese la donación y pulse «Calcular reparto», o abra uno del historial.
                        </p>
                    )}
                    {!loadingDetail && detail && (
                        <DistributionWorkspace
                            key={`${detail.id}|${detailSearch}`}
                            initialSearch={detailSearch}
                            detail={detail}
                            logoBase64={logoBase64}
                            onChange={handleChange}
                            onDetailUpdate={setDetail}
                            onRecalculate={calculate}
                            recalculating={calculating}
                        />
                    )}
                </>
            )}

            {/* Siempre montado: los filtros y la persona buscada se conservan al cambiar de pestaña. */}
            <div hidden={tab !== 'historial'}>
                <DistributionHistoryPanel history={history} currentId={detail?.id} onOpen={openDistribution} />
            </div>

            <ConfirmModal
                isOpen={confirmRecalc}
                title="Calcular un reparto nuevo"
                message={`Ya hay un reparto en borrador (#${borradorActual?.id}${
                    borradorActual?.intercambios ? `, con ${borradorActual.intercambios} intercambio(s)` : ''
                }). Calcular uno nuevo lo descarta (queda en el historial). ¿Continuar?`}
                confirmLabel="Sí, calcular de nuevo"
                processing={calculating}
                onConfirm={calculate}
                onCancel={() => setConfirmRecalc(false)}
            />
        </div>
    );
}
