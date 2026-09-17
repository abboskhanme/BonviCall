/**
 * `/rubric` — the page that decides how everybody is scored.
 *
 * The five things it must not get wrong:
 *
 *  1. **a non-admin cannot edit.** A manager reads the criteria and is offered
 *     no control at all — the server refuses `settings:write` anyway, and a
 *     button that always 403s is worse than no button;
 *  2. the save button stays dead until the blocks total exactly 100, because
 *     the server refuses anything else and an editor that only finds out on
 *     submit teaches people to distrust it;
 *  3. publishing sends the whole rubric to `PUT /analysis/rubric` — a new
 *     version, never an edit of the live one;
 *  4. the server's refusal is rendered as its Uzbek sentence, with the numbers
 *     it came back with;
 *  5. a database with nothing published says so, rather than pretending
 *     somebody chose the rubric it is scoring with.
 *
 * Plus the three `QueryBoundary` states (CONVENTIONS-CLIENT.md §10).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RubricPage } from '@/modules/rubric/RubricPage'
import { useAuth } from '@/modules/auth/store'
import { tokenStore } from '@/shared/api/client'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'

import { makePrompt, makeRubric, makeVersions } from './fixtures'

/** `noUncheckedIndexedAccess` is on: an index is `T | undefined` everywhere. */
function at<T>(items: readonly T[], index: number): T {
  const item = items[index]
  if (item === undefined) throw new Error(`nothing at index ${index}`)
  return item
}

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function respond(handler: (url: string, init?: RequestInit) => Response) {
  fetchMock.mockImplementation((input, init) => {
    const url =
      typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    return Promise.resolve(handler(url, init))
  })
}

function signIn(permissions: string[]) {
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: '55555555-5555-4555-8555-555555555555',
      email: 'tester@bonvi.uz',
      full_name: 'Test User',
      role: 'admin',
      permissions,
      must_change_password: false,
      agent_id: null,
    },
    permissions: new Set(permissions),
    loginError: null,
  })
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={['/rubric']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <RubricPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** The three GETs the page can make, answered from one place. */
function showing(rubric = makeRubric(), versions = makeVersions()) {
  respond((url) => {
    if (url.includes('/rubric/versions')) return jsonResponse(200, versions)
    if (url.includes('/rubric/prompt')) return jsonResponse(200, makePrompt())
    return jsonResponse(200, rubric)
  })
  return renderPage()
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  signIn([Perm.ANALYSIS_READ, Perm.SETTINGS_WRITE])
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('reading the rubric', () => {
  it('shows every block with what its criteria add up to', async () => {
    showing()

    expect(await screen.findByText('Skript')).toBeInTheDocument()
    expect(screen.getByText('Muomala')).toBeInTheDocument()
    expect(screen.getByText('40/40')).toBeInTheDocument()
    expect(screen.getByText('Salomlashish')).toBeInTheDocument()
    expect(screen.getByText(t('rubric.balanced'))).toBeInTheDocument()
  })

  /**
   * `optional` is why a 30-second "send me 50 of them" call is not scored
   * against a full sales script. An admin who cannot see the flag cannot
   * explain the score it produced.
   */
  it('marks the criteria the model may leave out of the arithmetic', async () => {
    showing()

    await screen.findByText('Ehtiyojni aniqlash')
    expect(screen.getByText(t('rubric.optionalBadge'))).toBeInTheDocument()
  })

  it('names a red flag that zeroes the whole score instead of printing a penalty', async () => {
    showing()

    await screen.findByText('Haqorat')
    expect(screen.getByText(t('rubric.zeroesScore'))).toBeInTheDocument()
    expect(screen.getByText('-20')).toBeInTheDocument()
  })

  it('says when nothing has been published and the pinned rubric is scoring', async () => {
    showing(makeRubric({ stored: false, id: null, created_at: null }), makeVersions({ items: [], total: 0 }))

    expect(await screen.findByText(t('rubric.pinned'))).toBeInTheDocument()
    expect(screen.getByText(t('rubric.pinnedHint'))).toBeInTheDocument()
  })
})

describe('who may change it', () => {
  /**
   * **A non-admin cannot edit.** `settings:write` is admin-only in the server's
   * registry, and this is the panel half of that decision: no save button, no
   * edit affordance on a criterion, no way into the modal.
   */
  it('offers a manager nothing to press', async () => {
    signIn([Perm.ANALYSIS_READ])
    showing()

    expect(await screen.findByText(t('rubric.adminOnly'))).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: t('rubric.save') })).toBeNull()
    expect(screen.queryByRole('button', { name: t('rubric.addCriterion') })).toBeNull()
    expect(screen.queryByRole('button', { name: t('rubric.addFlag') })).toBeNull()
    // The criteria are still readable — that is the whole point of the page for
    // a manager — but not clickable.
    expect(screen.getByText('Salomlashish')).toBeInTheDocument()
  })

  it('gives an admin the save button, dead until anything has changed', async () => {
    showing()

    const save = await screen.findByRole('button', { name: t('rubric.save') })
    expect(save).toBeDisabled()
  })
})

