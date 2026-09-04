/**
 * `buildFleet` — the merge that makes a silent phone visible.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * R3 is an OEM battery manager killing the capture service without saying so.
 * The device page exists to catch that, and its two rules are pinned here
 * because both are easy to undo by accident:
 *
 *   1. **A phone that never reported is a ROW, not a gap.** `GET /devices`
 *      inner-joins `device_health`, so an installation that was bound and
 *      never heard from is absent from that response entirely. Anyone
 *      "simplifying" this page to read `/devices` alone would delete the most
 *      alarming row in the fleet and the page would look tidier for it.
 *
 *   2. **The order serves the problem.** Worst first. A fleet sorted by name
 *      makes one broken phone exactly as prominent as fourteen working ones.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { describe, expect, it } from 'vitest'

import { buildFleet, CLOCK_SKEW_LIMIT_SEC, QUEUE_DEPTH_LIMIT } from '@/modules/devices/api'
import type { DeviceHealth, Installation } from '@/modules/devices/api'

function installation(overrides: Partial<Installation> = {}): Installation {
  return {
    id: 'inst-1',
    agent_id: 'agent-1',
    number_id: 'number-1',
    device_id: 'device-1',
    status: 'active',
    funnel_stage: 'capturing',
    funnel_changed_at: '2026-09-01T10:00:00+05:00',
    created_at: '2026-09-01T10:00:00+05:00',
    verification_method: 'sim_msisdn',
    verified_at: '2026-09-01T10:00:00+05:00',
    attest_reason: null,
    bound_at: '2026-09-01T10:00:00+05:00',
    replaced_at: null,
    revoked_at: null,
    revoke_confirmed_at: null,
    revoke_pending_bytes: null,
    revoke_pending_records: null,
    app_version: '1.0.0',
    app_variant: 'modern34',
    sim_slot: 0,
    sim_subscription_id: 1,
    ...overrides,
  }
}

function health(overrides: Partial<DeviceHealth> = {}): DeviceHealth {
  return {
    installation_id: 'inst-1',
    installation_status: 'active',
    agent_id: 'agent-1',
    number_id: 'number-1',
    manufacturer: 'Samsung',
    model: 'SM-A546E',
    android_release: '14',
    api_level: 34,
    app_version: '1.0.0',
    app_variant: 'modern34',
    is_online: true,
    last_heartbeat_at: '2026-09-05T10:00:00+05:00',
    last_call_at: null,
    battery_level: 80,
    battery_charging: false,
    battery_optimisation_exempt: true,
    power_save_mode: false,
    capture_enabled: true,
    service_running: true,
    recording_route: 'oem_file_harvest',
    recording_route_ok: true,
    queue_records: 0,
    queue_bytes: 0,
    queue_oldest_at: null,
    parked_records: 0,
    free_storage_bytes: 10_000_000_000,
    cellular_bytes_month: 1_000_000,
    clock_skew_sec: 1,
    device_timezone: 'Asia/Tashkent',
    network_type: 'wifi',
    updated_at: '2026-09-05T10:00:00+05:00',
    ...overrides,
  }
}

describe('a phone that has never reported', () => {
  it('appears as a row even though GET /devices omits it entirely', () => {
    const silent = installation({ id: 'never', agent_id: 'agent-2' })

    // Exactly what the server returns today: the installation exists, the
    // health row does not, so `/devices` has nothing for it.
    const fleet = buildFleet([installation(), silent], [health()])

    expect(fleet).toHaveLength(2)
    const row = fleet.find((item) => item.installation.id === 'never')
    expect(row).toBeDefined()
    expect(row?.state).toBe('never_reported')
    expect(row?.health).toBeNull()
  })

  it('sorts ahead of every other state, including offline', () => {
    const fleet = buildFleet(
      [
        installation({ id: 'healthy' }),
        installation({ id: 'offline' }),
        installation({ id: 'never' }),
        installation({ id: 'degraded' }),
      ],
      [
        health({ installation_id: 'healthy' }),
        health({ installation_id: 'offline', is_online: false }),
        health({ installation_id: 'degraded', recording_route_ok: false }),
      ],
    )

    // "Never started" outranks "worked once and stopped": the first is a
    // person waiting for help right now.
    expect(fleet.map((row) => row.installation.id)).toEqual([
      'never',
      'offline',
      'degraded',
      'healthy',
    ])
  })

  it('is never described as merely offline', () => {
    const [row] = buildFleet([installation()], [])
    expect(row?.state).toBe('never_reported')
    expect(row?.problems).toContain('never_reported')
    expect(row?.problems).not.toContain('offline')
  })
})

describe('problems', () => {
  it('names a broken capture route, which is R3 as the panel sees it', () => {
    const [row] = buildFleet([installation()], [health({ recording_route_ok: false })])
    expect(row?.state).toBe('degraded')
    expect(row?.problems).toContain('capture_route_broken')
  })

  it('names battery optimisation, the cause the alert cannot name for itself', () => {
    const [row] = buildFleet(
      [installation()],
      [health({ battery_optimisation_exempt: false })],
    )
    expect(row?.problems).toContain('battery_optimised')
  })

  it('only flags a queue and a clock once they pass the stated limits', () => {
    const [under] = buildFleet(
      [installation()],
      [health({ queue_records: QUEUE_DEPTH_LIMIT, clock_skew_sec: CLOCK_SKEW_LIMIT_SEC })],
    )
    expect(under?.problems).toEqual([])

    const [over] = buildFleet(
      [installation()],
      [health({ queue_records: QUEUE_DEPTH_LIMIT + 1, clock_skew_sec: -CLOCK_SKEW_LIMIT_SEC - 1 })],
    )
    expect(over?.problems).toContain('queue_backed_up')
    // Skew is flagged in both directions: a phone running fast is as wrong as
    // one running slow.
    expect(over?.problems).toContain('clock_skewed')
  })

  it('reports a healthy phone as healthy, with nothing to say about it', () => {
    const [row] = buildFleet([installation()], [health()])
    expect(row?.state).toBe('healthy')
    expect(row?.problems).toEqual([])
  })

  it('treats a revoked installation as its own state, not as a fault', () => {
    const [row] = buildFleet(
      [installation({ status: 'revoked' })],
      [health({ is_online: false })],
    )
    // Revoked is deliberate and sorts below the phones somebody must act on.
    expect(row?.state).toBe('revoked')
  })
})
