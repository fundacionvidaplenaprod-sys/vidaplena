import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext'; // ✅ 1. IMPORTA ESTO (Ajusta la ruta si es diferente)

import LoginPage from './pages/auth/LoginPage';
import DashboardLayout from './components/layout/DashboardLayout';
import PatientsListPage from './pages/patients/PatientsListPage';
import RegisterPatientPage from './pages/patients/RegisterPatientPage';
import PatientDetailsPage from './pages/patients/PatientDetailsPage';
import MyDocumentsPage from './pages/patients/MyDocumentsPage';
import PatientReviewPage from './pages/admin/PatientReviewPage';
import UsersManagementPage from './pages/admin/UsersManagementPage';
import ContributionsReviewPage from './pages/admin/ContributionsReviewPage';
import DashboardHome from './pages/dashboard/DashboardHome';
import DonationsWarehousePage from './pages/warehouse/DonationsWarehousePage';
import ReportsPage from './pages/reports/ReportsPage';
import LandingPage from './pages/LandingPage';

function App() {
  return (
    // ✅ 2. ENVUELVE TODO EL CONTENIDO CON AUTHPROVIDER
    <AuthProvider>
      <Routes>
        {/* 1. Landing, Login y Redirección Inicial */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<LoginPage />} />

        {/* 2. ZONA ADMIN (El Dashboard) */}
        <Route path="/dashboard" element={<DashboardLayout />}>
          {/* El Portero (index) decide a dónde vas */}
          <Route index element={<DashboardHome />} />

          {/* Rutas exclusivas de Admin */}
          <Route path="lista-pacientes" element={<PatientsListPage />} />
          <Route path="registro-paciente" element={<RegisterPatientPage />} />
          <Route path="editar-paciente/:id" element={<RegisterPatientPage />} />
          <Route path="pacientes/:id" element={<PatientDetailsPage />} />
          <Route path="pacientes/:id/review" element={<PatientReviewPage />} />
          <Route path="usuarios" element={<UsersManagementPage />} />
          <Route path="revision-aportes" element={<ContributionsReviewPage />} />
          <Route path="almacen-donaciones" element={<DonationsWarehousePage />} />
          <Route path="reportes" element={<ReportsPage />} />
        </Route>

        {/* 3. ZONA PACIENTE (Totalmente separada) */}
        {/* IMPORTANTE: Esta ruta NO está dentro de dashboard */}
        <Route path="/mi-portal" element={<MyDocumentsPage />} />

        {/* 4. Error 404 */}
        <Route path="*" element={<div className="p-10 text-center"><h1>404 - Página no encontrada</h1></div>} />
      </Routes>
    </AuthProvider>
  );
}

export default App;