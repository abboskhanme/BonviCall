/**
 * Audit actions and actors in Uzbek.
 *
 * Exhaustive over the generated enums, so an action added on the server is a
 * compile error rather than a snake_case identifier on an admin's screen.
 */
import type { MessageKey } from '@/shared/i18n'
import type { components } from '@/shared/api/types.gen'

type AuditAction = components['schemas']['AuditAction']
type ActorType = components['schemas']['ActorType']

export const ACTOR_TYPE_LABEL: Record<ActorType, MessageKey> = {
  user: 'actor.user',
  service: 'actor.service',
  device: 'actor.device',
  system: 'actor.system',
}

export const AUDIT_ACTION_LABEL: Record<AuditAction, MessageKey> = {
  login_succeeded: 'audit.login_succeeded',
  login_failed: 'audit.login_failed',
  logout: 'audit.logout',
  password_changed: 'audit.password_changed',
  password_reset: 'audit.password_reset',
  user_created: 'audit.user_created',
  user_updated: 'audit.user_updated',
  user_deactivated: 'audit.user_deactivated',
  agent_created: 'audit.agent_created',
  agent_updated: 'audit.agent_updated',
  agent_archived: 'audit.agent_archived',
  agents_imported: 'audit.agents_imported',
  number_created: 'audit.number_created',
  number_updated: 'audit.number_updated',
  assignment_created: 'audit.assignment_created',
  assignment_closed: 'audit.assignment_closed',
  calls_reattributed: 'audit.calls_reattributed',
  enrolment_code_issued: 'audit.enrolment_code_issued',
  enrolment_code_revoked: 'audit.enrolment_code_revoked',
  installation_attested: 'audit.installation_attested',
  installation_self_declared: 'audit.installation_self_declared',
  installation_revoked: 'audit.installation_revoked',
  installation_rebound: 'audit.installation_rebound',
  command_issued: 'audit.command_issued',
  call_note_updated: 'audit.call_note_updated',
  calls_exported: 'audit.calls_exported',
  audio_play: 'audit.audio_play',
  audio_download: 'audit.audio_download',
  audio_deleted: 'audit.audio_deleted',
  alert_acknowledged: 'audit.alert_acknowledged',
  setting_updated: 'audit.setting_updated',
  retention_changed: 'audit.retention_changed',
  line_directory_updated: 'audit.line_directory_updated',
  supported_model_updated: 'audit.supported_model_updated',
  app_version_published: 'audit.app_version_published',
  service_token_created: 'audit.service_token_created',
  service_token_revoked: 'audit.service_token_revoked',
  app_version_uploaded: 'audit.app_version_uploaded',
  export_read: 'audit.export_read',
}

/**
 * The actions worth colouring.
 *
 * `login_failed` and `credential`-adjacent actions are the ones somebody scans
 * this page for; everything else is neutral, because a log where every row is
 * highlighted is a log where nothing is.
 */
export const AUDIT_ACTION_TONE: Partial<Record<AuditAction, 'warn' | 'bad'>> = {
  login_failed: 'warn',
  installation_revoked: 'warn',
  installation_rebound: 'warn',
  user_deactivated: 'warn',
  password_reset: 'warn',
  retention_changed: 'bad',
  audio_deleted: 'bad',
  service_token_created: 'warn',
}
