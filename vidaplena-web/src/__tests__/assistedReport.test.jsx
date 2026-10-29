import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import AssistedBeneficiariesReport from '../pages/reports/AssistedBeneficiariesReport';

const api = vi.hoisted(() => ({ listAssistedRegistrations: vi.fn() }));
const xlsx = vi.hoisted(() => ({
  json_to_sheet: vi.fn(() => ({})),
  book_new: vi.fn(() => ({})),
  book_append_sheet: vi.fn(),
  writeFile: vi.fn(),
}));
const pdf = vi.hoisted(() => ({
  doc: {
    internal: { pageSize: { getWidth: () => 279, getHeight: () => 216 }, getNumberOfPages: () => 1 },
    setFillColor: vi.fn(), rect: vi.fn(), addImage: vi.fn(), setFontSize: vi.fn(), setTextColor: vi.fn(),
    setFont: vi.fn(), text: vi.fn(), save: vi.fn(),
  },
  options: vi.fn(),
  orientation: vi.fn(),
  autoTable: vi.fn(),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock('../api/assistedRegistrations', () => api);
vi.mock('xlsx', () => ({
  utils: { json_to_sheet: xlsx.json_to_sheet, book_new: xlsx.book_new, book_append_sheet: xlsx.book_append_sheet },
  writeFile: xlsx.writeFile,
}));
vi.mock('jspdf', () => ({
  default: function JsPdfFalso(options) {
    pdf.orientation(options.orientation);
    return pdf.doc;
  },
}));
vi.mock('jspdf-autotable', () => ({ default: (doc, options) => pdf.autoTable(options) }));
vi.mock('react-hot-toast', () => ({ toast }));
vi.mock('../utils/imageToBase64', () => ({ imageToBase64: () => Promise.resolve('data:image/png;base64,AAAA') }));

const registro = (extra = {}) => ({
  id: 5,
  codigo: 'RA-00005',
  estado: 'ACTIVO',
  nombre: 'Apodo Beto',
  ci: '9876543',
  fecha_nacimiento: null,
  edad_aproximada: 35,
  rango_edad: null,
  depto: 'Oruro',
  municipio: 'Caracollo',
  ciudad_localidad: null,
  tipo_diabetes: 'Tipo 2',
  anios_diabetes: 4,
  complicaciones_otras: 'Hipertensión, neuropatía',
  entidad_nombre: 'Recinto San Pedro',
  entidad_tipo: 'RECINTO_PENITENCIARIO',
  referente_vinculo: 'AMISTAD',
  referente: { id: 3, nombre_completo: 'Rosa Quispe', ci: '1234567', telefono: '70000000' },
  insumos_requeridos: null,
  urgente: false,
  revision_vencida: false,
  cese_causa: null,
  created_at: '2026-10-01T10:00:00Z',
  ultima_revision_at: null,
  treatments: [
    { id: 1, insulina: 'Protamina', dosis_diaria: 30 },
    { id: 2, insulina: 'Lispro', dosis_diaria: 12.5 },
  ],
  total_entregas: 2,
  ultima_entrega: '2026-10-20',
  ...extra,
});

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  Object.values(xlsx).forEach((fn) => fn.mockClear());
  Object.values(pdf).forEach((fn) => typeof fn.mockClear === 'function' && fn.mockClear());
  Object.values(pdf.doc).forEach((fn) => typeof fn.mockClear === 'function' && fn.mockClear());
  toast.success.mockClear();
  toast.error.mockClear();
  api.listAssistedRegistrations.mockResolvedValue([registro()]);
});

const abrir = async () => {
  render(<AssistedBeneficiariesReport />);
  await screen.findByText('RA-00005');
};

// Las columnas se eligen en el panel «Columnas» (sus nombres se repiten en los filtros de arriba).
const panelColumnas = () => within(screen.getByText('SELECCIONAR COLUMNAS').parentElement);
const elegirColumnas = (...labels) => {
  if (!screen.queryByText('SELECCIONAR COLUMNAS')) fireEvent.click(screen.getByRole('button', { name: /Columnas/ }));
  labels.forEach((label) => fireEvent.click(panelColumnas().getByLabelText(label)));
};

describe('Reporte del Registro Asistido', () => {
  it('pide por defecto los registros activos y muestra las columnas por defecto', async () => {
    await abrir();
    expect(api.listAssistedRegistrations).toHaveBeenLastCalledWith({ q: '', estado: 'ACTIVO', depto: '', revision_vencida: '' });
    const encabezados = screen.getAllByRole('columnheader').map((th) => th.textContent);
    expect(encabezados).toEqual([
      'Código interno', 'Estado', 'Nombre / apodo', 'C.I.', 'Edad', 'Departamento', 'Tipo de diabetes', 'Tratamiento',
      'Persona referente', 'Vínculo con el beneficiario', 'Última entrega',
    ]);
    const fila = screen.getByText('RA-00005').closest('tr');
    expect(within(fila).getByText('~35')).toBeInTheDocument();
    expect(within(fila).getByText('Amistad')).toBeInTheDocument();
  });

  it('se eligen las columnas y el PDF y el Excel llevan solo esas', async () => {
    await abrir();
    elegirColumnas('Municipio', 'Complicaciones / otras enfermedades', 'Años con diabetes', 'Estado', 'Edad');
    const encabezados = screen.getAllByRole('columnheader').map((th) => th.textContent);
    expect(encabezados).toContain('Municipio');
    expect(encabezados).not.toContain('Estado');
    expect(encabezados).not.toContain('Edad');

    // tratamiento: una insulina por línea y «Protamina» se muestra como «Mixta»
    const celdaTratamiento = screen.getByText((_, el) => el.tagName === 'TD' && el.textContent === 'Mixta: 30 UI al día\nLispro: 12.5 UI al día');
    expect(celdaTratamiento).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    const [fila] = xlsx.json_to_sheet.mock.calls[0][0];
    expect(Object.keys(fila)).toEqual([
      'Código interno', 'Nombre / apodo', 'C.I.', 'Departamento', 'Municipio', 'Tipo de diabetes', 'Años con diabetes',
      'Complicaciones / otras enfermedades', 'Tratamiento', 'Persona referente', 'Vínculo con el beneficiario', 'Última entrega',
    ]);
    expect(fila.Municipio).toBe('Caracollo');
    expect(fila['Años con diabetes']).toBe('4 años');
    expect(xlsx.writeFile.mock.calls[0][1]).toMatch(/^Registro_Asistido_\d{4}-\d{2}-\d{2}\.xlsx$/);

    fireEvent.click(screen.getByRole('button', { name: /PDF/ }));
    await waitFor(() => expect(pdf.autoTable).toHaveBeenCalledTimes(1));
    const tabla = pdf.autoTable.mock.calls[0][0];
    expect(tabla.head[0]).toEqual(Object.keys(fila));
    expect(tabla.body).toHaveLength(1);
    expect(tabla.body[0][0]).toBe('RA-00005');
    expect(tabla.body[0]).toContain('Caracollo');
    expect(pdf.orientation).toHaveBeenCalledWith('landscape'); // muchas columnas: horizontal
    expect(pdf.doc.save).toHaveBeenCalledWith(expect.stringMatching(/^Registro_Asistido_\d{4}-\d{2}-\d{2}\.pdf$/));
    expect(toast.success).toHaveBeenCalledWith('Reporte descargado exitosamente');
  });

  it('el encabezado del PDF resume los filtros', async () => {
    await abrir();
    fireEvent.click(screen.getByRole('button', { name: /PDF/ }));
    await waitFor(() => expect(pdf.autoTable).toHaveBeenCalled());
    // la cabecera se dibuja con didDrawPage
    pdf.autoTable.mock.calls[0][0].didDrawPage();
    const textos = pdf.doc.text.mock.calls.map((c) => c[0]);
    expect(textos).toContain('Registro Asistido por Situación Excepcional');
    expect(textos.some((t) => /Total registros: 1 \| Estado: Activo/.test(t))).toBe(true);
  });

  it('«solo con código» quita y bloquea las columnas que identifican a la persona o a su referente', async () => {
    await abrir();
    elegirColumnas('Municipio', 'Contacto persona referente');
    fireEvent.click(screen.getByLabelText('Solo con código (para donantes)'));

    const encabezados = screen.getAllByRole('columnheader').map((th) => th.textContent);
    expect(encabezados).toEqual(['Código interno', 'Estado', 'Edad', 'Departamento', 'Tipo de diabetes', 'Tratamiento', 'Vínculo con el beneficiario', 'Última entrega']);
    for (const label of ['Nombre / apodo', 'C.I.', 'Municipio', 'Persona referente', 'C.I. persona referente', 'Contacto persona referente', 'Entidad referente', 'Fecha de nacimiento']) {
      expect(panelColumnas().getByLabelText(label)).toBeDisabled();
    }
    expect(panelColumnas().getByLabelText('Departamento')).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    const [fila] = xlsx.json_to_sheet.mock.calls[0][0];
    expect(JSON.stringify(fila)).not.toMatch(/Apodo|9876543|Caracollo|Rosa|1234567|70000000|San Pedro/);
    expect(xlsx.writeFile.mock.calls[0][1]).toMatch(/^Registro_Asistido_solo_codigo_/);

    // al desactivarlo vuelven las columnas elegidas
    fireEvent.click(screen.getByLabelText('Solo con código (para donantes)'));
    expect(screen.getAllByRole('columnheader').map((th) => th.textContent)).toContain('Nombre / apodo');
  });

  it('con los filtros pide al servidor los registros que corresponden', async () => {
    await abrir();
    fireEvent.change(screen.getByLabelText('Estado'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Departamento'), { target: { value: 'Oruro' } });
    fireEvent.click(screen.getByLabelText('Revisión semestral vencida'));
    await waitFor(() =>
      expect(api.listAssistedRegistrations).toHaveBeenLastCalledWith({ q: '', estado: '', depto: 'Oruro', revision_vencida: true }),
    );
  });

  it('sin registros no se puede generar el PDF ni el Excel', async () => {
    api.listAssistedRegistrations.mockResolvedValue([]);
    render(<AssistedBeneficiariesReport />);
    await screen.findByText('No hay registros con esos filtros.');
    const botones = screen.getAllByRole('button', { name: 'Sin datos' });
    botones.forEach((b) => expect(b).toBeDisabled());
  });
});
