/**
 * The one small rule the account menu renders, kept out of the component.
 *
 * Not only for fast refresh, which is what eslint complains about: it is a
 * rule with edges — an empty name, one word, three words — and a rule that can
 * only be exercised by rendering a sidebar is a rule nobody tests.
 */

/**
 * `Aziz Karimov` → `AK`. Two letters, because three is a monogram and one is
 * ambiguous in a team where several names start with the same letter.
 *
 * Spread rather than indexed, so a name beginning with a character outside the
 * basic plane yields that character and not half of it.
 */
export function initialsOf(fullName: string): string {
  const words = fullName.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '?'
  return words
    .slice(0, 2)
    .map((word) => [...word][0] ?? '')
    .join('')
    .toUpperCase()
}
