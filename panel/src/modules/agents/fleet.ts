/**
 * One employee, one phone — which row of the fleet answers for which person.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * The devices page lists **installations**, worst first, because its question
 * is "which phone is broken". The roster lists **people**, and its question is
 * "does this person have a working phone" — so an agent with three rows in the
 * fleet (a replaced handset, a revoked one, and the phone in their pocket)
 * needs exactly one of them chosen, and choosing wrong is worse than showing
 * nothing: a revoked installation from August would report an active
 * salesperson as revoked.
 *
 * A rule with cases, tested on its own (`__tests__/fleet.test.ts`).
 * ═══════════════════════════════════════════════════════════════════════════
 */
import {
  buildFleet,
  supersededInstallationIds,
  type FleetRow,
  type FleetState,
} from '@/modules/devices/api'
import type { DeviceHealth, Installation } from '@/modules/devices/api'

/**
 * Best first, which is the OPPOSITE of the devices page's order and is
 * deliberate. There, worst-first puts the broken phone where the eye lands.
 * Here the list is already one row per person, and the question the row
 * answers is whether that person can be recorded at all — so the phone that
 * CAN is the true answer, and an old revoked handset beside it is history.
 */
const PREFERENCE: readonly FleetState[] = [
  'healthy',
  'degraded',
  'awaiting_telemetry',
  'offline',
  'never_reported',
  'install_disappeared',
  'revoked',
  'superseded',
]

function rank(state: FleetState): number {
  const index = PREFERENCE.indexOf(state)
  // An unknown state sorts last rather than first: a value this panel has not
  // been taught about must never be allowed to represent somebody's phone.
  return index === -1 ? PREFERENCE.length : index
}

/**
 * `agent_id` → the row that speaks for them, or nothing when they have no
 * handset at all. That last case is a real one and the roster shows it: an
 * employee hired last week with no phone yet is a row with an empty state, and
 * a fleet page could never render them because they have no installation.
 */
export function fleetForAgents(
  devices: DeviceHealth[] | undefined,
  installations: Installation[] | undefined,
): Map<string, FleetRow> {
  const rows = buildFleet(
    devices,
    stageByInstallation(installations),
    new Date(),
    supersededInstallationIds(installations),
  )

  const best = new Map<string, FleetRow>()
  for (const row of rows) {
    const agentId = row.health.agent_id
    const current = best.get(agentId)
    if (current === undefined || rank(row.state) < rank(current.state)) {
      best.set(agentId, row)
    }
  }
  return best
}

function stageByInstallation(
  installations: Installation[] | undefined,
): Map<string, Installation['funnel_stage']> {
  return new Map(
    (installations ?? []).map((installation) => [
      installation.id,
      installation.funnel_stage,
    ]),
  )
}
