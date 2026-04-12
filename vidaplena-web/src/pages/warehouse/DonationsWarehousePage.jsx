import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Package, PlusCircle, Calculator, Upload, Settings, Save, CheckCircle2, Truck, FileDown, FileUp } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { INSULIN_OPTIONS } from '../../constants/insulins';
import {
  calculateDonationDistribution,
  consolidateDonationLot,
  createDonationLot,
  createDonationProduct,
  createDelivery,
  getDeliveryByAllocation,
  getDeliveryReceipt,
  getDonationLotDetail,
  importDonationLotsCsv,
  listLotMovements,
  listDonationLots,
  listDonationProducts,
  updateDonationAllocation,
  uploadDeliveryReceipt,
} from '../../api/donations';

const PRODUCT_TYPE = 'INSULINA';

export default function DonationsWarehousePage() {
  const navigate = useNavigate();
  const [products, setProducts] = useState([]);
  const [lots, setLots] = useState([]);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [loadingLots, setLoadingLots] = useState(false);
  const [savingProduct, setSavingProduct] = useState(false);
  const [savingLot, setSavingLot] = useState(false);
  const [checkingLotId, setCheckingLotId] = useState(null);
  const [calculatingLotId, setCalculatingLotId] = useState(null);
  const [calculatedLots, setCalculatedLots] = useState({});
  const [calculationResult, setCalculationResult] = useState(null);
  const [csvFile, setCsvFile] = useState(null);
  const [importingCsv, setImportingCsv] = useState(false);
  const [csvResult, setCsvResult] = useState(null);
  const [managedLot, setManagedLot] = useState(null);
  const [loadingManagedLot, setLoadingManagedLot] = useState(false);
  const [allocationDrafts, setAllocationDrafts] = useState({});
  const [savingAllocationId, setSavingAllocationId] = useState(null);
  const [consolidatingLotId, setConsolidatingLotId] = useState(null);
  const [deliveryDrafts, setDeliveryDrafts] = useState({});
  const [deliveryByAllocation, setDeliveryByAllocation] = useState({});
  const [creatingDeliveryAllocationId, setCreatingDeliveryAllocationId] = useState(null);
  const [downloadingDeliveryId, setDownloadingDeliveryId] = useState(null);
  const [receiptFiles, setReceiptFiles] = useState({});
  const [uploadingReceiptDeliveryId, setUploadingReceiptDeliveryId] = useState(null);
  const [lotMovements, setLotMovements] = useState([]);

  const [productForm, setProductForm] = useState({
    tipo: PRODUCT_TYPE,
    nombre_generico: '',
    marca: '',
    nombre_comercial: '',
    presentacion: '',
    factor_conversion: '1',
  });

  const [lotForm, setLotForm] = useState({
    donation_id: '',
    cantidad_total: '',
    lote: '',
    fecha_venc: '',
  });

  const productsById = useMemo(() => {
    return products.reduce((acc, item) => {
      acc[item.id] = item;
      return acc;
    }, {});
  }, [products]);

  const loadProducts = async () => {
    try {
      setLoadingProducts(true);
      const data = await listDonationProducts();
      setProducts(data);
    } catch (error) {
      toast.error(error || 'Error al cargar productos');
    } finally {
      setLoadingProducts(false);
    }
  };

  const loadLots = async () => {
    try {
      setLoadingLots(true);
      const data = await listDonationLots();
      setLots(data);
    } catch (error) {
      toast.error(error || 'Error al cargar lotes');
    } finally {
      setLoadingLots(false);
    }
  };

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || '{}');
    if (user.role !== 'SUPER_ADMIN') {
      toast.error('Solo SUPER_ADMIN puede acceder al almacén.');
      navigate('/dashboard/lista-pacientes', { replace: true });
      return;
    }
    loadProducts();
    loadLots();
  }, [navigate]);

  const handleProductChange = (field) => (event) => {
    setProductForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const handleLotChange = (field) => (event) => {
    setLotForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const handleCreateProduct = async (event) => {
    event.preventDefault();
    if (!productForm.nombre_generico.trim()) {
      toast.error('Completa el nombre genérico');
      return;
    }

    const factorValue = productForm.factor_conversion
      ? Number(productForm.factor_conversion)
      : 1;

    if (Number.isNaN(factorValue) || factorValue <= 0) {
      toast.error('El factor de conversión debe ser mayor a 0');
      return;
    }

    const payload = {
      tipo: PRODUCT_TYPE,
      nombre_generico: productForm.nombre_generico.trim(),
      marca: productForm.marca.trim() || null,
      nombre_comercial: productForm.nombre_comercial.trim() || null,
      presentacion: productForm.presentacion.trim() || null,
      factor_conversion: factorValue,
    };

    try {
      setSavingProduct(true);
      await createDonationProduct(payload);
      toast.success('Producto registrado');
      setProductForm({
        tipo: PRODUCT_TYPE,
        nombre_generico: '',
        marca: '',
        nombre_comercial: '',
        presentacion: '',
        factor_conversion: '1',
      });
      loadProducts();
    } catch (error) {
      toast.error(error || 'No se pudo registrar el producto');
    } finally {
      setSavingProduct(false);
    }
  };

  const handleCreateLot = async (event) => {
    event.preventDefault();
    if (!lotForm.donation_id) {
      toast.error('Selecciona un producto');
      return;
    }
    const cantidadValue = Number(lotForm.cantidad_total);
    if (Number.isNaN(cantidadValue) || cantidadValue <= 0) {
      toast.error('La cantidad total debe ser mayor a 0');
      return;
    }

    const payload = {
      donation_id: Number(lotForm.donation_id),
      cantidad_total: cantidadValue,
      lote: lotForm.lote.trim() || null,
      fecha_venc: lotForm.fecha_venc || null,
    };

    try {
      setSavingLot(true);
      await createDonationLot(payload);
      toast.success('Lote registrado');
      setLotForm({
        donation_id: '',
        cantidad_total: '',
        lote: '',
        fecha_venc: '',
      });
      loadLots();
    } catch (error) {
      toast.error(error || 'No se pudo registrar el lote');
    } finally {
      setSavingLot(false);
    }
  };

  const buildAllocationDrafts = (lotDetail) => {
    const quantityDrafts = {};
    const nextDeliveryDrafts = {};
    (lotDetail?.allocations || []).forEach((allocation) => {
      quantityDrafts[allocation.id] = String(
        allocation.cantidad_ajustada ?? allocation.cantidad_sugerida ?? 0
      );
      nextDeliveryDrafts[allocation.id] = {
        fecha_entrega: new Date().toISOString().slice(0, 10),
        cantidad_entregada: String(
          allocation.cantidad_ajustada ?? allocation.cantidad_sugerida ?? 0
        ),
      };
    });
    setAllocationDrafts(quantityDrafts);
    setDeliveryDrafts(nextDeliveryDrafts);
  };

  const loadLotManagement = async (lotId) => {
    try {
      setLoadingManagedLot(true);
      const detail = await getDonationLotDetail(lotId);
      setManagedLot(detail);
      buildAllocationDrafts(detail);

      const movementData = await listLotMovements(lotId);
      setLotMovements(Array.isArray(movementData) ? movementData : []);

      const deliveryEntries = await Promise.all(
        (detail.allocations || []).map(async (allocation) => {
          if (allocation.estado !== 'CONSOLIDADO') return [allocation.id, null];
          const delivery = await getDeliveryByAllocation(allocation.id);
          return [allocation.id, delivery];
        })
      );
      setDeliveryByAllocation(Object.fromEntries(deliveryEntries));
    } catch (error) {
      toast.error(error || 'No se pudo cargar la gestión del lote');
    } finally {
      setLoadingManagedLot(false);
    }
  };

  const handleOpenLotManagement = async (lot) => {
    if (!lot?.id) return;
    await loadLotManagement(lot.id);
  };

  const handleAllocationDraftChange = (allocationId, value) => {
    setAllocationDrafts((prev) => ({ ...prev, [allocationId]: value }));
  };

  const handleSaveAllocation = async (allocation) => {
    const rawValue = allocationDrafts[allocation.id];
    const nextValue = Number(rawValue);
    if (!Number.isInteger(nextValue) || nextValue < 0) {
      toast.error('La cantidad ajustada debe ser un entero mayor o igual a 0');
      return;
    }

    try {
      setSavingAllocationId(allocation.id);
      await updateDonationAllocation(allocation.id, { cantidad_ajustada: nextValue });
      toast.success('Asignación actualizada');
      await loadLotManagement(allocation.lot_id);
    } catch (error) {
      toast.error(error || 'No se pudo guardar la asignación');
    } finally {
      setSavingAllocationId(null);
    }
  };

  const handleConsolidateLot = async () => {
    if (!managedLot?.id) return;
    try {
      setConsolidatingLotId(managedLot.id);
      await consolidateDonationLot(managedLot.id);
      toast.success('Lote consolidado correctamente');
      setCalculatedLots((prev) => ({ ...prev, [managedLot.id]: true }));
      await loadLots();
      await loadLotManagement(managedLot.id);
    } catch (error) {
      toast.error(error || 'No se pudo consolidar el lote');
    } finally {
      setConsolidatingLotId(null);
    }
  };

  const handleDeliveryDraftChange = (allocationId, field, value) => {
    setDeliveryDrafts((prev) => ({
      ...prev,
      [allocationId]: {
        ...(prev[allocationId] || {}),
        [field]: value,
      },
    }));
  };

  const handleCreateDelivery = async (allocation) => {
    const draft = deliveryDrafts[allocation.id];
    const cantidad = Number(draft?.cantidad_entregada);
    if (!draft?.fecha_entrega) {
      toast.error('Fecha de entrega obligatoria');
      return;
    }
    if (!Number.isInteger(cantidad) || cantidad <= 0) {
      toast.error('Cantidad entregada inválida');
      return;
    }

    try {
      setCreatingDeliveryAllocationId(allocation.id);
      const delivery = await createDelivery({
        allocation_id: allocation.id,
        fecha_entrega: draft.fecha_entrega,
        cantidad_entregada: cantidad,
      });
      setDeliveryByAllocation((prev) => ({ ...prev, [allocation.id]: delivery }));
      toast.success('Entrega registrada');
    } catch (error) {
      toast.error(error || 'No se pudo registrar la entrega');
    } finally {
      setCreatingDeliveryAllocationId(null);
    }
  };

  const handleDownloadReceipt = async (deliveryId) => {
    try {
      setDownloadingDeliveryId(deliveryId);
      const blob = await getDeliveryReceipt(deliveryId);
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
      toast.error(error || 'No se pudo descargar la boleta');
    } finally {
      setDownloadingDeliveryId(null);
    }
  };

  const handleReceiptFileChange = (deliveryId, file) => {
    setReceiptFiles((prev) => ({ ...prev, [deliveryId]: file || null }));
  };

  const handleUploadSignedReceipt = async (allocationId, delivery) => {
    const file = receiptFiles[delivery.id];
    if (!file) {
      toast.error('Selecciona la constancia firmada en PDF');
      return;
    }
    try {
      setUploadingReceiptDeliveryId(delivery.id);
      const updatedDelivery = await uploadDeliveryReceipt(delivery.id, file);
      setDeliveryByAllocation((prev) => ({ ...prev, [allocationId]: updatedDelivery }));
      setReceiptFiles((prev) => ({ ...prev, [delivery.id]: null }));
      toast.success('Constancia subida');
    } catch (error) {
      toast.error(error || 'No se pudo subir la constancia');
    } finally {
      setUploadingReceiptDeliveryId(null);
    }
  };

  const handleCalculate = async (lot) => {
    if (!lot?.id) {
      toast.error('Selecciona un lote válido');
      return;
    }

    try {
      setCheckingLotId(lot.id);
      const detail = await getDonationLotDetail(lot.id);
      const hasAllocations =
        Array.isArray(detail?.allocations) && detail.allocations.length > 0;

      if (hasAllocations) {
        const hasConsolidated = detail.allocations.some(
          (allocation) => allocation.estado === 'CONSOLIDADO'
        );
        if (hasConsolidated) {
          setCalculatedLots((prev) => ({ ...prev, [lot.id]: true }));
          await handleOpenLotManagement(lot);
          toast.error('Este lote ya está consolidado y no permite recálculo');
          return;
        }
        const confirmed = window.confirm(
          'Este lote ya tiene asignaciones en BORRADOR. ¿Desea recalcular y reemplazarlas?'
        );
        if (!confirmed) {
          await handleOpenLotManagement(lot);
          return;
        }
      }
    } catch (error) {
      toast.error(error || 'No se pudo verificar el lote');
      return;
    } finally {
      setCheckingLotId(null);
    }

    try {
      setCalculatingLotId(lot.id);
      const result = await calculateDonationDistribution(lot.id);
      setCalculationResult(result);
      setCalculatedLots((prev) => ({ ...prev, [lot.id]: true }));
      await handleOpenLotManagement(lot);
      toast.success('Distribución calculada');
      loadLots();
    } catch (error) {
      toast.error(error || 'No se pudo calcular la distribución');
    } finally {
      setCalculatingLotId(null);
    }
  };

  const handleCsvFileChange = (event) => {
    const file = event.target.files?.[0] || null;
    setCsvFile(file);
  };

  const handleImportCsv = async () => {
    if (!csvFile) {
      toast.error('Selecciona un archivo CSV');
      return;
    }

    try {
      setImportingCsv(true);
      const result = await importDonationLotsCsv(csvFile);
      setCsvResult(result);
      toast.success(`Importadas ${result.imported_rows} filas`);
      loadProducts();
      loadLots();
    } catch (error) {
      toast.error(error || 'No se pudo importar el CSV');
    } finally {
      setImportingCsv(false);
    }
  };

  const formatProductLabel = (product) => {
    if (!product) return 'Producto no encontrado';
    const extra = product.nombre_comercial || product.marca;
    return extra ? `${product.nombre_generico} - ${extra}` : product.nombre_generico;
  };

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto animate-fadeIn">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-800">Almacén / Donaciones</h1>
          <p className="text-gray-500">Registro de productos y control de lotes donados.</p>
        </div>
        <div className="flex items-center gap-2 text-vida-primary font-semibold">
          <Package size={20} />
          <span>Donaciones</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="bg-white rounded-2xl shadow-xl border border-gray-100 p-6">
          <h2 className="text-xl font-bold text-gray-800 mb-4">Registro de Producto</h2>
          <form onSubmit={handleCreateProduct} className="space-y-4">
            <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3 text-sm text-blue-800">
              Tipo de producto fijo: <span className="font-bold">INSULINA</span>
            </div>
            <div>
              <label className="text-sm font-bold text-vida-primary ml-1">Insulina (nombre canónico)</label>
              <select
                className="w-full bg-vida-bg text-ui-text rounded-xl px-4 py-3 outline-none transition-all border border-transparent focus:border-vida-main focus:bg-white focus:ring-4 focus:ring-vida-light/20"
                value={productForm.nombre_generico}
                onChange={handleProductChange('nombre_generico')}
                required
              >
                <option value="">Selecciona una insulina</option>
                {INSULIN_OPTIONS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Input
                label="Marca"
                value={productForm.marca}
                onChange={handleProductChange('marca')}
                placeholder="Opcional"
              />
              <Input
                label="Nombre comercial"
                value={productForm.nombre_comercial}
                onChange={handleProductChange('nombre_comercial')}
                placeholder="Opcional"
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Input
                label="Presentación"
                value={productForm.presentacion}
                onChange={handleProductChange('presentacion')}
                placeholder="Ej: Vial 10 mL U-100"
              />
              <Input
                label="Factor de conversión"
                type="number"
                min="1"
                step="0.01"
                value={productForm.factor_conversion}
                onChange={handleProductChange('factor_conversion')}
              />
            </div>
            <Button
              type="submit"
              className="bg-vida-main hover:bg-vida-hover text-white shadow-lg shadow-vida-main/20"
              disabled={savingProduct}
            >
              <PlusCircle size={18} />
              {savingProduct ? 'Guardando...' : 'Registrar producto'}
            </Button>
          </form>

          <div className="mt-6">
            <h3 className="text-lg font-bold text-gray-700 mb-3">Productos registrados</h3>
            <div className="overflow-x-auto border border-gray-100 rounded-xl">
              <table className="w-full">
                <thead className="bg-gray-50 border-b border-gray-100">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Producto</th>
                    <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Factor</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {loadingProducts ? (
                    <tr>
                      <td colSpan="2" className="px-4 py-6 text-center text-gray-400">
                        Cargando productos...
                      </td>
                    </tr>
                  ) : products.length === 0 ? (
                    <tr>
                      <td colSpan="2" className="px-4 py-6 text-center text-gray-400">
                        Sin productos registrados.
                      </td>
                    </tr>
                  ) : (
                    products.map((product) => (
                      <tr key={product.id} className="hover:bg-gray-50/80 transition-colors">
                        <td className="px-4 py-3 text-sm text-gray-800">
                          <div className="font-semibold">{product.nombre_generico}</div>
                          <div className="text-xs text-gray-500">
                            {product.nombre_comercial || product.marca || 'Sin marca'}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-sm text-right text-gray-600">
                          {product.factor_conversion ?? 1}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="bg-white rounded-2xl shadow-xl border border-gray-100 p-6">
          <h2 className="text-xl font-bold text-gray-800 mb-4">Registro de Lote</h2>
          <form onSubmit={handleCreateLot} className="space-y-4">
            <div>
              <label className="text-sm font-bold text-vida-primary ml-1">Producto</label>
              <select
                className="w-full bg-vida-bg text-ui-text rounded-xl px-4 py-3 outline-none transition-all border border-transparent focus:border-vida-main focus:bg-white focus:ring-4 focus:ring-vida-light/20"
                value={lotForm.donation_id}
                onChange={handleLotChange('donation_id')}
                required
              >
                <option value="">Selecciona un producto</option>
                {products.map((product) => (
                  <option key={product.id} value={product.id}>
                    {formatProductLabel(product)}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Input
                label="Cantidad total"
                type="number"
                min="1"
                value={lotForm.cantidad_total}
                onChange={handleLotChange('cantidad_total')}
                required
              />
              <Input
                label="Lote"
                value={lotForm.lote}
                onChange={handleLotChange('lote')}
                placeholder="Opcional"
              />
            </div>
            <Input
              label="Fecha de vencimiento"
              type="date"
              value={lotForm.fecha_venc}
              onChange={handleLotChange('fecha_venc')}
            />
            <Button
              type="submit"
              className="bg-vida-main hover:bg-vida-hover text-white shadow-lg shadow-vida-main/20"
              disabled={savingLot}
            >
              <PlusCircle size={18} />
              {savingLot ? 'Guardando...' : 'Registrar lote'}
            </Button>
          </form>

          <div className="mt-6">
            <h3 className="text-lg font-bold text-gray-700 mb-3">Lotes registrados</h3>
            <div className="overflow-x-auto border border-gray-100 rounded-xl">
              <table className="w-full">
                <thead className="bg-gray-50 border-b border-gray-100">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Producto</th>
                    <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Lote</th>
                    <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Vence</th>
                    <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Stock</th>
                    <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Acción</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {loadingLots ? (
                    <tr>
                      <td colSpan="5" className="px-4 py-6 text-center text-gray-400">
                        Cargando lotes...
                      </td>
                    </tr>
                  ) : lots.length === 0 ? (
                    <tr>
                      <td colSpan="5" className="px-4 py-6 text-center text-gray-400">
                        Sin lotes registrados.
                      </td>
                    </tr>
                  ) : (
                    lots.map((lot) => (
                      <tr key={lot.id} className="hover:bg-gray-50/80 transition-colors">
                        <td className="px-4 py-3 text-sm text-gray-800">
                          <div className="font-semibold">
                            {formatProductLabel(productsById[lot.donation_id])}
                          </div>
                          <div className="text-xs text-gray-500">
                            ID {lot.donation_id}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600">
                          {lot.lote || '-'}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600">
                          {lot.fecha_venc || '-'}
                        </td>
                        <td className="px-4 py-3 text-sm text-right text-gray-600">
                          {lot.cantidad_disponible ?? lot.cantidad_total}
                        </td>
                        <td className="px-4 py-3 text-sm text-right">
                          <div className="flex flex-col sm:flex-row justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => handleCalculate(lot)}
                              disabled={
                                checkingLotId === lot.id ||
                              calculatingLotId === lot.id
                              }
                              className={`inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold transition-all ${
                              calculatedLots[lot.id]
                                ? 'bg-blue-100 text-blue-700 hover:bg-blue-200'
                                : 'bg-vida-main text-white hover:bg-vida-hover shadow-lg shadow-vida-main/20'
                              }`}
                            >
                              <Calculator size={16} />
                            {calculatedLots[lot.id]
                              ? 'Recalcular distribución'
                                : calculatingLotId === lot.id
                                ? 'Calculando...'
                                : 'Calcular distribución'}
                            </button>
                            <button
                              type="button"
                              onClick={() => handleOpenLotManagement(lot)}
                              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold transition-all bg-gray-100 text-gray-700 hover:bg-gray-200"
                            >
                              <Settings size={16} />
                              Gestionar
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </div>

      <section className="mt-8 bg-white rounded-2xl shadow-xl border border-gray-100 p-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-4">
          <div>
            <h2 className="text-xl font-bold text-gray-800">Carga masiva por CSV</h2>
            <p className="text-sm text-gray-500">
              Formato: tipo,nombre_generico,marca,nombre_comercial,presentacion,factor_conversion,lote,fecha_venc,cantidad_total
            </p>
          </div>
          <Button
            type="button"
            className="bg-vida-main hover:bg-vida-hover text-white shadow-lg shadow-vida-main/20"
            onClick={handleImportCsv}
            disabled={importingCsv || !csvFile}
          >
            <Upload size={18} />
            {importingCsv ? 'Importando...' : 'Importar CSV'}
          </Button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-end">
          <div>
            <label className="text-sm font-bold text-vida-primary ml-1">Archivo CSV</label>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={handleCsvFileChange}
              className="mt-2 block w-full text-sm text-gray-600 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-vida-light/40 file:text-vida-primary hover:file:bg-vida-light/60"
            />
            {csvFile && (
              <p className="mt-2 text-xs text-gray-500">Seleccionado: {csvFile.name}</p>
            )}
          </div>
          <div className="text-xs text-gray-500">
            <p>Campos obligatorios: tipo, nombre_generico, factor_conversion, cantidad_total.</p>
            <p>fecha_venc debe ser YYYY-MM-DD. El tipo permitido es solo INSULINA.</p>
          </div>
        </div>

        {csvResult && (
          <div className="mt-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
              <div className="bg-vida-bg rounded-xl p-4">
                <p className="text-xs text-gray-500">Filas totales</p>
                <p className="text-lg font-bold text-gray-800">{csvResult.total_rows}</p>
              </div>
              <div className="bg-vida-bg rounded-xl p-4">
                <p className="text-xs text-gray-500">Importadas</p>
                <p className="text-lg font-bold text-gray-800">{csvResult.imported_rows}</p>
              </div>
              <div className="bg-vida-bg rounded-xl p-4">
                <p className="text-xs text-gray-500">Con error</p>
                <p className="text-lg font-bold text-gray-800">{csvResult.error_rows}</p>
              </div>
            </div>

            <div className="overflow-x-auto border border-gray-100 rounded-xl">
              <table className="w-full">
                <thead className="bg-gray-50 border-b border-gray-100">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Fila</th>
                    <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Estado</th>
                    <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Mensaje</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {csvResult.results?.length ? (
                    csvResult.results.map((item) => (
                      <tr key={`${item.row_number}-${item.status}`}>
                        <td className="px-4 py-3 text-sm text-gray-700">{item.row_number}</td>
                        <td className="px-4 py-3 text-sm">
                          <span
                            className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-semibold ${
                              item.status === 'IMPORTED'
                                ? 'bg-green-100 text-green-700'
                                : 'bg-red-100 text-red-700'
                            }`}
                          >
                            {item.status === 'IMPORTED' ? 'Importado' : 'Error'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600">{item.message}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan="3" className="px-4 py-6 text-center text-gray-400">
                        No hay resultados para mostrar.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      {managedLot && (
        <section className="mt-8 bg-white rounded-2xl shadow-xl border border-gray-100 p-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-4">
            <div>
              <h2 className="text-xl font-bold text-gray-800">Gestión operativa del lote #{managedLot.id}</h2>
              <p className="text-sm text-gray-500">
                Ajusta cantidades, consolida, registra entrega y sube constancias.
              </p>
            </div>
            <Button
              type="button"
              className="bg-green-600 hover:bg-green-700 text-white"
              disabled={
                loadingManagedLot ||
                consolidatingLotId === managedLot.id ||
                !(managedLot.allocations || []).length ||
                (managedLot.allocations || []).some((item) => item.estado === 'CONSOLIDADO')
              }
              onClick={handleConsolidateLot}
            >
              <CheckCircle2 size={18} />
              {consolidatingLotId === managedLot.id ? 'Consolidando...' : 'Consolidar lote'}
            </Button>
          </div>

          {loadingManagedLot ? (
            <p className="text-sm text-gray-500">Cargando detalle del lote...</p>
          ) : (
            <>
              <div className="overflow-x-auto border border-gray-100 rounded-xl mb-6">
                <table className="w-full">
                  <thead className="bg-gray-50 border-b border-gray-100">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Paciente</th>
                      <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Sugerido</th>
                      <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Ajustado</th>
                      <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Estado</th>
                      <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Acción</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {(managedLot.allocations || []).length ? (
                      managedLot.allocations.map((allocation) => {
                        const isConsolidated = allocation.estado === 'CONSOLIDADO';
                        return (
                          <tr key={`managed-allocation-${allocation.id}`}>
                            <td className="px-4 py-3 text-sm text-gray-800">
                              {allocation.patient
                                ? `${allocation.patient.nombres} ${allocation.patient.ap_paterno}`
                                : `Paciente #${allocation.patient_id}`}
                            </td>
                            <td className="px-4 py-3 text-sm text-right text-gray-600">{allocation.cantidad_sugerida}</td>
                            <td className="px-4 py-3 text-sm text-right">
                              <input
                                type="number"
                                min="0"
                                className="w-24 border rounded-md px-2 py-1 text-right text-sm"
                                value={allocationDrafts[allocation.id] ?? ''}
                                onChange={(event) => handleAllocationDraftChange(allocation.id, event.target.value)}
                                disabled={isConsolidated}
                              />
                            </td>
                            <td className="px-4 py-3 text-sm text-right">
                              <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-semibold ${
                                isConsolidated ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'
                              }`}>
                                {allocation.estado}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-sm text-right">
                              <button
                                type="button"
                                onClick={() => handleSaveAllocation(allocation)}
                                disabled={isConsolidated || savingAllocationId === allocation.id}
                                className={`inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold transition-all ${
                                  isConsolidated
                                    ? 'bg-gray-200 text-gray-500 cursor-not-allowed'
                                    : 'bg-blue-600 text-white hover:bg-blue-700'
                                }`}
                              >
                                <Save size={14} />
                                {savingAllocationId === allocation.id ? 'Guardando...' : 'Guardar'}
                              </button>
                            </td>
                          </tr>
                        );
                      })
                    ) : (
                      <tr>
                        <td colSpan="5" className="px-4 py-6 text-center text-gray-400">
                          Este lote aún no tiene asignaciones.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <h3 className="text-lg font-bold text-gray-700 mb-3">Entregas por asignación</h3>
              <div className="space-y-3 mb-6">
                {(managedLot.allocations || []).length ? (
                  managedLot.allocations.map((allocation) => {
                    const delivery = deliveryByAllocation[allocation.id];
                    const isConsolidated = allocation.estado === 'CONSOLIDADO';
                    return (
                      <div key={`delivery-block-${allocation.id}`} className="border border-gray-100 rounded-xl p-4">
                        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
                          <div>
                            <p className="font-semibold text-gray-800">
                              {allocation.patient
                                ? `${allocation.patient.nombres} ${allocation.patient.ap_paterno}`
                                : `Paciente #${allocation.patient_id}`}
                            </p>
                            <p className="text-xs text-gray-500">
                              Asignado: {allocation.cantidad_ajustada ?? allocation.cantidad_sugerida} | Estado: {allocation.estado}
                            </p>
                            {delivery && (
                              <p className="text-xs text-green-700 mt-1">
                                Entrega #{delivery.id} - {delivery.estado} - {delivery.fecha_entrega}
                              </p>
                            )}
                          </div>
                          {!delivery ? (
                            <div className="flex flex-wrap gap-2">
                              <input
                                type="date"
                                className="border rounded-md px-2 py-1 text-sm"
                                value={deliveryDrafts[allocation.id]?.fecha_entrega || ''}
                                onChange={(event) =>
                                  handleDeliveryDraftChange(allocation.id, 'fecha_entrega', event.target.value)
                                }
                                disabled={!isConsolidated}
                              />
                              <input
                                type="number"
                                min="1"
                                className="w-24 border rounded-md px-2 py-1 text-sm"
                                value={deliveryDrafts[allocation.id]?.cantidad_entregada || ''}
                                onChange={(event) =>
                                  handleDeliveryDraftChange(allocation.id, 'cantidad_entregada', event.target.value)
                                }
                                disabled={!isConsolidated}
                              />
                              <button
                                type="button"
                                onClick={() => handleCreateDelivery(allocation)}
                                disabled={!isConsolidated || creatingDeliveryAllocationId === allocation.id}
                                className={`inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold ${
                                  !isConsolidated
                                    ? 'bg-gray-200 text-gray-500 cursor-not-allowed'
                                    : 'bg-indigo-600 text-white hover:bg-indigo-700'
                                }`}
                              >
                                <Truck size={14} />
                                {creatingDeliveryAllocationId === allocation.id ? 'Registrando...' : 'Registrar entrega'}
                              </button>
                            </div>
                          ) : (
                            <div className="flex flex-wrap gap-2">
                              <button
                                type="button"
                                onClick={() => handleDownloadReceipt(delivery.id)}
                                disabled={downloadingDeliveryId === delivery.id}
                                className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold bg-gray-100 text-gray-700 hover:bg-gray-200"
                              >
                                <FileDown size={14} />
                                {downloadingDeliveryId === delivery.id ? 'Descargando...' : 'Boleta PDF'}
                              </button>
                              <input
                                type="file"
                                accept="application/pdf"
                                onChange={(event) =>
                                  handleReceiptFileChange(delivery.id, event.target.files?.[0] || null)
                                }
                                className="text-xs"
                              />
                              <button
                                type="button"
                                onClick={() => handleUploadSignedReceipt(allocation.id, delivery)}
                                disabled={uploadingReceiptDeliveryId === delivery.id}
                                className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold bg-amber-600 text-white hover:bg-amber-700"
                              >
                                <FileUp size={14} />
                                {uploadingReceiptDeliveryId === delivery.id ? 'Subiendo...' : 'Subir constancia'}
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <p className="text-sm text-gray-500">Sin asignaciones para gestionar entregas.</p>
                )}
              </div>

              <h3 className="text-lg font-bold text-gray-700 mb-3">Movimientos de stock del lote</h3>
              <div className="overflow-x-auto border border-gray-100 rounded-xl">
                <table className="w-full">
                  <thead className="bg-gray-50 border-b border-gray-100">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Fecha</th>
                      <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Tipo</th>
                      <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Cantidad</th>
                      <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Referencia</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {lotMovements.length ? (
                      lotMovements.map((movement) => (
                        <tr key={`movement-${movement.id}`}>
                          <td className="px-4 py-3 text-sm text-gray-700">
                            {new Date(movement.created_at).toLocaleString()}
                          </td>
                          <td className="px-4 py-3 text-sm">
                            <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-semibold ${
                              movement.tipo === 'ENTRADA'
                                ? 'bg-blue-100 text-blue-700'
                                : 'bg-orange-100 text-orange-700'
                            }`}>
                              {movement.tipo}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-sm text-right text-gray-700">{movement.cantidad}</td>
                          <td className="px-4 py-3 text-sm text-gray-600">{movement.referencia || '-'}</td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan="4" className="px-4 py-6 text-center text-gray-400">
                          Sin movimientos registrados.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      )}

      {calculationResult && (
        <section className="mt-8 bg-white rounded-2xl shadow-xl border border-gray-100 p-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-4">
            <h2 className="text-xl font-bold text-gray-800">Resultado de distribución</h2>
            <span className="text-sm text-gray-500">
              Lote #{calculationResult.lot_id} · Horizonte máximo: 3 meses
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
            <div className="bg-vida-bg rounded-xl p-4">
              <p className="text-xs text-gray-500">Pacientes compatibles</p>
              <p className="text-lg font-bold text-gray-800">{calculationResult.total_pacientes_compatibles}</p>
            </div>
            <div className="bg-vida-bg rounded-xl p-4">
              <p className="text-xs text-gray-500">Stock disponible</p>
              <p className="text-lg font-bold text-gray-800">{calculationResult.total_stock_disponible}</p>
            </div>
            <div className="bg-vida-bg rounded-xl p-4">
              <p className="text-xs text-gray-500">Requerido teórico</p>
              <p className="text-lg font-bold text-gray-800">{calculationResult.total_requerido_teorico}</p>
            </div>
            <div className="bg-vida-bg rounded-xl p-4">
              <p className="text-xs text-gray-500">Sobrante stock</p>
              <p className="text-lg font-bold text-gray-800">{calculationResult.sobrante_stock}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div>
              <h3 className="text-lg font-bold text-gray-700 mb-3">Asignaciones</h3>
              <div className="overflow-x-auto border border-gray-100 rounded-xl">
                <table className="w-full">
                  <thead className="bg-gray-50 border-b border-gray-100">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Paciente</th>
                      <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Sugerido</th>
                      <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase tracking-wider">Asignado</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {calculationResult.allocations?.length ? (
                      calculationResult.allocations.map((allocation) => (
                        <tr key={allocation.id}>
                          <td className="px-4 py-3 text-sm text-gray-800">
                            {allocation.patient
                              ? `${allocation.patient.nombres} ${allocation.patient.ap_paterno}`
                              : `Paciente #${allocation.patient_id}`}
                          </td>
                          <td className="px-4 py-3 text-sm text-right text-gray-600">
                            {allocation.cantidad_sugerida}
                          </td>
                          <td className="px-4 py-3 text-sm text-right text-gray-600">
                            {allocation.cantidad_ajustada ?? allocation.cantidad_sugerida}
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan="3" className="px-4 py-6 text-center text-gray-400">
                          Sin asignaciones generadas.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div>
              <h3 className="text-lg font-bold text-gray-700 mb-3">Excluidos</h3>
              <div className="overflow-x-auto border border-gray-100 rounded-xl">
                <table className="w-full">
                  <thead className="bg-gray-50 border-b border-gray-100">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Paciente</th>
                      <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Motivo</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {calculationResult.excluded_patients?.length ? (
                      calculationResult.excluded_patients.map((item) => (
                        <tr key={item.patient_id}>
                          <td className="px-4 py-3 text-sm text-gray-800">{item.nombre_completo}</td>
                          <td className="px-4 py-3 text-sm text-gray-600">{item.motivo}</td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan="2" className="px-4 py-6 text-center text-gray-400">
                          No hay pacientes excluidos.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
