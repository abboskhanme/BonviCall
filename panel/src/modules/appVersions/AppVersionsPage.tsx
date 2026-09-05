/**
 * `/settings/app-versions` — the distribution record (N33, N34).
 *
 * BonviCall is side-loaded, not published through a store, so this page IS the
 * distribution channel: what exists, what is published, what phones are
 * required to have, and the SHA-256 of each build.
 *
 * The fingerprint is not decoration. A build signed with the wrong key cannot
 * install as an update at all — only as an uninstall-and-reinstall, which
 * destroys every phone's unsent upload queue (`docs/APK-SIGNING.md`). It is
 * computed server-side from the bytes received and never accepted from a
 * client, and it is shown in full because comparing a prefix is not comparing.
 */
import { useState } from 'react'
import { Download, ShieldAlert, Trash2, Upload } from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { useUsers } from '@/modules/users/api'
import { isApiError, messageForError } from '@/shared/api/errors'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { formatBytes, formatDateTime, formatInstantTitle, shortId } from '@/shared/lib/format'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import { MinVersionModal } from './MinVersionModal'
import { UploadVersionModal } from './UploadVersionModal'
import {
  MIN_VERSION_KEY,
  downloadUrl,
  findSetting,
  settingNumber,
  useAppVersions,
  useDiscardVersion,
  usePublishVersion,
  useSettings,
  type AppVersion,
} from './api'


/**
 * The server answers a discard of a published build with a generic `conflict`
 * and `detail.reason = 'published'`. Generic is not actionable, and the reason
 * is: a published build is the distribution record and a phone may be
 * mid-download, so the answer is to publish a newer one, not to remove this.
 */
function discardMessage(error: unknown): string {
  if (isApiError(error)) {
    const reason = error.detail?.reason
    if (reason === 'published') return t('appVersions.cannotDiscardPublished')
  }
  return messageForError(error)
}

function VersionRow({
  version,
  minCode,
  mayWrite,
  uploaderName,
}: {
  version: AppVersion
  minCode: number | null
  mayWrite: boolean
  uploaderName: (id: string) => string | null
}) {
  const publish = usePublishVersion()
  const discard = useDiscardVersion()
  const published = version.published_at !== null
  const isMinimum = minCode !== null && version.version_code === minCode

  return (
    <TR>
      <TD>
        <span className="font-medium text-text">{version.version}</span>
        <span className="ms-2 font-mono text-xs text-muted">({version.version_code})</span>
      </TD>
      <TD className="text-xs text-muted">{version.variant}</TD>
      <TD className="whitespace-nowrap text-end font-mono tabular-nums text-muted">
        {formatBytes(version.size_bytes)}
      </TD>
      <TD>
        {/* In full. Comparing a prefix is not comparing, and this is the
            number that decides whether an update can install at all. */}
        <span className="break-all font-mono text-2xs text-muted">{version.apk_sha256}</span>
      </TD>
      <TD
        className="whitespace-nowrap text-xs text-muted"
        title={formatInstantTitle(version.created_at)}
      >
        {formatDateTime(version.created_at)}
        {/* A name if we may read the user list, a short id otherwise — never
            a full UUID in a column somebody reads. */}
        {version.created_by ? (
          <span className="ms-1">
            · {uploaderName(version.created_by) ?? shortId(version.created_by)}
          </span>
        ) : null}
      </TD>
      <TD>
        <div className="flex flex-wrap gap-1">
          {published ? (
            <Badge tone="good">{t('appVersions.published')}</Badge>
          ) : (
            <Badge tone="neutral">{t('appVersions.unpublished')}</Badge>
          )}
          {version.is_current ? <Badge tone="accent">{t('appVersions.current')}</Badge> : null}
          {isMinimum ? <Badge tone="warn">{t('appVersions.isMinimum')}</Badge> : null}
          {version.is_mandatory ? (
            <Badge tone="warn">{t('appVersions.mandatory')}</Badge>
          ) : null}
        </div>
      </TD>
      <TD>
        <div className="flex items-center justify-end gap-1">
          {published ? (
            <a
              href={downloadUrl(version.version_code)}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted hover:bg-surface-2 hover:text-text"
            >
              <Download className="size-3.5" aria-hidden />
              {t('appVersions.download')}
            </a>
          ) : null}
          {mayWrite && !published ? (
            <>
              <Button
                variant="secondary"
                size="sm"
                disabled={publish.status === 'pending'}
                onClick={() => publish.mutate(version.id)}
              >
                {t('appVersions.publish')}
              </Button>
              {/* Only an unpublished build can be taken back: a published one
                  is the distribution record and a phone may be mid-download.
                  This exists for a mistyped version code, which would
                  otherwise hold that number forever. */}
              <Button
                variant="ghost"
                size="sm"
                aria-label={t('appVersions.discard')}
                disabled={discard.status === 'pending'}
                onClick={() => discard.mutate(version.id)}
              >
                <Trash2 className="size-3.5" aria-hidden />
              </Button>
            </>
          ) : null}
        </div>
        {publish.error ? (
          <p className="text-end text-2xs text-bad">{messageForError(publish.error)}</p>
        ) : null}
        {discard.error ? (
          <p className="text-end text-2xs text-bad">{discardMessage(discard.error)}</p>
        ) : null}
      </TD>
    </TR>
  )
}

