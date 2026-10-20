import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import DirectorDeliveryForm from '../pages/director/DirectorDeliveryForm';
import DirectorNotebookReport from '../pages/reports/DirectorNotebookReport';

const api = vi.hoisted(() => ({
  searchBeneficiaries: vi.fn(),
  searchLastDelivery: vi.fn(),
  createDeliveryBatch: vi.fn(),
  getDirectorDeliveries: vi.fn(),
}));
const xlsx = vi.hoisted(() => ({
  json_to_sheet: vi.fn((rows) => ({ rows })),
  book_new: vi.fn(() => ({})),
  book_append_sheet: vi.fn(),
  writeFile: vi.fn(),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock('../api/directorDeliveries', () => api);
vi.mock('xlsx', () => ({
  utils: { json_to_sheet: xlsx.json_to_sheet, book_new: xlsx.book_new, book_append_sheet: xlsx.book_append_sheet },
  writeFile: xlsx.writeFile,
}));
vi.mock('react-hot-toast', () => ({ default: toast, toast }));
vi.mock('../utils/imageToBase64', () => ({ imageToBase64: () => Promise.resolve('data:image/png;base64,AAAA') }));

const maria = () => ({
  id: 7,
  nombres: 'María',
  ap_paterno: 'Quispe',
  ap_materno: 'Mamani',
  ci: '4503853',
  depto: 'La Paz',
  estado: 'ACTIVO',
  edad: 41,
  tratamientos: [
    { nombre: 'Lantus', insulina: 'Glargina', dosis_diaria: 24 },
    { nombre: 'Humalog', insulina: 'Lispro', dosis_diaria: 12 },
  ],
  ultima_entrega: null,
});

const buscarYElegir = async (beneficiario = maria()) => {
  api.searchBeneficiaries.mockResolvedValue([beneficiario]);
  render(<DirectorDeliveryForm />);
  fireEvent.change(screen.getByLabelText(/Buscar por nombre/), { target: { value: 'Quispe' } });
  fireEvent.click(await screen.findByText('María Quispe Mamani', {}, { timeout: 3000 }));
};

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  Object.values(toast).forEach((fn) => fn.mockReset());
  xlsx.json_to_sheet.mockClear();
  xlsx.writeFile.mockClear();
});

describe('Cuaderno de la Directora: formulario', () => {
  it('al elegir a la persona despliega sus insulinas anotadas, con la marca sugerida de la ficha', async () => {
    await buscarYElegir();

    expect(api.searchBeneficiaries).toHaveBeenCalledWith('Quispe');
    expect(screen.getByText('4503853')).toBeInTheDocument(); // C.I. de la persona elegida
    const filas = screen.getAllByTestId('fila-insulina');
    expect(filas).toHaveLength(2);
    expect(within(filas[0]).getByText('Glargina')).toBeInTheDocument();
    expect(within(filas[0]).getByText(/En su ficha: Lantus · 24 UI\/día/)).toBeInTheDocument();
    // la ficha dice «Lantus»: la marca ya viene elegida
    expect(screen.getByLabelText('Marca de Glargina')).toHaveValue('Lantus');
    expect(screen.getByLabelText('Marca de Lispro')).toHaveValue('Humalog');
    // las marcas ofrecidas son las de esa insulina, más «Otra»
    const marcas = Array.from(screen.getByLabelText('Marca de Glargina').options).map((o) => o.value);
    expect(marcas).toEqual(['', 'Lantus', 'Toujeo', 'Abasaglar', 'Semglee', 'Otra']);
    // presentaciones como en el módulo departamental
    const presentaciones = Array.from(screen.getByLabelText('Presentación de Glargina').options).map((o) => o.value);
    expect(presentaciones).toEqual(['', 'Frasco 10ml', 'Cartucho 3ml', 'Pen 3ml']);
  });

  it('registra solo las insulinas con cantidad, con su presentación y marca', async () => {
    api.createDeliveryBatch.mockResolvedValue([]);
    await buscarYElegir();

    fireEvent.change(screen.getByLabelText('Presentación de Glargina'), { target: { value: 'Pen 3ml' } });
    fireEvent.change(screen.getByLabelText('Marca de Glargina'), { target: { value: 'Toujeo' } });
    fireEvent.change(screen.getByLabelText('Cantidad de Glargina'), { target: { value: '4 pens' } });
    // la lispro queda sin cantidad: no se entrega
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar Registro' }));

    await waitFor(() => expect(api.createDeliveryBatch).toHaveBeenCalledTimes(1));
    const payload = api.createDeliveryBatch.mock.calls[0][0];
    expect(payload.patient_id).toBe(7);
    expect(payload.items).toEqual([
      { insulin_type: 'Glargina', presentacion: 'Pen 3ml', marca: 'Toujeo', quantity: '4 pens' },
    ]);
    expect(payload.patient_nombres).toBeUndefined();
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    // el formulario vuelve al buscador
    expect(screen.getByLabelText(/Buscar por nombre/)).toBeInTheDocument();
  });

  it('pide la presentación cuando hay cantidad y exige al menos una cantidad', async () => {
    await buscarYElegir();

    fireEvent.click(screen.getByRole('button', { name: 'Confirmar Registro' }));
    expect(toast.error).toHaveBeenLastCalledWith('Escriba la cantidad de al menos una insulina entregada.');

    fireEvent.change(screen.getByLabelText('Cantidad de Lispro'), { target: { value: '1 frasco' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar Registro' }));
    expect(toast.error).toHaveBeenLastCalledWith('Elija la presentación de Lispro.');
    expect(api.createDeliveryBatch).not.toHaveBeenCalled();
  });

  it('avisa si la última entrega fue hace menos de 25 días', async () => {
    const ayer = new Date(Date.now() - 24 * 3600 * 1000).toISOString().slice(0, 10);
    await buscarYElegir({
      ...maria(),
      ultima_entrega: {
        id: 1, patient_nombres: 'MARÍA', patient_ap_paterno: 'QUISPE', patient_ap_materno: 'MAMANI',
        insulin_type: 'Glargina', quantity: '3 pens', delivery_date: ayer, marca: 'Lantus', presentacion: 'Pen 3ml',
      },
    });
    expect(screen.getByText(/Posible entrega duplicada/)).toBeInTheDocument();
    expect(screen.getByText(/Han pasado menos de 25 días/)).toBeInTheDocument();
  });

  it('una persona fuera de la lista se registra con sus nombres y elige la insulina', async () => {
    api.createDeliveryBatch.mockResolvedValue([]);
    api.searchLastDelivery.mockResolvedValue(null);
    render(<DirectorDeliveryForm />);
    fireEvent.click(screen.getByText(/La persona no está en la lista/));

    fireEvent.change(screen.getByPlaceholderText('Ej. Juan Carlos'), { target: { value: 'Juana' } });
    fireEvent.change(screen.getByPlaceholderText('Ej. Perez'), { target: { value: 'Ayala' } });
    fireEvent.change(screen.getByLabelText('Insulina'), { target: { value: 'NPH' } });
    fireEvent.change(screen.getByLabelText('Presentación de NPH'), { target: { value: 'Frasco 10ml' } });
    fireEvent.change(screen.getByLabelText('Cantidad de NPH'), { target: { value: '1 frasco' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar Registro' }));

    await waitFor(() => expect(api.createDeliveryBatch).toHaveBeenCalledTimes(1));
    const payload = api.createDeliveryBatch.mock.calls[0][0];
    expect(payload).toMatchObject({ patient_nombres: 'Juana', patient_ap_paterno: 'Ayala', patient_ap_materno: null });
    expect(payload.patient_id).toBeUndefined();
    expect(payload.items).toEqual([{ insulin_type: 'NPH', presentacion: 'Frasco 10ml', marca: null, quantity: '1 frasco' }]);
  });

  it('se puede agregar otra insulina que no estaba en la ficha', async () => {
    await buscarYElegir();
    fireEvent.click(screen.getByText('Agregar otra insulina'));
    expect(screen.getAllByTestId('fila-insulina')).toHaveLength(3);
    expect(screen.getByLabelText('Insulina')).toBeInTheDocument();
  });
});

const entregas = () => ({
  total: 2,
  items: [
    {
      id: 2, patient_nombres: 'MARÍA', patient_ap_paterno: 'QUISPE', patient_ap_materno: 'MAMANI', insulin_type: 'Glargina',
      quantity: '4 pens', delivery_date: '2026-10-15', recorded_by_id: 3, created_at: '2026-10-15T10:00:00Z',
      patient_id: 7, presentacion: 'Pen 3ml', marca: 'Lantus', patient_ci: '4503853', patient_depto: 'La Paz',
      registrado_por: 'directora@vidaplena.org',
    },
    {
      id: 1, patient_nombres: 'RUFINA', patient_ap_paterno: 'VARGAS', patient_ap_materno: null, insulin_type: 'TOUJEO LYUMJEV',
      quantity: '3 TOUJEO 1LYUMJEV', delivery_date: '2026-10-02', recorded_by_id: 3, created_at: '2026-10-02T10:00:00Z',
      patient_id: null, presentacion: null, marca: null, patient_ci: null, patient_depto: null, registrado_por: 'directora@vidaplena.org',
    },
  ],
});

describe('Reporte del cuaderno de la Directora', () => {
  it('muestra lo registrado y pide el rango de fechas elegido', async () => {
    api.getDirectorDeliveries.mockResolvedValue(entregas());
    render(<DirectorNotebookReport />);

    await screen.findByText('MARÍA QUISPE MAMANI');
    expect(screen.getByText('Lantus')).toBeInTheDocument();
    expect(screen.getByText('Pen 3ml')).toBeInTheDocument();
    expect(screen.getByText('4503853')).toBeInTheDocument();
    // las entregas anteriores, sin marca ni presentación, siguen apareciendo
    expect(screen.getByText('RUFINA VARGAS')).toBeInTheDocument();
    expect(screen.getByText('TOUJEO LYUMJEV')).toBeInTheDocument();
    expect(screen.getByText((_, el) => el.tagName === 'P' && /2\s+registros/.test(el.textContent))).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2026-10-01' } });
    fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2026-10-31' } });
    await waitFor(() =>
      expect(api.getDirectorDeliveries).toHaveBeenLastCalledWith({ desde: '2026-10-01', hasta: '2026-10-31', q: '' }),
    );
  });

  it('el Excel trae la persona, la insulina, la marca, la presentación y la cantidad', async () => {
    api.getDirectorDeliveries.mockResolvedValue(entregas());
    render(<DirectorNotebookReport />);
    await screen.findByText('MARÍA QUISPE MAMANI');

    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    const filas = xlsx.json_to_sheet.mock.calls[0][0];
    expect(Object.keys(filas[0])).toEqual([
      'Fecha', 'Beneficiario', 'C.I.', 'Departamento', 'Insulina', 'Marca', 'Presentación', 'Cantidad', 'Registrado por',
    ]);
    expect(filas[0]).toMatchObject({
      Fecha: '15/10/2026', Beneficiario: 'MARÍA QUISPE MAMANI', 'C.I.': '4503853', Insulina: 'Glargina',
      Marca: 'Lantus', Presentación: 'Pen 3ml', Cantidad: '4 pens',
    });
    expect(filas[1]).toMatchObject({ Beneficiario: 'RUFINA VARGAS', Marca: '', Presentación: '' });
    expect(xlsx.writeFile.mock.calls[0][1]).toMatch(/^Cuaderno_Directora_.*\.xlsx$/);
  });

  it('sin registros no hay nada que descargar', async () => {
    api.getDirectorDeliveries.mockResolvedValue({ total: 0, items: [] });
    render(<DirectorNotebookReport />);
    await screen.findByText(/No hay entregas registradas/);
    expect(screen.getByRole('button', { name: /Excel/ })).toBeDisabled();
  });
});
