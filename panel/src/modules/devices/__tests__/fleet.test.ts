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

import {
  buildFleet,
  needsAttention,
  supersededInstallationIds,
  CLOCK_SKEW_LIMIT_SEC,
  QUEUE_DEPTH_LIMIT,
} from '@/modules/devices/api'
import type { DeviceHealth, Installation } from '@/modules/devices/api'

/**
 * A timestamp relative to the real clock, which is what `buildFleet` reads
 * when the caller passes no `now`.
 *
 * ⚠️ The fixtures used to carry absolute dates — `2026-09-05T10:00:00+05:00` —
 * while every call below let `now` default to `new Date()`. That is a test
 * suite with a fuse in it: `DISAPPEARED_AFTER_HOURS` is 48, so **every test in
 * this file began failing two days after it was written**, reporting a healthy
 * fixture as `install_disappeared`. Twelve of them were failing when this was
 * found, which means the file had stopped guarding anything it claims to
 * guard. Ages are stated as ages now, and they read better for it: "a
 * heartbeat an hour ago" is the fact the test is about.
 */
function hoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 3_600_000).toISOString()
}

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
    last_heartbeat_at: hoursAgo(1),
    last_call_at: null,
    battery_level: 80,
    battery_charging: false,
    battery_optimisation_exempt: true,
    power_save_mode: false,
    capture_enabled: true,
    capturing: true,
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
    updated_at: hoursAgo(1),
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
      health({ installation_id: 'recent', is_online: false, last_heartbeat_at: hoursAgo(3) }),
      health({ installation_id: 'stale', is_online: false, last_heartbeat_at: hoursAgo(96) }),
    ])
    expect(fleet.map((row) => row.health.installation_id)).toEqual(['stale', 'recent'])
  })
})

describe('a phone that has told us nothing yet', () => {
  /**
   * ═══════════════════════════════════════════════════════════════════════
   * The live failure this exists to stop.
   *
   * A handset sends a heartbeat before it sends any capture telemetry, so
   * `recording_route`, `capture_enabled` and `service_running` are all NULL
   * for a while after enrolment. Every problem check asks "is this field
   * false", and null is not false — so a phone we knew nothing about passed
   * every check and the fleet page called it **Yaxshi**.
   *
   * That was on screen, on the client's own Samsung, while `capturing` was
   * false. Absence of a reading is not a good reading.
   * ═══════════════════════════════════════════════════════════════════════
   */
  it('is not called healthy', () => {
    const [row] = buildFleet([
      health({
        is_online: true,
        recording_route: null,
        capture_enabled: null,
        service_running: null,
        recording_route_ok: null,
      }),
    ])

    expect(row?.state).not.toBe('healthy')
    expect(row?.state).toBe('awaiting_telemetry')
    expect(row?.problems).toContain('awaiting_telemetry')
  })

  it('is not called degraded either — nothing is known to be wrong', () => {
    const [row] = buildFleet([
      health({ is_online: true, recording_route: null, capture_enabled: null, service_running: null }),
    ])
    expect(row?.state).toBe('awaiting_telemetry')
  })

  it('becomes healthy as soon as ONE capture field arrives', () => {
    const [row] = buildFleet([
      health({
        is_online: true,
        recording_route: 'oem_file_harvest',
        capture_enabled: null,
        service_running: null,
      }),
    ])
    expect(row?.state).toBe('healthy')
  })

  it('still reports a real fault over a missing reading', () => {
    // Telemetry that says something bad outranks telemetry that says nothing.
    const [row] = buildFleet([
      health({ is_online: true, recording_route: null, capture_enabled: false, service_running: null }),
    ])
    expect(row?.state).toBe('degraded')
    expect(row?.problems).toContain('capture_disabled')
  })

  it('sorts below the known faults and above healthy', () => {
    const fleet = buildFleet([
      health({ installation_id: 'healthy', is_online: true, recording_route: 'app_mic' }),
      health({
        installation_id: 'awaiting',
        is_online: true,
        recording_route: null,
        capture_enabled: null,
        service_running: null,
      }),
      health({ installation_id: 'degraded', is_online: true, recording_route_ok: false }),
    ])
    expect(fleet.map((row) => row.health.installation_id)).toEqual([
      'degraded',
      'awaiting',
      'healthy',
    ])
  })
})

