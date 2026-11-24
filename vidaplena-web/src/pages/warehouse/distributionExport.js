import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';
import * as XLSX from 'xlsx';
import {
    ESTADO_LABELS,
    MOTIVO_BAJO_MINIMO,
    diasCubiertos,
    dosisTexto,
    estadoMargen,
    fmt,
    lotesConNumeroTexto,
    margenTexto,
    ventanaEntregaTexto,
} from '../../utils/insulinDistribution';

export const ESTADO_REPARTO = { BORRADOR: 'Borrador', CONSOLIDADO: 'Consolidado', DESCARTADO: 'Descartado' };

const fecha = (iso) => (iso ? new Date(iso).toLocaleString('es-BO') : '');

const filas = (pacientes) =>
    pacientes.flatMap((p) => p.insulinas.map((i) => ({ p, i })));

const sufijo = (detail) => `${detail.id}_${(detail.consolidated_at || detail.created_at || '').slice(0, 10)}`;

// «Entrega del 1 de diciembre al 10 de diciembre de 2026 (día y hora con el(la) responsable de cada departamento)».
const entregaTexto = (detail) =>
    detail.entrega_desde
        ? `Entrega ${ventanaEntregaTexto(detail.entrega_desde, detail.entrega_hasta)} (día y hora con el(la) responsable de cada departamento)`
        : '';

