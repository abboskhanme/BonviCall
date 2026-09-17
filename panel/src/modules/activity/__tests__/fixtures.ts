/**
 * One activity report, built from the generated types.
 *
 * Typed against `types.gen.ts` rather than a hand-written shape, so a renamed
 * server field breaks the fixture too — a fixture that keeps compiling after
 * the contract moved is a test that passes against something that no longer
 * exists.
 */
import type {
  ActivityDay,
  ActivityHour,
  ActivityReport,
  ActivityRow,
  MissedClient,
  MissedClientsReport,
} from '@/modules/activity/api'

export const AZIZ = '11111111-1111-4111-8111-111111111111'
export const DILNOZA = '22222222-2222-4222-8222-222222222222'

export function makeRow(overrides: Partial<ActivityRow> = {}): ActivityRow {
  const base: ActivityRow = {
    agent_id: AZIZ,
    agent_name: 'Aziz',
    outbound_total: 40,
    outbound_answered: 30,
    outbound_no_answer: 10,
    inbound_total: 20,
    inbound_answered: 14,
    missed: 6,
    missed_called_back: 4,
    missed_addressable: 6,
    missed_open: 2,
    missed_clients: 4,
    clients_reached: 3,
    clients_unreached: 1,
    missed_rate: 30,
    callback_rate: 75,
    callback_median_minutes: 12.5,
    total: 60,
    talk_seconds: 3600,
  }
  return { ...base, ...overrides }
}

export function makeDay(day: string, overrides: Partial<ActivityDay> = {}): ActivityDay {
  return {
    day,
    inbound: 10,
    inbound_answered: 7,
    missed: 3,
    outbound: 20,
    outbound_no_answer: 5,
    ...overrides,
  }
}

export function makeHour(hour: number, overrides: Partial<ActivityHour> = {}): ActivityHour {
  return {
    hour,
    inbound: 4,
    inbound_answered: 3,
    missed: 1,
    outbound: 6,
    outbound_no_answer: 2,
    missed_rate: 25,
    ...overrides,
  }
}

export function makeReport(overrides: Partial<ActivityReport> = {}): ActivityReport {
  const agents = overrides.agents ?? [
    makeRow(),
    makeRow({
      agent_id: DILNOZA,
      agent_name: 'Dilnoza',
      outbound_total: 10,
      outbound_answered: 8,
      outbound_no_answer: 2,
      inbound_total: 4,
      inbound_answered: 4,
      missed: 0,
      missed_called_back: 0,
      missed_addressable: 0,
      missed_open: 0,
      missed_clients: 0,
      clients_reached: 0,
      clients_unreached: 0,
      missed_rate: 0,
      callback_rate: null,
      callback_median_minutes: null,
      total: 14,
      talk_seconds: 600,
    }),
  ]
  const base: ActivityReport = {
    days: 7,
    date_from: '2026-08-14',
    date_to: '2026-08-20',
    callback_window_hours: 24,
    callback_median_minutes: 11.4,
    days_series: [
      makeDay('2026-08-14'),
      makeDay('2026-08-15', { inbound: 0, inbound_answered: 0, missed: 0, outbound: 0, outbound_no_answer: 0 }),
      makeDay('2026-08-16'),
      makeDay('2026-08-17'),
      makeDay('2026-08-18'),
      makeDay('2026-08-19'),
      makeDay('2026-08-20'),
    ],
    hours_series: Array.from({ length: 24 }, (_, hour) => makeHour(hour)),
    agents,
    total: makeRow({
      agent_id: '00000000-0000-0000-0000-000000000000',
      agent_name: '',
      outbound_total: 50,
      outbound_answered: 38,
      outbound_no_answer: 12,
      inbound_total: 24,
      inbound_answered: 18,
      missed: 6,
      missed_called_back: 4,
      missed_addressable: 6,
      missed_open: 2,
      missed_clients: 4,
      clients_reached: 3,
      clients_unreached: 1,
      missed_rate: 25,
      callback_rate: 75,
      callback_median_minutes: 11.4,
      total: 74,
      talk_seconds: 4200,
    }),
  }
  return { ...base, ...overrides, agents }
}

export function makeMissedClient(overrides: Partial<MissedClient> = {}): MissedClient {
  return {
    phone_key: '901234567',
    contact_name: 'Nodira',
    attempts: 2,
    first_missed_at: '2026-08-20T09:00:00+05:00',
    last_missed_at: '2026-08-20T09:30:00+05:00',
    contacted_at: '2026-08-20T09:42:00+05:00',
    contacted_by: 'Dilnoza',
    contact_inbound: false,
    minutes_to_contact: 12,
    ...overrides,
  }
}

export function makeMissedClients(
  overrides: Partial<MissedClientsReport> = {},
): MissedClientsReport {
  return {
    agent_id: AZIZ,
    agent_name: 'Aziz',
    date_from: '2026-08-14',
    date_to: '2026-08-20',
    callback_window_hours: 24,
    clients: [
      makeMissedClient({ phone_key: '907654321', contacted_at: null, contacted_by: null, contact_inbound: null, minutes_to_contact: null, attempts: 3, contact_name: null }),
      makeMissedClient(),
    ],
    unreached: 1,
    ...overrides,
  }
}
