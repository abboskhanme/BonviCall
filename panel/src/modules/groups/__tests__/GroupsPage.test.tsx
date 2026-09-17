/**
 * `/groups` — the page.
 *
 * What it must not get wrong:
 *
 *  1. opening the page issues ONE request — the tree. A closed node pulls no
 *     rows, which is the only reason a thousand groups is survivable;
 *  2. the groups nobody is bound to lead the page and are open by default:
 *     they receive nothing and nothing raises an error about it;
 *  3. the page says plainly that nothing is delivered, rather than reporting a
 *     send that did not happen;
 *  4. a reader without `numbers:write` gets no buttons.
 *
 * Plus the three `QueryBoundary` states, as CONVENTIONS-CLIENT.md §10 requires.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuth } from '@/modules/auth/store'
import { GroupsPage } from '@/modules/groups/GroupsPage'
import { tokenStore } from '@/shared/api/client'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'

import { AZIZ, makeGroup, makePage, makeTree } from './fixtures'

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function respond(handler: (url: string) => Response) {
  fetchMock.mockImplementation((input) => {
    const url =
      typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    return Promise.resolve(handler(url))
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
        initialEntries={['/groups']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <GroupsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function serving(tree = makeTree(), page = makePage()) {
  respond((url) => {
    if (url.includes('/groups/tree')) return jsonResponse(200, tree)
    if (url.includes('/groups')) return jsonResponse(200, page)
    if (url.includes('/agents')) return jsonResponse(200, { items: [], total: 0 })
    return jsonResponse(404, { error: { code: 'not_found', message: '', request_id: '' } })
  })
  return renderPage()
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  signIn([Perm.NUMBERS_READ, Perm.NUMBERS_WRITE, Perm.AGENTS_READ])
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
  useAuth.setState({ status: 'anonymous', user: null, permissions: new Set(), loginError: null })
})

describe('the three query states', () => {
  it('renders the loading skeleton first', () => {
    respond(() => jsonResponse(200, makeTree()))
    renderPage()
    expect(screen.getByTestId('query-loading')).toBeInTheDocument()
  })

  it('renders the error state when the tree fails', async () => {
    respond(() =>
      jsonResponse(500, {
        error: { code: 'internal_error', message: 'xatolik', request_id: 'r1' },
      }),
    )
    renderPage()
    expect(await screen.findByTestId('query-error')).toBeInTheDocument()
  })

  it('renders the empty state with an explanation when there are no groups', async () => {
    serving(makeTree({ agents: [], unassigned: { group_count: 0, response_count: 0 } }))
    expect(await screen.findByText(t('groups.empty'))).toBeInTheDocument()
    expect(screen.getByText(t('groups.emptyHint'))).toBeInTheDocument()
  })
})

describe('the page is honest about not sending anything', () => {
  it('leads with the banner', async () => {
    // ⚠️ There is no Telegram bot in this deployment. Saying so once at the
    // top beats a surprise on every button.
    serving()
    expect(await screen.findByText(t('groups.notDeliveredTitle'))).toBeInTheDocument()
  })
})

describe('scale', () => {
  it('pulls no group rows until a node is opened', async () => {
    serving()
    await screen.findByText('Aziz')

    const pulled = fetchMock.mock.calls
      .map(([input]) =>
        typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url,
      )
      // The tree, and the unbound bucket which is open by default. A closed
      // EMPLOYEE node must not have fetched anything.
      .filter((url) => url.includes('/groups?') && url.includes('agent_id='))
    expect(pulled).toHaveLength(0)
  })

  it('pulls that node only once it is opened', async () => {
    serving()
    const user = userEvent.setup()
    await user.click(await screen.findByText('Aziz'))

    await waitFor(() => {
      const pulled = fetchMock.mock.calls
        .map(([input]) =>
          typeof input === 'string'
            ? input
            : input instanceof URL
              ? input.toString()
              : input.url,
        )
        .filter((url) => url.includes(`agent_id=${AZIZ}`))
      expect(pulled.length).toBeGreaterThan(0)
    })
  })
})

describe('the groups nobody is bound to', () => {
  it('lead the page and are opened by default', async () => {
    // They receive nothing and nothing anywhere raises an error about it, so
    // putting them at the bottom would hide the one thing this page is for.
    serving()
    expect(await screen.findByText(t('groups.unassignedTitle'))).toBeInTheDocument()
    expect(screen.getByText(t('groups.unassignedHint'))).toBeInTheDocument()
  })

  it('are not shown at all when every group is bound', async () => {
    serving(makeTree({ unassigned: { group_count: 0, response_count: 0 } }))
    await screen.findByText('Aziz')
    expect(screen.queryByText(t('groups.unassignedTitle'))).not.toBeInTheDocument()
    expect(screen.getByText(t('groups.tileUnassignedOk'))).toBeInTheDocument()
  })
})

describe('write permission', () => {
  it('hides every action from a reader who only holds numbers:read', async () => {
    signIn([Perm.NUMBERS_READ])
    serving()
    await screen.findByText('Aziz')
    expect(screen.queryByText(t('groups.broadcast'))).not.toBeInTheDocument()
  })

  it('offers the broadcast to an admin', async () => {
    serving()
    expect(await screen.findByText(t('groups.broadcast'))).toBeInTheDocument()
  })
})

describe('the broadcast dialog', () => {
  it('warns that the window is ignored and that nothing is delivered', async () => {
    serving()
    const user = userEvent.setup()
    await user.click(await screen.findByText(t('groups.broadcast')))
    await waitFor(() =>
      expect(screen.getByText(t('groups.broadcastForce'))).toBeInTheDocument(),
    )
    // The bound count is what the confirm button offers, not the total.
    expect(
      screen.getByText(t('groups.broadcastCount', { count: '3' })),
    ).toBeInTheDocument()
  })

  it('accounts for every group in the outcome', async () => {
    // ⚠️ created + reused + skipped == total_groups. A partial answer sends
    // an admin to the list to count rows.
    const outcome = {
      created: 2,
      reused: 1,
      delivered: 0,
      total_groups: 4,
      skipped: [
        { group_id: 'g1', title: 'Mijoz 4', reason: 'group_not_bound' },
      ],
    }
    respond((url) => {
      if (url.includes('/groups/surveys/broadcast')) return jsonResponse(200, outcome)
      if (url.includes('/groups/tree')) return jsonResponse(200, makeTree())
      if (url.includes('/groups')) return jsonResponse(200, makePage())
      return jsonResponse(200, { items: [], total: 0 })
    })
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByText(t('groups.broadcast')))
    await user.click(
      await screen.findByText(t('groups.broadcastConfirm', { count: '3' })),
    )
    expect(
      await screen.findByText(
        t('groups.broadcastTotals', { total: 4, created: 2, reused: 1, skipped: 1 }),
      ),
    ).toBeInTheDocument()
    // And it says nothing actually went out.
    expect(screen.getAllByText(t('groups.notDeliveredHint')).length).toBeGreaterThan(0)
  })

  it('renders an unknown skip reason as the code rather than a blank badge', async () => {
    const outcome = {
      created: 0,
      reused: 0,
      delivered: 0,
      total_groups: 1,
      skipped: [{ group_id: 'g1', title: 'Mijoz', reason: 'some_new_reason' }],
    }
    respond((url) => {
      if (url.includes('/groups/surveys/broadcast')) return jsonResponse(200, outcome)
      if (url.includes('/groups/tree')) return jsonResponse(200, makeTree())
      if (url.includes('/groups')) return jsonResponse(200, makePage())
      return jsonResponse(200, { items: [], total: 0 })
    })
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByText(t('groups.broadcast')))
    await user.click(
      await screen.findByText(t('groups.broadcastConfirm', { count: '3' })),
    )
    expect(await screen.findByText('some_new_reason')).toBeInTheDocument()
  })
})

describe('a group row', () => {
  it('shows the manual badge so an admin can see which rows they hold', async () => {
    serving(
      makeTree({ unassigned: { group_count: 1, response_count: 0 } }),
      makePage({ items: [makeGroup({ bound_by: 'manual' })] }),
    )
    expect(await screen.findByText(t('groups.manual'))).toBeInTheDocument()
  })

  it('offers deletion only once the bot is out of the chat', async () => {
    serving(
      makeTree({ unassigned: { group_count: 1, response_count: 0 } }),
      makePage({ items: [makeGroup({ bot_status: 'member' })] }),
    )
    await screen.findByText('Mijoz 1')
    expect(screen.queryByLabelText(t('groups.delete'))).not.toBeInTheDocument()
  })

  it('offers deletion when the bot has been kicked', async () => {
    serving(
      makeTree({ unassigned: { group_count: 1, response_count: 0 } }),
      makePage({ items: [makeGroup({ bot_status: 'kicked' })] }),
    )
    expect(await screen.findByLabelText(t('groups.delete'))).toBeInTheDocument()
  })
})
