/**
 * Which server filter one search box becomes.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * The call list used to carry two boxes — "contact name" (`q`, an ILIKE over
 * `contact_name`) and "by number" (`remote_number`) — and made the reader
 * choose. People do not think in two boxes; they think "find this call" and
 * type either a name or a number. So the panel now shows one box and decides
 * which of the two parameters it becomes. **The server is unchanged and still
 * takes both** (SPEC §4.7) — the choice is the panel's, and it is this file.
 *
 * It lives on its own, as a pure function, because it is a RULE: it has cases,
 * the cases have edges, and a rule that can only be exercised by rendering a
 * page is a rule nobody tests (CONVENTIONS.md §0 makes the same call for the
 * server's `rules.py`). `__tests__/search.test.ts` covers the edges, the
 * threshold included — an explained constant that no test pins is a constant
 * the next person will change by accident.
 * ═══════════════════════════════════════════════════════════════════════════
 */

/** The two shapes `GET /calls` accepts for "find this call". */
export type CallSearchParam = { q: string } | { remote_number: string }

/**
 * What a number may be typed with.
 *
 * Digits, the punctuation people paste (`+998 90 111-22-33`, `(90) 111 22 33`)
 * **and `*` / `#`**, because a PBX extension is dialled `*700` and is a number
 * the list can genuinely find. One letter anywhere and this is a name — which
 * is what makes `A1` a name and `700` a number.
 */
const PHONE_SHAPED = /^[+*#\d\s()\-.]+$/

/**
 * How many digits before a numeric string is read as a number rather than a
 * name: one. No letters and at least one digit means a number.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * This is set by what the SERVER actually does, which is two branches, not one
 * (`modules/calls/service.py`):
 *
 *   phone_key(input) is not None   →  match on `remote_number_key`, the last
 *                                     9 digits. Real phone numbers.
 *   phone_key(input) is None       →  match `remote_number` EXACTLY, raw
 *                                     string against raw string. This is the
 *                                     branch that finds extension calls —
 *                                     `700`, `*700` — which `core/phone.py::
 *                                     is_extension` deliberately gives no key.
 *
 * An earlier version of this rule required four digits, on the theory that the
 * key branch was the only one. It wasn't, and the cost was concrete: `700` and
 * `*700` went to the contact-name search and found nothing, so extension calls
 * became unfindable — on a product whose line directory exists to classify
 * exactly those lines.
 *
 * The trade, stated so nobody re-litigates it silently: a contact-name search
 * for a string of pure digits no longer works. That is the right way round. A
 * contact called `700` is not a thing; a call to extension `700` is a thing,
 * and there are thousands of them.
 * ═══════════════════════════════════════════════════════════════════════════
 */
const MIN_PHONE_DIGITS = 1

/**
 * `"90 111 22 33"` → `{ remote_number }`, `"*700"` → `{ remote_number }`,
 * `"Aziz Karimov"` → `{ q }`, `"   "` → `null` (no filter at all).
 *
 * The value is passed on as it was typed, spacing and all: the server runs it
 * through `phone_key`, so `+998 93 555-44-33` and `935554433` find the same
 * calls, and the exact branch needs the raw string it was given. Normalising
 * it here would be the same rule written twice, and one copy would drift.
 */
export function searchParamFor(input: string): CallSearchParam | null {
  const text = input.trim()
  if (text === '') return null

  const digits = text.replace(/\D/g, '')
  if (PHONE_SHAPED.test(text) && digits.length >= MIN_PHONE_DIGITS) {
    return { remote_number: text }
  }
  return { q: text }
}
