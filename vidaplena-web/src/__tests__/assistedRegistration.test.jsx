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
  searchReferents: vi.fn(),
  createReferent: vi.fn(),
  getReferent: vi.fn(),
  updateReferent: vi.fn(),
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
  ci: '9876543',
  fecha_nacimiento: '1990-05-17',
  municipio: 'Quillacollo',
  tipo_diabetes: 'Tipo 1',
  anios_diabetes: 8,
  complicaciones_otras: 'Hipertensión, neuropatía',
  referente_id: 3,
  referente_vinculo: 'FAMILIAR',
  referente: {
    id: 3,
    nombre_completo: 'Rosa Quispe',
    ci: '1234567',
    telefono: '70000000',
    foto_url: 'https://storage.test/rosa.png',
    registros_activos: 2,
    codigos: [],
  },
  referente_pendiente: false,
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
  api.getReferent.mockResolvedValue({ id: 3, codigos: ['RA-00005', 'RA-00007'] });
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
    expect(screen.getByText(/Hogar Esperanza · Centro de acogida/)).toBeInTheDocument();
    expect(screen.getByText('Rosa Quispe')).toBeInTheDocument(); // la persona referente
  });

  it('el Excel «solo con código» no incluye nombre, entidad ni persona referente', async () => {
    api.listAssistedRegistrations.mockResolvedValue([registro()]);
    abrirLista();
    await screen.findByText('RA-00005');

    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    const completo = xlsx.json_to_sheet.mock.calls[0][0][0];
    expect(completo['Nombre / apodo']).toBe('Iniciales J.P.');
    expect(completo['Entidad referente']).toBe('Hogar Esperanza');
    expect(completo['Persona referente']).toBe('Rosa Quispe');
    expect(completo['C.I. persona referente']).toBe('1234567');
    expect(completo['Vínculo con el beneficiario']).toBe('Familiar');

    fireEvent.click(screen.getByLabelText(/Excel solo con código/));
    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    const anonimo = xlsx.json_to_sheet.mock.calls[1][0][0];
    expect(Object.keys(anonimo)).toEqual([
      'Código interno', 'Estado', 'Departamento', 'Tipo de entidad', 'Rango de edad', 'Tipo de diabetes',
      'Años con diabetes', 'Insulinas', 'Entregas', 'Última entrega',
    ]);
    expect(JSON.stringify(anonimo)).not.toMatch(/Iniciales|Esperanza|Rosa|70000000|9876543|1234567|Quillacollo|neuropatía/);
    expect(xlsx.writeFile.mock.calls[1][1]).toMatch(/^Registro_Asistido_solo_codigo_/);
  });

  it('los datos de la persona son opcionales, pero sin persona referente y vínculo no se registra', async () => {
    api.listAssistedRegistrations.mockResolvedValue([]);
    api.createAssistedRegistration.mockResolvedValue(registro({ id: 9, codigo: 'RA-00009' }));
    api.searchReferents.mockResolvedValue([registro().referente]);
    abrirLista();
    await screen.findByText('No hay registros con esos filtros.');

    fireEvent.click(screen.getByRole('button', { name: /Nuevo registro asistido/ }));
    expect(screen.getByText(/Los datos de la persona son opcionales; la persona referente es obligatoria/)).toBeInTheDocument();
    // el formulario no tiene campos de documentos, tutor ni causas
    expect(screen.queryByLabelText(/cédula|tutor|causa|motivo del acogimiento|antecedentes/i)).toBeNull();
    // pide los datos complementarios
    const formulario = within(screen.getByRole('button', { name: 'Registrar y asignar código' }).closest('form'));
    ['N.° de carnet de identidad (C.I.)', 'Fecha de nacimiento', 'Departamento', 'Municipio', 'Tipo de diabetes',
      'Años con la diabetes', 'Complicaciones u otras enfermedades (separadas por coma)'].forEach((label) => {
      expect(formulario.getByLabelText(label)).toBeInTheDocument();
    });

    // sin persona referente
    fireEvent.click(screen.getByRole('button', { name: 'Registrar y asignar código' }));
    expect(api.createAssistedRegistration).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith('Indique la persona referente: es quien recibirá la insulina.');

    // con persona referente, pero sin vínculo
    fireEvent.change(screen.getByLabelText('Buscar persona referente'), { target: { value: 'Rosa' } });
    fireEvent.click(await screen.findByRole('button', { name: /Rosa Quispe/ }));
    toast.error.mockClear();
    fireEvent.submit(screen.getByRole('button', { name: 'Registrar y asignar código' }).closest('form'));
    expect(api.createAssistedRegistration).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith('Indique el vínculo de la persona referente con el beneficiario.');

    // el vínculo solo admite las cuatro opciones, sin «no se sabe»
    const opciones = within(screen.getByLabelText(/Vínculo de la persona referente/)).getAllByRole('option').map((o) => o.textContent);
    expect(opciones).toEqual(['Elegir el vínculo…', 'Familiar', 'Conocido/a', 'Referido/a por terceros', 'Amistad']);

    fireEvent.change(screen.getByLabelText(/Vínculo de la persona referente/), { target: { value: 'AMISTAD' } });
    fireEvent.click(screen.getByRole('button', { name: 'Registrar y asignar código' }));
    await waitFor(() => expect(api.createAssistedRegistration).toHaveBeenCalledTimes(1));
    const payload = api.createAssistedRegistration.mock.calls[0][0];
    expect(payload).toMatchObject({ referente_id: 3, referente_vinculo: 'AMISTAD', nombre: '', ci: '', treatments: [] });
    expect(payload.edad_aproximada).toBeNull();
    expect(payload.anios_diabetes).toBeNull();
    await screen.findByText('DETALLE ABIERTO');
    expect(toast.success).toHaveBeenCalledWith('Registrado con el código RA-00009.');
  });

  it('registrar una persona referente nueva exige nombre, C.I., teléfono y foto', async () => {
    api.listAssistedRegistrations.mockResolvedValue([]);
    api.searchReferents.mockResolvedValue([]);
    api.createReferent.mockResolvedValue({ id: 8, nombre_completo: 'Pedro Condori', ci: '5555555', telefono: '71111111', foto_url: 'https://storage.test/p.png', registros_activos: 0 });
    abrirLista();
    await screen.findByText('No hay registros con esos filtros.');
    fireEvent.click(screen.getByRole('button', { name: /Nuevo registro asistido/ }));
    fireEvent.click(screen.getByRole('button', { name: /Registrar una nueva persona referente/ }));

    const registrar = () => fireEvent.click(screen.getByRole('button', { name: 'Registrar persona referente' }));
    registrar();
    expect(toast.error).toHaveBeenLastCalledWith('Indique el nombre completo de la persona referente.');
    fireEvent.change(screen.getByLabelText('Nombre completo *'), { target: { value: 'Pedro Condori' } });
    registrar();
    expect(toast.error).toHaveBeenLastCalledWith('Indique el C.I. de la persona referente.');
    fireEvent.change(screen.getByLabelText('C.I. *'), { target: { value: '5555555' } });
    registrar();
    expect(toast.error).toHaveBeenLastCalledWith('Indique un número de contacto válido.');
    fireEvent.change(screen.getByLabelText('N.° de contacto *'), { target: { value: '71111111' } });
    registrar();
    expect(toast.error).toHaveBeenLastCalledWith('La foto personal de la persona referente es obligatoria.');
    expect(api.createReferent).not.toHaveBeenCalled();

    // un PDF no es una foto
    const archivo = screen.getByLabelText(/Foto personal para identificarse/);
    fireEvent.change(archivo, { target: { files: [new File(['x'], 'doc.pdf', { type: 'application/pdf' })] } });
    expect(toast.error).toHaveBeenLastCalledWith('La foto debe ser una imagen JPG o PNG.');

    const foto = new File(['x'], 'foto.png', { type: 'image/png' });
    fireEvent.change(archivo, { target: { files: [foto] } });
    registrar();
    await waitFor(() => expect(api.createReferent).toHaveBeenCalledTimes(1));
    expect(api.createReferent.mock.calls[0][0]).toMatchObject({ nombre_completo: 'Pedro Condori', ci: '5555555', telefono: '71111111', foto });
    // queda elegida como persona referente
    await screen.findByText('C.I. 5555555 · Contacto 71111111');
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
  it('muestra a la persona referente con su foto, C.I., vínculo y los otros beneficiarios que atiende', async () => {
    api.getAssistedRegistration.mockResolvedValue(registro());
    abrirDetalle();
    await screen.findByText('RA-00005');

    expect(screen.getByAltText('Foto de Rosa Quispe')).toHaveAttribute('src', 'https://storage.test/rosa.png');
    expect(screen.getByText(/C\.I\. 1234567 · Contacto 70000000/)).toBeInTheDocument();
    expect(screen.getByText('Familiar')).toBeInTheDocument();
    await screen.findByText(/También es persona referente de: RA-00007/); // sin repetir el registro actual
    // datos complementarios
    expect(screen.getByText('9876543')).toBeInTheDocument();
    expect(screen.getByText('Quillacollo', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('Tipo 1')).toBeInTheDocument();
    expect(screen.getByText('8 años')).toBeInTheDocument();
    expect(screen.getByText('Hipertensión, neuropatía')).toBeInTheDocument();
  });

  it('avisa si un registro anterior no tiene persona referente o le faltan C.I. y foto', async () => {
    api.getAssistedRegistration.mockResolvedValue(registro({ referente: null, referente_id: null, referente_pendiente: true }));
    const { unmount } = abrirDetalle();
    await screen.findByText(/Este registro no tiene persona referente/);
    unmount();

    api.getAssistedRegistration.mockResolvedValue(
      registro({ referente: { ...registro().referente, ci: null, foto_url: null } }),
    );
    abrirDetalle();
    await screen.findByText(/Faltan el C\.I\. y la foto personal de la persona referente/);
  });

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
