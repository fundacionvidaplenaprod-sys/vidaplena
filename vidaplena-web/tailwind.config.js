/** @type {import('tailwindcss').Config} */
export default {
    content: [
      "./index.html",
      "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
      extend: {
        colors: {
          // TU PALETA PERSONALIZADA
          vida: {
            primary: '#0F3D1E',    // Verde oscuro (Sidebar / Títulos)
            main:    '#1F6B2C',    // Verde medio (Botones Primarios)
            hover:   '#145A25',    // Hover botones
            light:   '#6FBF73',    // Verde claro (Detalles)
            bg:      '#E9F5EC',    // Verde muy claro (Fondos / Inputs)
            white:   '#FFFFFF',    // Blanco base
          },
          // ACENTOS CALIDOS (Logo)
          accent: {
            gold:   '#F2C94C', // Amarillo dorado
            orange: '#F2994A', // Naranja
            lime:   '#8BC34A', // Verde lima
            blue:   '#2F80ED', // Azul globo
            sky:    '#56CCF2', // Azul claro
          },
          // NEUTROS UI
          ui: {
            gray:  '#F3F4F6', // Gris claro UI
            text:  '#1F2933', // Texto principal (casi negro)
            text2: '#6B7280', // Texto secundario
          }
        },
        borderRadius: {
          'xl': '1rem',
          '2xl': '1.5rem',
          '3xl': '2rem',
        },
        fontFamily: {
          sans: ['Inter', 'system-ui', 'sans-serif'], // Recomendado para UI limpia
        }
      },
    },
    plugins: [],
  }