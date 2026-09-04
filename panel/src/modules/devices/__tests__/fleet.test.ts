/**
 * `buildFleet` — how the fleet page decides what to worry about.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * R3 is an OEM battery manager killing the capture service without saying so.
 * The device page exists to catch that, and two rules are pinned here because
 * both are easy to undo by accident:
 *
 *   1. **`never_reported` is its own state and outranks `offline`.** A phone
 *      that was handed over and never started is a person waiting for help
 *      right now; one that worked and stopped is not. The panel used to have
 *      to synthesise this by merging `/installations`, because `GET /devices`
 *      inner-joined `device_health` and omitted the silent handset entirely;
 *      the server now LEFT OUTER JOINs and sends the flag. The rule outlived
 *      the workaround, so it is still tested.
 *
 *   2. **The order serves the problem.** Worst first. A fleet sorted by name
 *      makes one broken phone exactly as prominent as fourteen working ones.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { describe, expect, it } from 'vitest'

import { buildFleet, CLOCK_SKEW_LIMIT_SEC, QUEUE_DEPTH_LIMIT } from '@/modules/devices/api'
import type { DeviceHealth } from '@/modules/devices/api'

function health(overrides: Partial<DeviceHealth> = {}): DeviceHealth {
  return {
    installation_id: 'inst-1',
    installation_status: 'active',
    never_reported: false,
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
  it('is its own state, not merely offline', () => {
    const [row] = buildFleet([health({ never_reported: true, is_online: false })])

    expect(row?.state).toBe('never_reported')
    expect(row?.problems).toContain('never_reported')
    // "Offline" would imply we heard from it once. We never did.
    expect(row?.problems).not.toContain('offline')
  })

  it('claims nothing else about a phone that has never spoken', () => {
    // Every health field is null on a row the server synthesised from an
    // installation, and inventing problems from those nulls would fill the
    // page with faults nobody can act on.
    const [row] = buildFleet([
      health({
        never_reported: true,
        is_online: false,
        recording_route_ok: null,
        capture_enabled: null,
        service_running: null,
        battery_optimisation_exempt: null,
        last_heartbeat_at: null,
      }),
    ])

    expect(row?.problems).toEqual(['never_reported'])
  })

  it('sorts ahead of every other state, including offline', () => {
    const fleet = buildFleet([
      health({ installation_id: 'healthy' }),
      health({ installation_id: 'offline', is_online: false }),
      health({ installation_id: 'never', never_reported: true, is_online: false }),
      health({ installation_id: 'degraded', recording_route_ok: false }),
    ])

    expect(fleet.map((row) => row.health.installation_id)).toEqual([
      'never',
      'offline',
      'degraded',
      'healthy',
    ])
  })
})

describe('problems', () => {
  it('names a broken capture route, which is R3 as the panel sees it', () => {
    const [row] = buildFleet([health({ recording_route_ok: false })])
    expect(row?.state).toBe('degraded')
    expect(row?.problems).toContain('capture_route_broken')
  })

  it('names battery optimisation, the cause the alert cannot name for itself', () => {
    const [row] = buildFleet([health({ battery_optimisation_exempt: false })])
    expect(row?.problems).toContain('battery_optimised')
  })

  it('only flags a queue and a clock once they pass the stated limits', () => {
    const [under] = buildFleet([
      health({ queue_records: QUEUE_DEPTH_LIMIT, clock_skew_sec: CLOCK_SKEW_LIMIT_SEC }),
    ])
    expect(under?.problems).toEqual([])

    const [over] = buildFleet([
      health({ queue_records: QUEUE_DEPTH_LIMIT + 1, clock_skew_sec: -CLOCK_SKEW_LIMIT_SEC - 1 }),
    ])
    expect(over?.problems).toContain('queue_backed_up')
    // Skew is flagged in both directions: a phone running fast is as wrong as
    // one running slow.
    expect(over?.problems).toContain('clock_skewed')
  })

  it('reports a healthy phone as healthy, with nothing to say about it', () => {
    const [row] = buildFleet([health()])
    expect(row?.state).toBe('healthy')
    expect(row?.problems).toEqual([])
  })

  it('treats a revoked installation as its own state, not as a fault', () => {
    const [row] = buildFleet([health({ installation_status: 'revoked', is_online: false })])
    // Revoked is deliberate and sorts below the phones somebody must act on.
    expect(row?.state).toBe('revoked')
  })

  it('sorts the longest-unheard-from first within a state', () => {
    const fleet = buildFleet([
      health({ installation_id: 'recent', is_online: false, last_heartbeat_at: '2026-09-05T10:00:00+05:00' }),
      health({ installation_id: 'stale', is_online: false, last_heartbeat_at: '2026-09-01T10:00:00+05:00' }),
    ])
    expect(fleet.map((row) => row.health.installation_id)).toEqual(['stale', 'recent'])
  })
})
