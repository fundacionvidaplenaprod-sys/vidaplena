import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import ContributionsHistoryReport from '../pages/reports/ContributionsHistoryReport';
import VoucherControlReport from '../pages/reports/VoucherControlReport';

const api = vi.hoisted(() => ({
  getContributionsReport: vi.fn(),
  getContributionsReview: vi.fn(),
  downloadVouchersControlPdf: vi.fn(),
}));
const xlsx = vi.hoisted(() => ({
  json_to_sheet: vi.fn((rows) => ({ rows, '!ref': 'A1:H9' })),
  book_new: vi.fn(() => ({})),
  book_append_sheet: vi.fn(),
  writeFile: vi.fn(),
}));

vi.mock('../api/reports', () => ({ getContributionsReport: api.getContributionsReport }));
vi.mock('../api/contributions', () => ({
  getContributionsReview: api.getContributionsReview,
  downloadVouchersControlPdf: api.downloadVouchersControlPdf,
  periodLabel: ({ periodo, desde, hasta } = {}) =>
    periodo || (desde && hasta ? (desde === hasta ? desde : `${desde}_a_${hasta}`) : 'TODOS'),
}));
vi.mock('xlsx', () => ({
  utils: { json_to_sheet: xlsx.json_to_sheet, book_new: xlsx.book_new, book_append_sheet: xlsx.book_append_sheet },
  writeFile: xlsx.writeFile,
}));
vi.mock('react-hot-toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('../utils/imageToBase64', () => ({ imageToBase64: () => Promise.resolve('data:image/png;base64,AAAA') }));

const hoy = new Date().toISOString().slice(0, 7);

const reporte = () => ({
  periodo: null,
  periodo_desde: '2026-04',
  periodo_hasta: '2026-05',
  total_aceptados: 2,
  total_declarados: 1,
  total_observados: 0,
  total_beneficiarios: 2,
  items: [
    { id: 11, patient_id: 1, patient_nombre: 'Ana Quispe', patient_ci: '111', depto: 'La Paz', periodo: '2026-04', monto: 70, fecha_pago: '2026-04-10', metodo_pago: 'VOUCHER', estado: 'ACEPTADO' },
    { id: 12, patient_id: 1, patient_nombre: 'Ana Quispe', patient_ci: '111', depto: 'La Paz', periodo: '2026-05', monto: 70, fecha_pago: '2026-05-09', metodo_pago: 'EFECTIVO', estado: 'ACEPTADO' },
    { id: 13, patient_id: 2, patient_nombre: 'Beto Mamani', patient_ci: '222', depto: 'Cochabamba', periodo: '2026-05', monto: 70, fecha_pago: '2026-05-11', metodo_pago: 'VOUCHER', estado: 'DECLARADO' },
  ],
});

const vouchers = () => [
  { id: 21, patient_id: 1, patient_nombre: 'Ana Quispe', patient_ci: '111', depto: 'La Paz', periodo: '2026-04', fecha_pago: '2026-04-10', monto: 70, estado: 'ACEPTADO', url_comprobante: 'https://x.test/a.jpg' },
  { id: 22, patient_id: 1, patient_nombre: 'Ana Quispe', patient_ci: '111', depto: 'La Paz', periodo: '2026-05', fecha_pago: '2026-05-09', monto: 70, estado: 'ACEPTADO', url_comprobante: null },
  { id: 23, patient_id: 2, patient_nombre: 'Beto Mamani', patient_ci: '222', depto: null, periodo: '2026-05', fecha_pago: '2026-05-11', monto: 70, estado: 'DECLARADO', url_comprobante: 'https://x.test/b.jpg' },
];

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  xlsx.json_to_sheet.mockClear();
  xlsx.writeFile.mockClear();
});

