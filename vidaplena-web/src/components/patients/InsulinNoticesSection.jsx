import { useEffect, useState } from 'react';
import { AlertTriangle, Bell, CalendarDays, Camera, CheckCircle, Clock, FileText, Upload } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { listMyInsulinNotices, markInsulinNoticeSeen, uploadInsulinNoticePhoto } from '../../api/donations';
import { displayInsulinName } from '../../constants/insulins';
import { compressImage } from '../../utils/compressImage';
import { COORDINAR_ENTREGA, esPdf, fmt, ventanaEntregaTexto } from '../../utils/insulinDistribution';

const fecha = (iso) => (iso ? new Date(iso).toLocaleDateString('es-BO') : '');
const fechaVence = (iso) => (iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('es-BO') : '');

// «, lote LAN-2411» o «, lotes LAN-2411, LAN-2412» para el resumen de los repartos anteriores.
const lotesResumen = (productos) => {
    const lotes = [...new Set(productos.map((p) => p.lote).filter(Boolean))];
    return lotes.length ? `, lote${lotes.length > 1 ? 's' : ''} ${lotes.join(', ')}` : '';
};

// Lo que el beneficiario envía para cada entrega: una foto de cada una, que la Fundación revisa. Puede cambiarla
// mientras no esté aprobada; si se la observan, ve el motivo y sube otra.
const FOTOS = [
    {
        tipo: 'envases',
        titulo: 'Sus insulinas ya usadas',
        etiqueta: 'Foto de sus insulinas ya usadas',
        ayuda: 'Una foto de los envases vacíos (frascos o plumas) de su entrega anterior.',
        accept: 'image/*',
    },
    {
        tipo: 'hba1c',
        titulo: 'Hemoglobina glucosilada (HbA1c)',
        etiqueta: 'Foto de su hemoglobina glucosilada',
        ayuda: 'Una foto (o el PDF) de su último resultado de laboratorio. Se pide cada 3 meses y es gratuito en el SUS.',
        accept: 'image/*,application/pdf',
    },
];

// Cómo va la revisión de la foto que envió.
function EstadoFoto({ subida }) {
    if (subida.estado === 'APROBADA') {
        return (
            <p className="mt-1 text-xs font-semibold text-green-700 flex items-center gap-1">
                <CheckCircle size={14} /> Aprobada por la Fundación el {fecha(subida.revisada_at)}
            </p>
        );
    }
    if (subida.estado === 'OBSERVADA') {
        return (
            <p role="alert" className="mt-2 text-xs text-red-800 bg-red-50 border border-red-200 rounded-lg px-3 py-2 flex gap-2">
                <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                <span>
                    <b>La Fundación la observó:</b> {subida.observacion} Por favor, suba otra.
                </span>
            </p>
        );
    }
    return (
        <p className="mt-1 text-xs text-amber-700 flex items-center gap-1">
            <Clock size={14} /> Enviada el {fecha(subida.subida_at)} · en revisión
        </p>
    );
}

