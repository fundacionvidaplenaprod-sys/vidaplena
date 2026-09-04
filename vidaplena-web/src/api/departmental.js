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
 * `items`: [{ insulinType, presentacion, quantity }, ...] — un beneficiario
 * puede necesitar más de un tipo de insulina en la misma visita.
 * `observaciones`: nota libre sobre el beneficiario en esta visita (cambio
 * de insulina solicitado, impedimento por viaje, fallecimiento, sospecha de
 * reventa, etc.) — se aplica a todos los items de esta misma entrega.
 */
export const createDepartmentalInsulinDelivery = async ({ patientId, items, deliveryDate, observaciones }) => {
  const { data } = await client.post('/departmental/entregas-insulina', {
    patient_id: patientId,
    delivery_date: deliveryDate || undefined,
    items: items.map(({ insulinType, presentacion, quantity }) => ({
      insulin_type: insulinType,
      presentacion,
      quantity,
    })),
    observaciones: observaciones || undefined,
  });
  return data;
};

/**
 * Historial de entregas registradas, acotado por departamento. `search`
 * filtra por nombre/CI del beneficiario, para revisar qué se le entregó a
 * un paciente puntual.
 */
export const getDepartmentalInsulinDeliveries = async ({ skip = 0, limit = 20, patientId, depto = '', search = '' } = {}) => {
  const params = { skip, limit, patient_id: patientId || undefined, depto: depto || undefined, search: search || undefined };
  const { data } = await client.get('/departmental/entregas-insulina', { params });
  return data;
};

/**
 * Corrige una entrega ya registrada (tipo, presentación, cantidad, fecha,
 * observaciones) — para cuando el responsable departamental se da cuenta
 * de un error después de guardarla. Misma autorización que registrar
 * entregas (RESPONSABLE_DEPARTAMENTAL/SUPER_ADMIN), sin ventana de tiempo.
 */
export const updateDelivery = async (deliveryId, { insulinType, presentacion, quantity, deliveryDate, observaciones }) => {
  const { data } = await client.put(`/departmental/entregas-insulina/${deliveryId}`, {
    insulin_type: insulinType,
    presentacion,
    quantity,
    delivery_date: deliveryDate || undefined,
    observaciones: observaciones || undefined,
  });
  return data;
};

/**
 * Corrige SOLO la observación de una entrega, sin tocar el resto de sus
 * datos. Vía angosta exclusiva de COORDINADOR_NACIONAL/SUPER_ADMIN — el
 * responsable departamental usa `updateDelivery` (arriba), que también le
 * permite corregir la observación junto con el resto.
 */
export const updateDeliveryObservaciones = async (deliveryId, observaciones) => {
  const { data } = await client.put(`/departmental/entregas-insulina/${deliveryId}/observaciones`, {
    observaciones: observaciones || null,
  });
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
 * `items`: [{ insulinType, presentacion, quantity }, ...] — un responsable
 * puede necesitar recibir más de un tipo de insulina en el mismo envío.
 */
export const createInsulinShipment = async ({ recipientUserId, items, shipmentDate }) => {
  const { data } = await client.post('/departmental/envios-insulina', {
    recipient_user_id: recipientUserId,
    shipment_date: shipmentDate || undefined,
    items: items.map(({ insulinType, presentacion, quantity }) => ({
      insulin_type: insulinType,
      presentacion,
      quantity,
    })),
  });
  return data;
};

/** Historial de envíos del coordinador nacional a responsables de departamento. */
export const getInsulinShipments = async ({ skip = 0, limit = 20, depto = '' } = {}) => {
  const params = { skip, limit, depto: depto || undefined };
  const { data } = await client.get('/departmental/envios-insulina', { params });
  return data;
};
