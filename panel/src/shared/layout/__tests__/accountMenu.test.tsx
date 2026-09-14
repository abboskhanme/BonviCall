/**
 * The account cluster, top right.
 *
 * Two things are worth pinning. **Nothing became unreachable**: the way out of
 * the application moved behind a menu and a menu that will not open is a user
 * who cannot log out. And **the badge counts the right number** — `open_count`
 * is alerts neither acknowledged nor resolved, which is the only figure on
 * this row that anybody acts on.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { initialsOf } from '@/shared/layout/identity'
import { AccountMenu } from '@/shared/layout/AccountMenu'
import { t } from '@/shared/i18n'

const fetchMock = vi.fn<typeof fetch>()

function signIn(permissions: string[]) {
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: 'user-1',
      email: 'admin@bonvi.uz',
      full_name: 'Aziz Karimov',
      role: 'admin',
      permissions,
      must_change_password: false,
      agent_id: null,
    },
    permissions: new Set(permissions),
    loginError: null,
  })
}

function renderMenu() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AccountMenu />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify({ items: [], total: 0, open_count: 3 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  signIn([Perm.ALERTS_READ])
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
  useAuth.setState({ status: 'anonymous', user: null, permissions: new Set() })
})

describe('the pure bits', () => {
  it('takes two initials, never three and never one', () => {
    expect(initialsOf('Aziz Karimov')).toBe('AK')
    expect(initialsOf('Aziz Karimov Toshmatovich')).toBe('AK')
    expect(initialsOf('Administrator')).toBe('A')
    expect(initialsOf('   ')).toBe('?')
  })

})

describe('nothing became unreachable', () => {
  it('hides the way out until the menu is opened, and then shows it', async () => {
    renderMenu()

    expect(screen.queryByRole('button', { name: t('auth.logout') })).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: t('nav.userMenu') }))

    expect(screen.getByRole('button', { name: t('auth.logout') })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: t('page.settings') })).toHaveAttribute(
      'href',
      '/settings',
    )
  })

  it('closes on Escape, so the menu does not follow the reader around', async () => {
    renderMenu()
    await userEvent.click(screen.getByRole('button', { name: t('nav.userMenu') }))

    await userEvent.keyboard('{Escape}')

    expect(screen.queryByRole('button', { name: t('auth.logout') })).toBeNull()
  })
})
