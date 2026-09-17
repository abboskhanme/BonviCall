/**
 * The "why" sentence, the seller name, and the date.
 *
 * Three small pure modules, and each carries a decision worth pinning:
 *
 *  1. ONE sentence per row, strongest rule first (R3 → R1 → R2). A row can
 *     break several rules; beside "we have never spoken to this customer",
 *     "no call before the sale" is noise;
 *  2. `not_checkable` never produces a clean-looking sentence — the cause is
 *     in SAP's data, and that is NOT the same as "all is well";
 *  3. a sale's DATE must render the same day in every browser. The source
 *     appended `T00:00:00` before parsing, which is correct only when the
 *     formatter also uses the browser's zone. This panel always renders in
 *     Asia/Tashkent, so that trick would print the previous day for any reader
 *     east of UTC+5.
 */
import { describe, expect, it } from 'vitest'

import { saleReason, type SaleFacts } from '../reason'
import { formatSaleDate, formatUsd, shiftDay } from '../saleDate'
import { sellerHint, sellerName, sellerUnlinked } from '../seller'
import { t } from '@/shared/i18n'

function facts(overrides: Partial<SaleFacts> = {}): SaleFacts {
  return {
    occurred_on: '2026-08-12',
    verdict: 'suspicious',
    broken_rules: [],
    skip_reason: null,
    last_call_at: null,
    last_call_agent: null,
    days_before: null,
    previous_sale_on: null,
    ...overrides,
  }
}

describe('the "why" sentence', () => {
  it('leads with R3, the strongest, even when other rules also broke', () => {
    expect(saleReason(facts({ broken_rules: ['R1', 'R2', 'R3'] }))).toBe(t('sales.why.never'))
  })

  it('gives R1 the date of the conversation that DID happen, just outside the window', () => {
    // That number is the answer to the manager's actual question.
    expect(
      saleReason(
        facts({
          broken_rules: ['R1', 'R2'],
          last_call_at: '2026-08-03T09:14:00Z',
          days_before: 9,
        }),
      ),
    ).toBe(t('sales.why.noCallBefore', { count: 9, date: '03/08/2026' }))
  })

  it('falls back to the WINDOW when there was no conversation at all', () => {
    expect(saleReason(facts({ broken_rules: ['R1'] }), 3)).toBe(
      t('sales.why.noCallWindow', { count: 3 }),
    )
  })

  it('names BOTH sales for R2, or "which two?" is left hanging', () => {
    expect(
      saleReason(facts({ broken_rules: ['R2'], previous_sale_on: '2026-07-28' })),
    ).toBe(t('sales.why.betweenSales', { from: '28/07/2026', to: '12/08/2026' }))
  })

  it('says why a row could not be checked, and never that it is clean', () => {
    const generic = saleReason(
      facts({ verdict: 'not_checkable', skip_reason: 'generic_code' }),
    )
    expect(generic).toBe(t('sales.why.genericCode'))
    expect(generic).not.toBe(t('sales.verdictHint.ok'))

    expect(saleReason(facts({ verdict: 'not_checkable', skip_reason: 'no_phone' }))).toBe(
      t('sales.why.noPhone'),
    )
    // An unknown cause still must not read as "clean".
    expect(saleReason(facts({ verdict: 'not_checkable', skip_reason: 'something_new' }))).toBe(
      t('sales.verdictHint.not_checkable'),
    )
  })

  it('states the evidence for a CLEAN sale too, rather than leaving it blank', () => {
    // An empty cell reads as "not checked", when in fact there is evidence.
    expect(
      saleReason(
        facts({
          verdict: 'ok',
          last_call_at: '2026-08-12T05:00:00Z',
          last_call_agent: 'Zuhriddin',
        }),
      ),
    ).toBe(t('sales.why.ok', { date: '12/08/2026', agent: 'Zuhriddin' }))
  })
})

describe('the sale date', () => {
  it('renders a bare calendar date as the SAME day', () => {
    // ⚠️ THE DEFECT FIXED IN THE PORT. A bare `YYYY-MM-DD` parses as UTC
    // midnight, which is 05:00 the same day in Asia/Tashkent whatever the
    // browser's own zone. Appending `T00:00:00`, as the source did, would make
    // this the 11th for a reader east of UTC+5.
    expect(formatSaleDate('2026-08-12')).toBe('12/08/2026')
    expect(formatSaleDate('2026-01-01')).toBe('01/01/2026')
  })

  it('renders an instant as its Asia/Tashkent calendar date', () => {
    // 21:30 UTC is already the next day in Tashkent, and the panel renders the
    // Tashkent clock for everybody (SPEC §5.3).
    expect(formatSaleDate('2026-08-12T21:30:00Z')).toBe('13/08/2026')
  })

  it('moves a calendar date without crossing a zone', () => {
    expect(shiftDay('2026-08-12', -30)).toBe('2026-07-13')
    expect(shiftDay('2026-08-12', 30)).toBe('2026-09-11')
    // Across a year boundary, where naive arithmetic goes wrong.
    expect(shiftDay('2026-01-01', -1)).toBe('2025-12-31')
  })
})

describe('money', () => {
  it('rounds to whole dollars', () => {
    expect(formatUsd(340.49)).toBe('340 $')
  })

  it('renders an em dash for an absent amount, never "0 $"', () => {
    // "SAP's cell was empty" and "this sale was worth nothing" are different
    // statements, and only one of them is ever true.
    expect(formatUsd(null)).toBe('—')
    expect(formatUsd(undefined)).toBe('—')
    expect(formatUsd(0)).toBe('0 $')
  })
})

describe('who sold it', () => {
  it('prefers the employee card, falling back to SAP\'s own name', () => {
    // ⚠️ SAP's `Подразделение` IS the employee — often written as a territory.
    expect(sellerName({ branch: 'Нукус', agent_name: 'Zuhriddin' })).toBe('Zuhriddin')
    expect(sellerName({ branch: 'Нукус', agent_name: null })).toBe('Нукус')
    expect(sellerName({ branch: null, agent_name: null })).toBeNull()
  })

  it('never hides that a sale is unlinked', () => {
    // With no employee card the sale falls out of the per-employee cut
    // entirely, so saying nothing would lose it quietly.
    const row = { branch: 'Нукус', agent_name: null }
    expect(sellerHint(row)).toBe(t('sales.notLinked'))
    expect(sellerUnlinked(row)).toBe(true)
  })

  it('prints SAP\'s wording when the two names differ', () => {
    // Without it the manager cannot find the row in SAP.
    expect(sellerHint({ branch: 'Нукус', agent_name: 'Zuhriddin' })).toBe(
      t('sales.sapName', { name: 'Нукус' }),
    )
    // Identical names produce no note: repeating one word twice tells nobody
    // anything.
    expect(sellerHint({ branch: 'Zuhriddin', agent_name: 'Zuhriddin' })).toBeNull()
    expect(sellerUnlinked({ branch: 'Нукус', agent_name: 'Zuhriddin' })).toBe(false)
  })
})
