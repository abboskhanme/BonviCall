/**
 * Settings — TanStack Query hooks only (CONVENTIONS-CLIENT.md §1).
 *
 * Every threshold in the system lives in `app_settings` and nothing is
 * hard-coded elsewhere (SPEC §3.8), so this page edits the real values the
 * scheduler and the device read.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api } from '@/shared/api/client'
import { moduleKey, queryKey } from '@/shared/api/queryKeys'
import type { components } from '@/shared/api/types.gen'

export type Setting = components['schemas']['SettingResponse']
export type SettingList = components['schemas']['SettingListResponse']
export type UpdateSettingRequest = components['schemas']['UpdateSettingRequest']

/** The two keys the retention dialog is about (SPEC §3.8). */
export const RETENTION_MONTHS_KEY = 'retention.audio_months'
export const RETENTION_CONFIRM_BELOW_KEY = 'retention.confirm_below_months'

export function useSettings(): UseQueryResult<SettingList> {
  return useQuery({
    queryKey: queryKey('settings', 'list'),
    queryFn: () => api.get<SettingList>('/settings'),
  })
}

export function useUpdateSetting(): UseMutationResult<Setting, unknown, UpdateSettingRequest> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateSettingRequest) => api.put<Setting>('/settings', body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('settings') })
    },
  })
}

/**
 * A setting's value, narrowed by its own `value_type`.
 *
 * `SettingResponse.value` is untyped on the wire — the column holds JSON and
 * the schema says so — so this is the one place that decides what a value is,
 * against the `value_type` the row carries rather than against a guess.
 */
export function settingNumber(setting: Setting | undefined): number | null {
  if (!setting || typeof setting.value !== 'number') return null
  return setting.value
}

export function settingString(setting: Setting | undefined): string {
  if (!setting) return ''
  const value = setting.value
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value ?? null)
}

export function findSetting(list: Setting[] | undefined, key: string): Setting | undefined {
  return (list ?? []).find((setting) => setting.key === key)
}

/**
 * The Asia/Tashkent calendar date that is `months` months before today.
 *
 * Used to ask the server how many recordings fall outside a proposed
 * retention window — the answer has to come from the same filter builder the
 * call list uses, or the dialog would be quoting a number nothing else agrees
 * with.
 */
export function cutoffDate(months: number, now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tashkent',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
    .format(now)
    .split('-')
    .map(Number)
  const [year, month, day] = parts
  // Day 0 of the following month clamps 31 January minus one month to
  // 28 February rather than rolling into March.
  const target = new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1 - months, 1))
  const lastDay = new Date(
    Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0),
  ).getUTCDate()
  const safeDay = Math.min(day ?? 1, lastDay)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${target.getUTCFullYear()}-${pad(target.getUTCMonth() + 1)}-${pad(safeDay)}`
}

/**
 * How many stored recordings sit outside a proposed retention window.
 *
 * Counted by the SERVER, through the same `/calls` filter the list and the
 * export use (UC-22), so the number in the confirmation is the number a
 * sceptical admin can go and look at. Computing it in the panel would be a
 * second implementation of "which calls are old", and the two would drift.
 */
export function useRecordingsOutsideWindow(
  months: number | null,
  enabled: boolean,
): UseQueryResult<number> {
  const cutoff = months === null ? null : cutoffDate(months)
  return useQuery({
    queryKey: queryKey('calls', 'retentionPreview', { cutoff }),
    queryFn: async () => {
      const page = await api.get<{ total: number | null }>('/calls', {
        has_audio: true,
        date_to: cutoff,
        with_total: true,
        limit: 1,
      })
      return page.total ?? 0
    },
    enabled: enabled && cutoff !== null,
    staleTime: 30_000,
  })
}
