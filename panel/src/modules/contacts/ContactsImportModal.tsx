/**
 * Uploading a phonebook — in TWO steps, and that is the point.
 *
 * Ported from BonviZvonki `web/src/modules/contacts/ContactsImportModal.tsx`.
 *
 * file → **PREVIEW** → the user chooses a mode and confirms → **WRITE**.
 * Nothing changes in the database until the second call. Deliberate: this list
 * decides WHO a customer is, and a wrong upload attaches conversations to the
 * wrong code.
 *
 * ⚠️ The confirm step sends the SAME in-memory `File` the preview read, so what
 * was promised is what gets written. Cancelling sends no request at all.
 *
 * ⚠️ CSV only here, unlike the source. The server refuses a workbook with a
 * message naming the one-click fix rather than mis-reading it; the reasoning is
 * in `server/src/modules/contacts/reader.py`.
 */
import { useRef, useState } from 'react'
import { CheckCircle2, FileSpreadsheet, TriangleAlert, Upload } from 'lucide-react'

import { messageForError } from '@/shared/api/errors'
import { t, type MessageKey } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { formatCount } from '@/shared/lib/format'
import { Button } from '@/shared/ui/primitives'
import { Modal } from '@/shared/ui/Modal'

import {
  MODES,
  usePreviewContacts,
  useImportContacts,
  type ContactPreview,
  type ImportMode,
} from './api'

const MODE_LABEL: Record<ImportMode, MessageKey> = {
  coded: 'contacts.import.mode.coded',
  known: 'contacts.import.mode.known',
  all: 'contacts.import.mode.all',
}

const MODE_HINT: Record<ImportMode, MessageKey> = {
  coded: 'contacts.import.modeHint.coded',
  known: 'contacts.import.modeHint.known',
  all: 'contacts.import.modeHint.all',
}

/**
 * The lines that explain what was NOT taken out of the file.
 *
 * ⚠️ "No number written at all" and "a number that cannot be used" are counted
 * and shown SEPARATELY, and the difference is large: measured on a real export,
 * 7,316 rows of 9,103 carried no number (the phone's export gave none) against
 * 11 with an unusable one. One line reading "7,327 bad rows" would be a false
 * conclusion about somebody's data.
 */
const DROPPED: readonly { field: keyof ContactPreview; key: MessageKey }[] = [
  { field: 'no_phone', key: 'contacts.import.noPhone' },
  { field: 'bad_phone', key: 'contacts.import.badPhone' },
  { field: 'no_name', key: 'contacts.import.noName' },
  { field: 'duplicates', key: 'contacts.import.duplicates' },
]

function Tile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-surface-2 px-3 py-2">
      <span className="block text-2xs font-medium uppercase tracking-wide text-muted">
        {label}
      </span>
      <span className="block text-sm font-semibold tabular-nums text-text">
        {formatCount(value)}
      </span>
    </div>
  )
}

