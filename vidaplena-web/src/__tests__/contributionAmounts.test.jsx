import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import ContributionAmountsCard from '../pages/reports/ContributionAmountsCard';
import DynamicBeneficiaryReport from '../pages/reports/DynamicBeneficiaryReport';

const api = vi.hoisted(() => ({
  getContributionAmountsReport: vi.fn(),
  getPatients: vi.fn(),
  getContributionsReview: vi.fn(),
}));
vi.mock('../api/reports', () => ({ getContributionAmountsReport: api.getContributionAmountsReport }));
vi.mock('../api/patients', () => ({ getPatients: api.getPatients }));
vi.mock('../api/contributions', () => ({ getContributionsReview: api.getContributionsReview }));
vi.mock('react-hot-toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('../utils/imageToBase64', () => ({ imageToBase64: () => Promise.resolve('data:image/png;base64,AAAA') }));

const reporte = () => ({
  depto: null,
  total_activos: 11,
  exonerados_total: 3,
  exonerados_vulnerabilidad: 2,
  exonerados_cargo: 1,
  pagan: 7,
  sin_monto: 1,
  montos: [
    { monto: 25, cantidad: 2, total_bs: 50, reducido: true },
    { monto: 50, cantidad: 1, total_bs: 50, reducido: true },
    { monto: 100, cantidad: 4, total_bs: 400, reducido: false },
  ],
  ingreso_mensual_comprometido_bs: 500,
  registro_asistido: 5,
});

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  localStorage.removeItem('user');
});

describe('Resumen: beneficiarios según su aporte mensual', () => {
  it('muestra cuántos están exonerados y cuántos pagan Bs. 25, 50, 100…', async () => {
    api.getContributionAmountsReport.mockResolvedValue(reporte());
    render(<ContributionAmountsCard />);

    await screen.findByText(/Exonerados por vulnerabilidad/);
    const fila = (texto) => within(screen.getByText(texto).closest('tr'));
    expect(fila(/Exonerados por vulnerabilidad/).getByText('2')).toBeInTheDocument();
    expect(fila(/Exonerados por cargo/).getByText('1')).toBeInTheDocument();
    expect(fila(/Pagan Bs\. 25 al mes/).getByText('2')).toBeInTheDocument();
    expect(screen.getByText(/Pagan Bs\. 25 al mes \(aporte reducido\)/)).toBeInTheDocument();
    expect(screen.getByText(/Pagan Bs\. 50 al mes \(aporte reducido\)/)).toBeInTheDocument();
    // Bs. 100 no es un aporte reducido
    expect(screen.getByText('Pagan Bs. 100 al mes')).toBeInTheDocument();
    expect(fila('Pagan Bs. 100 al mes').getByText('4')).toBeInTheDocument();
    expect(fila(/Sin monto definido/).getByText('1')).toBeInTheDocument();
    expect(fila('Total de beneficiarios activos').getByText('11')).toBeInTheDocument();
    expect(screen.getByText(/Exonerados en total:/).textContent).toMatch(/Exonerados en total: 3 · Pagan: 7/);
    // el Registro Asistido, aparte y sin sumarse al total
    expect(screen.getByText((_, el) => el.tagName === 'P' && /5 persona\(s\) activa\(s\) del\s+Registro Asistido/.test(el.textContent))).toBeInTheDocument();
  });

  it('se puede filtrar por departamento', async () => {
    api.getContributionAmountsReport.mockResolvedValue(reporte());
    render(<ContributionAmountsCard />);
    await screen.findByText(/Exonerados por vulnerabilidad/);
    expect(api.getContributionAmountsReport).toHaveBeenLastCalledWith('');

    fireEvent.change(screen.getByLabelText('Departamento'), { target: { value: 'Oruro' } });
    await waitFor(() => expect(api.getContributionAmountsReport).toHaveBeenLastCalledWith('Oruro'));
  });
});

const paciente = (id, extra = {}) => ({
  id,
  nombres: `Nombre${id}`,
  ap_paterno: `Apellido${id}`,
  estado: 'ACTIVO',
  exonerado_aporte: false,
  exonerado_por_cargo: false,
  monto_aporte_comprometido: 100,
  ...extra,
});

describe('Reporte de beneficiarios: aporte comprometido', () => {
  it('muestra la columna «Aporte comprometido» y filtra por exonerados o por monto', async () => {
    api.getPatients.mockResolvedValue([
      paciente(1, { monto_aporte_comprometido: 25 }),
      paciente(2, { monto_aporte_comprometido: 25 }),
      paciente(3, { monto_aporte_comprometido: 50 }),
      paciente(4),
      paciente(5, { exonerado_aporte: true, monto_aporte_comprometido: null }),
      paciente(6, { monto_aporte_comprometido: null }),
    ]);
    api.getContributionsReview.mockResolvedValue([]);
    render(<DynamicBeneficiaryReport />);
    await screen.findByText('Apellido1');

    fireEvent.click(screen.getByRole('button', { name: /Columnas/ }));
    fireEvent.click(screen.getByLabelText('Aporte comprometido'));
    const celda = (texto) => screen.getByText((_, el) => el.tagName === 'TD' && el.textContent === texto);
    expect(celda('Bs. 50')).toBeInTheDocument();
    expect(celda('Exonerado (vulnerabilidad)')).toBeInTheDocument();
    expect(celda('Sin definir')).toBeInTheDocument();

    // el filtro lista los montos que hay
    const filtro = screen.getByLabelText('Aporte');
    const opciones = within(filtro).getAllByRole('option').map((o) => o.textContent);
    expect(opciones).toEqual([
      'Todos los aportes', 'Exonerados', 'Pagan Bs. 25', 'Pagan Bs. 50', 'Pagan Bs. 100', 'Sin monto definido', 'Registro asistido (gratuito)',
    ]);

    fireEvent.change(filtro, { target: { value: 'MONTO-25' } });
    expect(screen.getByText('Apellido1')).toBeInTheDocument();
    expect(screen.getByText('Apellido2')).toBeInTheDocument();
    expect(screen.queryByText('Apellido3')).toBeNull();
    expect(screen.getByText(/Mostrando 2 de 2 registros filtrados/)).toBeInTheDocument();

    fireEvent.change(filtro, { target: { value: 'EXONERADO' } });
    expect(screen.getByText('Apellido5')).toBeInTheDocument();
    expect(screen.queryByText('Apellido1')).toBeNull();
  });
});
