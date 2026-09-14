/**
 * Which phone answers for which person.
 *
 * The devices page lists installations worst-first, because its question is
 * "which phone is broken". The roster lists people, and its question is "does
 * this person have a working phone" — so an agent with a replaced handset, a
 * revoked one and the phone in their pocket needs exactly one chosen, and
 * choosing wrong reports an active salesperson as revoked.
 */
import { describe, expect, it } from 'vitest'

import { fleetForAgents } from '@/modules/agents/fleet'
import type { DeviceHealth } from '@/modules/devices/api'

const AGENT = 'agent-1'

function health(overrides: Partial<DeviceHealth> = {}): DeviceHealth {
  const now = Date.now()
  return {
    installation_id: 'inst-1',
    agent_id: AGENT,
    number_id: 'number-1',
    manufacturer: 'Xiaomi',
    model: 'Redmi Note 12',
    android_release: '13',
    api_level: 33,
    app_version: '1.0.7',
    app_variant: 'legacy28',
    battery_percent: 80,
    battery_charging: false,
    battery_optimisation_exempt: true,
    capturing: true,
    recording_route: 'oem_file_harvest',
    recording_route_ok: true,
    last_heartbeat_at: new Date(now - 60_000).toISOString(),
    last_call_at: null,
    queue_pending: 0,
    queue_bytes: null,
    never_reported: false,
    installation_status: 'active',
    bound_at: new Date(now - 86_400_000).toISOString(),
    created_at: new Date(now - 86_400_000).toISOString(),
    ...overrides,
  } as DeviceHealth
}

describe('one row per person', () => {
  it('gives an agent with no handset nothing at all', () => {
    /**
     * A real state, and one the fleet page could never show: an employee hired
     * last week who has not enrolled. The roster still lists them, which is
     * half the reason the roster is the spine of the merged page.
     */
    expect(fleetForAgents([], []).get(AGENT)).toBeUndefined()
    expect(fleetForAgents(undefined, undefined).get(AGENT)).toBeUndefined()
  })

  it('prefers the phone that works over the one that was revoked', () => {
    const rows = fleetForAgents(
      [
        health({ installation_id: 'old', installation_status: 'revoked' }),
        health({ installation_id: 'live' }),
      ],
      [],
    )

    expect(rows.get(AGENT)?.health.installation_id).toBe('live')
  })

  it('still answers when every handset is bad', () => {
    /** The roster must not go blank for the person who most needs attention. */
    const rows = fleetForAgents(
      [health({ never_reported: true, last_heartbeat_at: null })],
      [],
    )

    expect(rows.get(AGENT)).toBeDefined()
    expect(rows.get(AGENT)?.state).toBe('never_reported')
  })

  it('keeps each agent to their own phone', () => {
    const rows = fleetForAgents(
      [health(), health({ installation_id: 'inst-2', agent_id: 'agent-2' })],
      [],
    )

    expect(rows.get(AGENT)?.health.installation_id).toBe('inst-1')
    expect(rows.get('agent-2')?.health.installation_id).toBe('inst-2')
  })
})