function FotoAviso({ aviso, foto, onSubida }) {
    const [subiendo, setSubiendo] = useState(false);
    const [sinMiniatura, setSinMiniatura] = useState(null); // URL que no se pudo mostrar como imagen
    const subida = aviso[`foto_${foto.tipo}`];
    const url = subida?.url;
    const aprobada = subida?.estado === 'APROBADA';
    const inputId = `foto-${foto.tipo}-${aviso.id}`;
    const comoIcono = esPdf(url) || sinMiniatura === url;

    const elegir = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = ''; // para poder volver a elegir el mismo archivo
        if (!file) return;
        try {
            setSubiendo(true);
            onSubida(await uploadInsulinNoticePhoto(aviso.id, foto.tipo, await compressImage(file)));
            toast.success('Foto enviada');
        } catch (error) {
            toast.error(typeof error === 'string' ? error : 'No se pudo subir la foto');
        } finally {
            setSubiendo(false);
        }
    };

    return (
        <div className="border border-gray-100 rounded-xl p-4 flex items-start gap-4">
            {url ? (
                <a href={url} target="_blank" rel="noopener noreferrer" className="shrink-0" aria-label={`Ver ${foto.etiqueta.toLowerCase()}`}>
                    {comoIcono ? (
                        <span className="h-16 w-16 rounded-lg bg-red-50 text-red-700 flex items-center justify-center">
                            <FileText size={26} />
                        </span>
                    ) : (
                        <img
                            src={url}
                            alt=""
                            onError={() => setSinMiniatura(url)}
                            className="h-16 w-16 rounded-lg object-cover border border-gray-200"
                        />
                    )}
                </a>
            ) : (
                <span className="h-16 w-16 shrink-0 rounded-lg bg-gray-50 text-gray-400 flex items-center justify-center">
                    <Camera size={26} />
                </span>
            )}
            <div className="min-w-0 flex-1">
                <h4 className="font-bold text-gray-800">{foto.titulo}</h4>
                <p className="mt-0.5 text-xs text-gray-500">{foto.ayuda}</p>
                {subida && <EstadoFoto subida={subida} />}
                {!aprobada && (
                    <>
                        <input
                            id={inputId}
                            type="file"
                            accept={foto.accept}
                            aria-label={foto.etiqueta}
                            className="sr-only"
                            onChange={elegir}
                            disabled={subiendo}
                        />
                        <label
                            htmlFor={inputId}
                            className={`mt-2 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold cursor-pointer ${
                                subida?.estado === 'PENDIENTE'
                                    ? 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                                    : 'bg-vida-main text-white hover:bg-vida-hover'
                            } ${subiendo ? 'opacity-50 pointer-events-none' : ''}`}
                        >
                            <Upload size={16} />{' '}
                            {subiendo ? 'Subiendo...' : { PENDIENTE: 'Cambiar', OBSERVADA: 'Subir otra foto' }[subida?.estado] || 'Subir foto'}
                        </label>
                    </>
                )}
            </div>
        </div>
    );
}

function Tratamiento({ t }) {
    return (
        <div className="border border-gray-100 rounded-xl p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h4 className="font-bold text-gray-800">{displayInsulinName(t.insulina)}</h4>
                {t.envases > 0 && (
                    <p className="text-sm text-gray-700">
                        <b>{t.envases}</b> envase(s) · {fmt(t.ui)} UI · cubre ≈ <b>{t.dias_cubiertos}</b> días
                    </p>
                )}
            </div>
            {t.envases > 0 ? (
                <>
                    {/* Una línea por producto y lote; en el teléfono los datos pasan a la línea siguiente. */}
                    <ul className="mt-2 divide-y divide-gray-100 text-sm text-gray-700">
                        {t.productos.map((p) => (
                            <li key={`${p.producto}-${p.lote}`} className="py-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
                                <span className="text-gray-800">
                                    <b>{p.envases}</b> × {p.producto}
                                </span>
                                <span>
                                    N.º de lote:{' '}
                                    <b className="font-mono text-gray-800 whitespace-nowrap">{p.lote || 'sin dato'}</b>
                                </span>
                                {p.fecha_venc && <span className="whitespace-nowrap">Vence: {fechaVence(p.fecha_venc)}</span>}
                            </li>
                        ))}
                    </ul>
                    <p className="mt-2 text-xs text-gray-500">
                        Calculado con {t.dosis_diaria} UI/día
                        {t.dosis_limitada && ` (tope para menores de 18 años; la dosis registrada es ${t.dosis_registrada} UI/día)`}.
                    </p>
                    {t.sustituto && (
                        <p className="mt-2 text-xs text-blue-800 bg-blue-50 rounded-lg px-3 py-2">
                            Parte se cubre con {displayInsulinName(t.sustituto)}, un sustituto permitido de su insulina. Ante
                            cualquier duda sobre cómo usarla, consulte a su médico.
                        </p>
                    )}
                </>
            ) : (
                <p className="mt-2 text-sm text-gray-500">En este reparto no se asignó insulina para este tratamiento.</p>
            )}
        </div>
    );
}

