import React from 'react';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import DepartmentalDashboardPage from '../pages/departmental/DepartmentalDashboardPage';

const api = vi.hoisted(() => ({
  getActiveDepartmentalBeneficiaries: vi.fn(),
  getPendingDocDepartmentalBeneficiaries: vi.fn(),
  getDepartmentalInsulinDeliveries: vi.fn(),
  createDepartmentalInsulinDelivery: vi.fn(),
  updateDelivery: vi.fn(),
  updateDeliveryObservaciones: vi.fn(),
  getDepartmentalResponsables: vi.fn(),
  createInsulinShipment: vi.fn(),
  getInsulinShipments: vi.fn(),
}));
vi.mock('../api/departmental', () => api);
vi.mock('react-hot-toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const beneficiario = (extra = {}) => ({
  id: 1,
  nombres: 'Ana',
  ap_paterno: 'Quispe',
  ap_materno: null,
  ci: '111',
  depto: 'La Paz',
  tel_contacto: null,
  estado: 'ACTIVO',
  exonerado_aporte: false,
  exonerado_por_cargo: false,
  al_dia_aporte: true,
  periodo_actual: '2026-11',
  al_dia_mes_anterior: false,
  periodo_anterior: '2026-10',
  aportes_recientes: [
    { periodo: '2026-11', al_dia: true },
    { periodo: '2026-10', al_dia: false },
    { periodo: '2026-09', al_dia: true },
    { periodo: '2026-08', al_dia: true },
  ],
  tratamientos: [],
  ...extra,
});

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  localStorage.setItem('user', JSON.stringify({ role: 'COORDINADOR_NACIONAL' }));
});

describe('Panel departamental: aportes de los últimos 4 meses', () => {
  it('muestra el estado del aporte de los cuatro meses, el más reciente primero', async () => {
    api.getActiveDepartmentalBeneficiaries.mockResolvedValue({ total: 1, items: [beneficiario()] });
    render(<DepartmentalDashboardPage />);

    await screen.findByText(/Ana/);
    const fila = screen.getByText(/Ana/).closest('div[class*="flex"]').parentElement;
    const chips = within(fila).getAllByText(/\((2026-\d\d)\)/).map((el) => el.textContent.trim());
    expect(chips).toEqual(['Al día (2026-11)', 'Sin aporte (2026-10)', 'Al día (2026-09)', 'Al día (2026-08)']);
  });

  it('un exonerado muestra «Exonerado» y no los meses', async () => {
    api.getActiveDepartmentalBeneficiaries.mockResolvedValue({
      total: 1,
      items: [beneficiario({ exonerado_aporte: true })],
    });
    render(<DepartmentalDashboardPage />);
    await screen.findByText(/Exonerado/);
    expect(screen.queryByText(/Sin aporte/)).toBeNull();
    expect(screen.queryByText(/Al día \(2026/)).toBeNull();
  });

  it('con una respuesta antigua (sin la lista) sigue mostrando el mes actual y el anterior', async () => {
    api.getActiveDepartmentalBeneficiaries.mockResolvedValue({ total: 1, items: [beneficiario({ aportes_recientes: undefined })] });
    render(<DepartmentalDashboardPage />);
    await screen.findByText(/Ana/);
    expect(screen.getByText('Al día (2026-11)')).toBeInTheDocument();
    expect(screen.getByText('Sin aporte (2026-10)')).toBeInTheDocument();
    expect(screen.queryByText(/2026-09/)).toBeNull();
  });
});
