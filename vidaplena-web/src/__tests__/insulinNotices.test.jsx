import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import InsulinNoticesSection from '../components/patients/InsulinNoticesSection';
import { ventanaEntregaPorDefecto, ventanaEntregaTexto } from '../utils/insulinDistribution';

const api = vi.hoisted(() => ({
  listMyInsulinNotices: vi.fn(),
  markInsulinNoticeSeen: vi.fn(),
  uploadInsulinNoticePhoto: vi.fn(),
}));
vi.mock('../api/donations', () => api);
vi.mock('react-hot-toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const tratamiento = (insulina, productos, extra = {}) => ({
  insulina, dosis_diaria: 20, dosis_registrada: 20, dosis_limitada: false, sustituto: null,
  envases: productos.reduce((s, p) => s + p.envases, 0), ui: productos.reduce((s, p) => s + p.ui, 0),
  dias_cubiertos: 60, productos, ...extra,
});

const foto = (tipo, url, extra = {}) => ({
  tipo, url, subida_at: '2026-11-25T10:00:00Z', estado: 'PENDIENTE', observacion: null, revisada_at: null, revisada_por: null,
  ...extra,
});

const aviso = (id, distribution_id, consolidated_at, tratamientos, extra = {}) => ({
  id, distribution_id, consolidated_at, dias: 60, mensaje: null, visto_at: null,
  envases: tratamientos.reduce((s, t) => s + t.envases, 0), ui: tratamientos.reduce((s, t) => s + t.ui, 0),
  tratamientos, ...extra,
});

