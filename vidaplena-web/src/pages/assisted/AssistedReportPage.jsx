import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import AssistedBeneficiariesReport from '../reports/AssistedBeneficiariesReport';

export default function AssistedReportPage() {
  const navigate = useNavigate();
  return (
    <div className="max-w-7xl mx-auto animate-fadeIn space-y-4">
      <button onClick={() => navigate('/dashboard/registro-asistido')} className="text-sm text-gray-500 hover:text-gray-800 inline-flex items-center gap-1">
        <ArrowLeft size={16} /> Volver al Registro Asistido
      </button>
      <AssistedBeneficiariesReport />
    </div>
  );
}
