import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import DynamicBeneficiaryReport from '../pages/reports/DynamicBeneficiaryReport';
import DonationRequestReport from '../pages/reports/DonationRequestReport';
import { formatComplications, formatEvolutionTime, formatTreatments } from '../utils/beneficiaryFormat';

const api = vi.hoisted(() => ({
  getPatients: vi.fn(),
  getContributionsReview: vi.fn(),
  getDonationRequestReport: vi.fn(),
}));
const xlsx = vi.hoisted(() => ({
  json_to_sheet: vi.fn(() => ({})),
  aoa_to_sheet: vi.fn(() => ({})),
  book_new: vi.fn(() => ({})),
  book_append_sheet: vi.fn(),
  writeFile: vi.fn(),
}));

vi.mock('../api/patients', () => ({ getPatients: api.getPatients }));
vi.mock('../api/contributions', () => ({ getContributionsReview: api.getContributionsReview }));
vi.mock('../api/reports', () => ({ getDonationRequestReport: api.getDonationRequestReport }));
vi.mock('xlsx', () => ({
  utils: {
    json_to_sheet: xlsx.json_to_sheet,
    aoa_to_sheet: xlsx.aoa_to_sheet,
    book_new: xlsx.book_new,
    book_append_sheet: xlsx.book_append_sheet,
  },
  writeFile: xlsx.writeFile,
}));
vi.mock('react-hot-toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('../utils/imageToBase64', () => ({ imageToBase64: () => Promise.resolve('data:image/png;base64,AAAA') }));

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  xlsx.json_to_sheet.mockClear();
  xlsx.aoa_to_sheet.mockClear();
  xlsx.writeFile.mockClear();
});

describe('formato de los datos clínicos', () => {
  it('tratamiento: una insulina por línea con su dosis diaria', () => {
    expect(
      formatTreatments([
        { nombre: 'Glargina', dosis_diaria: 40 },
        { nombre: 'Glulisina', dosis_diaria: 25.0 },
        { nombre: 'Lispro', dosis_diaria: 12.5 },
        { nombre: 'NPH', dosis_diaria: 0 },
      ]),
    ).toBe('Glargina: 40 UI al día\nGlulisina: 25 UI al día\nLispro: 12.5 UI al día\nNPH');
    expect(formatTreatments([])).toBe('-');
    expect(formatTreatments(undefined)).toBe('-');
  });

  it('complicaciones: una por línea; «Otras» se separa por comas y no se repite', () => {
    expect(
      formatComplications([
        { complication_code: 'NEUROPATIA' },
        { complication_code: 'OTRAS', detalle: 'Hipertensión, hipotiroidismo;  neuropatía ' },
        { complication_code: 'PIE_DIABETICO' },
      ]),
    ).toBe('Neuropatía\nHipertensión\nHipotiroidismo\nPie diabético');
    expect(formatComplications([{ complication_code: 'OTRAS', detalle: ' ' }])).toBe('-');
    expect(formatComplications([])).toBe('-');
  });

  it('tiempo de evolución: los años tal como se registraron', () => {
    expect(formatEvolutionTime({ tiempo_enfermedad: '8 años' })).toBe('8 años');
    expect(formatEvolutionTime({ tiempo_enfermedad: null })).toBe('-');
    expect(formatEvolutionTime(null)).toBe('-');
  });
});

const beneficiario = {
  id: 1,
  nombres: 'Ana',
  ap_paterno: 'Quispe',
  ap_materno: 'Rojas',
  ci: '111',
  estado: 'ACTIVO',
  fecha_nac: '2012-03-04',
  tutor: { nombres: 'Rosa', apellidos: 'Quispe', ci: '9876543' },
  medical: { tipo_diabetes: 'Tipo 1', tiempo_enfermedad: '8 años' },
  treatments: [
    { id: 1, nombre: 'Glargina', dosis_diaria: 40 },
    { id: 2, nombre: 'Glulisina', dosis_diaria: 25 },
  ],
  complications: [
    { id: 1, complication_code: 'OTRAS', detalle: 'Hipertensión, Hipotiroidismo' },
    { id: 2, complication_code: 'NEUROPATIA' },
  ],
};

