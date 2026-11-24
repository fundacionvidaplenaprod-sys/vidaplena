import { useEffect, useState } from 'react';
import { FileCheck2, Upload } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { createDonationIntake, listDonationIntakes, previewDonationIntake } from '../../api/donations';
import { fmt } from '../../utils/insulinDistribution';

// Ingreso al almacén con el mismo Excel de la donación que recibe el reporte de distribución. Primero se revisa
// (vista previa con los errores por fila) y luego se ingresa todo o nada.
export default function WarehouseIntakePanel({ onIngresado }) {
    const [file, setFile] = useState(null);
    const [preview, setPreview] = useState(null);
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [intakes, setIntakes] = useState([]);

    const loadIntakes = () =>
        listDonationIntakes()
            .then(setIntakes)
            .catch((error) => toast.error(typeof error === 'string' ? error : 'No se pudieron cargar los ingresos'));

    useEffect(() => {
        loadIntakes();
    }, []);

    const handlePreview = async () => {
        if (!file) return;
        try {
            setLoading(true);
            setPreview(await previewDonationIntake(file));
        } catch (error) {
            setPreview(null);
            toast.error(typeof error === 'string' ? error : 'No se pudo leer el Excel');
        } finally {
            setLoading(false);
        }
    };

    const handleIngresar = async () => {
        try {
            setSaving(true);
            const result = await createDonationIntake(file);
            toast.success(`Ingresado: ${result.lotes_creados} lotes, ${result.envases} envases`);
            setPreview(null);
            setFile(null);
            loadIntakes();
            onIngresado?.();
        } catch (error) {
            toast.error(typeof error === 'string' ? error : 'No se pudo ingresar la donación');
        } finally {
            setSaving(false);
        }
    };

    return (
        <div>
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 mb-6">
                <div className="flex flex-col sm:flex-row sm:items-end gap-4">
                    <div className="flex-1 min-w-0">
                        <label htmlFor="excel-donacion" className="text-sm font-bold text-vida-primary ml-1">
                            Excel de la donación (.xlsx)
                        </label>
                        <input
                            id="excel-donacion"
                            type="file"
                            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            onChange={(e) => {
                                setFile(e.target.files?.[0] || null);
                                setPreview(null);
                            }}
                            className="mt-2 block w-full text-sm text-gray-600 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-vida-light/40 file:text-vida-primary hover:file:bg-vida-light/60"
                        />
                    </div>
                    <button
                        type="button"
                        onClick={handlePreview}
                        disabled={!file || loading}
                        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-vida-main text-white hover:bg-vida-hover disabled:opacity-50"
                    >
                        <Upload size={18} /> {loading ? 'Revisando...' : 'Revisar'}
                    </button>
                </div>
                <p className="mt-3 text-xs text-gray-500">
                    Columnas: CANTIDAD, PRODUCTO (con la marca, ej. «Lantus SoloStar 3 ml»), TIPO DE INSULINA, PRESENTACIÓN (ml),
                    CONCENTRACIÓN (U100, U200, U300), FECHA VENCIMIENTO y NRO LOTE. En el almacén el lote y el vencimiento son
                    obligatorios y no se ingresa nada vencido. Las UI por envase son ml × concentración.
                </p>
            </div>

            {preview && (
                <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 mb-6">
                    <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-4">
                        <div>
                            <h3 className="text-lg font-bold text-gray-800">{preview.archivo}</h3>
                            <p className="text-sm text-gray-500">
                                {preview.filas_leidas} filas · {preview.envases} envases · {fmt(preview.ui_total)} UI
                            </p>
                        </div>
                        <button
                            type="button"
                            onClick={handleIngresar}
                            disabled={!preview.puede_ingresar || saving}
                            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
                        >
                            <FileCheck2 size={18} /> {saving ? 'Ingresando...' : 'Ingresar al almacén'}
                        </button>
                    </div>
                    {preview.ingreso_previo && (
                        <div role="alert" className="mb-4 border border-red-200 bg-red-50 rounded-xl p-3 text-sm text-red-800">
                            Este archivo ya se ingresó el {new Date(preview.ingreso_previo.created_at).toLocaleString('es-BO')} (ingreso #
                            {preview.ingreso_previo.id}). No se puede ingresar dos veces.
                        </div>
                    )}
                    {preview.errores.length > 0 && (
                        <div role="alert" className="mb-4 border border-red-200 bg-red-50 rounded-xl p-3 text-sm text-red-800">
                            <b>{preview.errores.length} fila(s) con error: no se ingresará nada hasta corregir el Excel.</b>
                            <ul className="list-disc pl-5 mt-1">
                                {preview.errores.map((e) => (
                                    <li key={`${e.fila}-${e.mensaje}`}>
                                        Fila {e.fila}
                                        {e.producto ? ` (${e.producto})` : ''}: {e.mensaje}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                    <div className="overflow-x-auto border border-gray-100 rounded-xl">
                        <table className="w-full">
                            <thead className="bg-gray-50 border-b border-gray-100">
                                <tr>
                                    {['Fila', 'Producto', 'Insulina', 'Cantidad', 'Presentación', 'UI/envase', 'UI total', 'Lote', 'Vence'].map((h) => (
                                        <th key={h} className="px-3 py-2 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">
                                            {h}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                {preview.filas.map((f) => (
                                    <tr key={f.fila}>
                                        <td className="px-3 py-2 text-sm text-gray-500">{f.fila}</td>
                                        <td className="px-3 py-2 text-sm text-gray-800">{f.producto}</td>
                                        <td className="px-3 py-2 text-sm text-gray-700">{f.insulina}</td>
                                        <td className="px-3 py-2 text-sm text-gray-700">{f.cantidad}</td>
                                        <td className="px-3 py-2 text-sm text-gray-700">
                                            {f.presentacion_ml} ml · U{f.concentracion_ui_ml}
                                        </td>
                                        <td className="px-3 py-2 text-sm text-gray-700">{fmt(f.ui_por_envase)}</td>
                                        <td className="px-3 py-2 text-sm text-gray-700">{fmt(f.ui_total)}</td>
                                        <td className="px-3 py-2 text-sm text-gray-700">{f.lote || <span className="text-red-600">falta</span>}</td>
                                        <td className="px-3 py-2 text-sm text-gray-700">{f.fecha_venc || <span className="text-red-600">falta</span>}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            <h3 className="text-lg font-bold text-gray-700 mb-3">Ingresos registrados</h3>
            <div className="overflow-x-auto border border-gray-100 rounded-xl">
                <table className="w-full">
                    <thead className="bg-gray-50 border-b border-gray-100">
                        <tr>
                            {['#', 'Fecha', 'Archivo', 'Filas', 'Envases', 'UI', 'Ingresó'].map((h) => (
                                <th key={h} className="px-4 py-2 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">
                                    {h}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                        {intakes.length === 0 && (
                            <tr>
                                <td colSpan="7" className="px-4 py-6 text-center text-gray-400">
                                    Todavía no se ingresó ninguna donación.
                                </td>
                            </tr>
                        )}
                        {intakes.map((i) => (
                            <tr key={i.id}>
                                <td className="px-4 py-2 text-sm text-gray-500">{i.id}</td>
                                <td className="px-4 py-2 text-sm text-gray-700">{new Date(i.created_at).toLocaleString('es-BO')}</td>
                                <td className="px-4 py-2 text-sm text-gray-800">{i.archivo}</td>
                                <td className="px-4 py-2 text-sm text-gray-700">{i.filas}</td>
                                <td className="px-4 py-2 text-sm text-gray-700">{i.envases}</td>
                                <td className="px-4 py-2 text-sm text-gray-700">{fmt(i.ui_total)}</td>
                                <td className="px-4 py-2 text-xs text-gray-500">{i.autor || '-'}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
