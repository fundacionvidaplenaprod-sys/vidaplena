import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import InsulinDistributionReport from '../pages/reports/InsulinDistributionReport';

const api = vi.hoisted(() => ({ generateInsulinDistributionReport: vi.fn() }));
vi.mock('../api/reports', () => api);
vi.mock('react-hot-toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('../utils/imageToBase64', () => ({ imageToBase64: () => Promise.resolve('data:image/png;base64,AAAA') }));

const report = () => ({
  guardado: false,
  dias: 60,
  reserva_pct: 0.1,
  stock_total_ui: 10000,
  reserva_objetivo_ui: 1000,
  reserva_ui: 1050,
  asignado_ui: 8000,
  lotes_considerados: 3,
  lotes_excluidos_consolidados: 0,
  lotes_vencidos: 1,
  lotes_sin_catalogo: 0,
  asignaciones_generadas: 3,
  archivo: 'donacion.xlsx',
  prioritarios_sobre_120: 2,
  registros_por_corregir: [
    {
      patient_id: 50, nombre_completo: 'Eva DosRapidas', ci: '555', estado: 'ACTIVO', es_menor: true,
      grupo: 'RAPIDA', grupo_nombre: 'rápidas',
      insulinas: [{ insulina: 'Lispro', dosis_diaria: 28 }, { insulina: 'Aspart', dosis_diaria: 28 }],
      insulina_usada: 'Lispro', motivo: 'STOCK', sustituto: null, premezcla_descartada: true,
      mensaje: 'Tiene 2 insulinas rápidas registradas (Aspart, Lispro)...',
    },
  ],
  filas_leidas: 5,
  estados_considerados: ['ACTIVO', 'PENDIENTE_DOC', 'HABILITADO'],
  insulinas: [
    {
      insulina: 'Glargina', stock_ui: 10000, necesidad_ui: 12000, reserva_ui: 1050, asignado_ui: 8000,
      faltante_ui: 0, sobrante_ui: 950, pacientes_con_necesidad: 3, pacientes_sin_cubrir: 1,
      sustituido_ui: 600, entregado_como_sustituto_ui: 0,
    },
  ],
  reserva: [{ lot_id: 7, insulina: 'Glargina', producto: 'Abasaglar', unidades: 4, ui: 1050, lote: 'LOTE-ABA', fecha_venc: '2027-01-01' }],
  donacion: [],
  filas_con_error: [
    { fila: 4, producto: 'Lantus viejo', mensaje: 'Vencido el 2026-01-01: no se reparte' },
    { fila: 5, producto: 'Raro', mensaje: '«Zumo» no corresponde al catálogo de insulinas' },
  ],
  excluded_patients: [{ patient_id: 9, nombre_completo: 'Carla SinDosis', motivo: 'Tratamiento de insulina sin dosis diaria registrada' }],
  pacientes: [
    {
      patient_id: 1, nombre_completo: 'Ana Menor', es_menor: true, es_tipo1: true, ci: '111', estado: 'PENDIENTE_DOC',
      insulinas: [{
        insulina: 'Glargina', necesidad_ui: 1200, entregado_ui: 1200, cobertura_pct: 100,
        dosis_diaria_registrada: 48, dosis_diaria_aplicada: 20, dosis_limitada: true,
        lotes: [{ lot_id: 3, producto: 'Lantus SoloStar', unidades: 4, ui: 1200, lote: 'L-LANTUS' }],
      }],
    },
    {
      patient_id: 2, nombre_completo: 'Beto Adulto', es_menor: false, es_tipo1: false, ci: '222', estado: 'HABILITADO',
      insulinas: [{
        insulina: 'Glargina', necesidad_ui: 1200, entregado_ui: 600, cobertura_pct: 50,
        lotes: [{ lot_id: 7, producto: 'Abasaglar', unidades: 2, ui: 600, lote: 'LOTE-ABA' }],
      }],
    },
    {
      patient_id: 3, nombre_completo: 'Dora Sustituida', es_menor: false, es_tipo1: true, ci: '333', estado: 'ACTIVO',
      insulinas: [{
        insulina: 'Glargina', necesidad_ui: 600, entregado_ui: 600, cobertura_pct: 100, sustituto: 'Detemir', sustituto_ui: 600,
        lotes: [{ lot_id: 8, producto: 'Levemir Penfill', unidades: 2, ui: 600, lote: 'L-LEV' }],
      }],
    },
  ],
});

const excel = () =>
  new File(['x'], 'donacion.xlsx', {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });

const elegirArchivoYGenerar = async () => {
  const input = document.querySelector('input[type="file"]');
  fireEvent.change(input, { target: { files: [excel()] } });
  fireEvent.click(screen.getByRole('button', { name: /Generar reporte/ }));
  await screen.findByText('Ana Menor');
};

beforeEach(() => {
  api.generateInsulinDistributionReport.mockReset();
});

describe('InsulinDistributionReport', () => {
  it('no permite generar el reporte sin elegir un archivo', () => {
    render(<InsulinDistributionReport />);
    expect(screen.getByRole('button', { name: /Generar reporte/ })).toBeDisabled();
    expect(api.generateInsulinDistributionReport).not.toHaveBeenCalled();
  });

  it('sube el Excel y muestra reserva, beneficiarios por estado y filas omitidas', async () => {
    api.generateInsulinDistributionReport.mockResolvedValue(report());
    render(<InsulinDistributionReport />);

    await elegirArchivoYGenerar();

    expect(api.generateInsulinDistributionReport).toHaveBeenCalledTimes(1);
    expect(api.generateInsulinDistributionReport.mock.calls[0][0].name).toBe('donacion.xlsx');
    // Cada estado aparece en la tabla y en el selector de estados.
    expect(screen.getAllByText('Pendiente de documentos').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Habilitado').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('4 × Lantus SoloStar (lote L-LANTUS)')).toBeInTheDocument();
    expect(screen.getByText('+ Detemir')).toBeInTheDocument();
    // La cobertura se explica en días (50 % de 60 días = 30 días) y con una leyenda.
    expect(screen.getByText('≈ 30 de 60 días')).toBeInTheDocument();
    expect(screen.getByText(/Cómo leer la cobertura/)).toBeInTheDocument();
    // Tope de 30 UI/día para menores: se ve la dosis registrada y la usada.
    expect(screen.getByText('dosis limitada a 20 UI/día')).toBeInTheDocument();
    expect(screen.getByText('48 → 20 UI/día')).toBeInTheDocument();
    expect(screen.getByText(/2 tratamientos en este reporte/)).toBeInTheDocument();
    // Fichas con dos insulinas del mismo grupo: se avisan para corregirlas.
    expect(screen.getByText('Fichas por corregir (1)')).toBeInTheDocument();
    expect(screen.getByText('Eva DosRapidas')).toBeInTheDocument();
    expect(screen.getByText('Lispro (28 UI/día) + Aspart (28 UI/día)')).toBeInTheDocument();
    // Se muestra cuál de las dos se usó y por qué.
    expect(screen.getByText('tiene stock')).toBeInTheDocument();
    expect(screen.getByText(/premezcla descartada: no sustituye a una basal/)).toBeInTheDocument();
    expect(screen.getByText(/Vencido el 2026-01-01/)).toBeInTheDocument();
    expect(screen.getByText('Carla SinDosis')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /PDF/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Excel/ })).toBeInTheDocument();
  });

  it('filtra por menores, tipo 1, sin cubrir y con sustituto', async () => {
    api.generateInsulinDistributionReport.mockResolvedValue(report());
    render(<InsulinDistributionReport />);
    await elegirArchivoYGenerar();

    fireEvent.click(screen.getByRole('button', { name: 'Menores de 18' }));
    expect(screen.getByText('Ana Menor')).toBeInTheDocument();
    expect(screen.queryByText('Beto Adulto')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Sin cubrir' }));
    expect(screen.getByText('Beto Adulto')).toBeInTheDocument();
    expect(screen.queryByText('Ana Menor')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Con sustituto' }));
    expect(screen.getByText('Dora Sustituida')).toBeInTheDocument();
    expect(screen.queryByText('Beto Adulto')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Tipo 1' }));
    expect(screen.getByText('Ana Menor')).toBeInTheDocument();
    expect(screen.queryByText('Beto Adulto')).not.toBeInTheDocument();
  });

  it('busca por CI y filtra por estado', async () => {
    api.generateInsulinDistributionReport.mockResolvedValue(report());
    render(<InsulinDistributionReport />);
    await elegirArchivoYGenerar();

    fireEvent.change(screen.getByPlaceholderText('Buscar nombre o CI'), { target: { value: '222' } });
    expect(screen.getByText('Beto Adulto')).toBeInTheDocument();
    expect(screen.queryByText('Ana Menor')).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('Buscar nombre o CI'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Estado del beneficiario'), { target: { value: 'ACTIVO' } });
    expect(screen.getByText('Dora Sustituida')).toBeInTheDocument();
    expect(screen.queryByText('Ana Menor')).not.toBeInTheDocument();
  });

  it('muestra el error del servidor y no deja datos viejos', async () => {
    api.generateInsulinDistributionReport.mockRejectedValue('Faltan columnas en el Excel: CANTIDAD');
    render(<InsulinDistributionReport />);
    fireEvent.change(document.querySelector('input[type="file"]'), { target: { files: [excel()] } });
    fireEvent.click(screen.getByRole('button', { name: /Generar reporte/ }));

    await waitFor(() => expect(api.generateInsulinDistributionReport).toHaveBeenCalled());
    expect(screen.getByText(/Selecciona el Excel y pulsa/)).toBeInTheDocument();
    expect(screen.queryByText('Ana Menor')).not.toBeInTheDocument();
  });
});
