/**
 * Exporting the call list as CSV.
 *
 * Says what will be exported before it downloads: how many rows, and which
 * filters are in force. A download has no preview and no undo, and "I exported
 * the wrong month" is only discoverable by opening the file.
 *
 * The count is the list's own `total` — the same number UC-22 requires the
 * file's row count to equal, because the server re-runs the same filter
 * builder. Quoting a separately-computed figure here would be the one way to
 * make that guarantee look broken.
 */
import { useState } from 'react'
import { Download, FileSpreadsheet } from 'lucide-react'

import { t } from '@/shared/i18n'
import { formatCount } from '@/shared/lib/format'
import { Modal, ModalFields } from '@/shared/ui/Modal'

import { callsExportUrl, type CallListQuery } from './api'
import { downloadExport } from './export'

export function ExportCallsModal({
  open,
  onOpenChange,
  query,
  total,
  filterSummary,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  query: CallListQuery
  /** The list's own total, or null when it has not been asked for. */
  total: number | null
  /** The filters in force, already in Uzbek. */
  filterSummary: string[]
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function start() {
    setBusy(true)
    setError(null)
    void downloadExport(callsExportUrl(query))
      .catch(() => setError(t('calls.exportFailed')))
      .finally(() => {
        setBusy(false)
        onOpenChange(false)
      })
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={t('calls.exportTitle')}
      onSubmit={(event) => {
        event.preventDefault()
        start()
      }}
      submitting={busy}
      submitLabel={t('calls.exportAction')}
    >
      <ModalFields>
        <p className="flex items-start gap-2 text-sm text-text">
          <FileSpreadsheet className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
          {total === null
            ? t('calls.exportUnknownCount')
            : t('calls.exportCount', { n: formatCount(total) })}
        </p>

        {filterSummary.length > 0 ? (
          <div>
            <p className="text-2xs font-medium uppercase tracking-wide text-muted">
              {t('calls.exportFilters')}
            </p>
            <ul className="mt-1 space-y-0.5">
              {filterSummary.map((line) => (
                <li key={line} className="text-xs text-text">
                  · {line}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          // Saying "everything" out loud, because an unfiltered export of a
          // 500k-row table is a different decision from a filtered one.
          <p className="text-xs text-warn">{t('calls.exportNoFilters')}</p>
        )}

        <p className="text-xs text-muted">{t('calls.exportFormat')}</p>

        {error ? <p className="text-2xs text-bad">{error}</p> : null}
      </ModalFields>
    </Modal>
  )
}

export { Download }
