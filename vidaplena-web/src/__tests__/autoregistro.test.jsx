import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import App from '../App';
import LoginPage from '../pages/auth/LoginPage';
import { AuthProvider } from '../context/AuthContext';

// El interruptor vive en constants/features.js. Se mockea con un objeto mutable
// para poder probar los dos estados (cerrado / abierto) sin tocar el archivo real.
const flags = vi.hoisted(() => ({ AUTOREGISTRO_HABILITADO: false }));
vi.mock('../constants/features', () => flags);

const TEXTO_LINK_LOGIN = /¿Eres beneficiario de la Fundación\?/;
const TITULO_FORMULARIO = 'Registro de Beneficiario';
const TITULO_AVISO = 'Registro de beneficiarios cerrado';

function renderApp(ruta) {
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <App />
    </MemoryRouter>
  );
}

beforeEach(() => {
  localStorage.clear();
});

describe('Autoregistro de beneficiarios — registro CERRADO', () => {
  beforeEach(() => {
    flags.AUTOREGISTRO_HABILITADO = false;
  });

  it('el login no muestra el enlace de autoregistro', () => {
    renderApp('/login');

    expect(screen.getByText('Iniciar Sesión')).toBeInTheDocument();
    expect(screen.queryByText(TEXTO_LINK_LOGIN)).not.toBeInTheDocument();
  });

  it('el resto del login sigue intacto (incluido el acceso de la Directora)', () => {
    renderApp('/login');

    expect(screen.getByText(/Entrar al Sistema/)).toBeInTheDocument();
    expect(screen.getByText(/Módulo de Directora/)).toBeInTheDocument();
  });

  it('escribir la URL directa muestra el aviso y NO el formulario', () => {
    renderApp('/registro-beneficiario');

    expect(screen.getByText(TITULO_AVISO)).toBeInTheDocument();
    expect(screen.queryByText(TITULO_FORMULARIO)).not.toBeInTheDocument();
    // Ningún campo del formulario de registro llega a montarse.
    expect(screen.queryByText('Verificación de Identidad')).not.toBeInTheDocument();
  });

  it('el aviso ofrece salidas: iniciar sesión e ir al inicio', () => {
    renderApp('/registro-beneficiario');

    expect(screen.getByRole('button', { name: /Iniciar sesión/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Ir al inicio/ })).toBeInTheDocument();
  });

  it('"Iniciar sesión" del aviso lleva al login', () => {
    renderApp('/registro-beneficiario');

    fireEvent.click(screen.getByRole('button', { name: /Iniciar sesión/ }));

    expect(screen.getByText(/Entrar al Sistema/)).toBeInTheDocument();
    expect(screen.queryByText(TITULO_AVISO)).not.toBeInTheDocument();
  });
});

describe('Autoregistro de beneficiarios — registro ABIERTO (reversibilidad)', () => {
  beforeEach(() => {
    flags.AUTOREGISTRO_HABILITADO = true;
  });

  it('el login vuelve a mostrar el enlace', () => {
    renderApp('/login');

    expect(screen.getByText(TEXTO_LINK_LOGIN)).toBeInTheDocument();
  });

  it('el enlace del login lleva al formulario de registro', () => {
    // Router mínimo: solo se prueba el enlace, sin montar toda la aplicación.
    // LoginPage usa useAuth, así que necesita su AuthProvider.
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={['/login']}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/registro-beneficiario" element={<div>destino-registro</div>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    fireEvent.click(screen.getByText(TEXTO_LINK_LOGIN));

    expect(screen.getByText('destino-registro')).toBeInTheDocument();
  });

  it('la URL directa vuelve a mostrar el formulario y no el aviso', () => {
    renderApp('/registro-beneficiario');

    expect(screen.getByText(TITULO_FORMULARIO)).toBeInTheDocument();
    expect(screen.queryByText(TITULO_AVISO)).not.toBeInTheDocument();
  });
});
