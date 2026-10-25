import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import '@testing-library/jest-dom';
import AssistedRegistrationPage from '../pages/assisted/AssistedRegistrationPage';
import AssistedRegistrationDetailPage from '../pages/assisted/AssistedRegistrationDetailPage';

const api = vi.hoisted(() => ({
  listAssistedRegistrations: vi.fn(),
  createAssistedRegistration: vi.fn(),
  getAssistedRegistration: vi.fn(),
  updateAssistedRegistration: vi.fn(),
  addAssistedDelivery: vi.fn(),
  registerAssistedReview: vi.fn(),
  denyAssistedRegistration: vi.fn(),
  endAssistedRegistration: vi.fn(),
}));
const xlsx = vi.hoisted(() => ({
  json_to_sheet: vi.fn(() => ({})),
  book_new: vi.fn(() => ({})),
  book_append_sheet: vi.fn(),
  writeFile: vi.fn(),
}));
const auth = vi.hoisted(() => ({ role: 'EVALUADOR_SOCIAL' }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock('../api/assistedRegistrations', () => api);
vi.mock('xlsx', () => ({
  utils: { json_to_sheet: xlsx.json_to_sheet, book_new: xlsx.book_new, book_append_sheet: xlsx.book_append_sheet },
  writeFile: xlsx.writeFile,
}));
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ user: { role: auth.role } }) }));
vi.mock('react-hot-toast', () => ({ toast }));

const registro = (extra = {}) => ({
  id: 5,
  codigo: 'RA-00005',
  estado: 'ACTIVO',
  nombre: 'Iniciales J.P.',
  rango_edad: '12-17',
  edad_aproximada: null,
  depto: 'Cochabamba',
  ciudad_localidad: null,
  entidad_nombre: 'Hogar Esperanza',
  entidad_tipo: 'CENTRO_ACOGIDA',
  referente_nombre: 'Lic. Rosa',
  referente_vinculo: 'TRABAJADOR_SOCIAL',
  referente_contacto: '70000000',
  insumos_requeridos: null,
  urgente: true,
  buen_uso_comunicado_at: null,
  revision_vencida: true,
  treatments: [{ id: 1, insulina: 'Protamina', dosis_diaria: 20 }],
  total_entregas: 0,
  ultima_entrega: null,
  deliveries: [],
  ...extra,
});

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  Object.values(xlsx).forEach((fn) => fn.mockClear());
  toast.success.mockClear();
  toast.error.mockClear();
  auth.role = 'EVALUADOR_SOCIAL';
});

const abrirLista = () =>
  render(
    <MemoryRouter initialEntries={['/dashboard/registro-asistido']}>
      <Routes>
        <Route path="/dashboard/registro-asistido" element={<AssistedRegistrationPage />} />
        <Route path="/dashboard/registro-asistido/:id" element={<div>DETALLE ABIERTO</div>} />
      </Routes>
    </MemoryRouter>,
  );