/** PDF del reparto: resumen, prioridades y la lista de entrega por beneficiario con lote y vencimiento. */
export function exportDistributionPDF(detail, logoBase64) {
    const data = detail.resultado;
    const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'letter' });
    const pageWidth = doc.internal.pageSize.getWidth();
    const margin = 14;
    const estado = ESTADO_REPARTO[detail.estado] || detail.estado;
    const entrega = entregaTexto(detail);
    const top = entrega ? 44 : 40;

    const addHeader = () => {
        doc.setFillColor(248, 250, 252);
        doc.rect(0, 0, pageWidth, entrega ? 39 : 35, 'F');
        if (logoBase64) doc.addImage(logoBase64, 'PNG', margin, 5, 25, 25, 'logo', 'FAST');
        doc.setFontSize(18);
        doc.setTextColor(30, 58, 138);
        doc.setFont('helvetica', 'bold');
        doc.text('Fundación V.I.D.A. Plena', margin + 30, 16);
        doc.setFontSize(14);
        doc.text(`Reparto de insulina del almacén #${detail.id} · ${estado}`, margin + 30, 22);
        doc.setFontSize(9);
        doc.setTextColor(100, 116, 139);
        doc.setFont('helvetica', 'normal');
        doc.text(
            `Calculado: ${fecha(detail.created_at)}${detail.autor ? ` por ${detail.autor}` : ''}` +
                (detail.consolidated_at ? ` | Consolidado: ${fecha(detail.consolidated_at)}${detail.consolidado_por ? ` por ${detail.consolidado_por}` : ''}` : '') +
                ` | Horizonte: ${data.dias} días | Intercambios: ${detail.intercambios}`,
            margin + 30,
            27
        );
        doc.text(
            `Stock: ${fmt(data.stock_total_ui)} UI | Reserva: ${fmt(data.reserva_ui)} UI | Asignado: ${fmt(data.asignado_ui)} UI | Beneficiarios: ${data.pacientes.length} | Envases: ${detail.envases}`,
            margin + 30,
            32
        );
        if (entrega) {
            doc.setFont('helvetica', 'bold');
            doc.setTextColor(21, 128, 61);
            doc.text(entrega, margin + 30, 37);
        }
    };
    const base = {
        margin: { top, left: margin, right: margin, bottom: 20 },
        styles: { fontSize: 8, cellPadding: 2.5, font: 'helvetica' },
        alternateRowStyles: { fillColor: [248, 250, 252] },
        didDrawPage: addHeader,
    };

    if (detail.ingresos?.length) {
        autoTable(doc, {
            ...base,
            startY: top,
            head: [['Packing list', 'Ingreso', 'Ingresado', 'Lotes', 'Envases asignados', 'UI asignadas']],
            body: detail.ingresos.map((o) => [
                o.ingreso_id == null ? 'Lotes sin packing list' : o.archivo, o.ingreso_id == null ? '-' : `#${o.ingreso_id}`,
                o.ingresado_at ? fecha(o.ingresado_at) : '-', o.lotes, o.envases, fmt(o.ui),
            ]),
            headStyles: { fillColor: [71, 85, 105], textColor: 255, fontStyle: 'bold' },
        });
    }

    autoTable(doc, {
        ...base,
        startY: detail.ingresos?.length ? doc.lastAutoTable.finalY + 8 : top,
        head: [['Producto', 'Insulina', 'UI/envase', 'Lote', 'Vence', 'Disponibles', 'Asignados', 'Reserva', 'Sobrante']],
        body: (data.stock || []).map((s) => [
            s.producto, s.insulina, fmt(s.ui_por_envase), s.lote || '-', s.fecha_venc || '-',
            s.disponibles, s.asignados, s.reserva, s.sobrante,
        ]),
        headStyles: { fillColor: [30, 58, 138], textColor: 255, fontStyle: 'bold' },
    });

    if (data.prioridades?.length) {
        autoTable(doc, {
            ...base,
            startY: doc.lastAutoTable.finalY + 8,
            head: [['Prioridad', 'Margen', 'Beneficiarios', 'Cobertura', 'En margen', 'Bajo el mínimo', 'Sobre el máximo', 'En 0 %']],
            body: data.prioridades.map((g) => [
                `${g.grupo}. ${g.nombre}`, `${g.margen_min_pct}–${g.margen_max_pct} %`, g.beneficiarios, `${g.cobertura_pct} %`,
                g.en_margen, g.bajo_minimo, g.sobre_maximo, g.en_cero,
            ]),
            headStyles: { fillColor: [79, 70, 229], textColor: 255, fontStyle: 'bold' },
        });
    }

    autoTable(doc, {
        ...base,
        startY: doc.lastAutoTable.finalY + 8,
        head: [['Beneficiario', 'CI', 'Estado', 'Grupo', 'Insulina', 'Dosis/día', 'Necesita', 'Recibe', 'Cobertura', 'Días', 'Envases (lote, vencimiento)']],
        body: filas(data.pacientes).map(({ p, i }) => [
            p.nombre_completo, p.ci || '-', ESTADO_LABELS[p.estado] || p.estado || '-', p.grupo_prioridad_nombre,
            i.sustituto ? `${i.insulina} → ${i.sustituto}` : i.insulina, dosisTexto(i), `${fmt(i.necesidad_ui)} UI`,
            `${fmt(i.entregado_ui)} UI`, `${i.cobertura_pct}%${i.fuera_de_margen ? ' *' : ''}`,
            diasCubiertos(i.cobertura_pct, data.dias), lotesConNumeroTexto(i.lotes),
        ]),
        styles: { fontSize: 7, cellPadding: 2, font: 'helvetica' },
        headStyles: { fillColor: [21, 128, 61], textColor: 255, fontStyle: 'bold' },
        columnStyles: { 10: { cellWidth: 70 } },
        didDrawPage: () => {
            addHeader();
            doc.setFontSize(8);
            doc.setTextColor(150);
            doc.text(`Página ${doc.internal.getNumberOfPages()}`, pageWidth / 2, doc.internal.pageSize.getHeight() - 10, { align: 'center' });
        },
    });

    if (detail.intercambios_detalle?.length) {
        autoTable(doc, {
            ...base,
            startY: doc.lastAutoTable.finalY + 8,
            head: [['Intercambio', 'Entrega', 'Recibe', 'UI', 'Fecha']],
            body: detail.intercambios_detalle.map((s) => [
                `${s.nombre_a} ↔ ${s.nombre_b}`,
                `${s.envases_a} × ${s.producto_a} (de ${s.nombre_a})`,
                `${s.envases_b} × ${s.producto_b} (de ${s.nombre_b})`,
                fmt(s.ui),
                fecha(s.created_at),
            ]),
            headStyles: { fillColor: [180, 83, 9], textColor: 255, fontStyle: 'bold' },
        });
    }
    doc.save(`Reparto_insulina_${sufijo(detail)}.pdf`);
}

