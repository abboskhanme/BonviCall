/**
 * The theme store — the second and last zustand store (CONVENTIONS-CLIENT.md §2).
 *
 * **Two modes, light and dark.** A third, "system", was the default until
 * 2026-09-14 and the client asked for it to go: on a panel somebody keeps open
 * all day, a theme that changes itself at sunset is a surprise, not a feature.
 *
 * What survives from it is the only part that was worth keeping — the FIRST
 * visit still follows the operating system, because guessing light for
 * somebody whose machine is dark is a worse first impression than asking
 * nothing. After that the choice is theirs and it sticks.
 *
 * `data-theme` is now always written, which means the `dark:` variant would
 * finally work; it is still not used, because every colour in this panel comes
 * from a token and a component that reaches past them is the drift the tokens
 * exist to prevent.
 */
import { create } from 'zustand'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'bonvicall.theme'

/** What the machine prefers, for a visitor who has never chosen. */
function preferred(): Theme {
  if (typeof matchMedia === 'undefined') return 'light'
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function readStored(): Theme {
  if (typeof localStorage === 'undefined') return preferred()
  const value = localStorage.getItem(STORAGE_KEY)
  // `'system'` is read here on purpose: it is what everybody who used the
  // panel before today has in their browser, and it must resolve rather than
  // fall through to a default that ignores their machine.
  if (value === 'light' || value === 'dark') return value
  return preferred()
}

function apply(theme: Theme): void {
  if (typeof document === 'undefined') return
  document.documentElement.setAttribute('data-theme', theme)
}

interface ThemeState {
  theme: Theme
  setTheme: (theme: Theme) => void
}

export const useTheme = create<ThemeState>((set) => ({
  theme: readStored(),
  setTheme: (theme) => {
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, theme)
    apply(theme)
    set({ theme })
  },
}))

/** Apply the stored theme before the first paint. Called from main.tsx. */
export function initTheme(): void {
  apply(readStored())
}
