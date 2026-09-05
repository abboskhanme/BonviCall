/**
 * Changing your own password.
 *
 * This existed as an endpoint and nothing reached it: `seed.py` and every
 * admin reset set `must_change_password`, so the flag was permanent and the
 * panel had no way to clear it. What is pinned here is the part that makes it
 * worth having rather than the form mechanics.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ChangePasswordModal } from '@/modules/auth/ChangePasswordModal'
import { useAuth } from '@/modules/auth/store'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderModal(forced = false, onOpenChange = () => {}) {
  const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ChangePasswordModal open onOpenChange={onOpenChange} forced={forced} />
    </QueryClientProvider>,
  )
}

function signIn(mustChange: boolean) {
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: 'user-1',
      email: 'admin@bonvi.uz',
      full_name: 'Administrator',
      role: 'admin',
      permissions: [],
      must_change_password: mustChange,
      agent_id: null,
    },
    permissions: new Set<string>(),
    loginError: null,
  })
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  signIn(true)
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('the form', () => {
  it('asks for the CURRENT password, which is what makes it self-service', () => {
    renderModal()
    // An admin does not have it and uses the reset on /users instead.
    expect(screen.getByLabelText(t('password.current'))).toBeInTheDocument()
  })

  it('refuses a new password under the minimum', async () => {
    renderModal()
    await userEvent.type(screen.getByLabelText(t('password.current')), 'oldpassword')
    await userEvent.type(screen.getByLabelText(t('password.next')), 'short')
    await userEvent.type(screen.getByLabelText(t('password.repeat')), 'short')
    expect(screen.getByRole('button', { name: t('password.action') })).toBeDisabled()
  })

  it('refuses a mismatched repeat, and says which field is wrong', async () => {
    renderModal()
    await userEvent.type(screen.getByLabelText(t('password.current')), 'oldpassword')
    await userEvent.type(screen.getByLabelText(t('password.next')), 'longenoughpassword')
    await userEvent.type(screen.getByLabelText(t('password.repeat')), 'longenoughpasswerd')
    expect(screen.getByText(t('password.mismatch'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('password.action') })).toBeDisabled()
  })

  it('says that every other session ends', () => {
    renderModal()
    // The reason this is the right response to "somebody may have seen it".
    expect(screen.getByText(t('password.revokesSessions'))).toBeInTheDocument()
  })

  it('sends both passwords and clears the flag on success', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, {}))
    renderModal()
    await userEvent.type(screen.getByLabelText(t('password.current')), 'oldpassword')
    await userEvent.type(screen.getByLabelText(t('password.next')), 'longenoughpassword')
    await userEvent.type(screen.getByLabelText(t('password.repeat')), 'longenoughpassword')
    await userEvent.click(screen.getByRole('button', { name: t('password.action') }))

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({
        current_password: 'oldpassword',
        new_password: 'longenoughpassword',
      })
    })
    // Otherwise the forced dialog reappears on the next render.
    await waitFor(() => expect(useAuth.getState().user?.must_change_password).toBe(false))
  })

  it('renders a wrong current password as its Uzbek sentence', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(401, { error: { code: 'unauthorized', message: 'bad' } }),
    )
    renderModal()
    await userEvent.type(screen.getByLabelText(t('password.current')), 'wrongpassword')
    await userEvent.type(screen.getByLabelText(t('password.next')), 'longenoughpassword')
    await userEvent.type(screen.getByLabelText(t('password.repeat')), 'longenoughpassword')
    await userEvent.click(screen.getByRole('button', { name: t('password.action') }))

    expect(await screen.findByText(t('errors.unauthorized'))).toBeInTheDocument()
  })
})

describe('a forced change', () => {
  it('cannot be dismissed', async () => {
    const onOpenChange = vi.fn()
    renderModal(true, onOpenChange)

    await userEvent.click(screen.getByRole('button', { name: t('common.cancel') }))

    // The one state where letting somebody past would leave an account on a
    // password an admin chose and typed into a chat.
    expect(onOpenChange).not.toHaveBeenCalledWith(false)
    expect(screen.getByText(t('password.forcedHint'))).toBeInTheDocument()
  })

  it('can be dismissed when it is voluntary', async () => {
    const onOpenChange = vi.fn()
    renderModal(false, onOpenChange)

    await userEvent.click(screen.getByRole('button', { name: t('common.cancel') }))
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
