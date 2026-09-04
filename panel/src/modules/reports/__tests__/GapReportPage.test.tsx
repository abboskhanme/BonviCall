/**
 * `/reports/gap` — the product's own smoke alarm.
 *
 * The one thing that must never regress here is the distinction the audio
 * states already carry: **a recording removed by retention is not a gap.** It
 * existed, the 12-month job took it, and nobody did anything wrong. Putting it
 * in the numerator would point the report at the wrong person — and this
 * report is how Bonvi decides whether a handset or an employee has a problem.
 *
 * The other rule is arithmetic honesty: percentages arrive as decimal STRINGS
 * because the column is NUMERIC, and they are displayed as sent. Re-rounding
 * on the way to the screen is how a report ends up disagreeing with the call
 * list it is required to reconcile with (UC-22).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { GapReportPage } from '@/modules/reports/GapReportPage'
import { percentValue } from '@/modules/reports/api'
import type { GapReport } from '@/modules/reports/api'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

function makeReport(overrides: Partial<GapReport> = {}): GapReport {
  return {
    answered_calls: 100,
    calls_with_audio: 82,
    missing_total: 18,
    capture_rate: '82.40',
    by_reason: [
      // Not a capture failure: the audio is on its way.
      { reason: 'pending_upload', calls: 6, counts_against_capture_rate: false },
      // Not a capture failure: no recording was ever expected.
      { reason: 'not_expected', calls: 4, counts_against_capture_rate: false },
      // A real one.
      { reason: 'oem_recorder_off', calls: 8, counts_against_capture_rate: true },
    ],
    by_model: [
      {
        manufacturer: 'Xiaomi',
        model: 'Redmi 10C',
        app_variant: 'legacy28',
        api_level: 31,
        answered_calls: 40,
        calls_with_audio: 20,
        capture_rate: '50.00',
        baseline_rate: '85.00',
        delta_pp: '-35.00',
        regression: true,
      },
      {
        manufacturer: 'Samsung',
        model: 'SM-A546E',
        app_variant: 'modern34',
        api_level: 34,
        answered_calls: 60,
        calls_with_audio: 58,
        capture_rate: '96.67',
        baseline_rate: null,
        delta_pp: null,
        regression: false,
      },
    ],
    by_agent: [
      {
        agent_id: 'agent-1',
        agent_name: 'Aziz Karimov',
        answered_calls: 40,
        calls_with_audio: 20,
        capture_rate: '50.00',
      },
    ],
    open_deltas: [],
    ...overrides,
  }
}

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage(path = '/reports/gap') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/reports/gap" element={<GapReportPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: 'user-1',
      email: 'admin@bonvi.uz',
      full_name: 'Administrator',
      role: 'admin',
      permissions: [Perm.REPORTS_READ],
      must_change_password: false,
      agent_id: null,
    },
    permissions: new Set([Perm.REPORTS_READ]),
    loginError: null,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('what counts as a gap', () => {
  it('marks the reasons that are NOT capture failures as such', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, makeReport()))
    renderPage()

    await screen.findByText(t('gap.byReasonTitle'))
    const rows = screen.getAllByRole('row')

    const pending = rows.find((row) => row.textContent?.includes(t('calls.noAudioReason.pending_upload')))
    const notExpected = rows.find((row) => row.textContent?.includes(t('calls.noAudioReason.not_expected')))
    const real = rows.find((row) => row.textContent?.includes(t('calls.noAudioReason.oem_recorder_off')))

    expect(pending).toBeDefined()
    expect(notExpected).toBeDefined()
    expect(real).toBeDefined()

    // A healthy fleet must not look broken for the ninety seconds between a
    // call ending and its recording arriving.
    expect(within(pending as HTMLElement).getByText(t('gap.notAGap'))).toBeInTheDocument()
    expect(within(notExpected as HTMLElement).getByText(t('gap.notAGap'))).toBeInTheDocument()
    expect(within(real as HTMLElement).getByText(t('gap.isGap'))).toBeInTheDocument()
  })

  it('never lists a retention-expired recording as a reason at all', async () => {
    // There is no `expired` member of AudioMissingReason, and there must not
    // be one: an expired recording carries no missing reason, so it is not in
    // this report's numerator. If it ever appears here, the numerator has been
    // corrupted and the report will point at the wrong person.
    fetchMock.mockResolvedValue(jsonResponse(200, makeReport()))
    renderPage()

    await screen.findByText(t('gap.byReasonTitle'))
    expect(screen.queryByText(t('calls.audio.expired'))).toBeNull()
  })
})

describe('capture rate against the M0 baseline', () => {
  it('flags a model that has regressed', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, makeReport()))
    renderPage()

    await screen.findByText(t('gap.byModelTitle'))
    const rows = screen.getAllByRole('row')
    const xiaomi = rows.find((row) => row.textContent?.includes('Redmi 10C'))
    expect(xiaomi).toBeDefined()
    expect(within(xiaomi as HTMLElement).getByText(t('gap.regression'))).toBeInTheDocument()
    expect(within(xiaomi as HTMLElement).getByText('-35.00')).toBeInTheDocument()
  })

  it('leaves the baseline blank rather than implying a model passed', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, makeReport()))
    renderPage()

    await screen.findByText(t('gap.byModelTitle'))
    const samsung = screen
      .getAllByRole('row')
      .find((row) => row.textContent?.includes('SM-A546E'))
    expect(samsung).toBeDefined()
    // An absent baseline is not a passing one; T14 has not measured it yet.
    expect(within(samsung as HTMLElement).queryByText(t('gap.regression'))).toBeNull()
  })

  it('shows the percentage exactly as the server wrote it', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, makeReport()))
    renderPage()

    // "82.40", not 82.4 and not 82. The column is NUMERIC and the report has
    // to reconcile with the call list to the digit.
    expect(await screen.findByText('82.40%')).toBeInTheDocument()
    expect(screen.getByText('96.67%')).toBeInTheDocument()
  })
})

describe('reconciliation and states', () => {
  it('links the missing total to the call list that must match it', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, makeReport()))
    renderPage()

    // UC-22: the same filter builder produces both, and this link is how a
    // sceptical reader checks that claim in two clicks.
    const link = await screen.findByRole('link', { name: t('gap.openCalls') })
    expect(link).toHaveAttribute('href', '/calls?has_audio=false')
  })

  it('renders the empty state when nothing was answered', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        200,
        makeReport({
          answered_calls: 0,
          calls_with_audio: 0,
          missing_total: 0,
          capture_rate: null,
          by_reason: [],
          by_model: [],
          by_agent: [],
        }),
      ),
    )
    renderPage()

    expect(await screen.findByText(t('gap.emptyAll'))).toBeInTheDocument()
  })

  it('renders the error state in Uzbek', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(403, { error: { code: 'forbidden', message: 'Forbidden' } }),
    )
    renderPage()

    expect(await screen.findByTestId('query-error')).toBeInTheDocument()
    expect(screen.getByText(t('errors.forbidden'))).toBeInTheDocument()
  })

  it('renders the loading state', () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => {}))
    renderPage()
    expect(screen.getByTestId('query-loading')).toBeInTheDocument()
  })

  it('passes the date range to the server rather than filtering locally', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, makeReport()))
    renderPage('/reports/gap?date_from=2026-09-01&date_to=2026-09-05')

    await screen.findByText(t('gap.byReasonTitle'))
    const url = String(fetchMock.mock.calls[0]?.[0] ?? '')
    expect(url).toContain('date_from=2026-09-01')
    expect(url).toContain('date_to=2026-09-05')
  })
})

describe('percentValue', () => {
  it('parses the decimal string for comparison only', () => {
    expect(percentValue('82.40')).toBe(82.4)
    expect(percentValue(null)).toBeNull()
    expect(percentValue(undefined)).toBeNull()
    expect(percentValue('not a number')).toBeNull()
  })
})
