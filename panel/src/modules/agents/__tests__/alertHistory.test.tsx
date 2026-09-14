/**
 * The closed half of Ogohlantirishlar, on the person it was about.
 *
 * What is pinned is the thing that would quietly undo the change: the request
 * must ask for **this agent** and for **more than the open ones**. Either half
 * missing turns the section into a second copy of the inbox, which is what the
 * inbox was simplified to stop being.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AlertHistorySection } from '@/modules/agents/AlertHistorySection'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

const AGENT_ID = 'agent-1'
const fetchMock = vi.fn<typeof fetch>()

function alert(overrides: Record<string, unknown> = {}) {
  return {
    id: 'alert-1',
    kind: 'device_offline',
    severity: 'warning',
    title_uz: 'server-derived-title',
    body_uz: 'server-derived-body',
    agent_id: AGENT_ID,
    installation_id: 'inst-1',
    number_id: null,
    device_model: null,
    first_seen_at: '2026-08-01T08:00:00+05:00',
    last_seen_at: '2026-08-03T09:00:00+05:00',
    occurrence_count: 4,
    acknowledged_at: null,
    acknowledged_by: null,
    resolved_at: null,
    detail: {},
    installation_status: 'active',
    ...overrides,
  }
}

function manyAlerts(n: number) {
  return Array.from({ length: n }, (_, i) =>
    alert({ id: `alert-${i}`, title_uz: `ogohlantirish-${i}` }),
  )
}

function world(items: unknown[]) {
  fetchMock.mockImplementation(() =>
    Promise.resolve(
      new Response(
        JSON.stringify({ items, total: items.length, open_count: 0 }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ),
  )
  return () => String(fetchMock.mock.calls.at(-1)?.[0] ?? '')
}

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AlertHistorySection agentId={AGENT_ID} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('token')
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

describe('the request', () => {
  it('asks for this agent, and for the closed ones too', async () => {
    const lastUrl = world([alert()])
    renderSection()

    await screen.findByText('server-derived-title')

    expect(lastUrl()).toContain(`agent_id=${AGENT_ID}`)
    expect(lastUrl()).toContain('open_only=false')
  })
})

describe('what a row says', () => {
  it('marks a resolved alert as resolved rather than as open', async () => {
    world([alert({ resolved_at: '2026-08-04T10:00:00+05:00' })])
    renderSection()

    expect(await screen.findByText(t('agentDetail.alertsResolved'))).toBeInTheDocument()
    expect(screen.queryByText(t('agentDetail.alertsOpen'))).toBeNull()
  })

  it('counts repeats instead of listing them', async () => {
    /** A phone offline for a week is one alert seen many times, and the
     *  dedupe rule that makes it so is the reason this list stays readable. */
    world([alert({ occurrence_count: 4 })])
    renderSection()

    expect(
      await screen.findByText(t('agentDetail.alertsRepeats', { n: 4 })),
    ).toBeInTheDocument()
  })

  it('says so plainly when nothing was ever raised', async () => {
    world([])
    renderSection()

    await waitFor(() =>
      expect(screen.getByText(t('agentDetail.alertsEmpty'))).toBeInTheDocument(),
    )
  })
})


describe('pagination', () => {
  /**
   * A phone that has been through a long rollout collects a page of history,
   * and the card is a summary — not a place to scroll. Ten at a time, turned
   * in the browser: `GET /alerts` takes a limit and no offset, and one
   * person's history is small by construction because alerts dedupe.
   */
  it('shows ten rows at a time', async () => {
    world(manyAlerts(25))
    renderSection()

    expect(await screen.findByText('ogohlantirish-0')).toBeInTheDocument()
    expect(screen.getByText('ogohlantirish-9')).toBeInTheDocument()
    expect(screen.queryByText('ogohlantirish-10')).toBeNull()
  })

  it('turns to the next ten', async () => {
    world(manyAlerts(25))
    renderSection()

    await screen.findByText('ogohlantirish-0')
    await userEvent.click(screen.getByRole('button', { name: t('calls.nextPage') }))

    expect(await screen.findByText('ogohlantirish-10')).toBeInTheDocument()
    expect(screen.queryByText('ogohlantirish-0')).toBeNull()
  })

  it('says how many there are in total', async () => {
    world(manyAlerts(25))
    renderSection()

    expect(await screen.findByText(t('agentDetail.alertsCount', { n: 25 }))).toBeInTheDocument()
  })

  it('offers no controls at all when ten is the whole history', async () => {
    /** Two dead buttons under a four-row table is worse than no buttons. */
    world(manyAlerts(10))
    renderSection()

    await screen.findByText('ogohlantirish-0')
    expect(screen.queryByRole('button', { name: t('calls.nextPage') })).toBeNull()
    expect(screen.queryByRole('button', { name: t('calls.prevPage') })).toBeNull()
  })

  it('cannot go back from the first page', async () => {
    world(manyAlerts(25))
    renderSection()

    await screen.findByText('ogohlantirish-0')
    expect(screen.getByRole('button', { name: t('calls.prevPage') })).toBeDisabled()
  })
})
