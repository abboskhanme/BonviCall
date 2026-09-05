/**
 * The line directory (UC-25).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * This is what makes a call internal, and it fails by starving rather than by
 * breaking. BonviZvonki's had 10 of 33 employees in it: twenty-three people's
 * internal calls were filed as external, every "external volume" figure was
 * wrong, and nothing anywhere said so — the error looks like more business.
 *
 * Ours starts empty, so the two things pinned here are the warning that says
 * so, and the count of calls a rule rewrites. A directory edit is not a
 * preference; it is a correction applied backwards to calls that already
 * happened, and the receipt is what makes that visible.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LineDirectorySection } from '@/modules/lineDirectory/LineDirectorySection'
import { ruleExample } from '@/modules/lineDirectory/api'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

const fetchMock = vi.fn<typeof fetch>()

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const ENTRY = {
  id: 'entry-1',
  kind: 'suffix' as const,
  pattern: '700',
  label: 'Ofis',
  is_active: true,
  created_at: '2026-09-05T09:00:00+05:00',
}

function server(entries: unknown[], reclassified = 12) {
  fetchMock.mockImplementation((_input, init) => {
    const method = init?.method ?? 'GET'
    if (method === 'POST' || method === 'DELETE') {
      return Promise.resolve(json(201, { entry: ENTRY, calls_reclassified: reclassified }))
    }
    return Promise.resolve(json(200, { items: entries, total: entries.length }))
  })
}

function signIn(permissions: string[]) {
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: 'user-1',
      email: 'admin@bonvi.uz',
      full_name: 'Administrator',
      role: 'admin',
      permissions,
      must_change_password: false,
      agent_id: null,
    },
    permissions: new Set(permissions),
    loginError: null,
  })
}

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <LineDirectorySection />
    </QueryClientProvider>,
  )
}

async function expand() {
  await userEvent.click(screen.getByRole('button', { name: new RegExp(t('lineDirectory.title')) }))
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  signIn([Perm.SETTINGS_READ, Perm.SETTINGS_WRITE])
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('starvation is the failure mode', () => {
  it('says so when the directory is empty', async () => {
    server([])
    renderSection()
    await expand()

    // Nothing breaks when this list is empty — every internal call is simply
    // filed as external, and the number that comes out looks like more
    // business rather than like a bug.
    expect(await screen.findByText(t('lineDirectory.emptyWarning'))).toBeInTheDocument()
  })

  it('stops warning once a rule exists', async () => {
    server([ENTRY])
    renderSection()
    await expand()

    await screen.findByText('…700')
    expect(screen.queryByText(t('lineDirectory.emptyWarning'))).toBeNull()
  })
})

describe('a change rewrites calls that already happened', () => {
  it('reports how many were reclassified', async () => {
    server([], 12)
    renderSection()
    await expand()
    await screen.findByText(t('lineDirectory.emptyWarning'))

    await userEvent.type(screen.getByLabelText(t('lineDirectory.fieldPattern')), '700')
    await userEvent.click(screen.getByRole('button', { name: t('lineDirectory.add') }))

    // The receipt: a directory edit is a correction applied backwards.
    expect(
      await screen.findByText(t('lineDirectory.reclassified', { n: '12' })),
    ).toBeInTheDocument()
  })

  it('sends digits only, whatever was typed', async () => {
    server([])
    renderSection()
    await expand()
    await screen.findByText(t('lineDirectory.emptyWarning'))

    await userEvent.type(screen.getByLabelText(t('lineDirectory.fieldPattern')), '*700-x')
    await userEvent.click(screen.getByRole('button', { name: t('lineDirectory.add') }))

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
      expect(JSON.parse(String(post?.[1]?.body)).pattern).toBe('700')
    })
  })
})

describe('the rule is legible before it is saved', () => {
  it('shows what it will match', async () => {
    server([])
    renderSection()
    await expand()
    await screen.findByText(t('lineDirectory.emptyWarning'))

    await userEvent.type(screen.getByLabelText(t('lineDirectory.fieldPattern')), '700')
    // "Suffix" is jargon; `…700` is not. The hint line also carries the
    // kind's own sentence, so this asserts on the page text rather than
    // hunting for a node that holds the phrase exactly.
    expect(document.body.textContent).toContain(
      t('lineDirectory.willMatch', { example: '…700' }),
    )
    expect(document.body.textContent).toContain(t('lineDirectory.kindSuffixHint'))
  })

  it('renders each kind distinctly', () => {
    expect(ruleExample('exact', '700')).toBe('700')
    expect(ruleExample('prefix', '700')).toBe('700…')
    expect(ruleExample('suffix', '700')).toBe('…700')
  })
})

describe('permissions', () => {
  it('renders nothing at all without settings:read', () => {
    signIn([Perm.AGENTS_READ])
    const { container } = renderSection()
    // The roster page is gated on `agents:read`, which is wider than this.
    expect(container).toBeEmptyDOMElement()
  })

  it('offers no add form without settings:write', async () => {
    signIn([Perm.SETTINGS_READ])
    server([ENTRY])
    renderSection()
    await expand()

    await screen.findByText('…700')
    expect(screen.queryByRole('button', { name: t('lineDirectory.add') })).toBeNull()
    expect(screen.queryByRole('button', { name: t('lineDirectory.remove') })).toBeNull()
  })
})
