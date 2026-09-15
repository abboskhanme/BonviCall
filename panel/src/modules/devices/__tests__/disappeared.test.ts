/**
 * `install_disappeared` versus `offline` (T140).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * These are different faults and they need different people, which is the
 * entire reason for the distinction:
 *
 *   `offline`             missed a few heartbeats. Switched off, out of
 *                         signal, in a drawer for the afternoon. Comes back
 *                         by itself and usually needs nobody.
 *   `install_disappeared` reported normally and then said nothing for days.
 *                         The app has almost certainly been removed or
 *                         permanently force-stopped. Somebody has to go and
 *                         find that salesperson.
 *   `never_reported`      never started at all. Needs an enrolment, not a
 *                         visit.
 *
 * Collapsing the first two would bury a phone that needs a trip among a dozen
 * that need nothing, which is how a fleet page stops being read.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { describe, expect, it } from 'vitest'

import {
  DISAPPEARED_AFTER_HOURS,
  buildFleet,
  hasDisappeared,
  problemsFor,
  stateFor,
} from '@/modules/devices/api'
import type { DeviceHealth } from '@/modules/devices/api'

const NOW = new Date('2026-09-05T12:00:00+05:00')

function hoursAgo(hours: number): string {
  return new Date(NOW.getTime() - hours * 3_600_000).toISOString()
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
    is_online: false,
    last_heartbeat_at: hoursAgo(2),
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
    updated_at: hoursAgo(2),
    ...overrides,
  }
}

describe('a few hours of silence is offline', () => {
  it('does not call a phone disappeared after two hours', () => {
    expect(hasDisappeared(health({ last_heartbeat_at: hoursAgo(2) }), null, NOW)).toBe(false)
    expect(stateFor(health({ last_heartbeat_at: hoursAgo(2) }), null, NOW)).toBe('offline')
  })

  it('still says offline the hour before the threshold', () => {
    const health_ = health({ last_heartbeat_at: hoursAgo(DISAPPEARED_AFTER_HOURS - 1) })
    expect(stateFor(health_, null, NOW)).toBe('offline')
  })

  it('leaves a weekend alone', () => {
    // A phone switched off on Friday evening and back on Monday is not a
    // disappeared install, and a page that cries wolf every Monday gets
    // ignored by Tuesday.
    expect(stateFor(health({ last_heartbeat_at: hoursAgo(40) }), null, NOW)).toBe('offline')
  })
})

describe('days of silence is a removed app', () => {
  it('flips at the threshold', () => {
    const health_ = health({ last_heartbeat_at: hoursAgo(DISAPPEARED_AFTER_HOURS) })
    expect(hasDisappeared(health_, null, NOW)).toBe(true)
    expect(stateFor(health_, null, NOW)).toBe('install_disappeared')
  })

  it('is not ALSO reported as offline', () => {
    // It is offline, but saying so would file it in the bucket that needs
    // nobody — which is exactly the distinction being drawn.
    const problems = problemsFor(health({ last_heartbeat_at: hoursAgo(72) }), null, NOW)
    expect(problems).toContain('install_disappeared')
    expect(problems).not.toContain('offline')
  })

  it('believes the server over the clock', () => {
    // The server sees an uninstall the panel could only ever guess at from
    // silence, so its stage wins even on a fresh heartbeat.
    const fresh = health({ last_heartbeat_at: hoursAgo(1), is_online: true })
    expect(hasDisappeared(fresh, 'install_disappeared', NOW)).toBe(true)
    expect(stateFor(fresh, 'install_disappeared', NOW)).toBe('install_disappeared')
  })
})

describe('never_reported stays its own thing', () => {
  it('is not turned into "disappeared" by having no heartbeat at all', () => {
    // Nothing disappeared: nothing ever arrived. The fix is an enrolment, not
    // a trip to find the salesperson.
    const silent = health({ never_reported: true, last_heartbeat_at: null })
    expect(hasDisappeared(silent, null, NOW)).toBe(false)
    expect(stateFor(silent, null, NOW)).toBe('never_reported')
    expect(problemsFor(silent, null, NOW)).toEqual(['never_reported'])
  })
})

describe('ordering', () => {
  it('puts the two that need a person above the one that does not', () => {
    const fleet = buildFleet(
      [
        health({ installation_id: 'healthy', is_online: true }),
        health({ installation_id: 'offline', last_heartbeat_at: hoursAgo(3) }),
        health({ installation_id: 'gone', last_heartbeat_at: hoursAgo(96) }),
        health({ installation_id: 'never', never_reported: true, last_heartbeat_at: null }),
      ],
      undefined,
      NOW,
    )

    expect(fleet.map((row) => row.health.installation_id)).toEqual([
      'never',
      'gone',
      'offline',
      'healthy',
    ])
  })

  it('takes the stage map into account when sorting', () => {
    const fleet = buildFleet(
      [
        health({ installation_id: 'a', last_heartbeat_at: hoursAgo(1), is_online: true }),
        health({ installation_id: 'b', last_heartbeat_at: hoursAgo(1), is_online: true }),
      ],
      new Map([['b', 'install_disappeared' as const]]),
      NOW,
    )
    expect(fleet[0]?.health.installation_id).toBe('b')
  })
})
