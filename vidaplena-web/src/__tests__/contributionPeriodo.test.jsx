import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import ContributionsReviewPage from '../pages/admin/ContributionsReviewPage';

const api = vi.hoisted(() => ({
  get: vi.fn(),
  updateContributionPeriodo: vi.fn(),
  createContributionAdmin: vi.fn(),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock('../api/axios', () => ({ default: { get: api.get, put: vi.fn(), post: vi.fn() } }));
vi.mock('../api/patients', () => ({ getPaginatedPatients: vi.fn().mockResolvedValue({ items: [] }) }));
vi.mock('../api/contributions', () => ({
  updateContributionPeriodo: api.updateContributionPeriodo,
  createContributionAdmin: api.createContributionAdmin,
}));
vi.mock('react-hot-toast', () => ({ toast }));

const aporte = {
  id: 7,
  patient_id: 1,
  patient_nombre: 'Marta Quispe',
  patient_ci: '123',
  depto: 'La Paz',
  periodo: '2026-11',
  fecha_pago: '2026-11-05',
  monto: 100,
  estado: 'DECLARADO',
  metodo_pago: 'VOUCHER',
  url_comprobante: 'https://storage.test/voucher.jpg',
  observacion_admin: null,
};

const ocupado = {
  code: 'PERIODO_OCUPADO',
  message: 'Este beneficiario ya tiene un aporte OBSERVADO para el periodo 2026-10. Si lo reasigna, este aporte lo reemplaza.',
  periodo: '2026-10',
  existente: { id: 3, estado: 'OBSERVADO', fecha_pago: '2026-10-04', monto: 100, observacion_admin: 'El voucher no se lee' },
};

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  toast.success.mockClear();
  toast.error.mockClear();
  localStorage.setItem('user', JSON.stringify({ role: 'SUPER_ADMIN' }));
  api.get.mockResolvedValue({ data: [aporte] });
});

const abrirModal = async () => {
  render(<MemoryRouter><ContributionsReviewPage /></MemoryRouter>);
  await screen.findByText(/Marta Quispe/);
  fireEvent.click(screen.getByRole('button', { name: /Corregir periodo/ }));
  fireEvent.change(document.querySelector('input[type="month"]'), { target: { value: '2026-10' } });
};

describe('Corregir el periodo de un aporte', () => {
  it('si el periodo tiene un aporte observado, avisa y reemplaza solo cuando se confirma', async () => {
    api.updateContributionPeriodo
      .mockRejectedValueOnce({ response: { status: 409, data: { detail: ocupado } } })
      .mockResolvedValueOnce({ ...aporte, periodo: '2026-10' });
    await abrirModal();

    fireEvent.click(screen.getByRole('button', { name: 'Guardar periodo' }));
    const aviso = await screen.findByRole('alert');
    expect(aviso).toHaveTextContent('ya tiene un aporte OBSERVADO para el periodo 2026-10');
    expect(aviso).toHaveTextContent('El voucher no se lee');
    // el primer intento no reemplaza nada
    expect(api.updateContributionPeriodo).toHaveBeenCalledWith(7, '2026-10', false);
    expect(toast.error).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /Reemplazar el de 2026-10 con este voucher/ }));
    await waitFor(() => expect(api.updateContributionPeriodo).toHaveBeenLastCalledWith(7, '2026-10', true));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(toast.success.mock.calls[0][0]).toMatch(/reemplazó al aporte observado/);
    expect(screen.queryByRole('alert')).toBeNull(); // se cierra
  });

  it('si el periodo tiene un aporte ya aceptado, muestra el error y no ofrece reemplazar', async () => {
    api.updateContributionPeriodo.mockRejectedValue({
      response: { status: 409, data: { detail: 'Este beneficiario ya tiene un aporte ACEPTADO para el periodo 2026-10: no se puede reemplazar.' } },
    });
    await abrirModal();
    fireEvent.click(screen.getByRole('button', { name: 'Guardar periodo' }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('ACEPTADO')));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByRole('button', { name: /Reemplazar/ })).toBeNull();
  });

  it('un cambio sin conflicto se guarda directamente', async () => {
    api.updateContributionPeriodo.mockResolvedValue({ ...aporte, periodo: '2026-10' });
    await abrirModal();
    fireEvent.click(screen.getByRole('button', { name: 'Guardar periodo' }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Aporte reasignado al periodo 2026-10.'));
    expect(api.updateContributionPeriodo).toHaveBeenCalledTimes(1);
  });
});
