/**
 * `/settings` — every threshold the system runs on (SPEC §3.8).
 *
 * Nothing here is hard-coded elsewhere: the scheduler, the alert rules and the
 * device all read these rows, so a number changed on this page changes
 * behaviour. The grouping below is by what a change affects, not by key name,
 * because `alerts.silence_hours` and `device.heartbeat_seconds` are the same
 * conversation and sort ten rows apart alphabetically.
 *
 * **Retention gets its own dialog** and is the only setting that does. Every
 * other value here is a threshold somebody can put back; lowering retention
 * deletes recordings on a schedule and cannot be undone, so it is the one
 * change that has to show its consequence before it is made.
 */
import { useState } from 'react'
import { Pencil } from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { messageForError } from '@/shared/api/errors'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { formatDateTime, formatInstantTitle } from '@/shared/lib/format'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Section } from '@/shared/ui/detail'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import { RetentionModal } from './RetentionModal'
import { SettingModal } from './SettingModal'
import {
  RETENTION_CONFIRM_BELOW_KEY,
  RETENTION_MONTHS_KEY,
  findSetting,
  settingNumber,
  settingString,
  useSettings,
  type Setting,
} from './api'
import { SETTING_GROUPS, groupOf } from './labels'

function SettingRow({
  setting,
  mayWrite,
  onEdit,
}: {
  setting: Setting
  mayWrite: boolean
  onEdit: (setting: Setting) => void
}) {
  return (
    <TR>
      <TD className="font-mono text-xs text-text">{setting.key}</TD>
      <TD className="font-mono text-sm text-text">{settingString(setting)}</TD>
      <TD className="text-xs text-muted">{setting.description_uz ?? ''}</TD>
      <TD
        className="whitespace-nowrap text-xs text-muted"
        title={formatInstantTitle(setting.updated_at)}
      >
        {formatDateTime(setting.updated_at)}
      </TD>
      <TD className="w-0">
        {mayWrite ? (
          <Button
            variant="ghost"
            size="sm"
            aria-label={t('settings.edit')}
            onClick={() => onEdit(setting)}
          >
            <Pencil className="size-3.5" aria-hidden />
          </Button>
        ) : null}
      </TD>
    </TR>
  )
}

export function SettingsPage() {
  const can = useAuth((state) => state.can)
  const mayWrite = can(Perm.SETTINGS_WRITE)
  const settingsQuery = useSettings()
  const [editing, setEditing] = useState<Setting | null>(null)
  const [retentionOpen, setRetentionOpen] = useState(false)

  const items = settingsQuery.data?.items
  const retention = findSetting(items, RETENTION_MONTHS_KEY)
  const confirmBelow = settingNumber(findSetting(items, RETENTION_CONFIRM_BELOW_KEY)) ?? 3
  const retentionMonths = settingNumber(retention)

  return (
    <Page>
      <PageHeader title={t('page.settings')} description={t('settings.subtitle')} />

      <QueryBoundary
        query={settingsQuery}
        isEmpty={(data) => data.items.length === 0}
        emptyTitle={t('settings.emptyAll')}
        skeletonRows={8}
      >
        {(data) => (
          <div className="flex flex-col gap-4">
            {/* Retention is lifted out of the table: it is the only value on
                this page whose change destroys something. */}
            <Card className="flex flex-wrap items-center gap-4 p-4">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-text">{t('settings.retentionTitle')}</p>
                <p className="mt-1 text-xs text-muted">{t('settings.retentionSubtitle')}</p>
              </div>
              <Badge tone={retentionMonths !== null && retentionMonths < confirmBelow ? 'bad' : 'neutral'}>
                {retentionMonths === null
                  ? t('settings.unknownValue')
                  : t('settings.retentionValue', { n: retentionMonths })}
              </Badge>
              {mayWrite && retentionMonths !== null ? (
                <Button
                  variant="secondary"
                  size="sm"
                  className="ms-auto"
                  onClick={() => setRetentionOpen(true)}
                >
                  {t('settings.retentionChange')}
                </Button>
              ) : null}
            </Card>

            {SETTING_GROUPS.map((group) => {
              const rows = data.items
                .filter((setting) => groupOf(setting.key) === group.id)
                .filter((setting) => setting.key !== RETENTION_MONTHS_KEY)
              if (rows.length === 0) return null
              return (
                <Section key={group.id} title={t(group.label)} description={t(group.hint)}>
                  <TableWrap>
                    <Table>
                      <THead>
                        <tr>
                          <TH>{t('settings.colKey')}</TH>
                          <TH>{t('settings.colValue')}</TH>
                          <TH>{t('settings.colDescription')}</TH>
                          <TH>{t('settings.colUpdated')}</TH>
                          <TH />
                        </tr>
                      </THead>
                      <TBody>
                        {rows.map((setting) => (
                          <SettingRow
                            key={setting.key}
                            setting={setting}
                            mayWrite={mayWrite}
                            onEdit={setEditing}
                          />
                        ))}
                      </TBody>
                    </Table>
                  </TableWrap>
                </Section>
              )
            })}

            {settingsQuery.error ? (
              <p className="text-xs text-bad">{messageForError(settingsQuery.error)}</p>
            ) : null}
          </div>
        )}
      </QueryBoundary>

      {mayWrite ? (
        <>
          {retentionMonths !== null ? (
            <RetentionModal
              open={retentionOpen}
              onOpenChange={setRetentionOpen}
              currentMonths={retentionMonths}
              confirmBelowMonths={confirmBelow}
            />
          ) : null}
          <SettingModal
            open={editing !== null}
            onOpenChange={(open) => !open && setEditing(null)}
            setting={editing}
          />
        </>
      ) : null}
    </Page>
  )
}
