/**
 * Device health, installations and commands.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **A phone that has never reported is a row, not a gap** — and now the
 * server says so itself.
 *
 * `GET /devices` used to inner-join `device_health`, so an installation that
 * was bound and never sent a heartbeat was absent from the response and
 * `GET /devices/{id}` answered 404 for it. That was the single most alarming
 * device in the fleet, and R3 is precisely the failure that announces itself
 * by going quiet. The panel worked around it by merging `GET /installations`
 * over the top.
 *
 * The workaround is deleted: the join is now a LEFT OUTER JOIN and
 * `DeviceHealthResponse.never_reported` is a first-class field. The rule it
 * protected is kept and still tested — `never_reported` sorts above `offline`,
 * because "was handed a phone and never started" is a person waiting for help
 * right now, while "worked once and stopped" is not.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api } from '@/shared/api/client'
import { POLL_FAST_MS } from '@/app/queryClient'
import { moduleKey, queryKey } from '@/shared/api/queryKeys'
import type { components } from '@/shared/api/types.gen'

export type DeviceHealth = components['schemas']['DeviceHealthResponse']
/** `GET /devices/{id}` — health PLUS the capability matrix and `capturing`,
 *  which is the whole reason the device page exists. */
export type DeviceDetail = components['schemas']['DeviceDetailResponse']
export type CapabilityState = components['schemas']['CapabilityStateResponse']
export type DeviceHealthList = components['schemas']['DeviceHealthListResponse']
export type Installation = components['schemas']['InstallationResponse']
export type InstallationList = components['schemas']['InstallationListResponse']
export type InstallationStatus = components['schemas']['InstallationStatus']
export type FunnelStage = components['schemas']['FunnelStage']
export type Command = components['schemas']['CommandResponse']
export type CommandList = components['schemas']['CommandListResponse']
export type CreateCommandRequest = components['schemas']['CreateCommandRequest']
export type RevokeRequest = components['schemas']['RevokeRequest']
export type RevokeResponse = components['schemas']['RevokeResponse']
export type AttestRequest = components['schemas']['AttestRequest']

export function useDevices(): UseQueryResult<DeviceHealthList> {
  return useQuery({
    queryKey: queryKey('devices', 'list'),
    queryFn: () => api.get<DeviceHealthList>('/devices'),
    // A rollout is watched live (SPEC §5.3).
    refetchInterval: POLL_FAST_MS,
  })
}

export function useDevice(installationId: string | undefined): UseQueryResult<DeviceDetail> {
  return useQuery({
    queryKey: queryKey('devices', 'detail', { installationId }),
    queryFn: () => api.get<DeviceDetail>(`/devices/${installationId}`),
    enabled: Boolean(installationId),
    refetchInterval: POLL_FAST_MS,
  })
}

export function useInstallations(params?: {
  agentId?: string | undefined
  status?: InstallationStatus | undefined
}): UseQueryResult<InstallationList> {
  const query = {
    ...(params?.agentId ? { agent_id: params.agentId } : {}),
    ...(params?.status ? { status: params.status } : {}),
  }
  return useQuery({
    queryKey: queryKey('installations', 'list', query),
    queryFn: () => api.get<InstallationList>('/installations', query),
    refetchInterval: POLL_FAST_MS,
  })
}

/**
 * How a phone is doing, in the order somebody should be told about it.
 *
 * `never_reported` outranks `offline` because it is a different problem: an
 * offline phone worked once and stopped, a never-reported one was handed over
 * and never started, and the second is a person waiting for help right now.
 */
export type FleetState =
  | 'never_reported'
  | 'install_disappeared'
  | 'revoked'
  | 'offline'
  | 'degraded'
  | 'awaiting_telemetry'
  | 'superseded'
  | 'healthy'

export interface FleetRow {
  health: DeviceHealth
  state: FleetState
  /** Uzbek-free reasons; the page turns each into a sentence. */
  problems: FleetProblem[]
}

export type FleetProblem =
  | 'never_reported'
  | 'install_disappeared'
  | 'revoked'
  | 'offline'
  | 'awaiting_telemetry'
  | 'superseded'
  | 'capture_route_broken'
  | 'capture_disabled'
  | 'service_stopped'
  | 'battery_optimised'
  | 'queue_backed_up'
  | 'records_parked'
  | 'clock_skewed'

/** Beyond this the device's clock disagrees enough to matter (SPEC §3.12). */
export const CLOCK_SKEW_LIMIT_SEC = 120
/** A queue this deep means uploads are not draining. */
export const QUEUE_DEPTH_LIMIT = 50

