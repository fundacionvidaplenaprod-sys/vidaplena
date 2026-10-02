import { AlertTriangle } from 'lucide-react';
import { Modal } from './Modal';
import { Button } from './Button';

// Reemplaza a window.confirm() para acciones importantes. El diálogo nativo
// depende de que el navegador/dispositivo esté dispuesto a mostrarlo —hay
// navegadores móviles, webviews embebidos y extensiones que lo suprimen en
// silencio—, y cuando eso pasa el botón que lo dispara parece no hacer nada:
// sin error, sin aviso. Se descubrió así el bug de "Aprobar y Crear Usuario"
// en PatientDetailsPage, que dejaba al Super Admin sin ninguna señal de que
// la activación nunca se ejecutó.
export function ConfirmModal({
    isOpen,
    title = 'Confirmar acción',
    message,
    confirmLabel = 'Confirmar',
    cancelLabel = 'Cancelar',
    danger = false,
    processing = false,
    onConfirm,
    onCancel,
    // Campo de texto opcional, para reemplazar también a window.prompt() en el
    // mismo modal en vez de encadenar dos diálogos nativos distintos.
    inputLabel,
    inputValue,
    onInputChange,
    inputPlaceholder,
}) {
    const hasInput = inputLabel !== undefined;
    return (
        <Modal isOpen={isOpen} onClose={onCancel} title={title}>
            <div className="flex gap-3 mb-6">
                <AlertTriangle
                    size={22}
                    className={`shrink-0 mt-0.5 ${danger ? 'text-red-500' : 'text-amber-500'}`}
                />
                <p className="text-sm text-gray-600 whitespace-pre-line">{message}</p>
            </div>
            {hasInput && (
                <div className="mb-6">
                    <label className="block text-sm font-bold text-gray-700 mb-1">{inputLabel}</label>
                    <input
                        type="text"
                        value={inputValue}
                        onChange={(e) => onInputChange(e.target.value)}
                        placeholder={inputPlaceholder}
                        className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-vida-primary outline-none"
                    />
                </div>
            )}
            <div className="flex gap-3">
                <Button
                    type="button"
                    variant="secondary"
                    className="flex-1 bg-gray-100 text-gray-700"
                    onClick={onCancel}
                    disabled={processing}
                >
                    {cancelLabel}
                </Button>
                <Button
                    type="button"
                    className={`flex-1 text-white ${danger ? 'bg-red-600 hover:bg-red-700' : 'bg-vida-main hover:bg-vida-hover'}`}
                    onClick={onConfirm}
                    disabled={processing}
                >
                    {processing ? 'Procesando...' : confirmLabel}
                </Button>
            </div>
        </Modal>
    );
}
