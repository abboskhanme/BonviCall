/**
 * Where an alert is acted on, and how loudly it is shown.
 *
 * **The wording is no longer here.** `AlertResponse.title_uz` and `body_uz`
 * are derived from `kind` server-side now, from this catalogue's own Uzbek —
 * so the panel reads them instead of keeping a second copy that could drift.
 * The maps that used to live in `labels.ts` are deleted.
 *
 * What remains is the part nothing server-side replaces: which page can fix
 * this, and how the severity is coloured. Both are presentation decisions.
 */
import type { MessageKey } from '@/shared/i18n'
import type { components } from '@/shared/api/types.gen'

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

/**
 * Which page can actually fix this.
 *
 * `device` and `agent` alerts get a link through; the rest are about the
 * server itself, and a link to a handset would be a dead end that wastes the
 * one click somebody was willing to spend.
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
  // Both are about the server's own analysis pipeline. There is no handset to
  // open and no agent to talk to: the job log and the analysis settings are
  // where either one is dealt with.
  analysis_job_failed: 'none',
  analysis_cost_cap_reached: 'none',
}

/**
 * Was this the FIRST time we saw the capability broken, rather than a change?
 *
 * A phone that arrived already broken never *lost* anything, so wording that
 * asserts a transition — "the permission was taken away" — is simply untrue
 * for it, and it sends an admin looking for a change that never happened.
 *
 * The server distinguishes the two in `detail` rather than by adding a kind,
 * so this reads the flag and falls back to the shape of the transition
 * itself: no prior state, or a prior state of `unknown`, is a first
 * observation however it is spelled. Written to accept both because the flag
 * is landing separately from the alerts that already carry `from`/`to`.
 */
export function isFirstObservation(detail: Record<string, unknown> | null | undefined): boolean {
  if (!detail) return false
  if (detail.first_observation === true || detail.first_seen === true) return true
  if (!('from' in detail)) return false
  const from = detail.from
  return from === null || from === undefined || from === 'unknown'
}