export function AppVersionsPage() {
  const can = useAuth((state) => state.can)
  const mayWrite = can(Perm.APPVERSIONS_WRITE)
  const versionsQuery = useAppVersions()
  const settingsQuery = useSettings()
  // Only an admin holds `users:read`; a manager reading this page sees a short
  // id instead, which is honest rather than a 403 nobody asked for.
  const usersQuery = useUsers({}, can(Perm.USERS_READ))
  const uploaderName = (id: string) =>
    usersQuery.data?.items.find((user) => user.id === id)?.full_name ?? null
  const minCode = settingNumber(findSetting(settingsQuery.data?.items, MIN_VERSION_KEY))

  const [uploading, setUploading] = useState(false)
  const [changingMin, setChangingMin] = useState(false)

  const signingConfigured = versionsQuery.data?.signing_sha256_configured ?? true

  return (
    <Page>
      <PageHeader
        title={t('page.appVersions')}
        description={t('appVersions.subtitle')}
        actions={
          mayWrite ? (
            <Button size="sm" onClick={() => setUploading(true)}>
              <Upload className="size-4" aria-hidden />
              {t('appVersions.upload')}
            </Button>
          ) : undefined
        }
      />

      {!signingConfigured ? (
        /* Uploads are being accepted without the key check. A build signed by
           the wrong key destroys every phone's queue on install. */
        <Card className="flex items-start gap-3 border-warn/40 bg-warn/5 p-3">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
          <div>
            <p className="text-sm font-medium text-text">{t('appVersions.noSigningTitle')}</p>
            <p className="mt-0.5 text-xs text-muted">{t('appVersions.noSigningHint')}</p>
          </div>
        </Card>
      ) : null}

      <Card className="flex flex-wrap items-center gap-4 p-4">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-text">{t('appVersions.minVersionTitle')}</p>
          <p className="mt-1 text-xs text-muted">{t('appVersions.minVersionSubtitle')}</p>
        </div>
        <Badge tone="neutral">
          {minCode === null
            ? t('settings.unknownValue')
            : t('appVersions.minVersionValue', { n: minCode })}
        </Badge>
        {mayWrite && minCode !== null ? (
          <Button
            variant="secondary"
            size="sm"
            className="ms-auto"
            onClick={() => setChangingMin(true)}
          >
            {t('appVersions.changeMinVersion')}
          </Button>
        ) : null}
      </Card>

      <QueryBoundary
        query={versionsQuery}
        isEmpty={(data) => data.items.length === 0}
        emptyTitle={t('appVersions.emptyAll')}
        emptyHint={t('appVersions.emptyAllHint')}
        skeletonRows={4}
      >
        {(data) => (
          <TableWrap>
            <Table>
              <THead>
                <tr>
                  <TH>{t('appVersions.colVersion')}</TH>
                  <TH>{t('appVersions.colVariant')}</TH>
                  <TH className="text-end">{t('appVersions.colSize')}</TH>
                  <TH>{t('appVersions.colSha')}</TH>
                  <TH>{t('appVersions.colUploaded')}</TH>
                  <TH>{t('appVersions.colStatus')}</TH>
                  <TH className="w-0" />
                </tr>
              </THead>
              <TBody>
                {[...data.items]
                  .sort((a, b) => b.version_code - a.version_code)
                  .map((version) => (
                    <VersionRow
                      key={version.id}
                      version={version}
                      minCode={minCode}
                      mayWrite={mayWrite}
                      uploaderName={uploaderName}
                    />
                  ))}
              </TBody>
            </Table>
          </TableWrap>
        )}
      </QueryBoundary>

      {mayWrite ? (
        <>
          <UploadVersionModal
            open={uploading}
            onOpenChange={setUploading}
            signingConfigured={signingConfigured}
          />
          {minCode !== null ? (
            <MinVersionModal
              open={changingMin}
              onOpenChange={setChangingMin}
              currentMinCode={minCode}
            />
          ) : null}
        </>
      ) : null}
    </Page>
  )
}