// Portal del Beneficiario: al consolidarse un reparto del almacén, cuánta insulina le corresponde para el periodo.
// El aviso más reciente se destaca como «Nuevo» hasta que pulse «Entendido» (la Fundación ve quién lo vio).
export default function InsulinNoticesSection() {
    const [avisos, setAvisos] = useState([]);
    const [marcando, setMarcando] = useState(false);

    useEffect(() => {
        let vigente = true;
        listMyInsulinNotices()
            .then((res) => vigente && setAvisos(Array.isArray(res) ? res : []))
            .catch((error) => console.error('Error cargando avisos de insulina:', error));
        return () => {
            vigente = false;
        };
    }, []);

    if (!avisos.length) return null;
    const [actual, ...anteriores] = avisos;
    const nuevo = !actual.visto_at;

    const entendido = async () => {
        try {
            setMarcando(true);
            const { visto_at } = await markInsulinNoticeSeen(actual.id);
            setAvisos((prev) => prev.map((a) => (a.id === actual.id ? { ...a, visto_at } : a)));
        } catch (error) {
            toast.error(typeof error === 'string' ? error : 'No se pudo confirmar el aviso');
        } finally {
            setMarcando(false);
        }
    };

    return (
        <section
            aria-label="Insulina que le corresponde"
            className={`bg-white rounded-2xl shadow-xl p-5 sm:p-8 border mb-6 ${nuevo ? 'border-vida-main ring-2 ring-vida-main/30' : 'border-gray-100'}`}
        >
            <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
                <h2 className="text-xl sm:text-2xl font-bold text-gray-800 flex items-center gap-2">
                    <Bell size={22} /> Su insulina para este periodo
                </h2>
                {nuevo && <span className="px-3 py-1 rounded-full text-xs font-bold bg-vida-main text-white">Nuevo</span>}
            </div>
            <p className="text-gray-500 mb-4">
                Reparto del {fecha(actual.consolidated_at)}, para {actual.dias} días. Le corresponde{' '}
                <b className="text-gray-800">
                    {actual.envases} envase(s) ({fmt(actual.ui)} UI)
                </b>
                :
            </p>

            {actual.entrega_desde && (
                <div className="mb-4 flex items-start gap-3 bg-green-50 border border-green-200 rounded-xl px-4 py-3 text-green-900">
                    <CalendarDays size={22} className="shrink-0 mt-0.5" />
                    <p>
                        <b>Fecha de entrega:</b> {ventanaEntregaTexto(actual.entrega_desde, actual.entrega_hasta)}.
                        <br />
                        {COORDINAR_ENTREGA}
                    </p>
                </div>
            )}

            <div className="space-y-3">
                {actual.tratamientos.map((t) => (
                    <Tratamiento key={t.insulina} t={t} />
                ))}
            </div>

            {actual.mensaje && (
                <div className="mt-4 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-900">
                    <b>Indicaciones de la Fundación:</b> {actual.mensaje}
                </div>
            )}

            <div className="mt-6">
                <h3 className="font-bold text-gray-800">Envíe sus fotos para esta entrega</h3>
                <div className="mt-2 grid gap-3 md:grid-cols-2">
                    {FOTOS.map((foto) => (
                        <FotoAviso
                            key={foto.tipo}
                            aviso={actual}
                            foto={foto}
                            onSubida={(subida) =>
                                setAvisos((prev) =>
                                    prev.map((a) => (a.id === actual.id ? { ...a, [`foto_${foto.tipo}`]: subida } : a))
                                )
                            }
                        />
                    ))}
                </div>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-3">
                {nuevo ? (
                    <button
                        type="button"
                        onClick={entendido}
                        disabled={marcando}
                        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-vida-main text-white hover:bg-vida-hover disabled:opacity-50"
                    >
                        <CheckCircle size={18} /> {marcando ? 'Guardando...' : 'Entendido'}
                    </button>
                ) : (
                    <p className="text-xs text-green-700 flex items-center gap-1">
                        <CheckCircle size={14} /> Visto el {fecha(actual.visto_at)}
                    </p>
                )}
            </div>

            {anteriores.length > 0 && (
                <details className="mt-6">
                    <summary className="cursor-pointer text-sm font-semibold text-gray-600">
                        Repartos anteriores ({anteriores.length})
                    </summary>
                    <ul className="mt-2 divide-y divide-gray-100 text-sm text-gray-700">
                        {anteriores.map((a) => (
                            <li key={a.id} className="py-2">
                                <b>{fecha(a.consolidated_at)}</b>
                                {a.entrega_desde && ` (entrega ${ventanaEntregaTexto(a.entrega_desde, a.entrega_hasta)})`}:{' '}
                                {a.tratamientos
                                    .map(
                                        (t) =>
                                            `${displayInsulinName(t.insulina)} ${t.envases} envase(s)${lotesResumen(t.productos)}, ≈ ${t.dias_cubiertos} días`
                                    )
                                    .join(' · ')}
                            </li>
                        ))}
                    </ul>
                </details>
            )}
        </section>
    );
}
