/**
 * The decision.
 *
 * ⚠️ THE ONE THING THIS FILE EXISTS FOR: `reason` must NOT be sent with
 * `confirmed`. The server answers 422 with `detail.field = "reason"` rather
 * than dropping it — a deliberate change from the source, which dropped it
 * silently, so a manager could pick "Kelib oldi" beside "really suspicious"
 * and watch it disappear. Hiding the picker is not enough: the field must not
 * be on the wire.
 *
 * The two decisions also demand different things, and that asymmetry is the
 * point: a justification is worthless without a REASON (the value of the
 * statistic is the distribution of reasons), and a confirmation is worthless
 * without a NOTE, because it has consequences for a person.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ReviewModal } from '@/modules/sales/ReviewModal'
import { t } from '@/shared/i18n'

import { makeItem } from './fixtures'

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderModal(sale = makeItem()) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  })
  const onClose = vi.fn()
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <ReviewModal sale={sale} windowDays={3} onClose={onClose} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { onClose }
}

/** The body of the one POST this dialog makes. */
function postedBody(): Record<string, unknown> | undefined {
  const call = fetchMock.mock.calls.find(
    (candidate) => candidate[1]?.method === 'POST' && String(candidate[0]).includes('/review'),
  )
  return call ? (JSON.parse(String(call[1]?.body)) as Record<string, unknown>) : undefined
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockImplementation(() =>
    Promise.resolve(
      jsonResponse(200, {
        status: 'justified',
        reason: 'walk_in',
        note: null,
        reviewed_by: 'Test User',
        reviewed_at: '2026-08-13T10:00:00Z',
      }),
    ),
  )
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

describe('justifying a sale', () => {
  it('opens on "justified" with a reason, and sends it', async () => {
    renderModal()
    await userEvent.click(screen.getByRole('button', { name: t('sales.decision.save') }))

    await waitFor(() => {
      expect(postedBody()).toEqual({ status: 'justified', reason: 'walk_in', note: null })
    })
  })

  it('sends the reason that is selected', async () => {
    renderModal()
    await userEvent.selectOptions(screen.getByLabelText(t('sales.decision.reason')), 'telegram')
    await userEvent.click(screen.getByRole('button', { name: t('sales.decision.save') }))
    await waitFor(() => expect(postedBody()?.reason).toBe('telegram'))
  })

  it('does not require a note', async () => {
    renderModal()
    expect(screen.getByRole('button', { name: t('sales.decision.save') })).toBeEnabled()
  })
})

describe('confirming a sale as really suspicious', () => {
  it('NEVER puts `reason` on the wire', async () => {
    // ⚠️ THE TEST THIS FILE EXISTS FOR. The server refuses `reason` here with
    // a 422 naming the field; a UI that sent it would be shipping a control
    // that cannot work.
    renderModal()
    await userEvent.click(screen.getByRole('button', { name: /Haqiqatan shubhali/ }))
    await userEvent.type(
      screen.getByLabelText(t('sales.decision.noteRequired')),
      'SAP da tekshirildi, hujjat yo‘q',
    )
    await userEvent.click(screen.getByRole('button', { name: t('sales.decision.save') }))

    await waitFor(() => {
      const body = postedBody()
      expect(body?.status).toBe('confirmed')
      expect(body).not.toHaveProperty('reason')
    })
  })

  it('hides the reason picker entirely', async () => {
    renderModal()
    await userEvent.click(screen.getByRole('button', { name: /Haqiqatan shubhali/ }))
    expect(screen.queryByLabelText(t('sales.decision.reason'))).toBeNull()
  })

  it('demands a note before it can be saved', async () => {
    // This decision has consequences for a person, so it must not be one click
    // away.
    renderModal()
    await userEvent.click(screen.getByRole('button', { name: /Haqiqatan shubhali/ }))
    expect(screen.getByRole('button', { name: t('sales.decision.save') })).toBeDisabled()

    await userEvent.type(screen.getByLabelText(t('sales.decision.noteRequired')), 'yo‘q')
    expect(screen.getByRole('button', { name: t('sales.decision.save') })).toBeEnabled()
  })
})

describe('reopening a decided sale', () => {
  it('loads the existing decision rather than a blank form', async () => {
    // A manager most often reopens this to correct the note; a blank form
    // would make them type it again.
    renderModal(
      makeItem({
        review: {
          status: 'justified',
          reason: 'contract',
          note: 'Shartnoma bor',
          reviewed_by: 'Rahbar',
          reviewed_at: '2026-08-13T10:00:00Z',
        },
      }),
    )
    expect(screen.getByLabelText(t('sales.decision.reason'))).toHaveValue('contract')
    expect(screen.getByLabelText(t('sales.decision.note'))).toHaveValue('Shartnoma bor')
  })
})

describe('when the server refuses', () => {
  it('shows the failure and does not close the dialog', async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(
        jsonResponse(422, {
          error: {
            code: 'validation_error',
            message: 'Sabab faqat «Oqlandi» bilan yuboriladi',
            detail: { field: 'reason' },
            request_id: 'r',
          },
        }),
      ),
    )
    const { onClose } = renderModal()
    await userEvent.click(screen.getByRole('button', { name: t('sales.decision.save') }))

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })
})
