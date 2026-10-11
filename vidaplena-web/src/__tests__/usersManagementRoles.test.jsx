import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import UsersManagementPage from '../pages/admin/UsersManagementPage';

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }));
vi.mock('../api/axios', () => ({ default: api }));
vi.mock('react-hot-toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const usuario = (id, email, role) => ({
  id, email, role, estado: 'ACTIVO', depto_asignado: null, exoneracion_cargo: null,
  last_login: null, created_at: '2026-01-01T00:00:00', updated_at: '2026-01-01T00:00:00',
});

const opciones = () => Array.from(screen.getByLabelText('Rol').options).map((o) => o.value);

beforeEach(() => {
  api.get.mockReset();
  api.put.mockReset();
  api.post.mockReset();
});

describe('UsersManagementPage: rol de la cuenta de un beneficiario', () => {
  it('al editar una cuenta PACIENTE muestra y conserva su rol al restablecer la contraseña', async () => {
    api.get.mockResolvedValue({ data: { items: [usuario(7, 'maria@correo.com', 'PACIENTE')], total: 1 } });
    api.put.mockResolvedValue({ data: {} });
    render(<UsersManagementPage />);

    fireEvent.click(await screen.findByRole('button', { name: /Beneficiarios/ }));
    await screen.findByText('maria@correo.com');
    fireEvent.click(screen.getByTitle('Editar'));

    expect(screen.getByLabelText('Rol')).toHaveValue('PACIENTE');
    expect(opciones()).toContain('PACIENTE');

    fireEvent.change(document.querySelector('input[type="password"]'), { target: { value: 'NuevaClave2026!' } });
    fireEvent.click(screen.getByRole('button', { name: /Guardar|Actualizar/ }));

    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    const [url, payload] = api.put.mock.calls[0];
    expect(url).toBe('/users/7');
    expect(payload.role).toBe('PACIENTE');
    expect(payload.password).toBe('NuevaClave2026!');
  });

  it('no ofrece PACIENTE al crear una cuenta ni al editar personal', async () => {
    api.get.mockResolvedValue({ data: { items: [usuario(3, 'staff@vida.org', 'REGISTRADOR')], total: 1 } });
    render(<UsersManagementPage />);

    await screen.findByText('staff@vida.org');
    fireEvent.click(screen.getByTitle('Editar'));
    expect(opciones()).not.toContain('PACIENTE');
    expect(screen.getByLabelText('Rol')).toHaveValue('REGISTRADOR');
  });
});
