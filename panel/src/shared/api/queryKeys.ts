/**
 * The query-key convention, stated once (CONVENTIONS.md §12).
 *
 *     ['<module>', '<slice>', params]
 *
 * A mutation invalidates the whole module: `invalidateQueries({ queryKey:
 * moduleKey('calls') })` (CONVENTIONS-CLIENT.md §2). That is why the module
 * name is the first element and why it is a closed union — an invalidation
 * that misses because the key was spelled `'call'` is silent, and the user just
 * sees stale data.
 */
export const QUERY_MODULES = [
  'auth',
  'dashboard',
  'enrolment',
  'agents',
  'numbers',
  'installations',
  'devices',
  'commands',
  'calls',
  'audio',
  'alerts',
  'reports',
  'audit',
  'users',
  'settings',
  'appversions',
  // The panel's `analysis` module reads the server's `analysis` module one to
  // one (SPEC-ANALYTICS §7.2). The run mutation invalidates the whole module,
  // so the list, the call and the queue page never disagree about a stage.
  'analysis',
  // The rubric is a module of the panel's own — a page with its own state and
  // its own modal — reading the server's `analysis` module (§2.5). Its own key
  // rather than a slice of `analysis`: publishing a version changes nothing
  // about the scores already produced, and invalidating them would refetch
  // three pages to show the same numbers.
  'rubric',
  // The activity report: volume and answerability over a window, read from the
  // server's `activity` module one to one. It owns no mutation, so nothing
  // invalidates this key today — it is here because a key outside the closed
  // union does not compile, which is the point of the union.
  'activity',
  // The analytics dashboard: six aggregates over the scores, read from the
  // server's `analytics` module one to one. Six queries share one filter, so
  // they share one module key and the whole page moves together when the
  // window changes. Read-only, like `activity`.
  'analytics',
] as const

export type QueryModule = (typeof QUERY_MODULES)[number]

/** Parameters that identify a slice. Serialisable only — TanStack Query hashes it. */
export type QueryParams = Record<string, unknown>

/** The key every list, detail and aggregate query is built from. */
export function queryKey(
  module: QueryModule,
  slice: string,
  params?: QueryParams,
): readonly unknown[] {
  return params === undefined ? [module, slice] : [module, slice, params]
}

/** The key a mutation invalidates: everything the module owns. */
export function moduleKey(module: QueryModule): readonly [QueryModule] {
  return [module]
}