describe('editing', () => {
  it('keeps the save button dead while the blocks do not total a hundred', async () => {
    showing()

    const [editFirstBlock] = await screen.findAllByRole('button', { name: t('rubric.editBlock') })
    expect(editFirstBlock).toBeDefined()
    await userEvent.click(editFirstBlock as HTMLElement)
    const max = await screen.findByLabelText(t('rubric.blockMax'))
    await userEvent.clear(max)
    await userEvent.type(max, '35')
    await userEvent.click(screen.getByRole('button', { name: t('common.save') }))

    // 35 + 35 + 25 = 95: the rubric changed, so the button would be alive on
    // "dirty" alone — and it must not be.
    expect(await screen.findByText(t('rubric.unbalanced'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('rubric.save') })).toBeDisabled()
  })

  it('publishes the whole rubric as a new version', async () => {
    const posted: { url: string; body: unknown }[] = []
    respond((url, init) => {
      if (init?.method === 'PUT') {
        posted.push({ url, body: JSON.parse(String(init.body)) })
        return jsonResponse(200, makeRubric({ version: 2, label: 'v2', name: 'Mezonlar v2' }))
      }
      if (url.includes('/rubric/versions')) return jsonResponse(200, makeVersions())
      return jsonResponse(200, makeRubric())
    })
    renderPage()

    // A change that keeps the blocks at 100 — the button is disabled otherwise,
    // and this test is about what gets SENT, not about the arithmetic.
    await userEvent.click(await screen.findByText('Salomlashish'))
    const label = await screen.findByLabelText(t('rubric.label'))
    await userEvent.clear(label)
    await userEvent.type(label, 'Salomlashish va tanishtirish')
    await userEvent.click(screen.getByRole('button', { name: t('common.save') }))

    await userEvent.click(await screen.findByRole('button', { name: t('rubric.save') }))
    await userEvent.click(await screen.findByRole('button', { name: t('rubric.publish') }))

    await waitFor(() => expect(posted).toHaveLength(1))
    const [sent] = posted
    expect(sent?.url).toContain('/api/v1/analysis/rubric')
    const body = sent?.body as {
      name: string
      blocks: { key: string; max: number; criteria: { label: string }[] }[]
      red_flags: unknown[]
      extra_rules: string | null
    }
    // The WHOLE rubric goes, not a patch: a rubric is saved in one piece,
    // because half a rubric is one whose blocks do not total 100.
    expect(body.name).toBe(t('rubric.versionNameDefault', { version: 2 }))
    expect(body.blocks).toHaveLength(3)
    expect(at(body.blocks, 0).key).toBe('script')
    expect(at(at(body.blocks, 0).criteria, 0).label).toBe('Salomlashish va tanishtirish')
    expect(body.red_flags).toHaveLength(2)
    expect(body.extra_rules).toBeNull()
  })

  /**
   * The rule that survived the port from BonviZvonki, seen from the panel: the
   * refusal carries a machine reason and its numbers, and the sentence lives in
   * `uz.json` — no payload and no column ever holds display copy.
   */
  it('renders the server refusal as its Uzbek sentence, with the numbers', async () => {
    respond((url, init) => {
      if (init?.method === 'PUT') {
        return jsonResponse(422, {
          error: {
            code: 'validation_error',
            message: "Ma'lumot noto'g'ri",
            request_id: '01J9',
            detail: { reason: 'rubric_total_not_100', total: 95, expected: 100 },
          },
        })
      }
      if (url.includes('/rubric/versions')) return jsonResponse(200, makeVersions())
      return jsonResponse(200, makeRubric())
    })
    renderPage()

    // A change the page considers publishable: rename a block, totals untouched.
    const [editFirstBlock] = await screen.findAllByRole('button', { name: t('rubric.editBlock') })
    expect(editFirstBlock).toBeDefined()
    await userEvent.click(editFirstBlock as HTMLElement)
    const label = await screen.findByLabelText(t('rubric.label'))
    await userEvent.clear(label)
    await userEvent.type(label, 'Skript va struktura')
    await userEvent.click(screen.getByRole('button', { name: t('common.save') }))

    await userEvent.click(await screen.findByRole('button', { name: t('rubric.save') }))
    await userEvent.click(await screen.findByRole('button', { name: t('rubric.publish') }))

    expect(
      await screen.findByText(
        t('rubric.invalid.rubric_total_not_100', { total: 95, expected: 100 }),
      ),
    ).toBeInTheDocument()
  })

  it('will not let a new red flag take a key another one already has', async () => {
    showing()

    await userEvent.click(await screen.findByRole('button', { name: t('rubric.addFlag') }))
    // The key is derived from the label, and `shouting` is already taken by the
    // flag the fixture calls "Baqirish". Two flags with one key would make the
    // prompt list it twice and the panel label the wrong one.
    await userEvent.type(await screen.findByLabelText(t('rubric.label')), 'Shouting')

    expect(await screen.findByText(t('rubric.flagKeyDuplicate'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('common.save') })).toBeDisabled()
  })
})

