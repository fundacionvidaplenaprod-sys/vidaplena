import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import DistributionHistoryPanel from '../pages/warehouse/DistributionHistoryPanel';
import DistributionWorkspace from '../pages/warehouse/DistributionWorkspace';
import InsulinPhotosPanel from '../pages/warehouse/InsulinPhotosPanel';
import WarehouseIntakePanel from '../pages/warehouse/WarehouseIntakePanel';
import { buildMatrix, filterRows } from '../pages/warehouse/distributionMatrix';
import { exportDistributionPDF, exportDistributionXLS } from '../pages/warehouse/distributionExport';
import {
  FILTROS_INICIALES,
  filterHistory,
  packingListOptions,
  totalesConsolidados,
} from '../pages/warehouse/distributionHistory';

const api = vi.hoisted(() => ({
  searchDistributionBeneficiaries: vi.fn(),
  getBeneficiaryDistributions: vi.fn(),
  getDistributionSwapOptions: vi.fn(),
  createDistributionSwap: vi.fn(),
  consolidateWarehouseDistribution: vi.fn(),
  reviewInsulinPhoto: vi.fn(),
  listInsulinPhotos: vi.fn(),
  resetWarehouseDistribution: vi.fn(),
  discardWarehouseDistribution: vi.fn(),
  previewDonationIntake: vi.fn(),
  createDonationIntake: vi.fn(),
  listDonationIntakes: vi.fn(),
}));
vi.mock('../api/donations', () => api);
vi.mock('react-hot-toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const exportMocks = vi.hoisted(() => ({ saved: [], tables: [], sheets: [] }));
vi.mock('jspdf', () => ({
  default: vi.fn().mockImplementation(() => ({
    internal: { pageSize: { getWidth: () => 279, getHeight: () => 216 }, getNumberOfPages: () => 1 },
    setFillColor: vi.fn(), rect: vi.fn(), addImage: vi.fn(), setFontSize: vi.fn(), setTextColor: vi.fn(),
    setFont: vi.fn(), text: vi.fn(), lastAutoTable: { finalY: 50 },
    save: (name) => exportMocks.saved.push(name),
  })),
}));
vi.mock('jspdf-autotable', () => ({ default: (_doc, opts) => exportMocks.tables.push(opts) }));
vi.mock('xlsx', () => ({
  utils: {
    book_new: () => ({}),
    json_to_sheet: (rows) => rows,
    book_append_sheet: (_wb, rows, name) => exportMocks.sheets.push([name, rows]),
  },
  writeFile: (_wb, name) => exportMocks.saved.push(name),
}));

const lote = (lot_id, producto, unidades, extra = {}) => ({
  lot_id, producto, unidades, ui: unidades * 300, lote: `L-${lot_id}`, fecha_venc: '2027-12-31', ...extra,
});

const insulina = (nombre, lotes, extra = {}) => ({
  insulina: nombre, necesidad_ui: 1200, entregado_ui: 1200, cobertura_pct: 100, sustituto: null, sustituto_ui: 0,
  dosis_diaria_registrada: 20, dosis_diaria_aplicada: 20, dosis_limitada: false, margen_min_pct: 75,
  margen_max_pct: 108.3, fuera_de_margen: false, notas: [], lotes, ...extra,
});

const paciente = (patient_id, nombre, grupo, insulinas) => ({
  patient_id, nombre_completo: nombre, ci: `CI${patient_id}`, es_menor: grupo === 1, es_tipo1: grupo === 2,
  grupo_prioridad: grupo, grupo_prioridad_nombre: grupo === 1 ? 'Menores de 18 años' : 'Diabéticos tipo 2',
  estado: 'ACTIVO', insulinas,
});

const stockLot = (lot_id, donation_id, producto, insulinaNombre, asignados) => ({
  lot_id, donation_id, producto, insulina: insulinaNombre, presentacion_ml: 3, concentracion_ui_ml: 100,
  ui_por_envase: 300, lote: `L-${lot_id}`, fecha_venc: '2027-12-31', disponibles: 10, asignados, reserva: 1,
  sobrante: 10 - asignados - 1,
});

const detail = (overrides = {}) => ({
  id: 7,
  estado: 'BORRADOR',
  dias: 60,
  created_at: '2026-11-24T10:00:00Z',
  autor: 'admin@test.com',
  consolidated_at: null,
  consolidado_por: null,
  discarded_at: null,
  beneficiarios: 3,
  envases: 12,
  asignado_ui: 3600,
  intercambios: 0,
  stock_vigente: true,
  stock_cambios: [],
  intercambios_detalle: [],
  propuesta: [
    { beneficiario_id: 1, insulina: 'Glargina', lot_id: 11, envases: 4 },
    { beneficiario_id: 2, insulina: 'Glargina', lot_id: 12, envases: 4 },
    { beneficiario_id: 3, insulina: 'Detemir', lot_id: 13, envases: 4 },
  ],
  resultado: {
    guardado: true, dias: 60, reserva_pct: 0.03, stock_total_ui: 9000, reserva_objetivo_ui: 270, reserva_ui: 900,
    reserva_liberada_ui: 0, asignado_ui: 3600, lotes_considerados: 3, lotes_excluidos_consolidados: 0,
    lotes_vencidos: 0, lotes_sin_catalogo: 0, asignaciones_generadas: 3, insulinas: [], reserva: [],
    excluded_patients: [], registros_por_corregir: [], advertencias: [], minimo_imposible: [], bajo_minimo: [],
    prioridades: [], estados_considerados: ['ACTIVO', 'PENDIENTE_DOC', 'HABILITADO'], asistidos_incluidos: 0,
    optimizador_usado: true,
    pacientes: [
      paciente(1, 'Ana Menor', 1, [insulina('Glargina', [lote(11, 'Lantus SoloStar 3 ml', 4)])]),
      paciente(2, 'Beto Adulto', 4, [insulina('Glargina', [lote(12, 'Abasaglar KwikPen 3 ml', 4)])]),
      paciente(3, 'Carla Detemir', 4, [insulina('Detemir', [lote(13, 'Levemir FlexPen 3 ml', 4)])]),
    ],
    stock: [
      stockLot(11, 101, 'Lantus SoloStar 3 ml', 'Glargina', 4),
      stockLot(12, 102, 'Abasaglar KwikPen 3 ml', 'Glargina', 4),
      stockLot(13, 103, 'Levemir FlexPen 3 ml', 'Detemir', 4),
    ],
  },
  ...overrides,
});

const fotoAviso = (id, tipo, url, extra = {}) => ({
  id, tipo, url, subida_at: '2026-11-25T15:00:00Z', estado: 'PENDIENTE', observacion: null, revisada_at: null, revisada_por: null,
  ...extra,
});

// El mismo reparto después de intercambiar 1 Abasaglar de Beto por 1 Levemir de Carla.
const afterSwap = () => {
  const d = detail({ intercambios: 1 });
  d.resultado.pacientes[1].insulinas[0] = insulina(
    'Glargina', [lote(12, 'Abasaglar KwikPen 3 ml', 3), lote(13, 'Levemir FlexPen 3 ml', 1)], { sustituto: 'Detemir', notas: ['SUSTITUCION'] }
  );
  d.resultado.pacientes[2].insulinas[0] = insulina(
    'Detemir', [lote(12, 'Abasaglar KwikPen 3 ml', 1), lote(13, 'Levemir FlexPen 3 ml', 3)], { sustituto: 'Glargina', notas: ['SUSTITUCION'] }
  );
  d.intercambios_detalle = [{
    id: 1, created_at: '2026-11-24T11:00:00Z', autor: 'admin@test.com', beneficiario_a: 2, nombre_a: 'Beto Adulto',
    insulina_a: 'Glargina', lot_a_id: 12, producto_a: 'Abasaglar KwikPen 3 ml', envases_a: 1, beneficiario_b: 3,
    nombre_b: 'Carla Detemir', insulina_b: 'Detemir', lot_b_id: 13, producto_b: 'Levemir FlexPen 3 ml', envases_b: 1, ui: 300,
  }];
  return d;
};

describe('matriz del reparto', () => {
  it('arma una columna por producto y marca lo que cambió respecto de la propuesta', () => {
    const { columns, rows } = buildMatrix(afterSwap());
    expect(columns.map((c) => c.producto)).toEqual(['Levemir FlexPen 3 ml', 'Abasaglar KwikPen 3 ml', 'Lantus SoloStar 3 ml']);
    const beto = rows.find((r) => r.paciente.patient_id === 2);
    expect(beto.cells[102]).toMatchObject({ envases: 3, propuesta: 4 });
    expect(beto.cells[103]).toMatchObject({ envases: 1, propuesta: 0 });
    expect(beto.cambiada).toBe(true);
    expect(rows.find((r) => r.paciente.patient_id === 1).cambiada).toBe(false);
    expect(filterRows(rows, { soloCambios: true }).map((r) => r.paciente.patient_id)).toEqual([2, 3]);
    expect(filterRows(rows, { grupo: '1' }).map((r) => r.paciente.nombre_completo)).toEqual(['Ana Menor']);
    expect(filterRows(rows, { search: 'ci3' }).map((r) => r.paciente.patient_id)).toEqual([3]);
  });
});

describe('exportación del reparto', () => {
  it('el PDF y el Excel llevan el número de lote y los intercambios', () => {
    exportMocks.saved.length = 0;
    exportMocks.tables.length = 0;
    exportMocks.sheets.length = 0;
    const d = afterSwap();
    exportDistributionPDF(d, 'data:image/png;base64,AAAA');
    exportDistributionXLS(d);
    expect(exportMocks.saved).toEqual([
      'Reparto_insulina_7_2026-11-24.pdf',
      'Reparto_insulina_7_2026-11-24.xlsx',
    ]);
    const entrega = exportMocks.tables.find((t) => t.head[0][0] === 'Beneficiario');
    expect(entrega.body.find((r) => r[0] === 'Beto Adulto')[10]).toBe(
      '3 × Abasaglar KwikPen 3 ml (lote L-12, vence 2027-12-31); 1 × Levemir FlexPen 3 ml (lote L-13, vence 2027-12-31)'
    );
    expect(exportMocks.tables.some((t) => t.head[0][0] === 'Intercambio')).toBe(true);
    expect(exportMocks.sheets.map(([name]) => name)).toEqual(['Beneficiarios', 'Stock', 'Intercambios']);
    expect(exportMocks.sheets[0][1][0]).not.toHaveProperty('Entrega'); // borrador: aún sin fecha de entrega
  });

  it('un reparto consolidado lleva la fecha de entrega en el PDF y en el Excel', () => {
    exportMocks.tables.length = 0;
    exportMocks.sheets.length = 0;
    const d = detail({ estado: 'CONSOLIDADO', consolidated_at: '2026-11-24T12:00:00Z', entrega_desde: '2026-12-01', entrega_hasta: '2026-12-10' });
    exportDistributionPDF(d, null);
    exportDistributionXLS(d);
    expect(exportMocks.tables[0]).toMatchObject({ startY: 44, margin: { top: 44 } }); // espacio para la línea de la entrega
    const [, beneficiarios] = exportMocks.sheets.find(([name]) => name === 'Beneficiarios');
    expect(beneficiarios.map((r) => r.Entrega)).toEqual(Array(3).fill('del 1 de diciembre al 10 de diciembre de 2026'));
  });

  it('con packing lists de origen, los lleva en el PDF y en una hoja del Excel', () => {
    exportMocks.tables.length = 0;
    exportMocks.sheets.length = 0;
    const d = detail({ ingresos: [{ ingreso_id: 3, archivo: 'packing_noviembre.xlsx', ingresado_at: null, lotes: 2, envases: 10, ui: 3000 }] });
    exportDistributionPDF(d, null);
    exportDistributionXLS(d);
    expect(exportMocks.tables[0].body).toEqual([['packing_noviembre.xlsx', '#3', '-', 2, 10, '3.000']]);
    const [, hoja] = exportMocks.sheets.find(([name]) => name === 'Packing lists');
    expect(hoja).toEqual([{ 'Packing list': 'packing_noviembre.xlsx', Ingreso: 3, Ingresado: '', Lotes: 2, 'Envases asignados': 10, 'UI asignadas': 3000 }]);
  });
});

describe('DistributionWorkspace', () => {
  beforeEach(() => vi.clearAllMocks());

  it('abre el intercambio desde una celda y lo aplica con las mismas UI', async () => {
    api.getDistributionSwapOptions.mockResolvedValue({
      beneficiario_id: 2, insulina: 'Glargina', lot_id: 12, producto: 'Abasaglar KwikPen 3 ml', envases: 1, ui: 300,
      opciones: [{
        beneficiario_id: 3, nombre_completo: 'Carla Detemir', ci: 'CI3', grupo_prioridad: 4,
        grupo_prioridad_nombre: 'Diabéticos tipo 2', es_menor: false, insulina: 'Detemir', lot_id: 13,
        producto: 'Levemir FlexPen 3 ml', lote: 'L-13', fecha_venc: '2027-12-31', envases: 1, ui: 300, misma_insulina: false,
      }],
    });
    api.createDistributionSwap.mockResolvedValue(afterSwap());
    const onChange = vi.fn();
    render(<DistributionWorkspace detail={detail()} onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: 'Intercambiar 4 de Abasaglar KwikPen 3 ml de Beto Adulto' }));
    const dialog = await screen.findByRole('dialog', { name: 'Intercambiar envases' });
    await waitFor(() =>
      expect(api.getDistributionSwapOptions).toHaveBeenCalledWith(7, { beneficiarioId: 2, insulina: 'Glargina', lotId: 12, envases: 1 })
    );
    expect(await within(dialog).findByText('Carla Detemir')).toBeInTheDocument();
    expect(within(dialog).getByText(/sustituto permitido/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Intercambiar' }));
    await waitFor(() =>
      expect(api.createDistributionSwap).toHaveBeenCalledWith(7, {
        beneficiario_id: 2, insulina: 'Glargina', lot_id: 12, envases: 1,
        con_beneficiario_id: 3, con_insulina: 'Detemir', con_lot_id: 13, con_envases: 1,
      })
    );
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ intercambios: 1 }));
  });

  it('marca las celdas cambiadas y muestra el registro de intercambios', () => {
    render(<DistributionWorkspace detail={afterSwap()} onChange={vi.fn()} />);
    expect(screen.getAllByText('antes 4')).toHaveLength(2);
    expect(screen.getByText('Intercambios (1)')).toBeInTheDocument();
    expect(screen.getByText('Beto Adulto: 1 × Abasaglar KwikPen 3 ml')).toBeInTheDocument();
  });

  it('pide confirmación y consolida con la fecha de entrega y las indicaciones del aviso', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(2026, 10, 24, 10)); // 24/11/2026: por defecto, del 1 al 10 de diciembre
    try {
      api.consolidateWarehouseDistribution.mockResolvedValue(detail({ estado: 'CONSOLIDADO', consolidated_at: '2026-11-24T12:00:00Z' }));
      const onChange = vi.fn();
      render(<DistributionWorkspace detail={detail()} onChange={onChange} />);
      fireEvent.click(screen.getByRole('button', { name: /Consolidar/ }));
      expect(screen.getByText(/salen del almacén 12 envases/)).toBeInTheDocument();
      expect(screen.getByText(/verá en su portal cuánta insulina le corresponde, con el número de lote/)).toBeInTheDocument();
      expect(screen.getByLabelText('Desde')).toHaveValue('2026-12-01');
      expect(screen.getByLabelText('Hasta')).toHaveValue('2026-12-10');
      expect(
        screen.getByText(
          'El aviso dirá: «Entrega del 1 de diciembre al 10 de diciembre de 2026. Coordine el día y la hora con el(la) responsable de su departamento.»'
        )
      ).toBeInTheDocument();

      // Fechas al revés: no deja consolidar.
      fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2026-11-30' } });
      expect(screen.getByText(/Revise las fechas/)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Sí, consolidar' })).toBeDisabled();

      fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2026-12-12' } });
      fireEvent.change(screen.getByPlaceholderText(/carnet de identidad/), { target: { value: 'Llevar su carnet de identidad' } });
      fireEvent.click(screen.getByRole('button', { name: 'Sí, consolidar' }));
      await waitFor(() =>
        expect(api.consolidateWarehouseDistribution).toHaveBeenCalledWith(7, {
          mensaje: 'Llevar su carnet de identidad', entregaDesde: '2026-12-01', entregaHasta: '2026-12-12',
        })
      );
      expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ estado: 'CONSOLIDADO' }));
    } finally {
      vi.useRealTimers();
    }
  });

  it('en un consolidado muestra la fecha de entrega y quién vio el aviso en su portal', () => {
    const d = detail({
      estado: 'CONSOLIDADO', consolidated_at: '2026-11-24T12:00:00Z', aviso_mensaje: 'Recoger desde el 1/12',
      entrega_desde: '2026-12-01', entrega_hasta: '2026-12-10',
      avisos: [
        {
          beneficiario_id: 1, nombre_completo: 'Ana Menor', ci: 'CI1', estado: 'VISTO', visto_at: '2026-11-25T14:00:00Z',
          foto_envases: fotoAviso(51, 'envases', 'https://storage.test/insulinas_usadas_1.jpg'),
        },
        { beneficiario_id: 2, nombre_completo: 'Beto Adulto', ci: 'CI2', estado: 'PENDIENTE', visto_at: null },
        { beneficiario_id: -4, nombre_completo: 'RA-00004', ci: null, estado: 'SIN_PORTAL', visto_at: null },
      ],
    });
    render(<DistributionWorkspace detail={d} onChange={vi.fn()} />);
    expect(screen.getByText(/Aviso en el Portal del Beneficiario/).closest('summary')).toHaveTextContent(
      'Lo vio: 1 · Pendiente: 1 · Registro Asistido: avisar a su referente: 1'
    );
    expect(screen.getByText('Recoger desde el 1/12')).toBeInTheDocument();
    expect(screen.getByText(/Calculado el/)).toHaveTextContent('entrega del 1 de diciembre al 10 de diciembre de 2026');
    expect(screen.getByText(/coordina el día y la hora con el\(la\) responsable de su departamento/)).toBeInTheDocument();
    const avisos = screen.getByText(/Aviso en el Portal del Beneficiario/).closest('details');
    expect(within(within(avisos).getByText('Beto Adulto').closest('tr')).getByText('Pendiente')).toBeInTheDocument();
    // Las fotos que enviaron en su portal, con su revisión.
    expect(avisos.querySelector('summary')).toHaveTextContent('Fotos enviadas: insulinas usadas 1, HbA1c 0 (1 por revisar)');
    expect(screen.getByRole('button', { name: 'Insulinas usadas de Ana Menor: Por revisar' })).toBeInTheDocument();
    expect(within(within(avisos).getByText('Beto Adulto').closest('tr')).queryByRole('button')).not.toBeInTheDocument();
  });

  it('desde la tabla de avisos se revisa la foto de un beneficiario', async () => {
    const consolidado = detail({
      estado: 'CONSOLIDADO', consolidated_at: '2026-11-24T12:00:00Z',
      avisos: [
        { beneficiario_id: 2, nombre_completo: 'Beto Adulto', ci: 'CI2', estado: 'VISTO', visto_at: null,
          foto_hba1c: fotoAviso(62, 'hba1c', 'https://storage.test/hba1c_2.pdf') },
      ],
    });
    api.reviewInsulinPhoto.mockResolvedValue({
      ...fotoAviso(62, 'hba1c', 'https://storage.test/hba1c_2.pdf'), estado: 'APROBADA', revisada_at: '2026-11-26T10:00:00Z',
    });
    const actualizaciones = [];
    function Pantalla() {
      const [d, setD] = React.useState(consolidado);
      const actualizar = (nuevo) => {
        actualizaciones.push(nuevo);
        setD(nuevo);
      };
      return <DistributionWorkspace detail={d} onChange={vi.fn()} onDetailUpdate={actualizar} />;
    }
    render(<Pantalla />);

    fireEvent.click(screen.getByRole('button', { name: 'HbA1c de Beto Adulto: Por revisar' }));
    const dialog = screen.getByRole('dialog', { name: 'Revisar foto' });
    expect(within(dialog).getByTitle('Hemoglobina glucosilada (HbA1c) de Beto Adulto')).toHaveAttribute(
      'src', 'https://storage.test/hba1c_2.pdf'
    );
    fireEvent.click(within(dialog).getByRole('button', { name: /Aprobar/ }));
    await waitFor(() => expect(api.reviewInsulinPhoto).toHaveBeenCalledWith(62, { estado: 'APROBADA', observacion: null }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Revisar foto' })).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'HbA1c de Beto Adulto: Aprobada' })).toBeInTheDocument();
    expect(actualizaciones).toHaveLength(1);
  });

  it('un reparto consolidado se ve pero no se modifica', () => {
    render(<DistributionWorkspace detail={detail({ estado: 'CONSOLIDADO', consolidated_at: '2026-11-24T12:00:00Z' })} onChange={vi.fn()} />);
    expect(screen.getByText('Consolidado')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Consolidar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Intercambiar/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /PDF/ })).toBeInTheDocument();
  });

  it('muestra de qué packing lists sale y se abre filtrado en un beneficiario', () => {
    const d = detail({ ingresos: [origen(3, 'packing_noviembre.xlsx', 10), origen(null, null, 2)] });
    render(<DistributionWorkspace detail={d} onChange={vi.fn()} initialSearch="CI2" />);
    expect(screen.getByText(/packing_noviembre\.xlsx/)).toHaveTextContent('packing_noviembre.xlsx · ingreso #3');
    expect(screen.getByText(/Lotes sin packing list/)).toBeInTheDocument();
    expect(screen.getByText('1 de 3 tratamientos')).toBeInTheDocument();
    expect(screen.getByDisplayValue('CI2')).toBeInTheDocument();
  });

  it('si el stock cambió no deja consolidar y ofrece recalcular', () => {
    const onRecalculate = vi.fn();
    render(
      <DistributionWorkspace
        detail={detail({ stock_vigente: false, stock_cambios: ['Basaglar (lote B-1): ingresó después del cálculo (3 envases)'] })}
        onChange={vi.fn()}
        onRecalculate={onRecalculate}
      />
    );
    expect(screen.getByRole('alert')).toHaveTextContent('El stock cambió');
    expect(screen.getByRole('button', { name: /Consolidar/ })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /Volver a calcular/ }));
    expect(onRecalculate).toHaveBeenCalled();
  });
});

