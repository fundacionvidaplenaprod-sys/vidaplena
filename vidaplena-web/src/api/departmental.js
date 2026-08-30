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

/** Lista de RESPONSABLE_DEPARTAMENTAL para elegir destinatario de un envío. Exclusivo de COORDINADOR_NACIONAL/SUPER_ADMIN. */
export const getDepartmentalResponsables = async () => {
  const { data } = await client.get('/departmental/responsables');
  return data;
};

/**
 * Registra el envío de insulina del coordinador nacional a un responsable de
 * departamento (log de control, no descuenta stock). Exclusivo de
 * COORDINADOR_NACIONAL/SUPER_ADMIN.
 */
export const createInsulinShipment = async ({ recipientUserId, insulinType, quantity, shipmentDate }) => {
  const { data } = await client.post('/departmental/envios-insulina', {
    recipient_user_id: recipientUserId,
    insulin_type: insulinType,
    quantity,
    shipment_date: shipmentDate || undefined,
  });
  return data;
};

/** Historial de envíos del coordinador nacional a responsables de departamento. */
export const getInsulinShipments = async ({ skip = 0, limit = 20, depto = '' } = {}) => {
  const params = { skip, limit, depto: depto || undefined };
  const { data } = await client.get('/departmental/envios-insulina', { params });
  return data;
};
