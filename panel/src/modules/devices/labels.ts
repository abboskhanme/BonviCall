/**
 * The rollout enums in Uzbek.
 *
 * Every map is `Record<<generated enum>, MessageKey>`, so a value the server
 * adds stops the build instead of reaching a screen as a raw identifier. The
 * text itself lives in `uz.json` (CONVENTIONS.md §14).
 */
import type { MessageKey } from '@/shared/i18n'
import type { components } from '@/shared/api/types.gen'

import type { FleetProblem, FleetState } from './api'

type FunnelStage = components['schemas']['FunnelStage']
type InstallationStatus = components['schemas']['InstallationStatus']
type VerificationMethod = components['schemas']['VerificationMethod']
type CaptureRoute = components['schemas']['CaptureRoute']
type NetworkType = components['schemas']['NetworkType']
type CommandKind = components['schemas']['CommandKind']
type CommandStatus = components['schemas']['CommandStatus']
type EnrolmentOutcome = components['schemas']['EnrolmentOutcome']
type EnrolmentAttemptKind = components['schemas']['EnrolmentAttemptKind']
type Capability = components['schemas']['Capability']
type CapabilityStateValue = components['schemas']['CapabilityState']

type Tone = 'neutral' | 'good' | 'warn' | 'bad' | 'accent'

/**
 * The enrolment funnel (UC-17, SPEC §10.1).
 *
 * The order below is the order of the journey and is what the progress bar
 * reads; `needs_assisted_install`, `install_disappeared` and `revoked` are
 * **not** stages on that path, they are places a person stops, so they carry
 * no position and are rendered as a problem instead of as progress.
 */
export const FUNNEL_PATH: readonly FunnelStage[] = [
  'invited',
  'installed',
  'permitted',
  'number_verified',
  'capturing',
]

/** True when the stage means "stuck", not "further along". */
export function isStuckStage(stage: FunnelStage): boolean {
  return stage === 'needs_assisted_install' || stage === 'install_disappeared'
}

export const FUNNEL_STAGE_LABEL: Record<FunnelStage, MessageKey> = {
  invited: 'funnel.invited',
  installed: 'funnel.installed',
  permitted: 'funnel.permitted',
  number_verified: 'funnel.number_verified',
  verified_by_admin: 'funnel.verified_by_admin',
  capturing: 'funnel.capturing',
  needs_assisted_install: 'funnel.needs_assisted_install',
  install_disappeared: 'funnel.install_disappeared',
  revoked: 'funnel.revoked',
}

/** What the admin should DO about this stage — the funnel's actual job. */
export const FUNNEL_STAGE_HINT: Record<FunnelStage, MessageKey> = {
  invited: 'funnel.hint.invited',
  installed: 'funnel.hint.installed',
  permitted: 'funnel.hint.permitted',
  number_verified: 'funnel.hint.number_verified',
  verified_by_admin: 'funnel.hint.verified_by_admin',
  capturing: 'funnel.hint.capturing',
  needs_assisted_install: 'funnel.hint.needs_assisted_install',
  install_disappeared: 'funnel.hint.install_disappeared',
  revoked: 'funnel.hint.revoked',
}

export const FUNNEL_STAGE_TONE: Record<FunnelStage, Tone> = {
  invited: 'neutral',
  installed: 'accent',
  permitted: 'accent',
  number_verified: 'accent',
  // Attested is deliberately distinct from proven: it is weaker evidence.
  verified_by_admin: 'warn',
  capturing: 'good',
  needs_assisted_install: 'warn',
  install_disappeared: 'bad',
  revoked: 'neutral',
}

export const INSTALLATION_STATUS_LABEL: Record<InstallationStatus, MessageKey> = {
  pending: 'installation.pending',
  active: 'installation.active',
  replaced: 'installation.replaced',
  revoked: 'installation.revoked',
  revoked_pending_confirmation: 'installation.revoked_pending_confirmation',
}

export const VERIFICATION_METHOD_LABEL: Record<VerificationMethod, MessageKey> = {
  sim_msisdn: 'verification.sim_msisdn',
  callback: 'verification.callback',
  admin_attested: 'verification.admin_attested',
}

export const NETWORK_TYPE_LABEL: Record<NetworkType, MessageKey> = {
  wifi: 'network.wifi',
  cellular: 'network.cellular',
  none: 'network.none',
}

export const CAPTURE_ROUTE_LABEL: Record<CaptureRoute, MessageKey> = {
  oem_file_harvest: 'calls.captureRoute.oem_file_harvest',
  app_voice_recognition: 'calls.captureRoute.app_voice_recognition',
  app_voice_communication: 'calls.captureRoute.app_voice_communication',
  app_mic: 'calls.captureRoute.app_mic',
  none: 'calls.captureRoute.none',
}

export const COMMAND_KIND_LABEL: Record<CommandKind, MessageKey> = {
  dial: 'command.dial',
  config: 'command.config',
  logout: 'command.logout',
  ping: 'command.ping',
  recheck: 'command.recheck',
}

