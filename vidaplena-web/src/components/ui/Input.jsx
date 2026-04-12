import React from 'react';

export const Input = React.forwardRef(({ label, error, className, ...props }, ref) => {
  return (
    <div className="flex flex-col gap-1 w-full">
      {label && (
        <label className="text-sm font-bold text-vida-primary ml-1">
          {label}
        </label>
      )}
      <input
        ref={ref}
        className={`
          w-full 
          bg-vida-bg text-ui-text placeholder-gray-400
          rounded-xl px-4 py-3 outline-none transition-all 
          border border-transparent
          focus:border-vida-main focus:bg-white focus:ring-4 focus:ring-vida-light/20
          ${error ? 'border-red-500 bg-red-50' : ''}
          ${className || ''}
        `}
        {...props}
      />
      {error && <span className="text-xs text-red-500 ml-1 font-bold">{error.message}</span>}
    </div>
  );
});

Input.displayName = 'Input';