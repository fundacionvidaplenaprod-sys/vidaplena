import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import RegisterPatientPage from '../RegisterPatientPage';
import { createPatient } from '../../../api/patients';
import { useNavigate } from 'react-router-dom';
import { toast } from 'react-hot-toast';

vi.mock('../../../api/patients');
vi.mock('react-hot-toast', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
  },
}));
vi.mock('react-router-dom', async (importActual) => {
  const actual = await importActual();
  return {
    ...actual,
    useNavigate: vi.fn(),
  };
});

window.alert = vi.fn();

const mockNavigate = vi.fn();
useNavigate.mockReturnValue(mockNavigate);

describe('RegisterPatientPage - Minor User Flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.alert.mockClear();
  });

  it('shows tutor fields for minors and includes them in the payload', async () => {
    render(<RegisterPatientPage />);

    // Fill step 1 required fields
    fireEvent.change(screen.getByLabelText(/Nombres/i), { target: { value: 'Juan' } });
    fireEvent.change(screen.getByLabelText(/Ap\. Paterno/i), { target: { value: 'Perez' } });
    fireEvent.change(screen.getByLabelText(/C\.I\./i), { target: { value: '12345678' } });
    // Set birth date to make user a minor (e.g., 10 years ago)
    const tenYearsAgo = new Date();
    tenYearsAgo.setFullYear(tenYearsAgo.getFullYear() - 10);
    const isoDate = tenYearsAgo.toISOString().split('T')[0];
    fireEvent.change(screen.getByLabelText(/Nacimiento/i), { target: { value: isoDate } });
    fireEvent.change(screen.getByLabelText(/Peso \(Kg\)/i), { target: { value: '30' } });
    fireEvent.change(screen.getByLabelText(/Altura \(m\)/i), { target: { value: '1.2' } });
    fireEvent.change(screen.getByLabelText(/Tipo Sangre/i), { target: { value: 'O+' } });
    fireEvent.change(screen.getByLabelText(/Departamento \*/i), { target: { value: 'La Paz' } });
    fireEvent.change(screen.getByLabelText(/Municipio \*/i), { target: { value: 'La Paz' } });
    fireEvent.change(screen.getByLabelText(/Zona \*/i), { target: { value: 'Centro' } });
    fireEvent.change(screen.getByLabelText(/Dirección Detallada \*/i), { target: { value: 'Calle 1' } });
    fireEvent.change(screen.getByLabelText(/Tel\. Contacto \*/i), { target: { value: '12345678' } });
    fireEvent.change(screen.getByLabelText(/Correo Electrónico \*/i), { target: { value: 'juan@example.com' } });

    // Tutor fields should now be visible
    expect(screen.getByLabelText(/Nombre Tutor/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Nombre Tutor/i), { target: { value: 'Maria' } });
    fireEvent.change(screen.getByLabelText(/Apellidos Tutor/i), { target: { value: 'Gomez' } });
    fireEvent.change(screen.getByLabelText(/C\.I\. Tutor/i), { target: { value: '87654321' } });
    fireEvent.change(screen.getByLabelText(/Dirección Tutor/i), { target: { value: 'Avenida 2' } });
    fireEvent.change(screen.getByLabelText(/Teléfonos/i), { target: { value: '98765432' } });
    fireEvent.change(screen.getByLabelText(/Email Tutor/i), { target: { value: 'maria@example.com' } });

    // Move to next step
    fireEvent.click(screen.getByRole('button', { name: /Siguiente Paso/i }));

    // Fill medical info (step 2)
    await waitFor(() => expect(screen.getByText(/Información Médica/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/Tipo de Diabetes \*/i), { target: { value: 'Tipo 1' } });
    fireEvent.change(screen.getByLabelText(/Tiempo con la enfermedad \*/i), { target: { value: '2 años' } });
    
    // Fill insulin dose (it has a placeholder "Ej: 24")
    fireEvent.change(screen.getByPlaceholderText(/Ej: 24/i), { target: { value: '10' } });

    // Proceed to step 3
    fireEvent.click(screen.getByRole('button', { name: /Siguiente Paso/i }));

    // Submit
    await waitFor(() => expect(screen.getByText(/Finalizar Registro/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /Finalizar Registro/i }));

    await waitFor(() => {
      expect(createPatient).toHaveBeenCalledTimes(1);
      const payload = createPatient.mock.calls[0][0];
      expect(payload.tutor).toMatchObject({
        nombres: 'Maria',
        apellidos: 'Gomez',
        ci: '87654321',
        direccion: 'Avenida 2',
        telefonos: '98765432',
        email: 'maria@example.com',
      });
      expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('Paciente registrado correctamente'));
    });
  });
});
