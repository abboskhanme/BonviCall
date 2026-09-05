/**
 * Grouping the 28 settings by what a change AFFECTS, not by key name.
 *
 * `alerts.silence_hours` and `device.heartbeat_seconds` are one conversation —
 * "when do we decide a phone has gone quiet" — and they sort ten rows apart
 * alphabetically. A settings page ordered by string is a page where nobody
 * finds the second half of the thing they came to change.
 *
 * The prefix match is deliberately a fallback rather than a closed map: the
 * server owns these keys and adds them, and an unmatched key must still appear
 * on the page rather than vanish from it.
 */
import type { MessageKey } from '@/shared/i18n'

export type SettingGroupId =
  | 'alerts'
  | 'device'
  | 'enrolment'
  | 'upload'
  | 'data'
  | 'retention'
  | 'workingHours'
  | 'other'

export interface SettingGroup {
  id: SettingGroupId
  label: MessageKey
  hint: MessageKey
}

export const SETTING_GROUPS: readonly SettingGroup[] = [
  { id: 'alerts', label: 'settings.groupAlerts', hint: 'settings.groupAlertsHint' },
  { id: 'device', label: 'settings.groupDevice', hint: 'settings.groupDeviceHint' },
  { id: 'enrolment', label: 'settings.groupEnrolment', hint: 'settings.groupEnrolmentHint' },
  { id: 'upload', label: 'settings.groupUpload', hint: 'settings.groupUploadHint' },
  { id: 'data', label: 'settings.groupData', hint: 'settings.groupDataHint' },
  { id: 'retention', label: 'settings.groupRetention', hint: 'settings.groupRetentionHint' },
  { id: 'workingHours', label: 'settings.groupHours', hint: 'settings.groupHoursHint' },
  { id: 'other', label: 'settings.groupOther', hint: 'settings.groupOtherHint' },
]

const PREFIX_GROUP: ReadonlyArray<[string, SettingGroupId]> = [
  ['alerts.', 'alerts'],
  ['device.', 'device'],
  ['enrolment.', 'enrolment'],
  ['upload.', 'upload'],
  ['queue.', 'upload'],
  ['audio.', 'upload'],
  ['data.', 'data'],
  ['retention.', 'retention'],
  ['working_hours.', 'workingHours'],
  ['app.', 'other'],
]

export function groupOf(key: string): SettingGroupId {
  for (const [prefix, group] of PREFIX_GROUP) {
    if (key.startsWith(prefix)) return group
  }
  // A key the panel has never seen still gets a home rather than disappearing.
  return 'other'
}