/**
 * How long a phone must stay silent before "offline" stops being the honest
 * word for it (T140).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **`offline` and `install_disappeared` are different faults and need
 * different people.**
 *
 * A handset that has missed a few heartbeats is offline: switched off, out of
 * signal, on a charger in a drawer for the afternoon. It almost always needs
 * nothing — it comes back by itself, and treating every one of them as an
 * incident is how a fleet page becomes noise.
 *
 * A handset that reported normally and has then said nothing for two days has
 * almost certainly had the app removed, force-stopped permanently, or been
 * replaced. Nothing brings that back on its own. Somebody has to go and find
 * that salesperson, which is a different-sized request and belongs to a
 * different day.
 *
 * Two days rather than one: a phone left off over a weekend is common and is
 * not a disappeared install, and a page that cries wolf every Monday morning
 * gets ignored by Tuesday.
 *
 * `never_reported` stays distinct from both. That is somebody who never got
 * started, and the fix is an enrolment, not a visit.
 * ═══════════════════════════════════════════════════════════════════════════
 */
export const DISAPPEARED_AFTER_HOURS = 48

function hoursSince(iso: string | null | undefined, now: Date): number | null {
  if (!iso) return null
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return null
  return (now.getTime() - then) / 3_600_000
}

/**
 * Has this phone been silent long enough to look removed rather than merely
 * offline?
 *
 * The server's own `funnel_stage` is authoritative when it says so — it sees
 * things the panel cannot, such as an uninstall reported by the OS — and the
 * heartbeat age is the fallback that catches the ordinary case where nothing
 * announced itself.
 */
export function hasDisappeared(
  health: DeviceHealth,
  funnelStage?: FunnelStage | null,
  now: Date = new Date(),
): boolean {
  if (health.never_reported) return false
  if (funnelStage === 'install_disappeared') return true
  const age = hoursSince(health.last_heartbeat_at, now)
  return age !== null && age >= DISAPPEARED_AFTER_HOURS
}

/**
 * Has this phone told us anything about whether it can actually record?
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * A handset that has just enrolled sends a heartbeat before it sends any
 * capture telemetry, so `recording_route`, `capture_enabled` and
 * `service_running` are all NULL for a while. Every problem check is written
 * as "is this field false", and null is not false — so a phone we know nothing
 * about passed every check and came out `healthy`.
 *
 * That was live and wrong: the client's Samsung was online, `capturing:
 * false`, one capability reported, and the fleet page called it **Yaxshi**.
 * Absence of a reading is not a good reading, and on the page whose whole job
 * is to say which phones are recording, it is the most expensive place to
 * confuse the two.
 * ═══════════════════════════════════════════════════════════════════════════
 */
export function hasCaptureTelemetry(health: DeviceHealth): boolean {
  // The ROUTE specifically, not "any telemetry at all". A phone reporting
  // `capture_enabled: true` and `service_running: true` with no route has
  // told us it is willing and running — and nothing about whether it can
  // actually record, which is the only question this page answers. Three
  // handsets were live in exactly that state and the fleet called them
  // healthy.
  return health.recording_route !== null
}

function isRevoked(health: DeviceHealth): boolean {
  return (
    health.installation_status === 'revoked' ||
    health.installation_status === 'revoked_pending_confirmation'
  )
}

/**
 * Superseded by a later enrolment on the same number.
 *
 * A real rollout retries: the live fleet has forty-eight installations for six
 * agents, twenty-one of them `replaced`. Those are abandoned attempts, not
 * broken phones — but every one was being rendered as a fault, so thirty-three
 * dead rows buried the three that were actually live and the page stopped
 * being readable at exactly the moment it mattered most.
 */
function isSuperseded(health: DeviceHealth): boolean {
  return health.installation_status === 'replaced'
}

export function problemsFor(
  health: DeviceHealth,
  funnelStage?: FunnelStage | null,
  now: Date = new Date(),
): FleetProblem[] {
  const problems: FleetProblem[] = []
  if (isRevoked(health)) problems.push('revoked')
  if (isSuperseded(health)) {
    // History. Nothing else about it is worth a line on a page about phones
    // that need somebody to do something.
    problems.push('superseded')
    return problems
  }
  if (health.never_reported) {
    // Nothing else is knowable about a phone that has never spoken, and
    // listing "offline" beside it would suggest we once heard from it.
    problems.push('never_reported')
    return problems
  }
  if (hasDisappeared(health, funnelStage, now)) {
    // Not also "offline": it is offline, but saying so would put it in the
    // bucket that needs nothing, which is the whole distinction.
    problems.push('install_disappeared')
  } else if (!health.is_online) {
    problems.push('offline')
  }
  // Before any "is this false" check, because null is not false and a phone
  // we know nothing about must not pass them all silently.
  if (!hasCaptureTelemetry(health)) problems.push('awaiting_telemetry')
  if (health.recording_route_ok === false) problems.push('capture_route_broken')
  if (health.capture_enabled === false) problems.push('capture_disabled')
  if (health.service_running === false) problems.push('service_stopped')
  if (health.battery_optimisation_exempt === false) problems.push('battery_optimised')
  if ((health.queue_records ?? 0) > QUEUE_DEPTH_LIMIT) problems.push('queue_backed_up')
  if ((health.parked_records ?? 0) > 0) problems.push('records_parked')
  if (Math.abs(health.clock_skew_sec ?? 0) > CLOCK_SKEW_LIMIT_SEC) problems.push('clock_skewed')
  return problems
}

