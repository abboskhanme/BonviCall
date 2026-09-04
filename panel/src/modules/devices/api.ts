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
export type FleetState = 'never_reported' | 'revoked' | 'offline' | 'degraded' | 'healthy'

export interface FleetRow {
  health: DeviceHealth
  state: FleetState
  /** Uzbek-free reasons; the page turns each into a sentence. */
  problems: FleetProblem[]
}

export type FleetProblem =
  | 'never_reported'
  | 'revoked'
  | 'offline'
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

function isRevoked(health: DeviceHealth): boolean {
  return (
    health.installation_status === 'revoked' ||
    health.installation_status === 'revoked_pending_confirmation'
  )
}

export function problemsFor(health: DeviceHealth): FleetProblem[] {
  const problems: FleetProblem[] = []
  if (isRevoked(health)) problems.push('revoked')
  if (health.never_reported) {
    // Nothing else is knowable about a phone that has never spoken, and
    // listing "offline" beside it would suggest we once heard from it.
    problems.push('never_reported')
    return problems
  }
  if (!health.is_online) problems.push('offline')
  if (health.recording_route_ok === false) problems.push('capture_route_broken')
  if (health.capture_enabled === false) problems.push('capture_disabled')
  if (health.service_running === false) problems.push('service_stopped')
  if (health.battery_optimisation_exempt === false) problems.push('battery_optimised')
  if ((health.queue_records ?? 0) > QUEUE_DEPTH_LIMIT) problems.push('queue_backed_up')
  if ((health.parked_records ?? 0) > 0) problems.push('records_parked')
  if (Math.abs(health.clock_skew_sec ?? 0) > CLOCK_SKEW_LIMIT_SEC) problems.push('clock_skewed')
  return problems
}

export function stateFor(health: DeviceHealth): FleetState {
  if (health.never_reported) return 'never_reported'
  if (isRevoked(health)) return 'revoked'
  if (!health.is_online) return 'offline'
  return problemsFor(health).length > 0 ? 'degraded' : 'healthy'
}

/** Worst first. The default order must serve the problem, not the alphabet. */
export const FLEET_STATE_ORDER: Record<FleetState, number> = {
  never_reported: 0,
  offline: 1,
  degraded: 2,
  revoked: 3,
  healthy: 4,
}

export function buildFleet(devices: DeviceHealth[] | undefined): FleetRow[] {
  const rows = (devices ?? []).map((health) => ({
    health,
    state: stateFor(health),
    problems: problemsFor(health),
  }))
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
