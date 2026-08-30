// Lista fija de departamentos de Bolivia. Única fuente de verdad en el
// frontend — antes estaba duplicada en RegisterPatientPage y
// SelfRegisterPatientPage. También usada por UsersManagementPage para
// asignar departamento a un RESPONSABLE_DEPARTAMENTAL y por el panel
// departamental para filtrar (Coordinador Nacional).
export const DEPARTAMENTOS = [
  "La Paz", "Cochabamba", "Santa Cruz", "Oruro",
  "Potosí", "Chuquisaca", "Tarija", "Beni", "Pando",
];

// Departamentos donde la Fundación asigna un RESPONSABLE_DEPARTAMENTAL.
// Pando queda excluido (no hay responsable ahí). La lista completa se sigue
// usando para el filtro del Coordinador Nacional y el registro de pacientes.
export const DEPARTAMENTOS_RESPONSABLE = DEPARTAMENTOS.filter((d) => d !== "Pando");
