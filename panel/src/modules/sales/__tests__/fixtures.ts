/**
 * Shapes for the sales-control tests.
 *
 * Built to the CONTRACT rather than to what the page happens to read: a
 * fixture missing a field the server always sends is how a test keeps passing
 * while the page breaks (CONVENTIONS.md §13).
 *
 * The numbers come from the real measurements the module's own comments
 * record, so a reader of a failing assertion sees a plausible figure rather
 * than a row of ones.
 */
import type {
  ComplianceItem,
  ComplianceList,
  ComplianceSummary,
  ComplianceTimeline,
  ImportPreview,
  ImportReport,
  SaleBranchList,
} from '../api'

export function makeItem(overrides: Partial<ComplianceItem> = {}): ComplianceItem {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    occurred_on: '2026-08-12',
    external_id: '88681',
    doc_number: 'RN-004512',
    partner_code: 'К02711',
    partner_name: 'Alfa Savdo MChJ',
    phone: '+998901112233',
    phone_key: '901112233',
    branch: 'Нукус',
    direction: 'ВЕЛО',
    agent_id: '22222222-2222-4222-8222-222222222222',
    agent_name: 'Zuhriddin Rasulov',
    amount: 4_250_000,
    currency: 'UZS',
    amount_usd: 340,
    verdict: 'suspicious',
    broken_rules: ['R1'],
    calls_between: 0,
    calls_total: 4,
    skip_reason: null,
    last_call_at: '2026-08-03T09:14:00Z',
    last_call_agent: 'Zuhriddin Rasulov',
    last_call_id: '33333333-3333-4333-8333-333333333333',
    days_before: 9,
    previous_sale_on: '2026-07-28',
    over_limit: false,
    partner_excluded: false,
    review: null,
    ...overrides,
  }
}

export function makeList(
  items: ComplianceItem[] = [makeItem()],
  overrides: Partial<ComplianceList> = {},
): ComplianceList {
  return {
    items,
    next_cursor: null,
    has_more: false,
    total: items.length,
    window_days: 3,
    ...overrides,
  }
}

export function makeSummary(overrides: Partial<ComplianceSummary> = {}): ComplianceSummary {
  return {
    total: 451,
    ok: 372,
    suspicious: 45,
    not_checkable: 34,
    new: 41,
    justified: 3,
    confirmed: 1,
    over_limit: 0,
    over_limit_amount: 0,
    walk_in_limit: 0,
    window_days: 3,
    agents: [
      {
        agent_id: '22222222-2222-4222-8222-222222222222',
        agent_name: 'Zuhriddin Rasulov',
        sales: 120,
        ok: 100,
        suspicious: 12,
        not_checkable: 8,
        new: 11,
        justified: 1,
        confirmed: 0,
        over_limit: 0,
        over_limit_amount: 0,
      },
    ],
    ...overrides,
  }
}

/** The walk-in section: no classes, a ticket limit instead. */
export function makeWalkInSummary(): ComplianceSummary {
  return makeSummary({
    total: 718,
    ok: 0,
    suspicious: 0,
    not_checkable: 718,
    over_limit: 23,
    over_limit_amount: 531_432,
    walk_in_limit: 500,
  })
}

export function makeBranches(): SaleBranchList {
  return {
    items: [
      {
        branch: 'Нукус',
        agent_id: '22222222-2222-4222-8222-222222222222',
        agent_name: 'Zuhriddin Rasulov',
        matched_automatically: false,
        sales: 120,
        excluded: false,
      },
      {
        branch: 'Кукон метан булими',
        agent_id: null,
        agent_name: null,
        matched_automatically: true,
        sales: 47,
        excluded: false,
      },
      {
        branch: 'Логистика',
        agent_id: null,
        agent_name: null,
        matched_automatically: false,
        sales: 8,
        excluded: true,
      },
    ],
    total: 3,
  }
}

/**
 * A chain with the same-day rule already applied by the server: on 12.08 the
 * call comes before the sale, and nothing on the client re-sorts it.
 */
export function makeTimeline(overrides: Partial<ComplianceTimeline> = {}): ComplianceTimeline {
  return {
    truncated: false,
    window_days: 3,
    clients: [
      {
        partner_code: 'К02711',
        partner_name: 'Alfa Savdo MChJ',
        phone: '+998901112233',
        agents: ['Zuhriddin Rasulov'],
        sales_count: 2,
        suspicious_count: 1,
        amount_usd: 690,
        calls_count: 1,
        events: [
          {
            kind: 'sale',
            at: '2026-07-28T00:00:00Z',
            sale_id: '44444444-4444-4444-8444-444444444444',
            external_id: '88010',
            doc_number: 'RN-004001',
            amount_usd: 350,
            currency: 'UZS',
            verdict: 'ok',
            broken_rules: [],
            agent_name: 'Zuhriddin Rasulov',
          },
          {
            kind: 'call',
            at: '2026-08-12T04:14:00Z',
            call_id: '33333333-3333-4333-8333-333333333333',
            agent_name: 'Zuhriddin Rasulov',
            // `outgoing`/`incoming` — this product's own vocabulary
            // (`core/enums.py::CallDirection`), never BonviZvonki's
            // `inbound`/`outbound`, which the server cannot send.
            direction: 'outgoing',
            answered: true,
            duration_sec: 96,
            has_audio: true,
          },
          {
            kind: 'sale',
            at: '2026-08-12T00:00:00Z',
            sale_id: '11111111-1111-4111-8111-111111111111',
            external_id: '88681',
            doc_number: 'RN-004512',
            amount_usd: 340,
            currency: 'UZS',
            verdict: 'suspicious',
            broken_rules: ['R1'],
            agent_name: 'Zuhriddin Rasulov',
          },
        ],
      },
    ],
    ...overrides,
  }
}

export function makePreview(overrides: Partial<ImportPreview> = {}): ImportPreview {
  return {
    kind: 'register',
    filename: 'savdo-kunlik.xlsx',
    rows: 2384,
    new_rows: 1902,
    existing_rows: 481,
    date_from: '2026-08-01',
    date_to: '2026-08-12',
    by_type: [
      { type: 'sale', label: 'Продажа', count: 1840, amount_usd: 412_900 },
      { type: 'payment_in', label: 'Приход денег', count: 544, amount_usd: null },
    ],
    by_day: [{ day: '2026-08-12', count: 212, amount_usd: 41_000 }],
    unknown_partners: ['К09911', 'К09912'],
    unknown_partner_count: 2,
    unmatched_branches: ['Кукон метан булими'],
    without_phone: 17,
    warnings: [
      { code: 'duplicate_keys_in_file', count: 1 },
      { code: 'rows_without_amount', count: 6 },
    ],
    ...overrides,
  }
}

export function makeReport(overrides: Partial<ImportReport> = {}): ImportReport {
  return {
    kind: 'register',
    source: 'savdo-kunlik.xlsx',
    read: 2384,
    created: 1902,
    updated: 481,
    skipped: 1,
    unknown_partner: 2,
    unknown_op_type: 0,
    inactive_skipped: 0,
    inactive_deactivated: 0,
    phones_filled: 0,
    linked_sales: 0,
    attributed_sales: 12,
    unmatched_branches: ['Кукон метан булими'],
    ...overrides,
  }
}
