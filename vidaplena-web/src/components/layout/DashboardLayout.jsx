import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Menu } from 'lucide-react';
// CORRECCIÓN: Usamos './' porque ahora Sidebar estará en la MISMA carpeta
import Sidebar from './Sidebar'; 

export default function DashboardLayout() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  return (
    <div className="flex h-screen w-full bg-gray-100 overflow-hidden">
      
      {/* --- SIDEBAR (Menú Lateral) --- */}
      <Sidebar isOpen={isSidebarOpen} onClose={() => setIsSidebarOpen(false)} />

      {/* --- ÁREA PRINCIPAL --- */}
      <div className="flex-1 flex flex-col h-full overflow-hidden relative">
        
        {/* HEADER MÓVIL */}
        <header className="bg-white border-b border-gray-200 h-16 flex items-center px-4 justify-between md:hidden shadow-sm z-10">
          {/* Ajustado al color corporativo */}
          <span className="font-bold text-vida-primary text-lg">Vida Plena</span>
          <button 
            onClick={() => setIsSidebarOpen(true)}
            className="p-2 text-gray-600 hover:bg-gray-100 rounded-lg"
          >
            <Menu size={24} />
          </button>
        </header>

        {/* CONTENIDO (Outlet) */}
        <main className="flex-1 overflow-y-auto p-4 md:p-8 scroll-smooth">
           <Outlet />
        </main>
        
        {/* OVERLAY PARA MÓVIL */}
        {isSidebarOpen && (
          <div 
            className="fixed inset-0 bg-black/50 z-20 md:hidden backdrop-blur-sm"
            onClick={() => setIsSidebarOpen(false)}
          />
        )}
      </div>
    </div>
  );
}