describe('Historial de Aportes: rango de periodos y departamento', () => {
  it('pide el rango elegido y muestra una fila por voucher con su departamento y periodo', async () => {
    api.getContributionsReport.mockResolvedValue(reporte());
    render(<ContributionsHistoryReport />);

    await screen.findAllByText('Ana Quispe');
    // al abrir: el mes en curso, desde y hasta
    expect(api.getContributionsReport).toHaveBeenLastCalledWith({ desde: hoy, hasta: hoy, depto: '' });

    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2026-04' } });
    fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2026-10' } });
    fireEvent.change(screen.getByLabelText('Departamento'), { target: { value: 'La Paz' } });
    await waitFor(() =>
      expect(api.getContributionsReport).toHaveBeenLastCalledWith({ desde: '2026-04', hasta: '2026-10', depto: 'La Paz' }),
    );

    // dos vouchers de Ana (uno por periodo) más el de Beto
    expect(screen.getAllByText('Ana Quispe')).toHaveLength(2);
    const encabezados = screen.getAllByRole('columnheader').map((th) => th.textContent);
    expect(encabezados).toEqual([
      'Beneficiario', 'CI', 'Departamento', 'Monto (Bs.)', 'Fecha de pago', 'Método', 'Estado', 'Periodo',
    ]);
    expect(within(screen.getByRole('table')).getByText('Cochabamba')).toBeInTheDocument();
  });

  it('el Excel lleva el departamento y, a la derecha, el periodo de cada voucher', async () => {
    api.getContributionsReport.mockResolvedValue(reporte());
    render(<ContributionsHistoryReport />);
    await screen.findAllByText('Ana Quispe');

    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    const filas = xlsx.json_to_sheet.mock.calls[0][0];
    expect(filas).toHaveLength(3);
    expect(Object.keys(filas[0])).toEqual([
      'Beneficiario', 'CI', 'Departamento', 'Monto (Bs.)', 'Fecha de pago', 'Método', 'Estado', 'Periodo', 'Mes',
    ]);
    expect(filas.map((f) => [f.Beneficiario, f.Departamento, f.Periodo])).toEqual([
      ['Ana Quispe', 'La Paz', '2026-04'],
      ['Ana Quispe', 'La Paz', '2026-05'],
      ['Beto Mamani', 'Cochabamba', '2026-05'],
    ]);
    expect(xlsx.writeFile).toHaveBeenCalledTimes(1);
    expect(xlsx.writeFile.mock.calls[0][1]).toMatch(/^Historial_Aportes_.*\.xlsx$/);
  });

  it('no consulta si «Desde» es posterior a «Hasta»', async () => {
    api.getContributionsReport.mockResolvedValue(reporte());
    render(<ContributionsHistoryReport />);
    await screen.findAllByText('Ana Quispe');
    api.getContributionsReport.mockClear();

    fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2020-01' } });
    await new Promise((r) => setTimeout(r, 50));
    expect(api.getContributionsReport).not.toHaveBeenCalled();
  });
});

describe('Control de Vouchers: rango, departamento y periodo por fila', () => {
  it('muestra las columnas Departamento y Periodo y pide el rango elegido', async () => {
    api.getContributionsReview.mockResolvedValue(vouchers());
    render(<VoucherControlReport />);
    await screen.findAllByText('Ana Quispe');

    const encabezados = screen.getAllByRole('columnheader').map((th) => th.textContent);
    expect(encabezados).toEqual(['Captura', 'Beneficiario', 'CI', 'Departamento', 'Periodo', 'Fecha de pago', 'Estado']);

    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2026-04' } });
    fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2026-10' } });
    fireEvent.change(screen.getByLabelText('Departamento'), { target: { value: 'Cochabamba' } });
    await waitFor(() =>
      expect(api.getContributionsReview).toHaveBeenLastCalledWith({ desde: '2026-04', hasta: '2026-10', depto: 'Cochabamba' }),
    );

    const fila = screen.getAllByText('Ana Quispe')[0].closest('tr');
    expect(within(fila).getByText('La Paz')).toBeInTheDocument();
    expect(within(fila).getByText('2026-04')).toBeInTheDocument();
  });

  it('«Todos los periodos» no acota por fechas y el PDF recibe los mismos filtros', async () => {
    api.getContributionsReview.mockResolvedValue(vouchers());
    api.downloadVouchersControlPdf.mockResolvedValue();
    render(<VoucherControlReport />);
    await screen.findAllByText('Ana Quispe');

    fireEvent.click(screen.getByLabelText('Todos los periodos'));
    await waitFor(() => expect(api.getContributionsReview).toHaveBeenLastCalledWith({ depto: '' }));
    fireEvent.click(screen.getByRole('button', { name: /Descargar PDF/ }));
    await waitFor(() => expect(api.downloadVouchersControlPdf).toHaveBeenCalledWith({ depto: '' }));
  });

  it('el Excel trae el departamento y el periodo (a la derecha) de cada voucher, y el enlace al comprobante', async () => {
    api.getContributionsReview.mockResolvedValue(vouchers());
    render(<VoucherControlReport />);
    await screen.findAllByText('Ana Quispe');

    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    const filas = xlsx.json_to_sheet.mock.calls[0][0];
    expect(Object.keys(filas[0]).slice(-1)).toEqual(['Periodo']);
    expect(filas.map((f) => [f.Beneficiario, f.Departamento, f.Periodo])).toEqual([
      ['Ana Quispe', 'La Paz', '2026-04'],
      ['Ana Quispe', 'La Paz', '2026-05'],
      ['Beto Mamani', '-', '2026-05'],
    ]);
    expect(filas[0]['Enlace al comprobante']).toBe('https://x.test/a.jpg');
    expect(xlsx.writeFile.mock.calls[0][1]).toMatch(/^Control_Vouchers_.*\.xlsx$/);
  });
});
