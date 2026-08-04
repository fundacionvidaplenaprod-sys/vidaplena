import { useEffect, useState } from 'react';
import { toast } from 'react-hot-toast';
import { ScanLine, UploadCloud, CheckCircle2, QrCode } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { previewContributionOcr, createMyContribution } from '../../api/contributions';
import { getSiteAssets } from '../../api/siteAssets';

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function currentPeriod() {
  return new Date().toISOString().slice(0, 7);
}

export function VoluntaryContributionModal({
  isOpen,
  onClose,
  hasCommittedAmount,
  committedAmount,
  contributions,
  onSuccess,
}) {
  const [comprobante, setComprobante] = useState(null);
  const [ocrLoading, setOcrLoading] = useState(false);
  const [ocrRead, setOcrRead] = useState(false);
  const [monto, setMonto] = useState(hasCommittedAmount ? String(committedAmount) : '');
  const [periodo, setPeriodo] = useState(currentPeriod());
  const [fechaPago, setFechaPago] = useState(todayIso());
  const [submitting, setSubmitting] = useState(false);
  const [qrCompromisos, setQrCompromisos] = useState(null);

  useEffect(() => {
    getSiteAssets()
      .then((assets) => setQrCompromisos(assets.find((a) => a.key === 'qr_compromisos')?.url || null))
      .catch(() => setQrCompromisos(null));
  }, []);

  const isDuplicatePeriod = (contributions || []).some(
    (item) => item.periodo === periodo && item.estado === 'ACEPTADO'
  );

  const reset = () => {
    setComprobante(null);
    setOcrLoading(false);
    setOcrRead(false);
    setMonto(hasCommittedAmount ? String(committedAmount) : '');
    setPeriodo(currentPeriod());
    setFechaPago(todayIso());
    setSubmitting(false);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const handleFileChange = (file) => {
    if (file && file.size > 2 * 1024 * 1024) {
      toast.error('⚠️ El comprobante supera los 2 MB. Por favor, sube una imagen o PDF más ligero.');
      return;
    }
    setComprobante(file);
    setOcrRead(false);
  };

  const handleReadOcr = async () => {
    if (!comprobante) {
      toast.error('Selecciona primero el comprobante.');
      return;
    }
    try {
      setOcrLoading(true);
      const result = await previewContributionOcr(comprobante);
      if (!hasCommittedAmount) {
        if (result.monto) {
          setMonto(String(result.monto));
        } else {
          toast.error('No se detectó el monto automáticamente. Ingrésalo manualmente.');
        }
      }
      if (result.fecha) {
        setFechaPago(result.fecha);
      }
      setOcrRead(true);
      if (result.monto) {
        toast.success(`Monto detectado: Bs. ${result.monto}. Verifica antes de enviar.`);
      }
    } catch (error) {
      toast.error('No se pudo leer el comprobante. Ingresa el monto manualmente.');
      setOcrRead(true);
    } finally {
      setOcrLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (!comprobante) {
      toast.error('Adjunta el comprobante de tu aporte.');
      return;
    }
    if (isDuplicatePeriod) {
      toast.error(`El aporte del periodo ${periodo} ya fue validado y no puede reemplazarse.`);
      return;
    }
    const montoNum = Number(monto);
    if (!Number.isFinite(montoNum) || montoNum <= 0) {
      toast.error('Ingresa un monto válido.');
      return;
    }
    if (hasCommittedAmount && Math.abs(montoNum - committedAmount) > 0.001) {
      toast.error(`El monto debe coincidir con tu compromiso: Bs. ${committedAmount.toFixed(2)}.`);
      return;
    }

    try {
      setSubmitting(true);
      await createMyContribution({ monto: montoNum, periodo, fechaPago, comprobante });
      toast.success('Aporte registrado. Quedó en estado DECLARADO.');
      reset();
      onSuccess();
    } catch (error) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'No se pudo registrar el aporte.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Registrar Aporte Voluntario">
      <div className="space-y-4">
        {qrCompromisos && (
          <div className="flex flex-col items-center gap-2 bg-vida-bg/50 rounded-xl p-3">
            <p className="text-xs text-gray-600 flex items-center gap-1">
              <QrCode size={14} /> Escanea para realizar tu aporte
            </p>
            <img src={qrCompromisos} alt="QR Aporte Voluntario" className="w-32 h-32 border p-1 bg-white rounded-lg" />
          </div>
        )}

        <div>
          <label className="text-sm font-bold text-vida-primary ml-1 block mb-1">Comprobante</label>
          <label
            htmlFor="voluntary-contribution-file"
            className="w-full border-2 border-dashed border-gray-300 rounded-xl p-4 flex items-center gap-3 cursor-pointer hover:border-vida-main hover:bg-vida-bg/50 transition-colors"
          >
            <UploadCloud size={22} className="text-vida-main flex-shrink-0" />
            <span className="text-sm text-gray-600 truncate">
              {comprobante ? comprobante.name : 'Subir comprobante (imagen o PDF)'}
            </span>
          </label>
          <input
            id="voluntary-contribution-file"
            type="file"
            accept=".pdf,.jpg,.jpeg,.png"
            className="hidden"
            onChange={(e) => handleFileChange(e.target.files?.[0] || null)}
          />
        </div>

        <Button
          type="button"
          variant="outline"
          onClick={handleReadOcr}
          disabled={!comprobante || ocrLoading}
          className="w-auto px-4 py-2 text-sm inline-flex items-center gap-2"
        >
          {ocrRead ? <CheckCircle2 size={16} /> : <ScanLine size={16} />}
          {ocrLoading ? 'Leyendo comprobante...' : ocrRead ? 'Comprobante leído' : 'Leer comprobante (OCR)'}
        </Button>

        <div className="grid grid-cols-2 gap-3">
          <Input
            type="month"
            label="Periodo"
            value={periodo}
            onChange={(e) => setPeriodo(e.target.value)}
          />
          <Input
            type="date"
            label="Fecha de pago"
            value={fechaPago}
            onChange={(e) => setFechaPago(e.target.value)}
          />
        </div>

        <div>
          <Input
            type="number"
            min="1"
            step="0.01"
            label="Monto (Bs)"
            value={monto}
            onChange={(e) => setMonto(e.target.value)}
            readOnly={hasCommittedAmount}
            placeholder="Se completa al leer el comprobante, o ingrésalo manualmente"
          />
          {hasCommittedAmount ? (
            <p className="text-xs text-gray-500 mt-1">Monto fijo según compromiso firmado.</p>
          ) : (
            <p className="text-xs text-gray-500 mt-1">
              Puedes corregir el monto si el comprobante no se leyó correctamente.
            </p>
          )}
        </div>

        {isDuplicatePeriod && (
          <p className="text-xs text-amber-700">
            El periodo {periodo} ya fue validado. Para corregir, contacta a administración.
          </p>
        )}

        <div className="flex gap-3 pt-2">
          <Button
            type="button"
            variant="secondary"
            className="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-700"
            onClick={handleClose}
          >
            Cancelar
          </Button>
          <Button
            type="button"
            className="flex-1"
            onClick={handleSubmit}
            disabled={submitting || isDuplicatePeriod}
          >
            {submitting ? 'Enviando...' : 'Registrar aporte'}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
