/**
 * Raising the minimum supported version.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * This strands phones the company does not own. A handset below the floor
 * drains its queue, is refused with 426, and stays refused until somebody
 * physically reaches that salesperson — so the cost has to be on screen before
 * the button, not discoverable afterwards.
 *
 * Four things must never regress:
 *
 *   1. the count AND the names are shown before confirming;
 *   2. `acknowledged_stranded` is the number that was displayed — sending a
 *      freshly-read one would defeat the server's staleness check entirely;
 *   3. a count that could not be fetched never reads as "nobody is affected";
 *   4. `unknown_version_count` is never folded into the stranded count: the
 *      gate lets those phones through and we cannot say whether they are below
 *      the floor, so counting them either way would be a claim we cannot make.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { MinVersionModal } from '@/modules/settings/MinVersionModal'
import type { VersionGateImpact } from '@/modules/settings/appVersions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function impact(overrides: Partial<VersionGateImpact> = {}): VersionGateImpact {
  return {
    version_code: 3,
    current_min_version_code: 1,
    stranded_count: 2,
    stranded: [
      {
        installation_id: 'inst-1',
        agent_name: 'Aziz Karimov',
        device: 'Samsung SM-A546E',
        app_version: '1.0.0',
        app_version_code: 1,
        last_heartbeat_at: '2026-09-05T09:00:00+05:00',
        status: 'active',
      },
      {
        installation_id: 'inst-2',
        agent_name: 'Bekzod Yusupov',
        device: 'Xiaomi Redmi 10C',
        app_version: '1.0.0',
        app_version_code: 1,
        last_heartbeat_at: null,
        status: 'active',
      },
    ],
    unknown_version_count: 0,
    ...overrides,
  }
}

function world(response: VersionGateImpact | 'error') {
  fetchMock.mockImplementation((input, init) => {
    const url = String(input)
    if (url.includes('/app/min-version/impact')) {
      return Promise.resolve(
        response === 'error'
          ? jsonResponse(500, { error: { code: 'internal_error', message: '' } })
          : jsonResponse(200, response),
      )
    }
    if (init?.method === 'PUT') {
      return Promise.resolve(jsonResponse(200, { version_code: 3, stranded_count: 2 }))
    }
    return Promise.resolve(jsonResponse(200, {}))
  })
}

function renderModal(currentMinCode = 1) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <MinVersionModal open onOpenChange={() => {}} currentMinCode={currentMinCode} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function setCode(value: string) {
  const input = screen.getByLabelText(t('appVersions.fieldMinCode'))
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

describe('the cost, before the button', () => {
  it('names how many phones are stranded and WHOSE they are', async () => {
    world(impact())
    renderModal()
    await setCode('3')

    expect(
      await screen.findByText(t('appVersions.stranded', { n: '2' })),
    ).toBeInTheDocument()
    // "2 devices" and "Aziz and Bekzod" are different sentences to the person
    // about to click.
    expect(screen.getByText('Aziz Karimov')).toBeInTheDocument()
    expect(screen.getByText('Bekzod Yusupov')).toBeInTheDocument()
    expect(screen.getByText(t('appVersions.strandedExplain'))).toBeInTheDocument()
  })

  it('links each stranded phone to its device page', async () => {
    world(impact())
    renderModal()
    await setCode('3')

    const link = await screen.findByRole('link', { name: 'Aziz Karimov' })
    expect(link).toHaveAttribute('href', '/devices/inst-1')
  })

  it('says plainly when nobody is affected', async () => {
    world(impact({ stranded_count: 0, stranded: [] }))
    renderModal()
    await setCode('2')

    expect(await screen.findByText(t('appVersions.strandsNobody'))).toBeInTheDocument()
  })

  it('never implies safety when the impact could not be fetched', async () => {
    world('error')
    renderModal()
    await setCode('3')

    expect(await screen.findByText(t('appVersions.impactFailed'))).toBeInTheDocument()
    expect(screen.queryByText(t('appVersions.strandsNobody'))).toBeNull()
    // And there is nothing to acknowledge, so there is nothing to confirm.
    expect(screen.getByRole('button', { name: t('appVersions.minVersionConfirm') })).toBeDisabled()
  })

  it('keeps phones of unknown version separate from the stranded count', async () => {
    world(impact({ stranded_count: 0, stranded: [], unknown_version_count: 5 }))
    renderModal()
    await setCode('3')

    // The gate lets them through, so they are not stranded — but we cannot say
    // they are safe either, and the page says exactly that.
    expect(await screen.findByText(t('appVersions.strandsNobody'))).toBeInTheDocument()
    expect(
      screen.getByText(t('appVersions.unknownVersions', { n: 5 })),
    ).toBeInTheDocument()
  })
})

describe('acknowledging the count', () => {
  it('sends the number that was on screen, not a fresh one', async () => {
    world(impact())
    renderModal()
    await setCode('3')
    await screen.findByText(t('appVersions.stranded', { n: '2' }))

    await userEvent.click(
      screen.getByRole('button', { name: t('appVersions.minVersionConfirmStranding', { n: 2 }) }),
    )

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
      expect(put).toBeDefined()
      // Re-reading the live count here would defeat the server's staleness
      // check, which exists precisely to catch a picture that went stale.
      expect(JSON.parse(String(put?.[1]?.body))).toEqual({
        version_code: 3,
        acknowledged_stranded: 2,
      })
    })
  })

  it('explains a stale acknowledgement instead of showing "conflict"', async () => {
    fetchMock.mockImplementation((input, init) => {
      if (String(input).includes('/impact')) {
        return Promise.resolve(jsonResponse(200, impact()))
      }
      if (init?.method === 'PUT') {
        return Promise.resolve(
          jsonResponse(409, {
            error: { code: 'stranded_count_mismatch', message: 'conflict' },
          }),
        )
      }
      return Promise.resolve(jsonResponse(200, {}))
    })
    renderModal()
    await setCode('3')
    await screen.findByText(t('appVersions.stranded', { n: '2' }))

    await userEvent.click(
      screen.getByRole('button', { name: t('appVersions.minVersionConfirmStranding', { n: 2 }) }),
    )

    // The number moved between looking and deciding — say that.
    expect(await screen.findByText(t('appVersions.strandedMoved'))).toBeInTheDocument()
  })

  it('labels the confirm button with the consequence when there is one', async () => {
    world(impact())
    renderModal()
    await setCode('3')

    expect(
      await screen.findByRole('button', {
        name: t('appVersions.minVersionConfirmStranding', { n: 2 }),
      }),
    ).toBeInTheDocument()
  })
})
