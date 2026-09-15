/**
 * The one call the public front page makes — TanStack Query only
 * (CONVENTIONS-CLIENT.md §1).
 *
 * `GET /api/v1/app/latest` is in `PUBLIC_ROUTES`, so this runs with no token
 * and must keep running with no token: the whole point of the page is that a
 * salesperson who has never had an account can install the app. `api.get`
 * simply sends no `Authorization` header when the store holds nothing, and
 * the refresh-on-401 path is never reached because the endpoint does not
 * answer 401.
 *
 * An empty `items` is a real answer — a server with no published build — and
 * the page says so rather than rendering a button that goes nowhere.
 */
import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'

import { api } from '@/shared/api/client'
import { queryKey } from '@/shared/api/queryKeys'
import type { components } from '@/shared/api/types.gen'

export type PublicRelease = components['schemas']['PublicReleaseResponse']
export type PublicReleaseList = components['schemas']['PublicReleaseListResponse']

/** Where the bytes come from. Public too (SPEC §4.1 rule 5), and a plain
 *  browser navigation rather than a fetch: the response is a 30 MB stream with
 *  a `Content-Disposition`, and the browser's own downloader handles that
 *  better than anything this page could do with a blob. */
export function downloadPath(release: PublicRelease): string {
  // The VARIANT is what makes this unambiguous. Both flavours of one release
  // carry the same version code (SPEC §7.2), so the code alone named two
  // files and the server handed back whichever row it found first — the
  // "Android 13 va undan yuqori" card offered the legacy build as often as
  // not. Both install, so nothing looked wrong; what was lost is the reason
  // the flavours exist at all (S1: targetSdk decides the recording route).
  return `/api/v1/app/download/${release.version_code}?variant=${release.variant}`
}

export function useLatestReleases(): UseQueryResult<PublicReleaseList> {
  return useQuery({
    queryKey: queryKey('appversions', 'latest'),
    queryFn: () => api.get<PublicReleaseList>('/app/latest'),
    // The front page is not a dashboard; a build appears when somebody
    // publishes one, which is not something to poll for.
    refetchInterval: false,
    staleTime: 60_000,
  })
}