export function ContactsImportModal({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [mode, setMode] = useState<ImportMode>('coded')
  const preview = usePreviewContacts()
  const write = useImportContacts()

  function reset() {
    setFile(null)
    setMode('coded')
    preview.reset()
    write.reset()
    // So the same file can be picked again: without this the input keeps its
    // value and re-selecting it fires no `change` event.
    if (inputRef.current) inputRef.current.value = ''
  }

  function close() {
    reset()
    onOpenChange(false)
  }

  const report = write.data
  const plan = preview.data
  // `status === 'pending'` and not `isPending`: the house lint rule bans the
  // latter inside a module because a PAGE that reads it is the start of twenty
  // different loading states. A submit button is not that, and every other
  // modal in the panel spells it this way.
  const writing = write.status === 'pending'
  const failure = write.error ?? preview.error

  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (!next) close()
        else onOpenChange(true)
      }}
      title={t('contacts.import.title')}
      description={t('contacts.import.subtitle')}
      className="w-[min(40rem,calc(100vw-2rem))]"
      onSubmit={
        report
          ? undefined
          : (event) => {
              event.preventDefault()
              if (file) write.mutate({ file, mode })
            }
      }
      submitLabel={
        writing
          ? t('contacts.import.running')
          : t('contacts.import.confirm', {
              count: formatCount(plan?.would_import[mode] ?? 0),
            })
      }
      submitting={writing}
      submitDisabled={!plan || plan.parsed === 0 || writing}
    >
      <div className="space-y-4">
        {failure ? (
          <p className="flex items-start gap-2 rounded-md bg-bad/10 px-3 py-2 text-xs text-bad">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            {messageForError(failure) || t('contacts.import.failed')}
          </p>
        ) : null}

        {report ? null : (
          <>
            <input
              ref={inputRef}
              type="file"
              accept=".csv,.tsv,text/csv"
              hidden
              onChange={(event) => {
                const picked = event.target.files?.[0] ?? null
                setFile(picked)
                write.reset()
                if (picked) preview.mutate(picked)
              }}
            />
            <button
              type="button"
              className={cn(
                'flex w-full items-center gap-3 rounded-md border border-dashed',
                'border-border px-3 py-3 text-start transition-colors',
                'hover:border-accent focus-visible:outline-none focus-visible:ring-2',
                'focus-visible:ring-accent/20',
              )}
              onClick={() => inputRef.current?.click()}
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-surface-2 text-muted">
                <FileSpreadsheet className="size-4" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-text">
                  {file?.name ?? t('contacts.import.pick')}
                </span>
                <span className="block text-2xs text-muted">
                  {t('contacts.import.pickHint')}
                </span>
              </span>
              <Upload className="size-4 shrink-0 text-muted" aria-hidden />
            </button>
          </>
        )}

        {plan && !report ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Tile label={t('contacts.import.read')} value={plan.read} />
              <Tile label={t('contacts.import.parsed')} value={plan.parsed} />
              <Tile label={t('contacts.import.withCode')} value={plan.with_code} />
              <Tile label={t('contacts.import.created')} value={plan.created} />
            </div>

            {/* Only rendered when something actually was dropped: a permanent
                list of zeroes is noise the reader learns to skip. */}
            {DROPPED.some(({ field }) => (plan[field] as number) > 0) ? (
              <ul className="space-y-1 text-2xs text-muted">
                {DROPPED.filter(({ field }) => (plan[field] as number) > 0).map(
                  ({ field, key }) => (
                    <li key={field}>{t(key, { count: plan[field] as number })}</li>
                  ),
                )}
              </ul>
            ) : null}

            <fieldset className="space-y-2">
              <legend className="text-xs font-medium text-text">
                {t('contacts.import.modeTitle')}
              </legend>
              {MODES.map((option) => (
                <label
                  key={option}
                  className={cn(
                    'flex cursor-pointer items-start gap-3 rounded-md border',
                    'border-border px-3 py-2 transition-colors',
                    mode === option && 'bg-accent-soft ring-1 ring-accent/30',
                  )}
                >
                  <input
                    type="radio"
                    name="import-mode"
                    className="mt-1"
                    checked={mode === option}
                    onChange={() => setMode(option)}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline justify-between gap-3">
                      <span className="text-sm text-text">{t(MODE_LABEL[option])}</span>
                      <span className="text-sm font-semibold tabular-nums text-text">
                        {formatCount(plan.would_import[option] ?? 0)}
                      </span>
                    </span>
                    <span className="block text-2xs text-muted">
                      {t(MODE_HINT[option])}
                    </span>
                    {/* ⚠️ Both numbers, and the second is the one the decision
                        is taken on. A row count flatters the wide mode: "1 517"
                        sounds like a lot and "611" like a little, yet those 611
                        cover far more conversations, because customers are
                        spoken to often and private acquaintances almost never. */}
                    {(plan.would_cover[option] ?? 0) > 0 ? (
                      <span className="block text-2xs text-accent">
                        {t('contacts.import.modeCover', {
                          count: formatCount(plan.would_cover[option] ?? 0),
                        })}
                      </span>
                    ) : null}
                  </span>
                </label>
              ))}
            </fieldset>
          </div>
        ) : null}

        {report ? (
          <div className="space-y-3">
            <p className="flex items-start gap-2 rounded-md bg-good/10 px-3 py-2 text-xs text-good">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden />
              {t('contacts.import.done', {
                created: formatCount(report.created),
                updated: formatCount(report.updated),
              })}
            </p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Tile label={t('contacts.import.created')} value={report.created} />
              <Tile label={t('contacts.import.updated')} value={report.updated} />
              <Tile label={t('contacts.import.unchanged')} value={report.unchanged} />
              <Tile
                label={t('contacts.import.skippedFilter')}
                value={report.skipped_filter}
              />
            </div>
            <div className="flex justify-end">
              <Button variant="secondary" size="sm" onClick={close}>
                {t('common.close')}
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </Modal>
  )
}
