/**
 * `/users` — panel accounts.
 *
 * What is pinned is the distinction the SPEC is careful about and the two
 * guards that are easy to render as generic failures:
 *
 *  • a user is a LOGIN; the form says so and carries no agent-management
 *    controls at all;
 *  • `sales` forces an agent picker, because own-scope narrowing filters on
 *    `agent_id` and an account without one sees nothing or everything;
 *  • the last active admin cannot be removed — a panel with no admin can only
 *    be repaired from a shell;
 *  • you cannot deactivate or demote yourself.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { UsersPage } from '@/modules/users/UsersPage'
import { isLastActiveAdmin, type User } from '@/modules/users/api'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

const ME = 'user-admin'
const AGENT_ID = 'agent-1'

function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: 'user-1',
    email: 'manager@bonvi.uz',
    full_name: 'Manager Managerov',
    role: 'manager',
    agent_id: null,
    is_active: true,
    must_change_password: false,
    last_login_at: '2026-09-05T08:00:00+05:00',
    created_at: '2026-01-01T00:00:00+05:00',
    ...overrides,
  }
}

const admin = makeUser({ id: ME, email: 'admin@bonvi.uz', full_name: 'Administrator', role: 'admin' })
const sales = makeUser({
  id: 'user-sales',
  email: 'sales@bonvi.uz',
  full_name: 'Sales Salesov',
  role: 'sales',
  agent_id: AGENT_ID,
})

const agents = {
  items: [
    {
      id: AGENT_ID,
      full_name: 'Aziz Karimov',
      employee_code: 'BV-001',
      color: '#6366f1',
      hired_at: null,
      note: null,
      is_active: true,
      archived_at: null,
      created_at: '2025-01-01T00:00:00+05:00',
    },
  ],
  total: 1,
}

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function world(users: User[]) {
  fetchMock.mockImplementation((input) => {
    const url = String(input)
    if (url.includes('/api/v1/agents')) return Promise.resolve(jsonResponse(200, agents))
    if (url.includes('/api/v1/users')) {
      return Promise.resolve(jsonResponse(200, { items: users, total: users.length }))
    }
    return Promise.resolve(jsonResponse(200, {}))
  })
}

function signIn(permissions: string[]) {
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: ME,
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

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <UsersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  signIn([Perm.USERS_READ, Perm.USERS_WRITE, Perm.AGENTS_READ])
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('a user is a login, not a salesperson', () => {
  it('says so on the create form', async () => {
    world([admin])
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: t('users.create') }))
    expect(screen.getByText(t('users.createHint'))).toBeInTheDocument()
  })

  it('grows no number or enrolment controls — that lives on the agent page', async () => {
    world([admin, sales])
    renderPage()

    await screen.findByText('Sales Salesov')
    // The rollout belongs to the person, and the person lives on /agents/:id.
    expect(screen.queryByText(t('numbers.assign'))).toBeNull()
    expect(screen.queryByText(t('enrol.issue'))).toBeNull()
    expect(screen.queryByText(t('enrol.reissue'))).toBeNull()
  })

  it('links a sales account to the AGENT it points at', async () => {
    world([admin, sales])
    renderPage()

    const link = await screen.findByRole('link', { name: 'Aziz Karimov' })
    expect(link).toHaveAttribute('href', `/agents/${AGENT_ID}`)
  })

  it('forces an agent picker for a sales account', async () => {
    world([admin])
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: t('users.create') }))
    // Nothing to pick until the role asks for it.
    expect(screen.queryByLabelText(t('users.fieldAgent'))).toBeNull()

    await userEvent.selectOptions(screen.getByLabelText(t('users.fieldRole')), 'sales')
    expect(screen.getByLabelText(t('users.fieldAgent'))).toBeInTheDocument()
    expect(screen.getByText(t('users.agentHint'))).toBeInTheDocument()
  })

  it('refuses to submit a sales account with no agent', async () => {
    world([admin])
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: t('users.create') }))
    await userEvent.type(screen.getByLabelText(t('users.fieldEmail')), 'new@bonvi.uz')
    await userEvent.type(screen.getByLabelText(t('users.fieldName')), 'New Person')
    await userEvent.type(screen.getByLabelText(t('users.fieldPassword')), 'longenoughpassword')
    await userEvent.selectOptions(screen.getByLabelText(t('users.fieldRole')), 'sales')

    // The server answers 409 `sales_user_requires_agent`; the form does not
    // let it get that far.
    const submit = screen.getByRole('button', { name: t('common.save') })
    expect(submit).toBeDisabled()
  })
})

describe('the two guards', () => {
  it('marks the last active admin and explains why', async () => {
    world([admin, makeUser()])
    renderPage()

    const rows = await screen.findAllByRole('row')
    const mine = rows.find((row) => row.textContent?.includes('Administrator'))
    expect(mine).toBeDefined()
    // Marked inline beside the name, which costs the row no height.
    expect(mine?.textContent).toContain(t('users.lastAdminShort'))

    // Locked twice over here — my own account AND the last admin — and both
    // reasons travel on the control's `title` rather than as a caption that
    // wrapped the row onto four lines.
    const edit = within(mine as HTMLElement).getByRole('button', { name: t('users.edit') })
    expect(edit).toHaveAttribute('title', expect.stringContaining(t('users.lastAdminLocked')))
    expect(edit).toHaveAttribute('title', expect.stringContaining(t('users.selfLocked')))
  })

  it('keeps every row the same height', async () => {
    world([admin, makeUser(), sales])
    renderPage()

    await screen.findByText('Sales Salesov')
    const rows = screen.getAllByRole('row').slice(1)
    // The Administrator row carried a four-line caption under its buttons and
    // was roughly three times the height of its neighbours; the table stopped
    // looking like a table. Nothing in a cell may wrap onto a second line.
    for (const row of rows) {
      expect(row.textContent).not.toContain(t('users.selfLocked'))
      expect(row.textContent).not.toContain(t('users.lastAdminLocked'))
    }
  })

  it('marks the last admin even when it is somebody else', async () => {
    const other = makeUser({ id: 'user-other', role: 'admin', full_name: 'Other Admin' })
    // I am a manager here, so the lock is purely the last-admin rule.
    world([other, makeUser({ id: ME, role: 'manager', full_name: 'Administrator' })])
    renderPage()

    const rows = await screen.findAllByRole('row')
    const theirs = rows.find((row) => row.textContent?.includes('Other Admin'))
    expect(theirs).toBeDefined()
    expect(theirs?.textContent).toContain(t('users.lastAdminShort'))

    const edit = within(theirs as HTMLElement).getByRole('button', { name: t('users.edit') })
    expect(edit).toHaveAttribute('title', t('users.lastAdminLocked'))
  })

  it('stops marking one once a second admin exists', async () => {
    world([admin, makeUser({ id: 'user-2', role: 'admin', full_name: 'Second Admin' })])
    renderPage()

    await screen.findByText('Second Admin')
    expect(screen.queryByText(t('users.lastAdminLocked'))).toBeNull()
  })

  it('will not let you reset your own password from here', async () => {
    world([admin, makeUser()])
    renderPage()

    const rows = await screen.findAllByRole('row')
    const mine = rows.find((row) => row.textContent?.includes('Administrator'))
    expect(mine).toBeDefined()
    // Doing it here would sign you out mid-session; /auth/password is the
    // route for that and it asks for the current password.
    expect(
      within(mine as HTMLElement).getByRole('button', { name: t('users.reset') }),
    ).toBeDisabled()
  })

  it('does not offer to demote or deactivate yourself', async () => {
    world([admin, makeUser({ id: 'user-2', role: 'admin' })])
    renderPage()

    const rows = await screen.findAllByRole('row')
    const mine = rows.find((row) => row.textContent?.includes('Administrator'))
    await userEvent.click(within(mine as HTMLElement).getByRole('button', { name: t('users.edit') }))

    expect(screen.getByLabelText(t('users.fieldRole'))).toBeDisabled()
    expect(screen.getByText(t('users.cannotDeactivateSelf'))).toBeInTheDocument()
  })
})

describe('isLastActiveAdmin', () => {
  it('counts only ACTIVE admins', () => {
    const inactive = makeUser({ id: 'x', role: 'admin', is_active: false })
    // A deactivated admin cannot repair the panel, so it does not count.
    expect(isLastActiveAdmin([admin, inactive], admin)).toBe(true)
    expect(isLastActiveAdmin([admin, makeUser({ id: 'y', role: 'admin' })], admin)).toBe(false)
  })

  it('says nothing about a manager or a deactivated admin', () => {
    expect(isLastActiveAdmin([admin], makeUser())).toBe(false)
    const inactive = makeUser({ id: 'x', role: 'admin', is_active: false })
    expect(isLastActiveAdmin([inactive], inactive)).toBe(false)
  })
})

describe('states', () => {
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

  it('renders no write control without users:write', async () => {
    signIn([Perm.USERS_READ])
    world([admin])
    renderPage()

    await screen.findByText('Administrator')
    expect(screen.queryByRole('button', { name: t('users.create') })).toBeNull()
    expect(screen.queryByRole('button', { name: t('users.edit') })).toBeNull()
  })
})
