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
  listAssisted: vi.fn(),
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
vi.mock('../api/assistedRegistrations', () => ({ listAssistedRegistrations: api.listAssisted }));
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
const pdf = vi.hoisted(() => ({
  doc: {
    internal: { pageSize: { getWidth: () => 216 } },
    setFillColor: vi.fn(), rect: vi.fn(), addImage: vi.fn(), setFontSize: vi.fn(), setTextColor: vi.fn(),
    setFont: vi.fn(), text: vi.fn(), save: vi.fn(), lastAutoTable: { finalY: 100 },
  },
  tables: [],
}));
vi.mock('jspdf', () => ({ default: function JsPdfFalso() { return pdf.doc; } }));
vi.mock('jspdf-autotable', () => ({ default: (doc, options) => pdf.tables.push(options) }));
vi.mock('../utils/imageToBase64', () => ({ imageToBase64: () => Promise.resolve('data:image/png;base64,AAAA') }));

beforeEach(() => {
  localStorage.removeItem('user');
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

  it('una ficha guardada como «Protamina» se muestra como «Mixta»', () => {
    expect(formatTreatments([{ nombre: 'Protamina', dosis_diaria: 30 }, { nombre: ' protamina ', dosis_diaria: 0 }])).toBe(
      'Mixta: 30 UI al día\nMixta',
    );
    expect(formatTreatments([{ nombre: 'Protaphane', dosis_diaria: 10 }])).toBe('Protaphane: 10 UI al día'); // otros nombres no cambian
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

const asistido = {
  id: 5,
  codigo: 'RA-00005',
  estado: 'ACTIVO',
  nombre: 'Apodo Beto',
  ci: '7654321',
  fecha_nacimiento: null,
  edad_aproximada: 35,
  depto: 'Oruro',
  municipio: 'Caracollo',
  tipo_diabetes: 'Tipo 2',
  anios_diabetes: 4,
  complicaciones_otras: 'Hipertensión, neuropatía',
  referente: { id: 3, nombre_completo: 'Rosa Quispe', telefono: '70000000' },
  treatments: [{ id: 1, insulina: 'Protamina', dosis_diaria: 30 }],
};

describe('Reporte de beneficiarios: el Registro Asistido también cuenta', () => {
  it('incluye a las personas del Registro Asistido para quien puede verlas', async () => {
    localStorage.setItem('user', JSON.stringify({ role: 'SUPER_ADMIN' }));
    api.getPatients.mockResolvedValue([beneficiario]);
    api.getContributionsReview.mockResolvedValue([]);
    api.listAssisted.mockResolvedValue([asistido]);
    render(<DynamicBeneficiaryReport />);
    await screen.findByText('Quispe');

    expect(api.listAssisted).toHaveBeenCalledWith({ estado: 'ACTIVO' }); // solo los activos
    expect(screen.getByText('Apodo Beto')).toBeInTheDocument();
    expect(screen.getByText('EXONERADO (REGISTRO ASISTIDO)')).toBeInTheDocument();
    expect(screen.getByText('~35')).toBeInTheDocument(); // edad aproximada

    fireEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    ['Estado', 'Origen', 'Código asistido', 'Tratamiento', 'Tiempo de Evolución', 'Complicaciones/Otros', 'Municipio'].forEach((label) => {
      fireEvent.click(screen.getByLabelText(label));
    });
    const celda = (texto) => screen.getByText((_, el) => el.tagName === 'TD' && el.textContent === texto);
    expect(celda('ASISTIDO')).toBeInTheDocument();
    expect(celda('Registro asistido')).toBeInTheDocument();
    expect(celda('RA-00005')).toBeInTheDocument();
    expect(celda('Mixta: 30 UI al día')).toBeInTheDocument(); // «Protamina» se muestra como «Mixta»
    expect(celda('4 años')).toBeInTheDocument();
    expect(celda('Hipertensión\nNeuropatía')).toBeInTheDocument();
    expect(celda('Ordinario')).toBeInTheDocument();
  });

  it('se busca por código y se filtra por «Registro asistido»', async () => {
    localStorage.setItem('user', JSON.stringify({ role: 'EVALUADOR_SOCIAL' }));
    api.getPatients.mockResolvedValue([beneficiario]);
    api.getContributionsReview.mockResolvedValue([]);
    api.listAssisted.mockResolvedValue([asistido]);
    render(<DynamicBeneficiaryReport />);
    await screen.findByText('Quispe');

    fireEvent.change(screen.getByPlaceholderText('Buscar por nombre o CI...'), { target: { value: 'ra-00005' } });
    expect(screen.getByText('Apodo Beto')).toBeInTheDocument();
    expect(screen.queryByText('Quispe')).toBeNull();
    fireEvent.change(screen.getByPlaceholderText('Buscar por nombre o CI...'), { target: { value: '' } });

    fireEvent.change(screen.getByDisplayValue('Todos los estados'), { target: { value: 'ASISTIDO' } });
    expect(screen.getByText('Apodo Beto')).toBeInTheDocument();
    expect(screen.queryByText('Quispe')).toBeNull();
  });

  it('el Registro Asistido es de acceso restringido: no se pide a quien no puede verlo', async () => {
    localStorage.setItem('user', JSON.stringify({ role: 'REGISTRADOR' }));
    api.getPatients.mockResolvedValue([beneficiario]);
    api.getContributionsReview.mockResolvedValue([]);
    render(<DynamicBeneficiaryReport />);
    await screen.findByText('Quispe');
    expect(api.listAssisted).not.toHaveBeenCalled();
    expect(screen.queryByText('ASISTIDO')).toBeNull();
  });
});

const solicitud = () => ({
  dias: 60,
  estados_considerados: ['ACTIVO', 'PENDIENTE_DOC', 'HABILITADO'],
  total_beneficiarios: 208,
  sin_insulina_registrada: 3,
  insulinas: [
    // los ejemplos de la Fundación: 156.180 UI y 113.820 UI, en viales de 3 ml por concentración
    { insulina: 'Glargina', cantidad_ui: 156180, viales_3ml: { U100: 521, U200: 261, U300: 174 }, viales_10ml: { U100: 157 }, beneficiarios: 90 },
    { insulina: 'NPH', cantidad_ui: 113820, viales_3ml: { U100: 380, U200: 190, U300: 127 }, viales_10ml: { U100: 114 }, beneficiarios: 40 },
  ],
  menores_18: { cantidad: 30, porcentaje: 14.4 },
  entre_18_y_60: { cantidad: 140, porcentaje: 67.3 },
  mayores_61: { cantidad: 38, porcentaje: 18.3 },
  diabeticos_tipo_1: { cantidad: 134, porcentaje: 64.4 },
  diabeticos_tipo_2: { cantidad: 73, porcentaje: 35.1 },
});

// El servidor devuelve, con un reparto, el plan de cada insulina (aquí, los valores del ejemplo 30 % en 10 ml).
const conPlan = (reparto) => ({
  ...solicitud(),
  reparto,
  insulinas: [
    {
      ...solicitud().insulinas[0],
      plan: {
        '3ml_U100': { pct: reparto['3ml_U100'], ui: 36442, envases: 122 },
        '3ml_U200': { pct: reparto['3ml_U200'], ui: 36442, envases: 61 },
        '3ml_U300': { pct: reparto['3ml_U300'], ui: 36442, envases: 41 },
        '10ml_U100': { pct: reparto['10ml_U100'], ui: 46854, envases: 47 },
      },
    },
    {
      ...solicitud().insulinas[1],
      plan: {
        '3ml_U100': { pct: reparto['3ml_U100'], ui: 26558, envases: 89 },
        '3ml_U200': { pct: reparto['3ml_U200'], ui: 26558, envases: 45 },
        '3ml_U300': { pct: reparto['3ml_U300'], ui: 26558, envases: 30 },
        '10ml_U100': { pct: reparto['10ml_U100'], ui: 34146, envases: 35 },
      },
    },
  ],
});

describe('Solicitud de donación: reparto por porcentajes entre presentaciones', () => {
  beforeEach(() => {
    api.getDonationRequestReport.mockImplementation(async (reparto) => (reparto ? conPlan(reparto) : solicitud()));
  });

  it('sin activarlo muestra los escenarios y no manda porcentajes', async () => {
    render(<DonationRequestReport />);
    await screen.findByText('Glargina');
    expect(api.getDonationRequestReport).toHaveBeenLastCalledWith(null);
    expect(screen.queryByLabelText('Vial 10ml U100 (%)')).toBeNull();
  });

  it('propone 30 % en 10 ml y el resto en partes iguales, y muestra los envases por presentación con su porcentaje', async () => {
    render(<DonationRequestReport />);
    await screen.findByText('Glargina');
    fireEvent.click(screen.getByLabelText(/Calcular con un reparto por porcentajes/));

    expect(screen.getByLabelText('Vial 10ml U100 (%)')).toHaveValue(30);
    ['Vial 3ml U100 (%)', 'Vial 3ml U200 (%)', 'Vial 3ml U300 (%)'].forEach((label) => {
      expect(Number(screen.getByLabelText(label).value)).toBeCloseTo(70 / 3, 3);
    });
    expect(screen.getByText(/Suma: 100 %/)).toBeInTheDocument();

    await waitFor(() => expect(api.getDonationRequestReport.mock.calls.at(-1)[0]).toMatchObject({ '10ml_U100': 30 }));
    const enviado = api.getDonationRequestReport.mock.calls.at(-1)[0];
    expect(enviado['3ml_U100'] + enviado['3ml_U200'] + enviado['3ml_U300'] + enviado['10ml_U100']).toBeCloseTo(100, 2); // la parte en tres se redondea a 4 decimales: el servidor tolera 0,05

    await waitFor(() => expect(screen.getAllByRole('columnheader').map((th) => th.textContent)).toEqual([
      'Tipo de insulina', 'Cantidad requerida (60 días)', 'Cant. Vial 3ml U100 (23,33 %)', 'Cant. Vial 3ml U200 (23,33 %)',
      'Cant. Vial 3ml U300 (23,33 %)', 'Cant. Vial 10ml U100 (30 %)',
    ]));
    const celdas = (nombre) => Array.from(screen.getByText(nombre).closest('tr').querySelectorAll('td')).map((td) => td.textContent);
    expect(celdas('Glargina').slice(2)).toEqual(['122', '61', '41', '47']);
    expect(celdas('NPH').slice(2)).toEqual(['89', '45', '30', '35']);
    expect(screen.getByText(/se redondean hacia arriba/)).toBeInTheDocument();
  });

  it('al cambiar el frasco de 10 ml el resto se vuelve a dividir en partes iguales', async () => {
    render(<DonationRequestReport />);
    await screen.findByText('Glargina');
    fireEvent.click(screen.getByLabelText(/Calcular con un reparto por porcentajes/));
    fireEvent.change(screen.getByLabelText('Vial 10ml U100 (%)'), { target: { value: '40' } });
    ['Vial 3ml U100 (%)', 'Vial 3ml U200 (%)', 'Vial 3ml U300 (%)'].forEach((label) => {
      expect(Number(screen.getByLabelText(label).value)).toBeCloseTo(20, 3);
    });
    await waitFor(() => expect(api.getDonationRequestReport.mock.calls.at(-1)[0]['10ml_U100']).toBe(40));
  });

  it('si los porcentajes no suman 100 avisa y no pide el cálculo', async () => {
    render(<DonationRequestReport />);
    await screen.findByText('Glargina');
    fireEvent.click(screen.getByLabelText(/Calcular con un reparto por porcentajes/));
    await waitFor(() => expect(api.getDonationRequestReport.mock.calls.at(-1)[0]).not.toBeNull());
    const llamadas = api.getDonationRequestReport.mock.calls.length;

    fireEvent.change(screen.getByLabelText('Vial 3ml U200 (%)'), { target: { value: '50' } });
    expect(screen.getByText(/los porcentajes deben sumar 100 %/)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 600));
    expect(api.getDonationRequestReport.mock.calls.length).toBe(llamadas); // no se vuelve a pedir
  });

  it('el PDF y el Excel llevan los envases del reparto y su porcentaje en el título', async () => {
    pdf.tables.length = 0;
    render(<DonationRequestReport />);
    await screen.findByText('Glargina');
    fireEvent.click(screen.getByLabelText(/Calcular con un reparto por porcentajes/));
    await screen.findByText('Cant. Vial 10ml U100 (30 %)');

    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    const filas = xlsx.aoa_to_sheet.mock.calls.at(-1)[0];
    expect(filas[0].slice(2)).toEqual([
      'Cant. Vial 3ml U100 (23,33 %)', 'Cant. Vial 3ml U200 (23,33 %)', 'Cant. Vial 3ml U300 (23,33 %)', 'Cant. Vial 10ml U100 (30 %)',
    ]);
    expect(filas[1]).toEqual(['Glargina', 156180, 122, 61, 41, 47]);

    fireEvent.click(screen.getByRole('button', { name: /PDF/ }));
    await waitFor(() => expect(pdf.tables.length).toBeGreaterThanOrEqual(1));
    expect(pdf.tables[0].body[0].slice(2)).toEqual(['122', '61', '41', '47']);
    expect(pdf.doc.text.mock.calls.some((c) => /Reparto: .*Vial 10ml U100 30 %/.test(c[0]))).toBe(true);
  });
});

describe('Reporte de solicitud de cantidades requeridas de donación', () => {
  it('muestra el cuadro por tipo de insulina y, debajo, los porcentajes y el total', async () => {
    api.getDonationRequestReport.mockResolvedValue(solicitud());
    render(<DonationRequestReport />);

    await screen.findByText('Glargina');
    const encabezados = screen.getAllByRole('columnheader').map((th) => th.textContent);
    // el cuadro tiene 6 columnas: la cantidad en UI, los viales de 3 ml por concentración y los de 10 ml solo en U100
    expect(encabezados).toEqual([
      'Tipo de insulina', 'Cantidad requerida (60 días)', 'Cant. Vial 3ml U100', 'Cant. Vial 3ml U200', 'Cant. Vial 3ml U300',
      'Cant. Vial 10ml U100',
    ]);
    const celdas = (nombre) => Array.from(screen.getByText(nombre).closest('tr').querySelectorAll('td')).map((td) => td.textContent);
    const n = (valor) => valor.toLocaleString('es-BO');
    expect(celdas('Glargina')).toEqual(['Glargina', `${n(156180)} UI`, '521', '261', '174', '157']);
    expect(celdas('NPH')).toEqual(['NPH', `${n(113820)} UI`, '380', '190', '127', '114']);

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

  it('avisa cuántas personas del Registro Asistido están incluidas en el total', async () => {
    api.getDonationRequestReport.mockResolvedValue({ ...solicitud(), asistidos_incluidos: 7 });
    render(<DonationRequestReport />);
    await screen.findByText('Glargina');
    expect(screen.getByText('Del Registro Asistido (incluidos en el total)').nextSibling.textContent).toBe('7');
    // el total sigue siendo la última fila
    const filas = screen.getAllByText(/Total de beneficiarios|Del Registro Asistido/).map((el) => el.textContent);
    expect(filas[filas.length - 1]).toBe('Total de beneficiarios');
  });

  it('el PDF lleva el cuadro de 6 columnas con los viales de 3 ml por concentración y de 10 ml en U100', async () => {
    pdf.tables.length = 0;
    api.getDonationRequestReport.mockResolvedValue(solicitud());
    render(<DonationRequestReport />);
    await screen.findByText('Glargina');

    fireEvent.click(screen.getByRole('button', { name: /PDF/ }));
    await waitFor(() => expect(pdf.tables.length).toBeGreaterThanOrEqual(1));
    const cuadro = pdf.tables[0];
    expect(cuadro.head[0]).toEqual([
      'Tipo de insulina', 'Cantidad requerida (60 días)', 'Cant. Vial 3ml U100', 'Cant. Vial 3ml U200', 'Cant. Vial 3ml U300',
      'Cant. Vial 10ml U100',
    ]);
    expect(cuadro.body[0]).toEqual(['Glargina', `${(156180).toLocaleString('es-BO')} UI`, '521', '261', '174', '157']);
    expect(cuadro.body[1]).toEqual(['NPH', `${(113820).toLocaleString('es-BO')} UI`, '380', '190', '127', '114']);
    expect(pdf.doc.save).toHaveBeenCalledWith(expect.stringMatching(/^Solicitud_Donacion_.*\.pdf$/));
  });

  it('el Excel trae el cuadro, una fila en blanco y los datos finales con el total al final', async () => {
    api.getDonationRequestReport.mockResolvedValue(solicitud());
    render(<DonationRequestReport />);
    await screen.findByText('Glargina');

    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    await waitFor(() => expect(xlsx.writeFile).toHaveBeenCalledTimes(1));
    const filas = xlsx.aoa_to_sheet.mock.calls[0][0];
    expect(filas[0]).toEqual([
      'Tipo de insulina', 'Cantidad requerida (60 días)', 'Cant. Vial 3ml U100', 'Cant. Vial 3ml U200', 'Cant. Vial 3ml U300',
      'Cant. Vial 10ml U100',
    ]);
    expect(filas[1]).toEqual(['Glargina', 156180, 521, 261, 174, 157]);
    expect(filas[2]).toEqual(['NPH', 113820, 380, 190, 127, 114]);
    expect(filas[3]).toEqual([]);
    expect(filas[4]).toEqual(['Porcentajes por Rango Etario']);
    expect(filas[7]).toEqual(['Porcentaje de adultos mayores de 61 años en adelante', expect.stringMatching(/^18,3\s?%$/)]);
    expect(filas[8]).toEqual(['Porcentaje por Tipo de Diabetes']);
    expect(filas[filas.length - 1]).toEqual(['Total de beneficiarios', '208']);
    expect(xlsx.writeFile.mock.calls[0][1]).toMatch(/^Solicitud_Donacion_.*\.xlsx$/);
  });
});
