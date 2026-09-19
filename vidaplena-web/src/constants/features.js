// Interruptores de funcionalidades que la Fundación abre y cierra por decisión
// propia (plazos, campañas, etc.). Están en un solo lugar para que un mismo
// interruptor gobierne todos los accesos a una funcionalidad y no puedan quedar
// desalineados —p. ej. el link oculto pero la URL todavía abierta—.

// Autoregistro público de beneficiarios (/registro-beneficiario).
//
// Mientras sea `false`:
//   - el login no muestra el enlace "¿Eres beneficiario de la Fundación?...";
//   - la ruta /registro-beneficiario muestra un aviso de "registro cerrado" en
//     vez del formulario, así que tampoco se llega escribiendo la URL.
//
// Es un cierre a nivel de pantalla: la página del formulario y el endpoint
// POST /patients/self-register siguen existiendo. Para reabrir el registro,
// basta con poner esta constante en `true`.
export const AUTOREGISTRO_HABILITADO = false;