// --------------------------------------------------------------------------------------------- historial
const origen = (ingreso_id, archivo, envases) => ({
  ingreso_id, archivo, ingresado_at: ingreso_id ? '2026-09-01T15:00:00Z' : null, lotes: 1, envases, ui: envases * 300,
});

const reparto = (id, estado, fecha, ingresos, extra = {}) => ({
  id, estado, dias: 60, created_at: fecha, autor: 'admin@test.com',
  consolidated_at: estado === 'CONSOLIDADO' ? fecha : null, consolidado_por: null,
  discarded_at: estado === 'DESCARTADO' ? fecha : null, beneficiarios: 3,
  envases: ingresos.reduce((s, o) => s + o.envases, 0), asignado_ui: ingresos.reduce((s, o) => s + o.ui, 0),
  intercambios: 0, ingresos, ...extra,
});

const historial = () => [
  reparto(4, 'BORRADOR', '2026-11-20T15:00:00Z', [origen(3, 'packing_noviembre.xlsx', 10), origen(2, 'packing_octubre.xlsx', 2)]),
  reparto(3, 'DESCARTADO', '2026-11-19T15:00:00Z', [origen(3, 'packing_noviembre.xlsx', 12)]),
  reparto(2, 'CONSOLIDADO', '2026-10-15T15:00:00Z', [origen(2, 'packing_octubre.xlsx', 20)]),
  reparto(1, 'CONSOLIDADO', '2026-09-10T15:00:00Z', [origen(1, 'packing_septiembre.xlsx', 14), origen(null, null, 1)]),
];