/** Excel del reparto: beneficiarios (con lote), stock, intercambios, prioridades y avisos. */
export function exportDistributionXLS(detail) {
    const data = detail.resultado;
    const workbook = XLSX.utils.book_new();
    const beneficiarios = filas(data.pacientes).map(({ p, i }) => ({
        Beneficiario: p.nombre_completo,
        CI: p.ci || '',
        Departamento: p.depto || '',
        Estado: ESTADO_LABELS[p.estado] || p.estado || '',
        Edad: p.edad ?? '',
        'Tipo de diabetes': p.tipo_diabetes || '',
        Grupo: p.grupo_prioridad_nombre,
        Insulina: i.insulina,
        'Se le da en su lugar': i.sustituto || '',
        'Dosis diaria usada (UI)': i.dosis_diaria_aplicada,
        'Necesita (UI)': Math.round(i.necesidad_ui),
        'Recibe (UI)': Math.round(i.entregado_ui),
        'Margen de cobertura': margenTexto(i),
        'Cobertura (%)': i.cobertura_pct,
        'Fuera de margen': estadoMargen(i),
        [`Días cubiertos (de ${data.dias})`]: diasCubiertos(i.cobertura_pct, data.dias),
        Notas: (i.notas || []).join('; '),
        'Envases (lote, vencimiento)': lotesConNumeroTexto(i.lotes),
        ...(detail.entrega_desde && { Entrega: ventanaEntregaTexto(detail.entrega_desde, detail.entrega_hasta) }),
    }));
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(beneficiarios), 'Beneficiarios');

    const stock = (data.stock || []).map((s) => ({
        Producto: s.producto,
        Insulina: s.insulina,
        'Presentación (ml)': s.presentacion_ml ?? '',
        'Concentración (UI/ml)': s.concentracion_ui_ml ?? '',
        'UI por envase': s.ui_por_envase,
        Lote: s.lote || '',
        Vencimiento: s.fecha_venc || '',
        Disponibles: s.disponibles,
        Asignados: s.asignados,
        Reserva: s.reserva,
        Sobrante: s.sobrante,
    }));
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(stock), 'Stock');

    if (detail.ingresos?.length) {
        const ingresos = detail.ingresos.map((o) => ({
            'Packing list': o.ingreso_id == null ? 'Lotes sin packing list' : o.archivo,
            Ingreso: o.ingreso_id ?? '',
            Ingresado: o.ingresado_at ? fecha(o.ingresado_at) : '',
            Lotes: o.lotes,
            'Envases asignados': o.envases,
            'UI asignadas': Math.round(o.ui),
        }));
        XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(ingresos), 'Packing lists');
    }

    if (detail.intercambios_detalle?.length) {
        const swaps = detail.intercambios_detalle.map((s) => ({
            Fecha: fecha(s.created_at),
            Autor: s.autor || '',
            'Beneficiario A': s.nombre_a,
            'A entrega': `${s.envases_a} × ${s.producto_a}`,
            'Beneficiario B': s.nombre_b,
            'B entrega': `${s.envases_b} × ${s.producto_b}`,
            UI: s.ui,
        }));
        XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(swaps), 'Intercambios');
    }
    if (data.prioridades?.length) {
        const prioridades = data.prioridades.map((g) => ({
            Prioridad: g.grupo, Grupo: g.nombre, 'Margen mínimo (%)': g.margen_min_pct, 'Margen máximo (%)': g.margen_max_pct,
            Beneficiarios: g.beneficiarios, 'Cobertura (%)': g.cobertura_pct, 'En margen': g.en_margen,
            'Bajo el mínimo': g.bajo_minimo, 'Sobre el máximo': g.sobre_maximo, 'En 0 %': g.en_cero,
        }));
        XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(prioridades), 'Prioridades');
    }
    if (data.bajo_minimo?.length) {
        const bajo = data.bajo_minimo.map((b) => ({
            Beneficiario: b.nombre_completo, CI: b.ci || '', Insulina: b.insulina, 'Cobertura (%)': b.cobertura_pct,
            'Mínimo (%)': b.margen_min_pct, 'Falta (UI)': Math.round(b.falta_ui), Motivo: MOTIVO_BAJO_MINIMO[b.motivo] || b.motivo,
        }));
        XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(bajo), 'Bajo el mínimo');
    }
    const avisos = [...(data.advertencias || []), ...(data.excluded_patients || []).map((e) => `${e.nombre_completo}: ${e.motivo}`)];
    if (avisos.length) {
        XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(avisos.map((a) => ({ Aviso: a }))), 'Avisos');
    }
    XLSX.writeFile(workbook, `Reparto_insulina_${sufijo(detail)}.xlsx`);
}