describe('the prompt and the history', () => {
  it('shows what the model receives, with only one section editable', async () => {
    showing()

    await userEvent.click(await screen.findByRole('button', { name: t('rubric.promptShow') }))

    expect(await screen.findByText(t('rubric.promptEditable'))).toBeInTheDocument()
    expect(screen.getAllByText(t('rubric.promptLocked'))).toHaveLength(2)
    expect(screen.getByText(t('rubric.promptNote'))).toBeInTheDocument()
  })

  it('lists every published version and offers to go back to an old one', async () => {
    const posted: string[] = []
    respond((url, init) => {
      if (init?.method === 'POST') {
        posted.push(url)
        return jsonResponse(200, makeRubric())
      }
      if (url.includes('/rubric/versions')) return jsonResponse(200, makeVersions())
      return jsonResponse(200, makeRubric({ version: 2, label: 'v2' }))
    })
    renderPage()

    await screen.findByText(t('rubric.history'))
    // The names rather than the labels: `v2` is also the badge in the header,
    // and a test that matched it there would pass with an empty history.
    expect(screen.getByText('Mezonlar v2')).toBeInTheDocument()
    expect(screen.getByText('Mezonlar v1')).toBeInTheDocument()
    expect(screen.getByText(t('rubric.activeBadge'))).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: t('rubric.restore') }))
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0] ?? '').toContain('/analysis/rubric/versions/1/activate')
  })

  it('offers a manager no way back to an old version', async () => {
    signIn([Perm.ANALYSIS_READ])
    showing()

    await screen.findByText(t('rubric.history'))
    expect(screen.queryByRole('button', { name: t('rubric.restore') })).toBeNull()
  })
})

describe('the three QueryBoundary states', () => {
  it('renders the skeleton before the response arrives', async () => {
    let release: ((response: Response) => void) | undefined
    // Only the rubric itself is held back. The version history answers at once,
    // so the skeleton that is still on screen afterwards can only be the one
    // this test is about.
    fetchMock.mockImplementation((input) => {
      if (String(input).includes('/rubric/versions')) {
        return Promise.resolve(jsonResponse(200, makeVersions()))
      }
      return new Promise<Response>((resolve) => {
        release = resolve
      })
    })

    renderPage()

    expect(screen.getByTestId('query-loading')).toBeInTheDocument()
    release?.(jsonResponse(200, makeRubric()))
    await waitFor(() => expect(screen.queryByTestId('query-loading')).toBeNull())
  })

  it('renders an error code from the envelope as its Uzbek sentence', async () => {
    respond(() =>
      jsonResponse(403, {
        error: { code: 'forbidden', message: 'Forbidden', request_id: '01J9' },
      }),
    )

    renderPage()

    expect(await screen.findByTestId('query-error')).toBeInTheDocument()
    expect(within(screen.getByTestId('query-error')).getByText(t('errors.forbidden'))).toBeInTheDocument()
    expect(screen.queryByText('Forbidden')).toBeNull()
  })

  it('says the history is empty rather than drawing an empty list', async () => {
    showing(makeRubric(), makeVersions({ items: [], total: 0 }))

    expect(await screen.findByTestId('query-empty')).toBeInTheDocument()
    expect(screen.getByText(t('rubric.historyEmpty'))).toBeInTheDocument()
  })
})