describe('InsulinPhotosPanel', () => {
  beforeEach(() => vi.clearAllMocks());

  const enLista = (id, tipo, nombre, extra = {}) => ({
    ...fotoAviso(id, tipo, 'https://storage.test/' + id + (tipo === 'hba1c' ? '.pdf' : '.jpg')), beneficiario_id: id,
    nombre_completo: nombre, ci: 'CI' + id, ...extra,
  });

  it('el super admin revisa las fotos por revisar una tras otra: aprueba u observa con el motivo', async () => {
    api.listInsulinPhotos.mockResolvedValue([enLista(1, 'envases', 'Ana Menor'), enLista(2, 'hba1c', 'Beto Adulto')]);
    api.reviewInsulinPhoto.mockImplementation(async (id, { estado, observacion }) => ({
      ...fotoAviso(id, 'envases', 'x'), estado, observacion, revisada_at: '2026-11-26T10:00:00Z', revisada_por: 'admin@test.com',
    }));
    const onCambio = vi.fn();
    render(<InsulinPhotosPanel onCambio={onCambio} />);
    await waitFor(() => expect(api.listInsulinPhotos).toHaveBeenCalledWith({ estado: 'PENDIENTE', q: '' }));
    expect(await screen.findByText('Ana Menor')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Revisar una tras otra \(2\)/ }));
    let dialog = screen.getByRole('dialog', { name: 'Revisar foto' });
    expect(within(dialog).getByText('Insulinas ya usadas · Ana Menor')).toBeInTheDocument();
    expect(within(dialog).getByRole('img', { name: 'Insulinas ya usadas de Ana Menor' })).toHaveAttribute(
      'src', 'https://storage.test/1.jpg'
    );
    expect(within(dialog).getByText('Quedan 1 foto(s) más por revisar.')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: /Aprobar/ }));
    await waitFor(() => expect(api.reviewInsulinPhoto).toHaveBeenCalledWith(1, { estado: 'APROBADA', observacion: null }));

    // Se abre sola la siguiente, y la aprobada sale de «Por revisar».
    dialog = await screen.findByRole('dialog', { name: 'Revisar foto' });
    expect(within(dialog).getByText('Hemoglobina glucosilada (HbA1c) · Beto Adulto')).toBeInTheDocument();
    expect(screen.queryByText('Ana Menor')).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: /Observar/ }));
    const enviar = within(dialog).getByRole('button', { name: /Enviar observación/ });
    expect(enviar).toBeDisabled(); // sin motivo no se observa
    fireEvent.change(within(dialog).getByLabelText('Qué debe corregir el beneficiario'), { target: { value: '  No se lee  ' } });
    fireEvent.click(enviar);
    await waitFor(() => expect(api.reviewInsulinPhoto).toHaveBeenLastCalledWith(2, { estado: 'OBSERVADA', observacion: 'No se lee' }));

    // Era la última: se cierra y no queda nada por revisar.
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Revisar foto' })).not.toBeInTheDocument());
    expect(screen.getByText('No hay fotos por revisar.')).toBeInTheDocument();
    expect(onCambio).toHaveBeenCalledTimes(2);
  });

  it('filtra por estado y busca por beneficiario', async () => {
    api.listInsulinPhotos.mockResolvedValue([]);
    render(<InsulinPhotosPanel />);
    expect(await screen.findByText('No hay fotos por revisar.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Estado'), { target: { value: 'OBSERVADA' } });
    await waitFor(() => expect(api.listInsulinPhotos).toHaveBeenLastCalledWith({ estado: 'OBSERVADA', q: '' }));
    fireEvent.change(screen.getByLabelText('Estado'), { target: { value: '' } });
    await waitFor(() => expect(api.listInsulinPhotos).toHaveBeenLastCalledWith({ estado: null, q: '' }));
    fireEvent.change(screen.getByLabelText('Buscar beneficiario'), { target: { value: 'rosa' } });
    await waitFor(() => expect(api.listInsulinPhotos).toHaveBeenLastCalledWith({ estado: null, q: 'rosa' }));
    expect(await screen.findByText('No hay fotos con ese filtro.')).toBeInTheDocument();
  });
});

