import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import '@testing-library/jest-dom';
import PatientDetailsPage from '../pages/patients/PatientDetailsPage';

const api = vi.hoisted(() => ({
  getPatientById: vi.fn(),
  getSocialEvaluation: vi.fn(),
  updateCommitmentAmount: vi.fn(),
}));
const auth = vi.hoisted(() => ({ role: 'SUPER_ADMIN' }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock('../api/patients', () => ({
  getPatientById: api.getPatientById,
  activatePatient: vi.fn(),
  updatePatient: vi.fn(),
  changePatientStatus: vi.fn(),
  updateCommitmentAmount: api.updateCommitmentAmount,
}));
vi.mock('../api/evaluations', () => ({ getSocialEvaluation: api.getSocialEvaluation }));
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ user: { role: auth.role } }) }));
vi.mock('react-hot-toast', () => ({ toast }));

const paciente = (extra = {}) => ({
  id: 7,
  user_id: 70,
  nombres: 'Jorge Enrique',
  ap_paterno: 'Villamor',
  ap_materno: 'Loras',
  ci: '123',
  estado: 'ACTIVO',
  edad_calc: 12,
  exonerado_aporte: false,
  exonerado_por_cargo: false,
  monto_aporte_comprometido: 100,
  treatments: [],
  complications: [],
  medical: null,
  tutor: null,
  ...extra,
});

const evaluacion = {
  estado_revision: 'APROBADO',
  categoria_final: 'MEDIA',
  created_at: '2026-09-15T17:31:13Z',
  revisado_at: '2026-09-22T19:54:20Z',
};

const abrir = () =>
  render(
    <MemoryRouter initialEntries={['/patients/7']}>
      <Routes>
        <Route path="/patients/:id" element={<PatientDetailsPage />} />
      </Routes>
    </MemoryRouter>,
  );

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  toast.success.mockClear();
  toast.error.mockClear();
  auth.role = 'SUPER_ADMIN';
  api.getPatientById.mockResolvedValue(paciente());
  api.getSocialEvaluation.mockResolvedValue(evaluacion);
});

describe('Corregir el aporte comprometido', () => {
  it('el SUPER_ADMIN corrige el monto indicando el motivo y la ficha muestra el nuevo aporte', async () => {
    api.updateCommitmentAmount.mockResolvedValue(paciente({ monto_aporte_comprometido: 25, estado: 'PENDIENTE_DOC' }));
    abrir();

    await screen.findByText('Bs. 100');
    fireEvent.click(screen.getByRole('button', { name: /Corregir monto/ }));

    const monto = screen.getByLabelText('Nuevo aporte mensual (Bs.)');
    expect(monto).toHaveValue(100); // parte del monto actual
    fireEvent.change(monto, { target: { value: '25' } });
    fireEvent.change(screen.getByLabelText('Motivo de la corrección'), {
      target: { value: 'El informe indica un aporte de Bs. 25.' },
    });
    // el botón del modal es el último «Corregir monto»
    const botones = screen.getAllByRole('button', { name: 'Corregir monto' });
    fireEvent.click(botones[botones.length - 1]);

    await waitFor(() =>
      expect(api.updateCommitmentAmount).toHaveBeenCalledWith('7', 25, 'El informe indica un aporte de Bs. 25.'),
    );
    await screen.findByText('Bs. 25');
    expect(toast.success).toHaveBeenCalled();
  });

  it('exige el motivo antes de enviar y muestra el error del servidor', async () => {
    api.updateCommitmentAmount.mockRejectedValue({ response: { data: { detail: 'El aporte mínimo es de Bs. 100.' } } });
    abrir();
    await screen.findByText('Bs. 100');
    fireEvent.click(screen.getByRole('button', { name: /Corregir monto/ }));

    fireEvent.change(screen.getByLabelText('Nuevo aporte mensual (Bs.)'), { target: { value: '25' } });
    const botones = () => screen.getAllByRole('button', { name: 'Corregir monto' });
    fireEvent.click(botones()[botones().length - 1]);
    expect(api.updateCommitmentAmount).not.toHaveBeenCalled(); // sin motivo
    expect(toast.error).toHaveBeenCalledWith('Indique el motivo de la corrección.');

    fireEvent.change(screen.getByLabelText('Motivo de la corrección'), { target: { value: 'Informe de Bs. 25' } });
    fireEvent.click(botones()[botones().length - 1]);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('El aporte mínimo es de Bs. 100.'));
  });

  it('quien no es SUPER_ADMIN no ve el botón', async () => {
    auth.role = 'REGISTRADOR';
    abrir();
    await screen.findByText('Bs. 100');
    expect(screen.queryByRole('button', { name: /Corregir monto/ })).toBeNull();
  });
});