export function stateFor(
  health: DeviceHealth,
  funnelStage?: FunnelStage | null,
  now: Date = new Date(),
): FleetState {
  // Before every other test: a superseded attempt is not a phone with a
  // problem, whatever else is true of it.
  if (isSuperseded(health)) return 'superseded'
  if (health.never_reported) return 'never_reported'
  if (isRevoked(health)) return 'revoked'
  if (hasDisappeared(health, funnelStage, now)) return 'install_disappeared'
  if (!health.is_online) return 'offline'
  const problems = problemsFor(health, funnelStage, now)
  // "We have not heard whether it can record" is its own answer, and it is
  // not `degraded` either: nothing is known to be wrong, and nothing is known
  // to be right.
  if (problems.length === 1 && problems[0] === 'awaiting_telemetry') return 'awaiting_telemetry'
  return problems.length > 0 ? 'degraded' : 'healthy'
}

/** Worst first. The default order must serve the problem, not the alphabet. */
export const FLEET_STATE_ORDER: Record<FleetState, number> = {
  never_reported: 0,
  // Above `offline` because it needs a person to travel; an offline phone
  // usually needs nobody.
  install_disappeared: 1,
  offline: 2,
  degraded: 3,
  // Below the known faults but above healthy: during a rollout this is the
  // phone somebody is standing next to right now, and it is the one state
  // that resolves itself within a minute or never.
  awaiting_telemetry: 4,
  healthy: 5,
  // Deliberately last, below healthy: these are abandoned enrolment attempts
  // and nobody needs to look at them.
  revoked: 6,
  superseded: 7,
}

export function buildFleet(
  devices: DeviceHealth[] | undefined,
  /** `funnel_stage` per installation, when the caller has it. The server sees
   *  an uninstall the panel cannot infer from silence alone. */
  stageByInstallation?: ReadonlyMap<string, FunnelStage>,
  now: Date = new Date(),
): FleetRow[] {
  const rows = (devices ?? []).map((health) => {
    const stage = stageByInstallation?.get(health.installation_id) ?? null
    return {
      health,
      state: stateFor(health, stage, now),
      problems: problemsFor(health, stage, now),
    }
  })
  rows.sort((a, b) => {
    const byState = FLEET_STATE_ORDER[a.state] - FLEET_STATE_ORDER[b.state]
    if (byState !== 0) return byState
    // Within a state, the one heard from longest ago comes first.
    return (a.health.last_heartbeat_at ?? '').localeCompare(b.health.last_heartbeat_at ?? '')
  })
  return rows
}

export function useCommands(installationId: string | undefined): UseQueryResult<CommandList> {
  return useQuery({
    queryKey: queryKey('commands', 'list', { installationId }),
    queryFn: () => api.get<CommandList>(`/devices/${installationId}/commands`),
    enabled: Boolean(installationId),
    refetchInterval: POLL_FAST_MS,
  })
}

export function useIssueCommand(
  installationId: string,
): UseMutationResult<Command, unknown, CreateCommandRequest> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateCommandRequest) =>
      api.post<Command>(`/devices/${installationId}/commands`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('commands') })
    },
  })
}

/** UC-08. The response reports what the phone was still holding at last
 *  contact, which is the number that decides whether revoking loses data. */
export function useRevokeInstallation(
  installationId: string,
): UseMutationResult<RevokeResponse, unknown, RevokeRequest> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: RevokeRequest) =>
      api.post<RevokeResponse>(`/installations/${installationId}/revoke`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('installations') })
      void client.invalidateQueries({ queryKey: moduleKey('devices') })
    },
  })
}

/** T142. Weaker evidence than a proven binding, so the reason is mandatory. */
export function useAttestInstallation(
  installationId: string,
): UseMutationResult<Installation, unknown, AttestRequest> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: AttestRequest) =>
      api.post<Installation>(`/installations/${installationId}/attest`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('installations') })
      void client.invalidateQueries({ queryKey: moduleKey('devices') })
    },
  })
}