export const COMMAND_STATUS_LABEL: Record<CommandStatus, MessageKey> = {
  pending: 'command.pending',
  sent: 'command.sent',
  acknowledged: 'command.acknowledged',
  failed: 'command.failed',
  expired: 'command.expired',
}

export const COMMAND_STATUS_TONE: Record<CommandStatus, Tone> = {
  pending: 'neutral',
  sent: 'accent',
  acknowledged: 'good',
  failed: 'bad',
  expired: 'warn',
}

export const ENROLMENT_OUTCOME_LABEL: Record<EnrolmentOutcome, MessageKey> = {
  ok: 'enrolOutcome.ok',
  code_not_found: 'enrolOutcome.code_not_found',
  code_already_used: 'enrolOutcome.code_already_used',
  code_expired: 'enrolOutcome.code_expired',
  code_revoked: 'enrolOutcome.code_revoked',
  number_mismatch: 'enrolOutcome.number_mismatch',
  msisdn_empty: 'enrolOutcome.msisdn_empty',
  no_caller_id: 'enrolOutcome.no_caller_id',
  timeout: 'enrolOutcome.timeout',
  receiver_down: 'enrolOutcome.receiver_down',
  already_bound: 'enrolOutcome.already_bound',
  rejected: 'enrolOutcome.rejected',
}

export const ENROLMENT_ATTEMPT_KIND_LABEL: Record<EnrolmentAttemptKind, MessageKey> = {
  code_redeem: 'enrolKind.code_redeem',
  msisdn_check: 'enrolKind.msisdn_check',
  callback_start: 'enrolKind.callback_start',
  callback_match: 'enrolKind.callback_match',
  admin_attest: 'enrolKind.admin_attest',
  step_timing: 'enrolKind.step_timing',
}

export const FLEET_STATE_LABEL: Record<FleetState, MessageKey> = {
  never_reported: 'fleet.never_reported',
  revoked: 'fleet.revoked',
  offline: 'fleet.offline',
  degraded: 'fleet.degraded',
  healthy: 'fleet.healthy',
}

export const FLEET_STATE_TONE: Record<FleetState, Tone> = {
  never_reported: 'bad',
  revoked: 'neutral',
  offline: 'bad',
  degraded: 'warn',
  healthy: 'good',
}

export const FLEET_PROBLEM_LABEL: Record<FleetProblem, MessageKey> = {
  never_reported: 'fleetProblem.never_reported',
  revoked: 'fleetProblem.revoked',
  offline: 'fleetProblem.offline',
  capture_route_broken: 'fleetProblem.capture_route_broken',
  capture_disabled: 'fleetProblem.capture_disabled',
  service_stopped: 'fleetProblem.service_stopped',
  battery_optimised: 'fleetProblem.battery_optimised',
  queue_backed_up: 'fleetProblem.queue_backed_up',
  records_parked: 'fleetProblem.records_parked',
  clock_skewed: 'fleetProblem.clock_skewed',
}

/**
 * The capability matrix (UC-03, UC-06, N42).
 *
 * Each row is a permission or an OS behaviour the app needs, and the page
 * exists so an admin can see which one is missing on a handset that is not
 * recording — without asking the salesperson to read a settings screen aloud.
 */
export const CAPABILITY_LABEL: Record<Capability, MessageKey> = {
  phone_state: 'capability.phone_state',
  call_log: 'capability.call_log',
  microphone: 'capability.microphone',
  contacts: 'capability.contacts',
  notifications: 'capability.notifications',
  call_phone: 'capability.call_phone',
  battery_exemption: 'capability.battery_exemption',
  storage_access: 'capability.storage_access',
  oem_autostart: 'capability.oem_autostart',
  foreground_service: 'capability.foreground_service',
  oem_recorder: 'capability.oem_recorder',
  subscription_resolution: 'capability.subscription_resolution',
}

export const CAPABILITY_STATE_LABEL: Record<CapabilityStateValue, MessageKey> = {
  granted_working: 'capState.granted_working',
  granted_not_working: 'capState.granted_not_working',
  denied: 'capState.denied',
  denied_permanently: 'capState.denied_permanently',
  not_applicable: 'capState.not_applicable',
  unknown: 'capState.unknown',
}

/**
 * `granted_not_working` is the one that matters and it is deliberately red.
 *
 * "The permission is granted but the thing still does not work" is exactly R3
 * — an OEM layer quietly refusing what Android says is allowed — and it is
 * the state somebody would otherwise read as fine. `denied_permanently` is
 * equally red because it cannot be fixed by asking again: it needs a visit to
 * the phone's settings.
 */
export const CAPABILITY_STATE_TONE: Record<CapabilityStateValue, Tone> = {
  granted_working: 'good',
  granted_not_working: 'bad',
  denied: 'warn',
  denied_permanently: 'bad',
  not_applicable: 'neutral',
  unknown: 'neutral',
}
