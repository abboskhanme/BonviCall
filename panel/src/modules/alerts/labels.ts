/**
 * What each alert means, and **what to do about it**.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * `AlertResponse` carries `title_uz` and `body_uz`, and the panel does not
 * rely on them. On the live server today they read:
 *
 *     title_uz: "Device offline"                                  ← English
 *     body_uz:  "Xatolik yuz berdi. Administratorga murojaat qiling."
 *               ("An error occurred. Contact the administrator.")
 *
 * An English title breaks §14 for a string an end user reads, and that body is
 * the generic fallback — it says nothing about this alert at all. A page built
 * on those two fields would be a list of identical shrugs, which is the
 * "alert nobody acts on" this page exists to avoid.
 *
 * So the wording is derived from `kind`, which is a closed enum and part of
 * the machine contract. `title_uz` is kept as a fallback for a kind added on
 * the server before the panel regenerates — but a missing entry is a compile
 * error first, because these maps are `Record<AlertKind, MessageKey>`.
 *
 * The HINT is the load-bearing half. "Device offline" is a noun; "the phone
 * has not reported — check whether it is switched on and has internet" is
 * something an admin can do. Same reasoning as the enrolment funnel's stage
 * hints, and for the same reason: the person reading is not standing next to
 * the phone.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import type { MessageKey } from '@/shared/i18n'
import type { components } from '@/shared/api/types.gen'

export type Alert = components['schemas']['AlertResponse']
export type AlertKind = components['schemas']['AlertKind']
export type AlertSeverity = components['schemas']['AlertSeverity']

type Tone = 'neutral' | 'good' | 'warn' | 'bad' | 'accent'

export const ALERT_SEVERITY_LABEL: Record<AlertSeverity, MessageKey> = {
  info: 'alerts.severity.info',
  warning: 'alerts.severity.warning',
  critical: 'alerts.severity.critical',
}

export const ALERT_SEVERITY_TONE: Record<AlertSeverity, Tone> = {
  info: 'neutral',
  warning: 'warn',
  critical: 'bad',
}

/** Worst first — the page is read top-down by somebody with limited time. */
export const ALERT_SEVERITY_ORDER: Record<AlertSeverity, number> = {
  critical: 0,
  warning: 1,
  info: 2,
}

export const ALERT_KIND_LABEL: Record<AlertKind, MessageKey> = {
  capture_disabled: 'alertKind.capture_disabled',
  permission_lost_microphone: 'alertKind.permission_lost_microphone',
  permission_lost_phone_state: 'alertKind.permission_lost_phone_state',
  permission_lost_call_log: 'alertKind.permission_lost_call_log',
  battery_optimisation_reenabled: 'alertKind.battery_optimisation_reenabled',
  app_force_stopped: 'alertKind.app_force_stopped',
  install_disappeared: 'alertKind.install_disappeared',
  recording_route_lost: 'alertKind.recording_route_lost',
  service_not_running: 'alertKind.service_not_running',
  device_offline: 'alertKind.device_offline',
  device_silent: 'alertKind.device_silent',
  fleet_silent: 'alertKind.fleet_silent',
  capture_rate_regression: 'alertKind.capture_rate_regression',
  queue_full: 'alertKind.queue_full',
  storage_low: 'alertKind.storage_low',
  poisoned_record: 'alertKind.poisoned_record',
  auth_expired: 'alertKind.auth_expired',
  credential_replay: 'alertKind.credential_replay',
  installation_rebound: 'alertKind.installation_rebound',
  callback_receiver_down: 'alertKind.callback_receiver_down',
  enrolment_stalled: 'alertKind.enrolment_stalled',
  attribution_out_of_range: 'alertKind.attribution_out_of_range',
  attribution_discarded_spike: 'alertKind.attribution_discarded_spike',
  retention_job_failed: 'alertKind.retention_job_failed',
  backup_failed: 'alertKind.backup_failed',
  storage_capacity_low: 'alertKind.storage_capacity_low',
  min_version_refusals: 'alertKind.min_version_refusals',
}

/** The next action, in one sentence. This is why the page is worth having. */
export const ALERT_KIND_HINT: Record<AlertKind, MessageKey> = {
  capture_disabled: 'alertHint.capture_disabled',
  permission_lost_microphone: 'alertHint.permission_lost_microphone',
  permission_lost_phone_state: 'alertHint.permission_lost_phone_state',
  permission_lost_call_log: 'alertHint.permission_lost_call_log',
  battery_optimisation_reenabled: 'alertHint.battery_optimisation_reenabled',
  app_force_stopped: 'alertHint.app_force_stopped',
  install_disappeared: 'alertHint.install_disappeared',
  recording_route_lost: 'alertHint.recording_route_lost',
  service_not_running: 'alertHint.service_not_running',
  device_offline: 'alertHint.device_offline',
  device_silent: 'alertHint.device_silent',
  fleet_silent: 'alertHint.fleet_silent',
  capture_rate_regression: 'alertHint.capture_rate_regression',
  queue_full: 'alertHint.queue_full',
  storage_low: 'alertHint.storage_low',
  poisoned_record: 'alertHint.poisoned_record',
  auth_expired: 'alertHint.auth_expired',
  credential_replay: 'alertHint.credential_replay',
  installation_rebound: 'alertHint.installation_rebound',
  callback_receiver_down: 'alertHint.callback_receiver_down',
  enrolment_stalled: 'alertHint.enrolment_stalled',
  attribution_out_of_range: 'alertHint.attribution_out_of_range',
  attribution_discarded_spike: 'alertHint.attribution_discarded_spike',
  retention_job_failed: 'alertHint.retention_job_failed',
  backup_failed: 'alertHint.backup_failed',
  storage_capacity_low: 'alertHint.storage_capacity_low',
  min_version_refusals: 'alertHint.min_version_refusals',
}

/**
 * Where an alert of this kind is acted on.
 *
 * `device` and `agent` alerts get a link through to the page that can fix
 * them; the rest are about the installation as a whole or about the server
 * itself, and a link to a phone would be a dead end.
 */
export type AlertTarget = 'device' | 'agent' | 'none'

export const ALERT_TARGET: Record<AlertKind, AlertTarget> = {
  capture_disabled: 'device',
  permission_lost_microphone: 'device',
  permission_lost_phone_state: 'device',
  permission_lost_call_log: 'device',
  battery_optimisation_reenabled: 'device',
  app_force_stopped: 'device',
  install_disappeared: 'agent',
  recording_route_lost: 'device',
  service_not_running: 'device',
  device_offline: 'device',
  device_silent: 'device',
  fleet_silent: 'none',
  capture_rate_regression: 'none',
  queue_full: 'device',
  storage_low: 'device',
  poisoned_record: 'device',
  auth_expired: 'device',
  credential_replay: 'device',
  installation_rebound: 'agent',
  callback_receiver_down: 'none',
  enrolment_stalled: 'agent',
  attribution_out_of_range: 'agent',
  attribution_discarded_spike: 'agent',
  retention_job_failed: 'none',
  backup_failed: 'none',
  storage_capacity_low: 'none',
  min_version_refusals: 'none',
}