describe('Registro Asistido: lista', () => {
  it('muestra el código, las alertas de urgencia y de revisión vencida, y la insulina con el nombre nuevo', async () => {
    api.listAssistedRegistrations.mockResolvedValue([registro()]);
    abrirLista();

    await screen.findByText('RA-00005');
    expect(screen.getByText('Urgente')).toBeInTheDocument();
    expect(screen.getByText('Revisar')).toBeInTheDocument();
    expect(screen.getByText('Mixta (20 UI)')).toBeInTheDocument(); // «Protamina» se muestra como «Mixta»
    expect(screen.getByText('Centro de acogida')).toBeInTheDocument();
  });

  it('el Excel «solo con código» no incluye nombre, entidad ni persona referente', async () => {
    api.listAssistedRegistrations.mockResolvedValue([registro()]);
    abrirLista();
    await screen.findByText('RA-00005');

    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    const completo = xlsx.json_to_sheet.mock.calls[0][0][0];
    expect(completo['Nombre / apodo']).toBe('Iniciales J.P.');
    expect(completo['Entidad referente']).toBe('Hogar Esperanza');

    fireEvent.click(screen.getByLabelText(/Excel solo con código/));
    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    const anonimo = xlsx.json_to_sheet.mock.calls[1][0][0];
    expect(Object.keys(anonimo)).toEqual([
      'Código interno', 'Estado', 'Departamento', 'Tipo de entidad', 'Rango de edad', 'Insulinas', 'Entregas', 'Última entrega',
    ]);
    expect(JSON.stringify(anonimo)).not.toMatch(/Iniciales|Esperanza|Rosa|70000000/);
    expect(xlsx.writeFile.mock.calls[1][1]).toMatch(/^Registro_Asistido_solo_codigo_/);
  });

  it('se puede registrar a una persona sin llenar ningún dato y se abre su ficha con el código asignado', async () => {
    api.listAssistedRegistrations.mockResolvedValue([]);
    api.createAssistedRegistration.mockResolvedValue(registro({ id: 9, codigo: 'RA-00009' }));
    abrirLista();
    await screen.findByText('No hay registros con esos filtros.');

    fireEvent.click(screen.getByRole('button', { name: /Nuevo registro asistido/ }));
    expect(screen.getByText(/Ningún dato es obligatorio y no se piden documentos/)).toBeInTheDocument();
    // el formulario no tiene campos de documentos, tutor ni causas
    expect(screen.queryByLabelText(/cédula|tutor|causa|motivo del acogimiento|antecedentes/i)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Registrar y asignar código' }));
    await waitFor(() => expect(api.createAssistedRegistration).toHaveBeenCalledTimes(1));
    const payload = api.createAssistedRegistration.mock.calls[0][0];
    expect(payload.nombre).toBe('');
    expect(payload.treatments).toEqual([]);
    expect(payload.edad_aproximada).toBeNull();
    await screen.findByText('DETALLE ABIERTO');
    expect(toast.success).toHaveBeenCalledWith('Registrado con el código RA-00009.');
  });
});

const abrirDetalle = () =>
  render(
    <MemoryRouter initialEntries={['/dashboard/registro-asistido/5']}>
      <Routes>
        <Route path="/dashboard/registro-asistido/:id" element={<AssistedRegistrationDetailPage />} />
        <Route path="/dashboard/registro-asistido" element={<div>LISTA</div>} />
      </Routes>
    </MemoryRouter>,
  );

describe('Registro Asistido: ficha', () => {
  it('registra una entrega sin constancia ni datos del receptor', async () => {
    api.getAssistedRegistration.mockResolvedValue(registro());
    api.addAssistedDelivery.mockResolvedValue(
      registro({ total_entregas: 1, deliveries: [{ id: 1, fecha: '2026-10-24', insumo: 'Insulina Glargina', cantidad: '2 frascos', receptor_tipo: null, constancia_tipo: null, entregado_por: 'eval@x.com' }] }),
    );
    abrirDetalle();
    await screen.findByText('RA-00005');

    fireEvent.change(screen.getByLabelText('Insumo'), { target: { value: 'Insulina Glargina' } });
    fireEvent.change(screen.getByLabelText('Cantidad'), { target: { value: '2 frascos' } });
    fireEvent.click(screen.getByRole('button', { name: 'Registrar entrega' }));

    await waitFor(() => expect(api.addAssistedDelivery).toHaveBeenCalledTimes(1));
    const [id, payload] = api.addAssistedDelivery.mock.calls[0];
    expect(id).toBe('5');
    expect(payload).toMatchObject({ insumo: 'Insulina Glargina', cantidad: '2 frascos', receptor_tipo: null, constancia_tipo: null });
    await screen.findByText('2 frascos');
  });

  it('exige insumo y cantidad, y nada más, para entregar', async () => {
    api.getAssistedRegistration.mockResolvedValue(registro());
    abrirDetalle();
    await screen.findByText('RA-00005');
    fireEvent.click(screen.getByRole('button', { name: 'Registrar entrega' }));
    expect(api.addAssistedDelivery).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith('Indique el insumo y la cantidad entregados.');
  });

  it('el cese ofrece solo las causas del reglamento y la falta grave exige detalle', async () => {
    api.getAssistedRegistration.mockResolvedValue(registro());
    api.endAssistedRegistration.mockResolvedValue(registro({ estado: 'CESADO', cese_causa: 'SIN_NECESIDAD' }));
    abrirDetalle();
    await screen.findByText('RA-00005');

    fireEvent.click(screen.getByRole('button', { name: 'Cesar registro' }));
    const causas = within(screen.getByLabelText('Causa')).getAllByRole('option').map((o) => o.textContent);
    expect(causas).toHaveLength(5);
    expect(causas.join(' ')).not.toMatch(/contacto|institución/i); // no son causales de cese

    fireEvent.change(screen.getByLabelText('Causa'), { target: { value: 'FALTA_GRAVE' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar cese' }));
    expect(api.endAssistedRegistration).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText('Causa'), { target: { value: 'SIN_NECESIDAD' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar cese' }));
    await waitFor(() =>
      expect(api.endAssistedRegistration).toHaveBeenCalledWith('5', { causa: 'SIN_NECESIDAD', detalle: null, patient_id: null }),
    );
    await screen.findByText(/Registro cesado el/);
  });

  it('solo el Evaluador Social o la Dirección ven «Denegar admisión»', async () => {
    api.getAssistedRegistration.mockResolvedValue(registro());
    auth.role = 'COORDINADOR_NACIONAL';
    const { unmount } = abrirDetalle();
    await screen.findByText('RA-00005');
    expect(screen.queryByRole('button', { name: /Denegar admisión/ })).toBeNull();
    unmount();

    auth.role = 'EVALUADOR_SOCIAL';
    abrirDetalle();
    await screen.findByText('RA-00005');
    expect(screen.getByRole('button', { name: /Denegar admisión/ })).toBeInTheDocument();
  });

  it('registra la revisión semestral', async () => {
    api.getAssistedRegistration.mockResolvedValue(registro());
    api.registerAssistedReview.mockResolvedValue(registro({ revision_vencida: false, ultima_revision_at: '2026-10-24T10:00:00Z' }));
    abrirDetalle();
    await screen.findByText('Revisión semestral vencida');

    fireEvent.click(screen.getByRole('button', { name: 'Registrar revisión realizada' }));
    await waitFor(() => expect(api.registerAssistedReview).toHaveBeenCalledWith('5'));
    await waitFor(() => expect(screen.queryByText('Revisión semestral vencida')).toBeNull());
  });
});