describe('Reporte de beneficiarios: columnas nuevas', () => {
  it('ofrece C.I. Tutor, Tratamiento, Tiempo de Evolución y Complicaciones/Otros y las muestra con el formato pedido', async () => {
    api.getPatients.mockResolvedValue([beneficiario]);
    api.getContributionsReview.mockResolvedValue([]);
    render(<DynamicBeneficiaryReport />);
    await screen.findByText('Quispe');

    fireEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    ['C.I. Tutor', 'Tratamiento', 'Tiempo de Evolución', 'Complicaciones/Otros'].forEach((label) => {
      fireEvent.click(screen.getByLabelText(label));
    });

    const celda = (texto) => screen.getByText((_, el) => el.tagName === 'TD' && el.textContent === texto);
    expect(celda('9876543')).toBeInTheDocument(); // solo el número, sin el nombre del tutor
    expect(celda('Glargina: 40 UI al día\nGlulisina: 25 UI al día')).toBeInTheDocument();
    expect(celda('8 años')).toBeInTheDocument();
    expect(celda('Hipertensión\nHipotiroidismo\nNeuropatía')).toBeInTheDocument();
  });

  it('el Excel lleva las columnas nuevas con una línea por tratamiento y por complicación', async () => {
    api.getPatients.mockResolvedValue([beneficiario]);
    api.getContributionsReview.mockResolvedValue([]);
    render(<DynamicBeneficiaryReport />);
    await screen.findByText('Quispe');

    fireEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    ['C.I. Tutor', 'Tratamiento', 'Tiempo de Evolución', 'Complicaciones/Otros'].forEach((label) => {
      fireEvent.click(screen.getByLabelText(label));
    });
    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));

    const [fila] = xlsx.json_to_sheet.mock.calls[0][0];
    expect(fila['C.I. Tutor']).toBe('9876543');
    expect(fila.Tratamiento).toBe('Glargina: 40 UI al día\nGlulisina: 25 UI al día');
    expect(fila['Tiempo de Evolución']).toBe('8 años');
    expect(fila['Complicaciones/Otros']).toBe('Hipertensión\nHipotiroidismo\nNeuropatía');
  });
});

const solicitud = () => ({
  dias: 60,
  estados_considerados: ['ACTIVO', 'PENDIENTE_DOC', 'HABILITADO'],
  total_beneficiarios: 208,
  sin_insulina_registrada: 3,
  insulinas: [
    { insulina: 'Glargina', cantidad_ui: 125400, beneficiarios: 90 },
    { insulina: 'Lispro', cantidad_ui: 48000, beneficiarios: 40 },
  ],
  menores_18: { cantidad: 30, porcentaje: 14.4 },
  entre_18_y_60: { cantidad: 140, porcentaje: 67.3 },
  mayores_61: { cantidad: 38, porcentaje: 18.3 },
  diabeticos_tipo_1: { cantidad: 134, porcentaje: 64.4 },
  diabeticos_tipo_2: { cantidad: 73, porcentaje: 35.1 },
});

describe('Reporte de solicitud de cantidades requeridas de donación', () => {
  it('muestra el cuadro por tipo de insulina y, debajo, los porcentajes y el total', async () => {
    api.getDonationRequestReport.mockResolvedValue(solicitud());
    render(<DonationRequestReport />);

    await screen.findByText('Glargina');
    const encabezados = screen.getAllByRole('columnheader').map((th) => th.textContent);
    expect(encabezados).toEqual(['Tipo de insulina', 'Cantidad requerida (60 días)']);
    expect(screen.getByText(`${(125400).toLocaleString('es-BO')} UI`)).toBeInTheDocument();
    expect(screen.getByText('Lispro')).toBeInTheDocument();

    // dos bloques con título: rango etario y tipo de diabetes
    expect(screen.getByText('Porcentajes por Rango Etario')).toBeInTheDocument();
    expect(screen.getByText('Porcentaje por Tipo de Diabetes')).toBeInTheDocument();
    const dato = (etiqueta) => screen.getByText(etiqueta).nextSibling.textContent;
    expect(dato('Porcentaje de beneficiarios menores de 18 años')).toMatch(/^14,4\s?%$/);
    expect(dato('Porcentaje de beneficiarios entre 18 y 60 años')).toMatch(/^67,3\s?%$/);
    expect(dato('Porcentaje de adultos mayores de 61 años en adelante')).toMatch(/^18,3\s?%$/);
    expect(dato('Porcentaje de diabéticos tipo 1')).toMatch(/^64,4\s?%$/);
    expect(dato('Porcentaje de diabéticos tipo 2 insulino requirentes')).toMatch(/^35,1\s?%$/);
    expect(dato('Total de beneficiarios')).toBe('208');
    // el texto aclaratorio sobre aporte y documentos ya no va en el encabezado
    expect(screen.queryByText(/estén o no al día/)).toBeNull();
  });

  it('el Excel trae el cuadro, una fila en blanco y los datos finales con el total al final', async () => {
    api.getDonationRequestReport.mockResolvedValue(solicitud());
    render(<DonationRequestReport />);
    await screen.findByText('Glargina');

    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    await waitFor(() => expect(xlsx.writeFile).toHaveBeenCalledTimes(1));
    const filas = xlsx.aoa_to_sheet.mock.calls[0][0];
    expect(filas[0]).toEqual(['Tipo de insulina', 'Cantidad requerida (60 días)']);
    expect(filas[1]).toEqual(['Glargina', 125400]);
    expect(filas[3]).toEqual([]);
    expect(filas[4]).toEqual(['Porcentajes por Rango Etario']);
    expect(filas[7]).toEqual(['Porcentaje de adultos mayores de 61 años en adelante', expect.stringMatching(/^18,3\s?%$/)]);
    expect(filas[8]).toEqual(['Porcentaje por Tipo de Diabetes']);
    expect(filas[filas.length - 1]).toEqual(['Total de beneficiarios', '208']);
    expect(xlsx.writeFile.mock.calls[0][1]).toMatch(/^Solicitud_Donacion_.*\.xlsx$/);
  });
});
