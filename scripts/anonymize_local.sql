-- ============================================================================
--  Anonimiza los datos personales de beneficiarios en una copia LOCAL de la BD.
--
--  Uso (después de restore_local_db.sh):
--      psql -d vidaplena -f scripts/anonymize_local.sql
--
--  NUNCA correr contra producción. Solo para trabajar con datos reales en
--  desarrollo sin tener PII de pacientes en tu máquina.
--
--  Cubre la PII principal (nombres, apellidos, CI, domicilio, teléfonos,
--  correos de pacientes). NO toca montos, estados, fechas, departamentos ni
--  relaciones — justamente lo que necesitás para reproducir los casos de
--  filtrado/paginación. Revisá que sea suficiente para tu caso antes de
--  confiar en él (p. ej. audit_logs guarda payloads JSON que pueden incluir
--  nombres y no se limpian aquí).
-- ============================================================================

BEGIN;

-- Beneficiarios
UPDATE patients SET
    nombres       = 'Beneficiario',
    ap_paterno    = 'Apellido' || id,
    ap_materno    = NULL,
    ci            = 'CI' || id,
    direccion     = NULL,
    zona          = NULL,
    email         = NULL,
    tel_contacto  = NULL,
    tel_referencia = NULL;

-- Usuarios vinculados a un beneficiario (login de paciente)
UPDATE users u SET
    email = 'paciente' || u.id || '@example.test'
FROM patients p
WHERE p.user_id = u.id;

-- Tutores
UPDATE tutors SET
    nombres       = 'Tutor',
    apellidos     = 'Apellido' || id,
    ci            = 'CIT' || id,
    direccion     = NULL,
    telefonos     = NULL,
    telef_celular = NULL,
    email         = NULL;

-- Citas (SAPAM) — tabla independiente, guarda nombre/CI/fecha nac. sueltos
UPDATE appointments SET
    nombres         = 'Beneficiario',
    ap_paterno      = 'Apellido' || id,
    ap_materno      = NULL,
    ci              = 'CI' || id,
    fecha_nac       = DATE '1990-01-01',
    motivo_rechazo  = NULL,
    url_comprobante = NULL;

-- Entregas de "la Directora" (flujo aislado, guarda el nombre suelto)
UPDATE director_insulin_deliveries SET
    patient_nombres    = 'Beneficiario',
    patient_ap_paterno = 'Apellido' || id,
    patient_ap_materno = NULL;

-- Padrón precargado (control de autoregistro)
UPDATE preregistered_beneficiaries SET
    nombres    = 'Padron',
    ap_paterno = 'Apellido' || id,
    ap_materno = NULL;

-- Evaluación socioeconómica: único texto libre con posible dato identificable
UPDATE social_evaluations SET
    nombre_institucion_ayuda = NULL
WHERE nombre_institucion_ayuda IS NOT NULL;

-- Payloads JSONB y observaciones: pueden traer nombres/CI incrustados y no
-- hacen falta para reproducir casos de filtrado. Se limpian por completo.
UPDATE audit_logs            SET payload = NULL;
UPDATE patient_status_events SET payload = NULL, observacion = NULL;

COMMIT;

VACUUM ANALYZE;