describe('abandoned enrolment attempts', () => {
  /**
   * A real rollout retries. The live fleet reached forty-eight installations
   * for six agents, twenty-one of them `replaced`, and every one was rendered
   * as a fault — thirty-three dead rows burying the three that were live. The
   * page stopped being readable at exactly the moment it mattered.
   */
  it('is history, not a fault', () => {
    const [row] = buildFleet([
      health({ installation_status: 'replaced', never_reported: true, is_online: false }),
    ])
    expect(row?.state).toBe('superseded')
    // Nothing else about it is worth a line.
    expect(row?.problems).toEqual(['superseded'])
  })

  it('outranks everything else that could be said about it', () => {
    // A replaced install can also be never-reported, offline and broken. None
    // of that needs anybody's attention.
    const [row] = buildFleet([
      health({
        installation_status: 'replaced',
        is_online: false,
        recording_route_ok: false,
        capture_enabled: false,
      }),
    ])
    expect(row?.state).toBe('superseded')
  })

  it('sorts below healthy, not above it', () => {
    const fleet = buildFleet([
      health({ installation_id: 'replaced', installation_status: 'replaced' }),
      health({ installation_id: 'healthy', is_online: true, recording_route: 'app_mic' }),
      health({ installation_id: 'broken', is_online: true, recording_route: 'app_mic', recording_route_ok: false }),
    ])
    expect(fleet.map((row) => row.health.installation_id)).toEqual([
      'broken',
      'healthy',
      'replaced',
    ])
  })
})

describe('willing and running is not the same as able', () => {
  it('does not call a phone healthy when it has no capture route', () => {
    // Live: `capture_enabled: true`, `service_running: true`,
    // `recording_route: null`. The phone has said it is willing and running,
    // and nothing about whether it can actually record.
    const [row] = buildFleet([
      health({
        is_online: true,
        capture_enabled: true,
        service_running: true,
        recording_route: null,
        recording_route_ok: null,
      }),
    ])
    expect(row?.state).toBe('awaiting_telemetry')
  })

  it('is healthy once a route is named', () => {
    const [row] = buildFleet([
      health({ is_online: true, capture_enabled: true, service_running: true, recording_route: 'app_mic' }),
    ])
    expect(row?.state).toBe('healthy')
  })
})

describe('attempts overtaken by a later enrolment', () => {
  function installation(id: string, numberId: string, createdAt: string): Installation {
    return {
      id,
      agent_id: 'agent-1',
      number_id: numberId,
      device_id: 'device-1',
      status: 'pending',
      funnel_stage: 'installed',
      funnel_changed_at: createdAt,
      created_at: createdAt,
      verification_method: null,
      verified_at: null,
      attest_reason: null,
      attested_by: null,
      bound_at: null,
      replaced_at: null,
      revoked_at: null,
      revoke_confirmed_at: null,
      revoke_pending_bytes: null,
      revoke_pending_records: null,
      app_version: null,
      app_variant: null,
      sim_slot: null,
      sim_subscription_id: null,
    } as Installation
  }

  it('keeps only the newest per NUMBER', () => {
    // Keyed on the line, not the agent: an installation is bound to a number
    // and one agent may legitimately hold two.
    const superseded = supersededInstallationIds([
      installation('old', 'number-1', '2026-09-06T08:00:00Z'),
      installation('new', 'number-1', '2026-09-06T09:00:00Z'),
      installation('other-line', 'number-2', '2026-09-06T07:00:00Z'),
    ])
    expect([...superseded]).toEqual(['old'])
  })

  it('marks a never-reported pending attempt as history once a newer one exists', () => {
    // The server marks some `replaced`; a phone that redeemed a code and never
    // reported stays `pending`, and the live fleet had fifty-eight of those
    // for two people because tapping "enrol" again is what anybody does when
    // nothing happens.
    const superseded = new Set(['old'])
    const [row] = buildFleet(
      [health({ installation_id: 'old', never_reported: true, installation_status: 'pending' })],
      undefined,
      new Date(),
      superseded,
    )
    expect(row?.state).toBe('superseded')
  })

  it('leaves the current attempt alone', () => {
    const [row] = buildFleet(
      [health({ installation_id: 'current', never_reported: true, installation_status: 'pending' })],
      undefined,
      new Date(),
      new Set(['old']),
    )
    expect(row?.state).toBe('never_reported')
  })
})

describe('what counts as work', () => {
  it('excludes history from the attention count', () => {
    // The banner said "129 of 129 need attention" while 67 were abandoned
    // attempts, which is the same noise the count was meant to replace.
    expect(needsAttention('superseded')).toBe(false)
    expect(needsAttention('revoked')).toBe(false)
    expect(needsAttention('healthy')).toBe(false)
  })

  it('includes every state somebody must act on', () => {
    for (const state of ['never_reported', 'install_disappeared', 'offline', 'degraded', 'awaiting_telemetry'] as const) {
      expect(needsAttention(state)).toBe(true)
    }
  })
})
