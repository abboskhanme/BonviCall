/**
 * The Uzbek string catalogue (CONVENTIONS.md §14, CONVENTIONS-CLIENT.md §3).
 *
 * There is no i18n library and no second locale. Release 1 is Uzbek only, and
 * BonviZvonki's three-locale setup with `fallbackLng` is rejected here: its
 * `ru.json` and `en.json` rot. What is kept is the reason the catalogue exists
 * at all — strings stay out of components, so a second locale would later be a
 * file rather than a refactor.
 *
 * Keys are flat and dotted, `<module>.<thing>` (§12). Flat is deliberate: it
 * makes `MessageKey` a literal union, so a typo is a compile error rather than
 * a "nav.dashbord" rendered on screen.
 */
import uz from './uz.json'

export type MessageKey = keyof typeof uz

const CATALOGUE: Record<string, string> = uz

/** Values interpolated into `{name}` placeholders. */
export type MessageVars = Record<string, string | number>

/**
 * The Uzbek text for `key`.
 *
 * A missing key returns the key itself. That is deliberate and loud: an English
 * dotted identifier on screen is unmistakable in review, where a silent empty
 * string is not.
 */
export function t(key: MessageKey, vars?: MessageVars): string {
  const template = CATALOGUE[key] ?? key
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  )
}

/** Every key in the catalogue. Used by tests that assert completeness. */
export function messageKeys(): string[] {
  return Object.keys(CATALOGUE)
}