describe('filtros del historial', () => {
  it('por estado (sin descartados de entrada), por fechas y por packing list', () => {
    const h = historial();
    const ids = (filtros) => filterHistory(h, { ...FILTROS_INICIALES, ...filtros }).map((r) => r.id);
    expect(ids({})).toEqual([4, 2, 1]);
    expect(ids({ estado: 'todos' })).toEqual([4, 3, 2, 1]);
    expect(ids({ estado: 'CONSOLIDADO' })).toEqual([2, 1]);
    expect(ids({ estado: 'DESCARTADO' })).toEqual([3]);
    expect(ids({ desde: '2026-10-01' })).toEqual([4, 2]);
    expect(ids({ desde: '2026-10-01', hasta: '2026-10-31' })).toEqual([2]);
    expect(ids({ ingreso: '2' })).toEqual([4, 2]); // el sobrante de octubre también salió en el reparto 4
    expect(ids({ ingreso: 'sin' })).toEqual([1]);
    expect(packingListOptions(h).map((o) => o.value)).toEqual(['3', '2', '1', 'sin']);
    expect(totalesConsolidados(filterHistory(h, FILTROS_INICIALES))).toEqual({ repartos: 2, envases: 35, ui: 10500 });
  });
});

describe('DistributionHistoryPanel', () => {
  beforeEach(() => vi.clearAllMocks());

  it('muestra los packing lists de cada reparto y filtra', () => {
    const onOpen = vi.fn();
    render(<DistributionHistoryPanel history={historial()} onOpen={onOpen} />);
    expect(screen.getByText('3 de 4 reparto(s)', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('packing_septiembre.xlsx · 14 env.')).toBeInTheDocument();
    expect(screen.getByText('Lotes sin packing list · 1 env.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ver el reparto #3' })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Packing list'), { target: { value: '2' } });
    expect(screen.getByRole('button', { name: 'Ver el reparto #4' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ver el reparto #2' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ver el reparto #1' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Limpiar filtros' }));
    fireEvent.change(screen.getByLabelText('Estado'), { target: { value: 'DESCARTADO' } });
    fireEvent.click(screen.getByRole('button', { name: 'Ver el reparto #3' }));
    expect(onOpen).toHaveBeenCalledWith(3);
  });

  it('busca a un beneficiario y muestra lo que recibió en cada reparto', async () => {
    api.searchDistributionBeneficiaries.mockResolvedValue([
      { beneficiario_id: 1, nombre_completo: 'Ana Menor', ci: 'CI1', registro_asistido: false, repartos: 2, ultimo_reparto: '2026-11-20T15:00:00Z' },
    ]);
    const entrega = (distribution_id, estado, fecha, lotes) => ({
      distribution_id, estado, dias: 60, created_at: fecha, consolidated_at: estado === 'CONSOLIDADO' ? fecha : null,
      envases: lotes.reduce((s, l) => s + l.unidades, 0), ui: lotes.reduce((s, l) => s + l.ui, 0), intercambios: 0,
      paciente: paciente(1, 'Ana Menor', 1, [insulina('Glargina', lotes)]),
    });
    api.getBeneficiaryDistributions.mockResolvedValue({
      beneficiario_id: 1, nombre_completo: 'Ana Menor', ci: 'CI1', registro_asistido: false,
      repartos: [
        entrega(4, 'BORRADOR', '2026-11-20T15:00:00Z', [lote(31, 'Lantus SoloStar 3 ml', 4)]),
        entrega(2, 'CONSOLIDADO', '2026-10-15T15:00:00Z', [lote(21, 'Lantus SoloStar 3 ml', 3)]),
        entrega(1, 'CONSOLIDADO', '2026-09-10T15:00:00Z', [lote(11, 'Lantus SoloStar 3 ml', 4)]),
      ],
    });
    const onOpen = vi.fn();
    render(<DistributionHistoryPanel history={historial()} onOpen={onOpen} />);

    fireEvent.change(screen.getByLabelText('Beneficiario'), { target: { value: 'ana' } });
    fireEvent.click(await screen.findByRole('button', { name: /Ana Menor/ }));
    expect(api.searchDistributionBeneficiaries).toHaveBeenCalledWith('ana', false);
    await waitFor(() => expect(api.getBeneficiaryDistributions).toHaveBeenCalledWith(1, false));

    expect(await screen.findByText('4 × Lantus SoloStar 3 ml (lote L-31, vence 2027-12-31)')).toBeInTheDocument();
    expect(screen.getByText('3 × Lantus SoloStar 3 ml (lote L-21, vence 2027-12-31)')).toBeInTheDocument();
    expect(screen.getByText(/Recibió en/)).toHaveTextContent('Recibió en 2 reparto(s) consolidado(s): 7 envases');

    // Los filtros del historial también valen para la persona.
    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2026-10-01' } });
    expect(screen.queryByText('4 × Lantus SoloStar 3 ml (lote L-11, vence 2027-12-31)')).not.toBeInTheDocument();
    expect(screen.getByText(/Recibió en/)).toHaveTextContent('Recibió en 1 reparto(s) consolidado(s): 3 envases');

    fireEvent.click(screen.getByRole('button', { name: 'Ver el reparto #2' }));
    expect(onOpen).toHaveBeenCalledWith(2, 'CI1');
  });
});

describe('WarehouseIntakePanel', () => {
  beforeEach(() => vi.clearAllMocks());

  it('revisa el Excel y no deja ingresar si hay filas con error', async () => {
    api.listDonationIntakes.mockResolvedValue([]);
    api.previewDonationIntake.mockResolvedValue({
      archivo: 'donacion.xlsx', filas_leidas: 2, envases: 10, ui_total: 3000, puede_ingresar: false, ingreso_previo: null,
      errores: [{ fila: 3, producto: 'Abasaglar KwikPen 3 ml', mensaje: 'NRO LOTE es obligatorio en el almacén' }],
      filas: [
        { fila: 2, producto: 'Lantus SoloStar 3 ml', insulina: 'Glargina', cantidad: 5, presentacion_ml: 3, concentracion_ui_ml: 100,
          ui_por_envase: 300, ui_total: 1500, lote: 'L-1', fecha_venc: '2027-12-31' },
        { fila: 3, producto: 'Abasaglar KwikPen 3 ml', insulina: 'Glargina', cantidad: 5, presentacion_ml: 3, concentracion_ui_ml: 100,
          ui_por_envase: 300, ui_total: 1500, lote: null, fecha_venc: '2027-12-31' },
      ],
    });
    render(<WarehouseIntakePanel />);
    const file = new File(['x'], 'donacion.xlsx');
    fireEvent.change(screen.getByLabelText('Excel de la donación (.xlsx)'), { target: { files: [file] } });
    fireEvent.click(screen.getByRole('button', { name: /Revisar/ }));
    expect(await screen.findByText(/1 fila\(s\) con error/)).toBeInTheDocument();
    expect(screen.getByText(/NRO LOTE es obligatorio/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Ingresar al almacén/ })).toBeDisabled();
    expect(api.createDonationIntake).not.toHaveBeenCalled();
  });

  it('ingresa el Excel cuando la revisión está limpia', async () => {
    api.listDonationIntakes.mockResolvedValue([]);
    api.previewDonationIntake.mockResolvedValue({
      archivo: 'donacion.xlsx', filas_leidas: 1, envases: 5, ui_total: 1500, puede_ingresar: true, ingreso_previo: null,
      errores: [],
      filas: [{ fila: 2, producto: 'Lantus SoloStar 3 ml', insulina: 'Glargina', cantidad: 5, presentacion_ml: 3,
        concentracion_ui_ml: 100, ui_por_envase: 300, ui_total: 1500, lote: 'L-1', fecha_venc: '2027-12-31' }],
    });
    api.createDonationIntake.mockResolvedValue({ id: 1, lotes_creados: 1, envases: 5 });
    const onIngresado = vi.fn();
    render(<WarehouseIntakePanel onIngresado={onIngresado} />);
    fireEvent.change(screen.getByLabelText('Excel de la donación (.xlsx)'), { target: { files: [new File(['x'], 'donacion.xlsx')] } });
    fireEvent.click(screen.getByRole('button', { name: /Revisar/ }));
    fireEvent.click(await screen.findByRole('button', { name: /Ingresar al almacén/ }));
    await waitFor(() => expect(api.createDonationIntake).toHaveBeenCalled());
    await waitFor(() => expect(onIngresado).toHaveBeenCalled());
  });
});
