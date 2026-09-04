/**
 * The theme store — the second and last zustand store (CONVENTIONS-CLIENT.md §2).
 *
 * Three modes, and "system" is the default. In system mode NO `data-theme`
 * attribute is written: the CSS media query in index.css decides. That is
 * exactly why components never use the `dark:` variant — in the default mode
 * there is no attribute for it to key off, so it would be dead code.
 */
import { create } from 'zustand'

export type Theme = 'system' | 'light' | 'dark'

const STORAGE_KEY = 'bonvicall.theme'

function readStored(): Theme {
  if (typeof localStorage === 'undefined') return 'system'
  const value = localStorage.getItem(STORAGE_KEY)
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'system'
}

function apply(theme: Theme): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  if (theme === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme)
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
