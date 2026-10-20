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

const items = () => [
  { id: 11, patient_id: 1, patient_nombre: 'Ana Quispe', patient_ci: '111', depto: 'La Paz', periodo: '2026-04', monto: 70, fecha_pago: '2026-04-10', metodo_pago: 'VOUCHER', estado: 'ACEPTADO' },
  { id: 12, patient_id: 1, patient_nombre: 'Ana Quispe', patient_ci: '111', depto: 'La Paz', periodo: '2026-05', monto: 70, fecha_pago: '2026-05-09', metodo_pago: 'EFECTIVO', estado: 'ACEPTADO' },
  { id: 13, patient_id: 2, patient_nombre: 'Beto Mamani', patient_ci: '222', depto: 'Cochabamba', periodo: '2026-05', monto: 70, fecha_pago: '2026-05-11', metodo_pago: 'VOUCHER', estado: 'DECLARADO' },
];

// Con periodo elegido: una fila por beneficiario y una columna por mes.
const reportePorMes = () => ({
  periodo: null,
  periodo_desde: '2026-04',
  periodo_hasta: '2026-05',
  meses: ['2026-04', '2026-05'],
  total_aceptados: 2,
  total_declarados: 1,
  total_observados: 0,
  total_beneficiarios: 2,
  items: items(),
  beneficiarios: [
    { patient_id: 1, patient_nombre: 'Ana Quispe', patient_ci: '111', depto: 'La Paz', monto: 70, fecha_pago: '2026-05-09', metodo_pago: 'EFECTIVO', meses: { '2026-04': 'ACEPTADO', '2026-05': 'ACEPTADO' } },
    { patient_id: 2, patient_nombre: 'Beto Mamani', patient_ci: '222', depto: 'Cochabamba', monto: 70, fecha_pago: '2026-05-11', metodo_pago: 'VOUCHER', meses: { '2026-04': 'NO_REGISTRADO', '2026-05': 'DECLARADO' } },
    { patient_id: 3, patient_nombre: 'Carla Rojas', patient_ci: '333', depto: 'Oruro', monto: 70, fecha_pago: '2026-04-20', metodo_pago: 'EFECTIVO', meses: { '2026-04': 'OBSERVADO', '2026-05': 'NO_REGISTRADO' } },
    { patient_id: 4, patient_nombre: 'Diego Vela', patient_ci: '444', depto: 'Oruro', exonerado: true, monto: null, fecha_pago: null, metodo_pago: null, meses: { '2026-04': 'EXONERADO', '2026-05': 'EXONERADO' } },
  ],
});

