/**
 * The retention dialog.
 *
 * Lowering retention deletes recordings irreversibly, on a schedule. A dialog
 * that asks "are you sure?" asks about the wrong thing — the admin already
 * knows they typed a smaller number. What they do not know is **how many
 * recordings that number destroys**, and this file pins that they are told
 * before they can confirm.
 *
 * The count comes from the server through the same `/calls` filter the list
 * and the export use, so it is a number somebody can go and check rather than
 * a claim. The three things that must never regress:
 *
 *   1. lowering shows a count, and the count is the SERVER's;
 *   2. a failure to count never reads as "nothing will be deleted";
 *   3. `confirm` is sent only when the admin actually confirmed something.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RetentionModal } from '@/modules/settings/RetentionModal'
import { cutoffDate } from '@/modules/settings/api'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderModal(currentMonths = 12, confirmBelowMonths = 3) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <RetentionModal
          open
          onOpenChange={() => {}}
          currentMonths={currentMonths}
          confirmBelowMonths={confirmBelowMonths}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function setMonths(value: string) {
  const input = screen.getByLabelText(t('settings.retentionMonths'))
  await userEvent.clear(input)
  await userEvent.type(input, value)
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('lowering retention', () => {
  it('says how many recordings will be destroyed, and where to look at them', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { items: [], total: 137, has_more: false, next_cursor: null }))
    renderModal(12, 3)

    await setMonths('6')

    expect(
      await screen.findByText(
        t('settings.retentionAffected', { n: '137', date: cutoffDate(6) }),
      ),
    ).toBeInTheDocument()
    // Not a claim to be taken on faith: a list somebody can open first.
    expect(screen.getByRole('link', { name: t('settings.retentionSeeList') })).toBeInTheDocument()
  })

  it('counts through the SERVER, with the same filter the call list uses', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { items: [], total: 5, has_more: false, next_cursor: null }))
    renderModal(12, 3)

    await setMonths('6')
    await screen.findByText(new RegExp(String(5)))

    const url = String(fetchMock.mock.calls.find(([i]) => String(i).includes('/calls'))?.[0] ?? '')
    // Counting in the panel would be a second definition of "old" (UC-22).
    expect(url).toContain('has_audio=true')
    expect(url).toContain(`date_to=${cutoffDate(6)}`)
    expect(url).toContain('with_total=true')
  })

  it('says plainly when nothing is old enough to be affected', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { items: [], total: 0, has_more: false, next_cursor: null }))
    renderModal(12, 3)

    await setMonths('6')
    expect(await screen.findByText(t('settings.retentionNoneAffected'))).toBeInTheDocument()
  })

  it('never implies safety when the count could not be fetched', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(500, { error: { code: 'internal_error', message: '' } }),
    )
    renderModal(12, 3)

    await setMonths('6')

    // Silence here would be the most expensive kind of reassurance.
    expect(await screen.findByText(t('settings.retentionCountFailed'))).toBeInTheDocument()
    expect(screen.queryByText(t('settings.retentionNoneAffected'))).toBeNull()
  })

  it('shows no warning at all when the window is being RAISED', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { items: [], total: 0, has_more: false, next_cursor: null }))
    renderModal(12, 3)

    await setMonths('24')

    expect(screen.queryByText(t('settings.retentionWarning'))).toBeNull()
    // Nothing is counted for the value they settled on, because raising the
    // window deletes nothing. (Typing "24" passes through "2", which is a
    // lowering, so a count for THAT intermediate value is expected and
    // harmless — it is cached and never shown.)
    const counted = fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) => url.includes(`date_to=${cutoffDate(24)}`))
    expect(counted).toHaveLength(0)
  })
})

describe('the confirmation gate', () => {
  it('sends confirm=true only below the threshold', async () => {
    fetchMock.mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/calls')) {
        return Promise.resolve(jsonResponse(200, { items: [], total: 3, has_more: false, next_cursor: null }))
      }
      return Promise.resolve(jsonResponse(200, { key: 'retention.audio_months', value: 2 }))
    })
    renderModal(12, 3)

    await setMonths('2')
    await screen.findByText(t('settings.retentionWarning'))
    await userEvent.click(screen.getByRole('button', { name: t('settings.retentionConfirmAction') }))

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
      expect(put).toBeDefined()
      expect(JSON.parse(String(put?.[1]?.body))).toEqual({
        key: 'retention.audio_months',
        value: 2,
        confirm: true,
      })
    })
  })

  it('does not claim a confirmation that was never asked for', async () => {
    fetchMock.mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/calls')) {
        return Promise.resolve(jsonResponse(200, { items: [], total: 1, has_more: false, next_cursor: null }))
      }
      return Promise.resolve(jsonResponse(200, { key: 'retention.audio_months', value: 6 }))
    })
    renderModal(12, 3)

    await setMonths('6')
    await screen.findByText(t('settings.retentionWarning'))
    await userEvent.click(screen.getByRole('button', { name: t('settings.retentionConfirmAction') }))

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
      // 6 is above the confirm threshold: the server does not demand a
      // confirmation, so the panel does not assert one was given.
      expect(JSON.parse(String(put?.[1]?.body)).confirm).toBe(false)
    })
  })

  it('refuses a value outside the allowed range', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { items: [], total: 0, has_more: false, next_cursor: null }))
    renderModal(12, 3)

    await setMonths('0')
    expect(screen.getByText(t('settings.retentionInvalid'))).toBeInTheDocument()
  })
})

describe('cutoffDate', () => {
  it('subtracts whole months in Asia/Tashkent', () => {
    expect(cutoffDate(6, new Date('2026-09-05T12:00:00Z'))).toBe('2026-03-05')
    expect(cutoffDate(12, new Date('2026-09-05T12:00:00Z'))).toBe('2025-09-05')
  })

  it('clamps a day that does not exist in the target month', () => {
    // 31 March minus one month is 28 February, not 3 March: rolling over
    // would quietly widen the window by three days.
    expect(cutoffDate(1, new Date('2026-03-31T12:00:00Z'))).toBe('2026-02-28')
  })

  it('reads the day in Tashkent, not in UTC', () => {
    // 20:00 UTC is already the next day in Tashkent (UTC+5).
    expect(cutoffDate(1, new Date('2026-09-05T20:00:00Z'))).toBe('2026-08-06')
  })
})
