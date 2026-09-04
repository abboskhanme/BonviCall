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
  'monitor',
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
