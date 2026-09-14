/**
 * Which build to put first on the public download page.
 *
 * A salesperson standing on that page does not know what `targetSdk` is, so
 * the page has to choose and then let them override. The rule is the one the
 * server-rendered install page already uses (`enrolment/landing.py`): Android
 * 13 and above takes `modern34`, everything else `legacy28`.
 *
 * Rough on purpose, and cheap when wrong: both builds are always offered, so a
 * bad guess costs a tap on the other card rather than a failed install. The
 * fallback is `legacy28` because that is what the fleet actually runs, and
 * because a desktop browser — where an admin looks at this page — matches
 * nothing here.
 *
 * Its own file so `LandingPage.tsx` exports components and nothing else.
 */
export type Variant = 'legacy28' | 'modern34'

export function preferredVariant(userAgent: string): Variant {
  const match = /Android\s+(\d+)/i.exec(userAgent)
  if (!match) return 'legacy28'
  return Number(match[1]) >= 13 ? 'modern34' : 'legacy28'
}