// Sin periodo: una fila por voucher.
const reportePlano = () => ({
  periodo: null,
  periodo_desde: null,
  periodo_hasta: null,
  meses: [],
  total_aceptados: 2,
  total_declarados: 1,
  total_observados: 0,
  total_beneficiarios: 2,
  items: items(),
  beneficiarios: [],
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

describe('Historial de Aportes: con periodo, una columna por mes', () => {
  it('pide el rango elegido y muestra el estado del aporte de cada beneficiario en cada mes', async () => {
    api.getContributionsReport.mockResolvedValue(reportePorMes());
    render(<ContributionsHistoryReport />);

    await screen.findByText('Ana Quispe');
    // al abrir: el mes en curso, desde y hasta
    expect(api.getContributionsReport).toHaveBeenLastCalledWith({ desde: hoy, hasta: hoy, depto: '' });

    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2026-04' } });
    fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2026-05' } });
    fireEvent.change(screen.getByLabelText('Departamento'), { target: { value: 'La Paz' } });
    await waitFor(() =>
      expect(api.getContributionsReport).toHaveBeenLastCalledWith({ desde: '2026-04', hasta: '2026-05', depto: 'La Paz' }),
    );

    // Beneficiario … Método y luego un encabezado por mes (ya no «Estado» ni «Periodo»)
    const encabezados = screen.getAllByRole('columnheader').map((th) => th.textContent);
    expect(encabezados).toEqual([
      'Beneficiario', 'CI', 'Departamento', 'Monto (Bs.)', 'Fecha de pago', 'Método', 'Abril 2026', 'Mayo 2026',
    ]);

    // una fila por beneficiario (Ana ya no se repite por voucher)
    const tabla = within(screen.getByRole('table'));
    expect(tabla.getAllByText('Ana Quispe')).toHaveLength(1);
    const filaBeto = tabla.getByText('Beto Mamani').closest('tr');
    expect(within(filaBeto).getByText('No Registrado')).toBeInTheDocument();
    expect(within(filaBeto).getByText('Declarado')).toBeInTheDocument();
    const filaAna = tabla.getByText('Ana Quispe').closest('tr');
    expect(within(filaAna).getAllByText('Aceptado')).toHaveLength(2);
    // un voucher rechazado se informa como «Observado»
    const filaCarla = tabla.getByText('Carla Rojas').closest('tr');
    expect(within(filaCarla).getByText('Observado')).toBeInTheDocument();
    expect(within(filaCarla).getByText('No Registrado')).toBeInTheDocument();
    // un exonerado sin voucher figura como «Exonerado», no como «No Registrado»
    const filaDiego = tabla.getByText('Diego Vela').closest('tr');
    expect(within(filaDiego).getAllByText('Exonerado')).toHaveLength(2);
    expect(within(filaDiego).queryByText('No Registrado')).toBeNull();
  });

  it('el Excel lleva los datos del beneficiario y, a la derecha, una columna por mes con el estado', async () => {
    api.getContributionsReport.mockResolvedValue(reportePorMes());
    render(<ContributionsHistoryReport />);
    await screen.findByText('Ana Quispe');

    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    const filas = xlsx.json_to_sheet.mock.calls[0][0];
    expect(filas).toHaveLength(4);
    expect(Object.keys(filas[0])).toEqual([
      'Beneficiario', 'CI', 'Departamento', 'Monto (Bs.)', 'Fecha de pago', 'Método', 'Abril 2026', 'Mayo 2026',
    ]);
    expect(filas.map((f) => [f.Beneficiario, f['Abril 2026'], f['Mayo 2026']])).toEqual([
      ['Ana Quispe', 'Aceptado', 'Aceptado'],
      ['Beto Mamani', 'No Registrado', 'Declarado'],
      ['Carla Rojas', 'Observado', 'No Registrado'],
      ['Diego Vela', 'Exonerado', 'Exonerado'],
    ]);
    expect(xlsx.writeFile.mock.calls[0][1]).toMatch(/^Historial_Aportes_.*\.xlsx$/);
  });

  it('no consulta si «Desde» es posterior a «Hasta» ni si el rango pasa de 4 meses', async () => {
    api.getContributionsReport.mockResolvedValue(reportePorMes());
    render(<ContributionsHistoryReport />);
    await screen.findByText('Ana Quispe');
    api.getContributionsReport.mockClear();

    fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2020-01' } });
    await new Promise((r) => setTimeout(r, 50));
    expect(api.getContributionsReport).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2019-12' } });
    fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2020-04' } }); // 5 meses
    await new Promise((r) => setTimeout(r, 50));
    expect(api.getContributionsReport).not.toHaveBeenCalledWith({ desde: '2019-12', hasta: '2020-04', depto: '' });

    fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2020-03' } }); // 4 meses: sí
    await waitFor(() =>
      expect(api.getContributionsReport).toHaveBeenLastCalledWith({ desde: '2019-12', hasta: '2020-03', depto: '' }),
    );
  });
});

describe('Historial de Aportes: sin periodo se mantiene la tabla por voucher', () => {
  it('«Todos los periodos» lista cada voucher con su estado y su periodo', async () => {
    api.getContributionsReport.mockResolvedValueOnce(reportePorMes()).mockResolvedValue(reportePlano());
    render(<ContributionsHistoryReport />);
    await screen.findByText('Ana Quispe');

    fireEvent.click(screen.getByLabelText('Todos los periodos'));
    await waitFor(() => expect(api.getContributionsReport).toHaveBeenLastCalledWith({ depto: '' }));
    await waitFor(() => expect(screen.getAllByText('Ana Quispe')).toHaveLength(2));

    const encabezados = screen.getAllByRole('columnheader').map((th) => th.textContent);
    expect(encabezados).toEqual([
      'Beneficiario', 'CI', 'Departamento', 'Monto (Bs.)', 'Fecha de pago', 'Método', 'Estado', 'Periodo',
    ]);

    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    const filas = xlsx.json_to_sheet.mock.calls[0][0];
    expect(Object.keys(filas[0])).toEqual([
      'Beneficiario', 'CI', 'Departamento', 'Monto (Bs.)', 'Fecha de pago', 'Método', 'Estado', 'Periodo', 'Mes',
    ]);
    expect(filas.map((f) => [f.Beneficiario, f.Periodo])).toEqual([
      ['Ana Quispe', '2026-04'],
      ['Ana Quispe', '2026-05'],
      ['Beto Mamani', '2026-05'],
    ]);
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
