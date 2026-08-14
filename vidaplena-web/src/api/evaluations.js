import client from './axios';

// ─────────────────────────────────────────────────────────────────────────────
//  AUTOSERVICIO DEL BENEFICIARIO (rol PACIENTE)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Obtiene la evaluación socioeconómica del beneficiario autenticado.
 * @returns {Promise<Object|null>} SocialEvaluationResponse, o null si aún no existe.
 */
export const getMySocialEvaluation = async () => {
  try {
    const { data } = await client.get('/social-evaluations/me');
    return data;
  } catch (error) {
    if (error?.response?.status === 404) return null;
    throw error;
  }
};

/**
 * Registra o actualiza la evaluación socioeconómica propia (upsert).
 * Las URLs de evidencias deben subirse antes con `uploadMyEvaluationDocument`.
 * @param {Object} payload - SocialEvaluationSelfCreate payload
 */
export const submitMySocialEvaluation = (payload) =>
  client.post('/social-evaluations/me', payload).then((r) => r.data);

/**
 * Sube una evidencia individual (foto) de la evaluación propia.
 * @param {string} docType - 'ci' | 'fachada' | 'sala' | 'dormitorio'
 * @param {File|Blob} file
 * @returns {Promise<{msg: string, url: string, type: string}>}
 */
export const uploadMyEvaluationDocument = async (docType, file) => {
  const formData = new FormData();
  formData.append('doc_type', docType);
  formData.append('file', file);

  const response = await client.post('/social-evaluations/me/upload-document', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

// ─────────────────────────────────────────────────────────────────────────────
//  STAFF (SUPER_ADMIN / EVALUADOR_SOCIAL)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Envía el payload completo de evaluación socioeconómica al backend en
 * nombre de un beneficiario.
 * @param {Object} payload - SocialEvaluationCreate payload
 */
export const createSocialEvaluation = (payload) =>
  client.post('/social-evaluations/', payload).then((r) => r.data);

/**
 * Obtiene la evaluación socioeconómica de un paciente por su ID.
 * @param {number} patientId
 */
export const getSocialEvaluation = (patientId) =>
  client.get(`/social-evaluations/${patientId}`).then((r) => r.data);

/**
 * Lista evaluaciones. Accesible para SUPER_ADMIN y EVALUADOR_SOCIAL.
 * @param {Object} params - { alerta_urgente, estado_revision }
 */
export const listSocialEvaluations = (params = {}) =>
  client.get('/social-evaluations/', { params }).then((r) => r.data);

/**
 * Avala (aprueba) o rechaza la evaluación socioeconómica de un paciente.
 * Requiere que la entrevista virtual ya haya sido registrada.
 * @param {number} patientId
 * @param {{decision: 'APROBADO'|'RECHAZADO', motivo?: string}} payload
 */
export const reviewSocialEvaluation = (patientId, payload) =>
  client.put(`/social-evaluations/${patientId}/review`, payload).then((r) => r.data);

/**
 * Registra que el evaluador social realizó la entrevista virtual (por
 * medios externos al sistema) con el beneficiario. Requisito obligatorio
 * antes de poder llamar a `reviewSocialEvaluation`.
 * @param {number} patientId
 * @param {string} notas
 */
export const markEvaluationInterviewDone = (patientId, notas) =>
  client.put(`/social-evaluations/${patientId}/interview`, { notas }).then((r) => r.data);
