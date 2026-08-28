// src/api/departmental.js
// Endpoints del módulo departamental (RESPONSABLE_DEPARTAMENTAL / COORDINADOR_NACIONAL).
import client from './axios';

/**
 * Beneficiarios ACTIVOS del departamento del usuario (o de todos, para
 * Coordinador Nacional sin filtro), con bandera de si están al día con el
 * aporte del mes actual.
 */
export const getActiveDepartmentalBeneficiaries = async ({ skip = 0, limit = 20, search = '', depto = '' } = {}) => {
  const params = { skip, limit, search: search || undefined, depto: depto || undefined };
  const { data } = await client.get('/departmental/beneficiarios/activos', { params });
  return data;
};

/** Beneficiarios con documentación pendiente/observada, del mismo departamento. */
export const getPendingDocDepartmentalBeneficiaries = async ({ skip = 0, limit = 20, search = '', depto = '' } = {}) => {
  const params = { skip, limit, search: search || undefined, depto: depto || undefined };
  const { data } = await client.get('/departmental/beneficiarios/pendientes-docs', { params });
  return data;
};

/**
 * Registra la entrega de insulina a un beneficiario (solo log de control,
 * no descuenta stock). Exclusivo de RESPONSABLE_DEPARTAMENTAL/SUPER_ADMIN.
 */
export const createDepartmentalInsulinDelivery = async ({ patientId, insulinType, quantity, deliveryDate }) => {
  const { data } = await client.post('/departmental/entregas-insulina', {
    patient_id: patientId,
    insulin_type: insulinType,
    quantity,
    delivery_date: deliveryDate || undefined,
  });
  return data;
};

/** Historial de entregas registradas, acotado por departamento. */
export const getDepartmentalInsulinDeliveries = async ({ skip = 0, limit = 20, patientId, depto = '' } = {}) => {
  const params = { skip, limit, patient_id: patientId || undefined, depto: depto || undefined };
  const { data } = await client.get('/departmental/entregas-insulina', { params });
  return data;
};
