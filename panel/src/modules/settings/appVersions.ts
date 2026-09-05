/**
 * APK distribution — TanStack Query hooks only (CONVENTIONS-CLIENT.md §1).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * BonviCall is not distributed through Google Play (N33). It is a signed APK
 * served from Bonvi's own host and side-loaded onto ~15 handsets **the company
 * does not own**, which makes two things on this page unusually consequential:
 *
 * **The signing key.** Android refuses an update signed by a different key,
 * and with no store to re-publish through the only remedy is
 * uninstall-and-reinstall on every phone — which destroys each one's unsent
 * upload queue (`docs/APK-SIGNING.md`). That is why the SHA-256 is shown, why
 * it is computed server-side and never accepted from the client, and why
 * `signing_sha256_configured: false` is worth a banner rather than a footnote.
 *
 * **The minimum version.** Raising it strands every handset below it: the
 * phone drains its queue, is refused with 426, and stays refused until
 * somebody physically reaches that salesperson (N34, UC-28). On personal
 * phones that is a decision about people's afternoons, not a config change.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api } from '@/shared/api/client'
import { moduleKey, queryKey } from '@/shared/api/queryKeys'
import type { components } from '@/shared/api/types.gen'

export type AppVersion = components['schemas']['AppVersionResponse']
export type AppVersionList = components['schemas']['AppVersionListResponse']
export type VersionGateImpact = components['schemas']['VersionGateImpactResponse']
export type StrandedInstallation = components['schemas']['StrandedInstallationOut']
export type SetMinimumVersionRequest = components['schemas']['SetMinimumVersionRequest']
export type SetMinimumVersionResponse = components['schemas']['SetMinimumVersionResponse']
export type UploadRelease = components['schemas']['UploadReleaseResponse']
export type AppVariant = components['schemas']['AppVariant']

export function useAppVersions(): UseQueryResult<AppVersionList> {
  return useQuery({
    queryKey: queryKey('appversions', 'list'),
    queryFn: () => api.get<AppVersionList>('/app/versions'),
  })
}

export interface UploadFields {
  apk: File
  version: string
  version_code: number
  variant: AppVariant
  min_api_level?: number
  is_mandatory?: boolean
  release_notes_uz?: string
}

/**
 * Upload a build.
 *
 * Multipart, through `api.postForm`, which does **not** set `Content-Type` —
 * the browser must, because `multipart/form-data` carries a `boundary=` only
 * it knows. Writing the header by hand drops the boundary and the server
 * reports it as "field required", i.e. "I sent a file, but there is no file"
 * (CONVENTIONS-CLIENT.md §2).
 *
 * The SHA-256 is not sent: the server computes it from the bytes it received,
 * which is the only version of that number worth having.
 */
export function useUploadVersion(): UseMutationResult<UploadRelease, unknown, UploadFields> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (fields: UploadFields) => {
      const form = new FormData()
      form.append('apk', fields.apk)
      form.append('version', fields.version)
      form.append('version_code', String(fields.version_code))
      form.append('variant', fields.variant)
      if (fields.min_api_level !== undefined) {
        form.append('min_api_level', String(fields.min_api_level))
      }
      if (fields.is_mandatory !== undefined) {
        form.append('is_mandatory', String(fields.is_mandatory))
      }
      if (fields.release_notes_uz) form.append('release_notes_uz', fields.release_notes_uz)
      return api.postForm<UploadRelease>('/app/versions', form)
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('appversions') })
    },
  })
}

export function usePublishVersion(): UseMutationResult<AppVersion, unknown, string> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (versionId: string) => api.post<AppVersion>(`/app/versions/${versionId}/publish`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('appversions') })
    },
  })
}

/**
 * Discard a build — **unpublished only**.
 *
 * A published build is the distribution record and a phone may be mid-download,
 * so the server refuses. This exists for the one case that would otherwise be
 * unrecoverable: an upload with a mistyped `version_code`, which would hold
 * that code forever.
 */
export function useDiscardVersion(): UseMutationResult<unknown, unknown, string> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (versionId: string) => api.delete(`/app/versions/${versionId}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('appversions') })
    },
  })
}

/** What raising the floor to `versionCode` would cost, before it is raised. */
export function useVersionGateImpact(
  versionCode: number | null,
  enabled: boolean,
): UseQueryResult<VersionGateImpact> {
  return useQuery({
    queryKey: queryKey('appversions', 'impact', { versionCode }),
    queryFn: () =>
      api.get<VersionGateImpact>('/app/min-version/impact', { version_code: versionCode }),
    enabled: enabled && versionCode !== null,
    // Never served from cache: the count is what the admin is about to
    // acknowledge, and a stale one is exactly what the server's check rejects.
    staleTime: 0,
    gcTime: 0,
  })
}

/**
 * Raise or lower the floor.
 *
 * `acknowledged_stranded` is the count the admin was actually shown. The
 * server compares it against the live figure and refuses if it moved
 * (`stranded_count_mismatch`) — which happens exactly when a phone checked in
 * between looking and deciding, i.e. when the picture on screen stopped being
 * true. Passing the displayed number rather than re-reading it is the whole
 * point; re-fetching here would defeat the check.
 */
export function useSetMinimumVersion(): UseMutationResult<
  SetMinimumVersionResponse,
  unknown,
  SetMinimumVersionRequest
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: SetMinimumVersionRequest) =>
      api.put<SetMinimumVersionResponse>('/app/min-version', body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('appversions') })
      void client.invalidateQueries({ queryKey: moduleKey('settings') })
    },
  })
}

/** The public download URL. Same-origin, and carries no credential — the
 *  per-agent link is for attribution, not secrecy (SPEC §4.1). */
export function downloadUrl(versionCode: number): string {
  return `/api/v1/app/download/${versionCode}`
}
