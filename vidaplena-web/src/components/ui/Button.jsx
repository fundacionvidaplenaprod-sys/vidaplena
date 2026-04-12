import React from 'react';

export const Button = ({ children, variant = 'primary', className, ...props }) => {
  
  const baseStyles = "w-full py-3 px-6 rounded-3xl font-bold transition-all active:scale-95 flex items-center justify-center gap-2 cursor-pointer shadow-sm";
  
  const variants = {
    // Primario: Verde Medio (Institucional)
    primary: "bg-vida-main hover:bg-vida-hover text-white",
    
    // Secundario: Dorado (Para resaltar acciones especiales o volver atrás)
    secondary: "bg-accent-gold hover:bg-yellow-500 text-vida-primary",
    
    // Bordeado
    outline: "bg-transparent border-2 border-vida-main text-vida-main hover:bg-vida-bg",
    
    // Ghost
    ghost: "text-vida-primary hover:bg-vida-bg",
  };

  return (
    <button 
      className={`${baseStyles} ${variants[variant] || variants.primary} ${className || ''}`}
      {...props}
    >
      {children}
    </button>
  );
};