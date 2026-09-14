/**
 * The account cluster, top right: theme, alerts, and the person's own name.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * It began as six stacked rows at the bottom of the sidebar — a theme toggle,
 * a name, an e-mail, "change password", "log out", "collapse" — full-width
 * controls for things somebody touches once a month, directly under the menu
 * they use all day. The client asked for it shortened and then moved, and both
 * asks point at the same convention: identity sits top right, the two things
 * you glance at stay visible, and everything else goes behind your own name.
 *
 * It carried an alert bell for a few hours on 2026-09-14 and the client took
 * it out again: Ogohlantirishlar is a menu entry people open deliberately, and
 * a count that follows the reader onto every page is a notification, which is
 * not what this product is.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronUp, LogOut, Moon, Settings, SunMedium } from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { t, type MessageKey } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { useTheme, type Theme } from '@/shared/theme/store'
import { Button } from '@/shared/ui/primitives'

import { initialsOf } from './identity'

const THEME_ICON = { light: SunMedium, dark: Moon } as const
const THEME_LABEL: Record<Theme, MessageKey> = {
  light: 'theme.light',
  dark: 'theme.dark',
}

/** Icon only, because the top bar is a strip and not a menu. */
function ThemeButton() {
  const { theme, setTheme } = useTheme()
  // Two modes since 2026-09-14, so this is a toggle and no longer a cycle —
  // the fallback is the other one, not a third state that stopped existing.
  const next: Theme = theme === 'dark' ? 'light' : 'dark'
  const Icon = THEME_ICON[theme]
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      title={t('theme.label')}
      aria-label={t(THEME_LABEL[theme])}
      className="grid size-8 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-text"
    >
      <Icon className="size-4" aria-hidden />
    </button>
  )
}

export function AccountMenu() {
  const user = useAuth((state) => state.user)
  const logout = useAuth((state) => state.logout)
  const [open, setOpen] = useState(false)
  const holder = useRef<HTMLDivElement>(null)

  // A menu that only closes on its own items is a menu that follows the reader
  // around the page. Escape and a click elsewhere both close it.
  useEffect(() => {
    if (!open) return
    function onDocument(event: MouseEvent) {
      if (!holder.current?.contains(event.target as Node)) setOpen(false)
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocument)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocument)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (user === null) return null

  return (
    <div ref={holder} className="relative flex items-center gap-1">
      <ThemeButton />
      <span className="mx-1 h-6 w-px shrink-0 bg-border" aria-hidden />
      <button
        type="button"
        aria-label={t('nav.userMenu')}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-w-0 items-center gap-2 rounded-md px-1 py-1 text-start hover:bg-surface-2"
      >
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-accent-soft text-2xs font-bold text-accent">
          {initialsOf(user.full_name)}
        </span>
        {/* The name is hidden on a narrow screen and the avatar is not: the
            cluster has to survive a phone-width top bar, and an avatar with no
            name is still recognisably "you". */}
        {/* The name alone since 2026-09-14: the e-mail under it was the
            login, and the client wanted it off every screen. Hidden below
            `sm`, where the avatar carries the identity by itself. */}
        <span className="hidden max-w-40 truncate text-xs font-medium text-text sm:block">
          {user.full_name}
        </span>
        <ChevronUp
          className={cn('size-4 shrink-0 text-muted transition-transform', !open && 'rotate-180')}
          aria-hidden
        />
      </button>

      {open ? (
        <div className="absolute end-0 top-full z-30 mt-1 min-w-52 rounded-lg border border-border bg-surface p-1 shadow-soft">
          {/* Settings, not "change password": the password is one thing you
              do to your own account, and it now has a page rather than a
              modal with no home. */}
          <Link
            to="/settings"
            onClick={() => setOpen(false)}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-text hover:bg-surface-2"
          >
            <Settings className="size-4 shrink-0" aria-hidden />
            <span className="truncate">{t('page.settings')}</span>
          </Link>
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start text-bad"
            onClick={() => {
              setOpen(false)
              void logout()
            }}
          >
            <LogOut className="size-4 shrink-0" aria-hidden />
            <span>{t('auth.logout')}</span>
          </Button>
        </div>
      ) : null}
    </div>
  )
}
