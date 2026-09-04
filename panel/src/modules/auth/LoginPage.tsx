/**
 * Login. Public, outside the shell.
 *
 * Errors come from the N35 envelope through the Uzbek catalogue
 * (`messageForError`), never from a raw English string (SPEC §5.3, T100).
 */
import { useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { landingPath } from '@/shared/auth/landing'
import { t } from '@/shared/i18n'
import { Button, Card, Input, Label } from '@/shared/ui/primitives'

import { useAuth } from './store'

interface FromState {
  from?: { pathname?: string }
}

export function LoginPage() {
  const { status, loginError, login } = useAuth()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fieldError, setFieldError] = useState<string | null>(null)

  // Where the user was when the session ended, so a mid-session expiry returns
  // them to the page they were reading. With no such page, `landingPath` picks
  // one. Since the TV board was removed that is always the dashboard, but the
  // question is still asked in one place rather than hard-coded at two.
  const state = location.state as FromState | null
  const target = state?.from?.pathname ?? landingPath()

  if (status === 'authenticated') return <Navigate to={target} replace />

  const submitting = status === 'loading'

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!email.trim()) {
      setFieldError(t('auth.emailRequired'))
      return
    }
    if (!password) {
      setFieldError(t('auth.passwordRequired'))
      return
    }
    setFieldError(null)
    void login(email.trim(), password)
  }

  return (
    <main className="grid min-h-screen place-items-center bg-bg p-6">
      <Card className="w-full max-w-sm p-6">
        <h1 className="text-lg font-semibold text-text">{t('auth.loginTitle')}</h1>
        <p className="mt-1 text-xs text-muted">{t('auth.loginSubtitle')}</p>

        <form className="mt-5 space-y-4" onSubmit={onSubmit} noValidate>
          <div className="space-y-1">
            <Label htmlFor="email">{t('auth.email')}</Label>
            <Input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={submitting}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="password">{t('auth.password')}</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={submitting}
            />
          </div>

          {fieldError ?? loginError ? (
            <p role="alert" className="text-xs text-bad">
              {fieldError ?? loginError}
            </p>
          ) : null}

          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? t('auth.submitting') : t('auth.submit')}
          </Button>
        </form>
      </Card>
    </main>
  )
}