describe('Aviso de insulina en el Portal del Beneficiario', () => {
  beforeEach(() => vi.clearAllMocks());

  it('muestra lo que le corresponde y registra «Entendido»', async () => {
    api.listMyInsulinNotices.mockResolvedValue([
      aviso(12, 89, '2026-11-24T15:00:00Z', [
        tratamiento('Glargina', [
          { producto: 'Lantus SoloStar 3 ml', envases: 3, ui: 900, lote: 'LAN-2411', fecha_venc: '2027-12-31' },
          { producto: 'Levemir FlexPen 3 ml', envases: 1, ui: 300, lote: 'LEV-5520', fecha_venc: '2027-06-30' },
        ], { sustituto: 'Detemir', dosis_diaria: 30, dosis_registrada: 48, dosis_limitada: true }),
        tratamiento('Lispro', [], { envases: 0, ui: 0, dias_cubiertos: 0 }),
      ], { mensaje: 'Llevar su carnet de identidad', entrega_desde: '2026-12-01', entrega_hasta: '2026-12-10' }),
      aviso(5, 87, '2026-09-10T15:00:00Z', [tratamiento('Glargina', [
        { producto: 'Lantus SoloStar 3 ml', envases: 4, ui: 1200, lote: 'LAN-1', fecha_venc: '2027-01-31' },
      ])], { visto_at: '2026-09-11T10:00:00Z', entrega_desde: '2026-10-01', entrega_hasta: '2026-10-10' }),
    ]);
    api.markInsulinNoticeSeen.mockResolvedValue({ id: 12, visto_at: '2026-11-25T14:00:00Z' });
    render(<InsulinNoticesSection />);

    const seccion = await screen.findByRole('region', { name: 'Insulina que le corresponde' });
    expect(seccion).toHaveTextContent('Nuevo');
    expect(seccion).toHaveTextContent('Le corresponde 4 envase(s) (1.200 UI)');
    expect(seccion).toHaveTextContent(
      'Fecha de entrega: del 1 de diciembre al 10 de diciembre de 2026.Coordine el día y la hora con el(la) responsable de su departamento.'
    );
    expect(seccion).toHaveTextContent('4 envase(s) · 1.200 UI · cubre ≈ 60 días');
    // El número de lote, rotulado, en la línea de cada producto.
    const linea = (producto) => screen.getByText(new RegExp(producto)).closest('li');
    expect(linea('Lantus SoloStar 3 ml')).toHaveTextContent(/^3 × Lantus SoloStar 3 mlN\.º de lote: LAN-2411Vence: /);
    expect(linea('Levemir FlexPen 3 ml')).toHaveTextContent(/^1 × Levemir FlexPen 3 mlN\.º de lote: LEV-5520Vence: /);
    expect(screen.getByText(/Parte se cubre con Detemir/)).toBeInTheDocument();
    expect(screen.getByText(/la dosis registrada es 48 UI\/día/)).toBeInTheDocument();
    expect(screen.getByText('En este reparto no se asignó insulina para este tratamiento.')).toBeInTheDocument();
    expect(screen.getByText('Llevar su carnet de identidad')).toBeInTheDocument();
    expect(screen.getByText('Repartos anteriores (1)')).toBeInTheDocument();
    expect(screen.getByText(/entrega del 1 de octubre al 10 de octubre de 2026/)).toHaveTextContent(/lote LAN-1, ≈ 60 días/);

    fireEvent.click(screen.getByRole('button', { name: /Entendido/ }));
    await waitFor(() => expect(api.markInsulinNoticeSeen).toHaveBeenCalledWith(12));
    expect(await screen.findByText(/Visto el/)).toBeInTheDocument();
    expect(screen.queryByText('Nuevo')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Entendido/ })).not.toBeInTheDocument();
  });

  it('sube la foto de sus insulinas usadas y muestra la de HbA1c que ya envió', async () => {
    const pdf = 'https://storage.test/pacientes/1/repartos/89/hemoglobina_glucosilada_abc.pdf';
    const jpg = 'https://storage.test/pacientes/1/repartos/89/insulinas_usadas_def.jpg';
    api.listMyInsulinNotices.mockResolvedValue([
      aviso(12, 89, '2026-11-24T15:00:00Z', [tratamiento('Glargina', [
        { producto: 'Lantus SoloStar 3 ml', envases: 3, ui: 900, lote: 'LAN-2411', fecha_venc: '2027-12-31' },
      ])], { foto_hba1c: foto('hba1c', pdf) }),
    ]);
    api.uploadInsulinNoticePhoto.mockResolvedValue(foto('envases', jpg));
    render(<InsulinNoticesSection />);
    await screen.findByText('Envíe sus fotos para esta entrega');

    // La HbA1c ya enviada (en PDF) se puede ver y cambiar; la de las insulinas usadas todavía no está.
    expect(screen.getByRole('link', { name: 'Ver foto de su hemoglobina glucosilada' })).toHaveAttribute('href', pdf);
    expect(screen.getByLabelText('Foto de su hemoglobina glucosilada')).toHaveAttribute('accept', 'image/*,application/pdf');
    expect(screen.getByLabelText('Foto de sus insulinas ya usadas')).toHaveAttribute('accept', 'image/*');
    expect(screen.queryByRole('link', { name: 'Ver foto de sus insulinas ya usadas' })).not.toBeInTheDocument();

    const file = new File(['jpeg'], 'plumas.jpg', { type: 'image/jpeg' });
    fireEvent.change(screen.getByLabelText('Foto de sus insulinas ya usadas'), { target: { files: [file] } });
    await waitFor(() => expect(api.uploadInsulinNoticePhoto).toHaveBeenCalledWith(12, 'envases', file));
    expect(await screen.findByRole('link', { name: 'Ver foto de sus insulinas ya usadas' })).toHaveAttribute('href', jpg);
    expect(screen.getAllByText(/en revisión/)).toHaveLength(2);
    expect(screen.getAllByText('Cambiar')).toHaveLength(2);
  });

  it('una foto aprobada ya no se cambia y una observada muestra el motivo para subir otra', async () => {
    api.listMyInsulinNotices.mockResolvedValue([
      aviso(12, 89, '2026-11-24T15:00:00Z', [tratamiento('Glargina', [
        { producto: 'Lantus SoloStar 3 ml', envases: 3, ui: 900, lote: 'LAN-2411', fecha_venc: '2027-12-31' },
      ])], {
        foto_envases: foto('envases', 'https://storage.test/insulinas_usadas_1.jpg', { estado: 'APROBADA', revisada_at: '2026-11-26T10:00:00Z' }),
        foto_hba1c: foto('hba1c', 'https://storage.test/hba1c_1.jpg', {
          estado: 'OBSERVADA', observacion: 'La foto está borrosa y no se lee el resultado.', revisada_at: '2026-11-26T10:00:00Z',
        }),
      }),
    ]);
    render(<InsulinNoticesSection />);
    await screen.findByText('Envíe sus fotos para esta entrega');

    expect(screen.getByText(/Aprobada por la Fundación el/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Foto de sus insulinas ya usadas')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(
      'La Fundación la observó: La foto está borrosa y no se lee el resultado. Por favor, suba otra.'
    );
    expect(screen.getByLabelText('Foto de su hemoglobina glucosilada')).toBeInTheDocument();
    expect(screen.getByText('Subir otra foto')).toBeInTheDocument();
  });

  it('un aviso sin fecha de entrega no muestra el recuadro de la entrega', async () => {
    api.listMyInsulinNotices.mockResolvedValue([
      aviso(3, 80, '2026-11-24T15:00:00Z', [tratamiento('Glargina', [
        { producto: 'Lantus SoloStar 3 ml', envases: 2, ui: 600, lote: null, fecha_venc: null },
      ])]),
    ]);
    render(<InsulinNoticesSection />);
    await screen.findByRole('region', { name: 'Insulina que le corresponde' });
    expect(screen.queryByText(/Fecha de entrega/)).not.toBeInTheDocument();
    expect(screen.getByText(/Lantus SoloStar 3 ml/).closest('li')).toHaveTextContent('2 × Lantus SoloStar 3 mlN.º de lote: sin dato');
    expect(screen.queryByText(/Vence:/)).not.toBeInTheDocument();
  });

  it('sin repartos consolidados no muestra nada', async () => {
    api.listMyInsulinNotices.mockResolvedValue([]);
    const { container } = render(<InsulinNoticesSection />);
    await waitFor(() => expect(api.listMyInsulinNotices).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe('ventana de entrega', () => {
  it('por defecto, del 1 al 10 del mes siguiente (también en diciembre)', () => {
    expect(ventanaEntregaPorDefecto(new Date(2026, 10, 24))).toEqual({ desde: '2026-12-01', hasta: '2026-12-10' });
    expect(ventanaEntregaPorDefecto(new Date(2026, 11, 15))).toEqual({ desde: '2027-01-01', hasta: '2027-01-10' });
  });

  it('dice «del … al …», con el año en las dos fechas solo si cambia', () => {
    expect(ventanaEntregaTexto('2026-12-01', '2026-12-10')).toBe('del 1 de diciembre al 10 de diciembre de 2026');
    expect(ventanaEntregaTexto('2026-12-28', '2027-01-05')).toBe('del 28 de diciembre de 2026 al 5 de enero de 2027');
    expect(ventanaEntregaTexto('2026-12-05', '2026-12-05')).toBe('el 5 de diciembre de 2026');
    expect(ventanaEntregaTexto(null, null)).toBe('');
  });
});
