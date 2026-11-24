// Textos del reparto de insulina, compartidos por el reporte de distribución y el reparto del almacén
// (los dos usan el mismo motor y devuelven el mismo formato).

export const fmt = (n) => Math.round(n || 0).toLocaleString('es-BO');

export const ESTADO_LABELS = {
    ACTIVO: 'Activo',
    PENDIENTE_DOC: 'Pendiente de documentos',
    HABILITADO: 'Habilitado',
    ASISTIDO: 'Registro asistido',
};

// Cobertura en días: lo que recibe ÷ lo que necesita al día. Con envases enteros puede pasar de
// los días del reporte (166 % de 60 días = 100 días): no se puede entregar medio pen.
export const diasCubiertos = (cobertura, dias) => Math.round((cobertura * dias) / 100);

// «75–108,3 %»: margen de cobertura de todos los beneficiarios (piso del 75 % y tope de 65 días).
export const margenTexto = (i) =>
    i.margen_min_pct !== undefined && i.margen_max_pct !== undefined
        ? `${i.margen_min_pct}–${i.margen_max_pct} %`
        : '';

// Un tratamiento está dentro del margen salvo que el servidor diga lo contrario.
export const dentroDelMargen = (i) =>
    i.fuera_de_margen === undefined ? i.cobertura_pct >= 99.9 : !i.fuera_de_margen;

export const estadoMargen = (i) => {
    if (i.fuera_de_margen !== true) return '';
    return i.cobertura_pct < (i.margen_min_pct ?? 0) ? 'Bajo el mínimo' : 'Sobre el máximo';
};

export const MOTIVO_BAJO_MINIMO = {
    STOCK: 'falta stock de su insulina y de sus sustitutos',
    ENVASE: 'el envase entero no permite quedar entre el 75 % y los 65 días',
    OTRO: 'revisar',
};

// Notas del motor que el equipo debe ver. ENVASE_MINIMO, SIN_ASIGNACION y SUSTITUCION simple ya se
// muestran en otros lugares (texto del envase, cobertura 0 %, etiqueta «+ sustituto»).
export const notaTexto = (nota) => {
    if (nota.startsWith('REVISION_CLINICA')) return 'revisión clínica: dosis alta en un menor';
    if (nota === 'ENVASE_ENTERO') return 'el envase entero no permite quedar entre 75 % y 65 días';
    if (nota.startsWith('SUSTITUCION (MENOR')) return 'sustituto en un menor: requiere aval médico';
    if (nota === 'CEDIÓ_ENVASE_A_PRIORITARIO') return 'cedió un envase a un menor o tipo 1';
    if (nota === 'FICHA_POR_CORREGIR') return 'ficha por corregir';
    return '';
};
export const notasVisibles = (i) => (i.notas || []).map(notaTexto).filter(Boolean);

export const MOTIVO_ELECCION = {
    STOCK: 'tiene stock',
    SUSTITUTO: 'se cubre con sustituto',
    SIN_STOCK: 'sin stock: mayor dosis',
    MENOR_DEGLUDEC: 'menor: mantiene la degludec',
};

// «30 UI/día» o, si se limitó, «48 → 30 UI/día» (tope de 30 UI/día para menores).
export const dosisTexto = (i) =>
    i.dosis_limitada
        ? `${i.dosis_diaria_registrada} → ${i.dosis_diaria_aplicada} UI/día`
        : `${i.dosis_diaria_aplicada} UI/día`;

// «2 × Toujeo DoubleStar 3 ml · 900 UI c/u»: un envase de «3 ml» no siempre tiene 300 UI,
// depende de la concentración (U100 = 300 UI, U200 = 600 UI, U300 = 900 UI), así que se muestra.
// Sin número de lote: el mismo producto de varios lotes se suma en una sola línea.
export const lotesTexto = (lotes) => {
    if (!lotes.length) return '—';
    const porProducto = new Map();
    lotes.forEach((l) => {
        const porEnvase = l.unidades ? Math.round(l.ui / l.unidades) : 0;
        const key = `${l.producto}|${porEnvase}`;
        const actual = porProducto.get(key) || { producto: l.producto, porEnvase, unidades: 0 };
        actual.unidades += l.unidades;
        porProducto.set(key, actual);
    });
    return [...porProducto.values()]
        .map((x) => `${x.unidades} × ${x.producto} · ${fmt(x.porEnvase)} UI c/u`)
        .join(', ');
};

// --- Ventana de entrega del aviso del reparto («del 1 de … al 10 de …») ----------------------------------
const MESES = [
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
];
const isoDia = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

export const hoyIso = () => isoDia(new Date());

// Del 1 al 10 del mes siguiente, igual que el servidor cuando no se indican fechas.
export const ventanaEntregaPorDefecto = (hoy = new Date()) => ({
    desde: isoDia(new Date(hoy.getFullYear(), hoy.getMonth() + 1, 1)),
    hasta: isoDia(new Date(hoy.getFullYear(), hoy.getMonth() + 1, 10)),
});

// «del 1 de diciembre al 10 de diciembre de 2026»; con el año en las dos fechas si la entrega cambia de año.
export const ventanaEntregaTexto = (desde, hasta) => {
    if (!desde || !hasta) return '';
    const parte = (iso) => {
        const [y, m, d] = iso.split('-').map(Number);
        return { y, texto: `${d} de ${MESES[m - 1]}` };
    };
    const a = parte(desde);
    const b = parte(hasta);
    if (desde === hasta) return `el ${a.texto} de ${a.y}`;
    return `del ${a.texto}${a.y !== b.y ? ` de ${a.y}` : ''} al ${b.texto} de ${b.y}`;
};

export const COORDINAR_ENTREGA = 'Coordine el día y la hora con el(la) responsable de su departamento.';

// --- Fotos que el beneficiario sube en el aviso (insulinas ya usadas y HbA1c) y su revisión ---------------
export const FOTO_TIPOS = ['envases', 'hba1c'];
export const FOTO_TITULOS = { envases: 'Insulinas ya usadas', hba1c: 'Hemoglobina glucosilada (HbA1c)' };
export const FOTO_ESTADOS = {
    PENDIENTE: { label: 'Por revisar', clase: 'bg-amber-100 text-amber-700' },
    APROBADA: { label: 'Aprobada', clase: 'bg-green-100 text-green-700' },
    OBSERVADA: { label: 'Observada', clase: 'bg-red-100 text-red-700' },
};
export const esPdf = (url) => /\.pdf($|\?)/i.test(url || '');

// Con número de lote y vencimiento, para la hoja de entrega del almacén (trazabilidad).
export const lotesConNumeroTexto = (lotes) =>
    lotes.length
        ? lotes
              .map((l) => `${l.unidades} × ${l.producto} (lote ${l.lote || '-'}${l.fecha_venc ? `, vence ${l.fecha_venc}` : ''})`)
              .join('; ')
        : '—';
