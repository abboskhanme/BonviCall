/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Source: contract/error-codes.json
 * Regenerate: make types   (panel: npm run gen:types)
 *
 * Hand-editing this file is a CONVENTIONS.md §1 violation: the Pydantic schemas
 * are the source of truth and a hand-written copy drifts silently.
 */

/** Every error code the server can emit (server/src/core/errors.py::ErrorCode). */
export const ERROR_CODES = [
  'agent_has_open_assignment',
  'apk_rejected',
  'app_error',
  'app_version_unsupported',
  'assignment_overlap',
  'audio_expired',
  'audio_not_attributable',
  'audio_not_found',
  'bad_request',
  'call_identity_conflict',
  'call_not_found',
  'callback_receiver_down',
  'cannot_modify_self',
  'checksum_mismatch',
  'chunk_checksum_mismatch',
  'chunk_offset_mismatch',
  'conflict',
  'delete_not_allowed',
  'enrolment_code_expired',
  'enrolment_code_not_found',
  'enrolment_code_revoked',
  'enrolment_code_used',
  'forbidden',
  'header_missing',
  'installation_already_active',
  'installation_mismatch',
  'installation_revoked',
  'internal_error',
  'last_admin',
  'method_not_allowed',
  'msisdn_unavailable',
  'not_found',
  'number_already_assigned',
  'number_mismatch',
  'payload_too_large',
  'range_not_satisfiable',
  'rate_limited',
  'refresh_reused',
  'retention_confirmation_required',
  'sales_user_requires_agent',
  'self_declared_disabled',
  'stranded_count_mismatch',
  'unauthorized',
  'upload_expired',
  'validation_error',
  'verification_required',
] as const

/** The stable machine contract clients branch on. Never branch on the message. */
export type ErrorCode = (typeof ERROR_CODES)[number]

export function isErrorCode(value: string): value is ErrorCode {
  return (ERROR_CODES as readonly string[]).includes(value)
}
