/**
 * Uploading a SAP export — in TWO steps, and that is the point.
 *
 *   1. a file is picked → `POST /sales/import/preview` (WRITES NOTHING, only
 *      counts);
 *   2. the estimate is shown → the user confirms → THE SAME file goes to
 *      `POST /sales/import`;
 *   3. the report.
 *
 * ⚠️ WHY TWO STEPS. The file used to land in the database the moment it was
 * picked, and the user learned what had gone in only afterwards. Two mistakes
 * passed silently: the wrong file (last week's export, another department's)
 * and a repeat upload. Neither can be undone — the sales are already written.
 *
 * ⚠️ CANCELLING SENDS NOTHING. Step two holds only the in-memory `File` and the
 * estimate; closing the dialog drops both.
 *
 * THE KIND IS NOT PICKED. Three different exports arrive (the operations
 * register, the contractor catalogue, the balance report) and the server
 * recognises each from its HEADER. A "kind" picker on screen would only ever
 * be a source of error.
 *
 * ⚠️ ORDER OF IMPORT IS FREE. Load the register before the catalogue and the
 * sales have no phone numbers, so the list looks EMPTY — which reads as "all
 * is well". When the catalogue arrives the server restores the links, which is
 * why `linked_sales` gets a line of its own in the report.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ⚠️ THE WARNINGS AND THE UPLOAD ERRORS ARE CODES, AND THE UZBEK IS OURS.
 * The source's backend shipped ready-made Uzbek sentences that the panel
 * printed blind — user-facing text living on the far side of the wire, where
 * nobody who writes copy could find it. Here the server sends
 * `{code, count}` and `detail.reason`, and every sentence below comes out of
 * `uz.json` like every other string in this product (CONVENTIONS.md §14).
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useRef, useState } from 'react'
import { CalendarRange, CheckCircle2, FileSpreadsheet, Info, TriangleAlert, Upload } from 'lucide-react'

import { t, type MessageKey } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { formatCount } from '@/shared/lib/format'
import { Badge, Button } from '@/shared/ui/primitives'
import { Modal } from '@/shared/ui/Modal'
import { ProgressBar } from '@/shared/ui/ProgressBar'

import {
  FILE_KIND_LABEL,
  OP_TYPE_LABEL,
  PREVIEW_SLICE_LABEL,
  WARNING_LABEL,
  useImportSales,
  usePreviewSalesImport,
  type ImportPreview,
  type ImportReport,
} from './api'
import { formatSaleDate, formatUsd } from './saleDate'
import { uploadFailure } from './uploadError'

/** What the file dialog offers. `.xlsx` only: the server reads it with
 *  `openpyxl`, which cannot open the old `.xls` or a `.csv` at all. */
const ACCEPT = '.xlsx'

/** How many unknown customer codes are shown. The list answers "what sort of
 *  codes are these?"; the full count stands beside it. */
const CODE_SAMPLE = 5

const BYTES_PER_MB = 1024 * 1024

/** Days in an inclusive range. */
function dayCount(from: string, to: string): number {
  const start = new Date(`${from}T00:00:00Z`).getTime()
  const end = new Date(`${to}T00:00:00Z`).getTime()
  if (Number.isNaN(start) || Number.isNaN(end)) return 0
  return Math.round((end - start) / 86_400_000) + 1
}

function ErrorNote({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-3 rounded-md bg-bad/10 p-3" role="alert">
      <TriangleAlert className="mt-0.5 size-4 shrink-0 text-bad" aria-hidden />
      <div className="min-w-0">
        <p className="text-xs font-medium text-bad">{t('sales.import.failed')}</p>
        <p className="mt-0.5 text-2xs leading-relaxed text-muted">{message}</p>
      </div>
    </div>
  )
}

function BigStat({
  label,
  value,
  tone,
}: {
  label: string
  value: number
  tone?: 'good' | 'muted'
}) {
  return (
    <div className="rounded-md bg-surface-2 px-3 py-2">
      <div className="text-2xs text-muted">{label}</div>
      <div
        className={cn(
          'mt-0.5 text-xl font-semibold tabular-nums text-text',
          tone === 'good' && value > 0 && 'text-good',
          tone === 'muted' && value === 0 && 'text-muted',
        )}
      >
        {formatCount(value)}
      </div>
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div className="mb-1.5 text-2xs font-medium text-muted">{children}</div>
}

/**
 * Operations per day.
 *
 * A horizontal list rather than a column chart: the number of days is not
 * known in advance (a daily export is a few, a monthly one over thirty) and a
 * horizontal list stays readable and scrollable at any length, where columns
 * would compress past recognition.
 *
 * ⚠️ The bar is drawn against the BIGGEST day, not the total — the point is to
 * compare days with each other. It uses `shared/ui/ProgressBar`, which
 * quantises the width into a real class: a computed width can only be an
 * inline style, and those are forbidden (CONVENTIONS-CLIENT.md §11). The exact
 * count is printed beside the bar, so nothing is lost to the rounding.
 */
function DayChart({ days }: { days: ImportPreview['by_day'] }) {
  const rows = days ?? []
  const max = Math.max(...rows.map((row) => row.count), 1)

  return (
    <section>
      <SectionTitle>{t('sales.import.preview.byDay')}</SectionTitle>
      <div className="max-h-52 space-y-1 overflow-y-auto rounded-md bg-surface-2 p-3">
        {rows.map((row) => (
          <div key={row.day} className="flex items-center gap-2.5">
            <span className="w-16 shrink-0 text-2xs tabular-nums text-muted">
              {formatSaleDate(row.day)}
            </span>
            <span className="min-w-0 flex-1">
              <ProgressBar
                fraction={row.count / max}
                label={t('sales.import.preview.dayBar', {
                  day: formatSaleDate(row.day),
                  count: row.count,
                })}
              />
            </span>
            <span className="w-10 shrink-0 text-end text-2xs font-medium tabular-nums text-text">
              {formatCount(row.count)}
            </span>
          </div>
        ))}
      </div>
    </section>
  )
}

/**
 * What is wrong with the file.
 *
 * This block never STOPS the import — it says what will not come through, and
 * behind every line there is a concrete next step: load the catalogue, assign
 * a branch to an employee.
 */
function WarningBlock({ preview }: { preview: ImportPreview }) {
  const warnings = preview.warnings ?? []
  const branches = preview.unmatched_branches ?? []
  const codes = preview.unknown_partners ?? []

  return (
    <div className="space-y-2 rounded-md bg-warn/10 p-3">
      <div className="flex items-center gap-1.5 text-2xs font-medium text-warn">
        <TriangleAlert className="size-3.5" aria-hidden />
        {t('sales.import.preview.warnings')}
      </div>

      {/* A code with no Uzbek entry is SKIPPED rather than printed raw: an
          English identifier in a warning block cannot be acted on either way,
          but only one of the two looks broken. */}
      {warnings
        .map((warning) => ({ code: warning.code, count: warning.count, key: WARNING_LABEL[warning.code] }))
        .filter((warning): warning is typeof warning & { key: MessageKey } => Boolean(warning.key))
        .map((warning) => (
          <p key={warning.code} className="text-2xs leading-relaxed text-muted">
            {t(warning.key, { count: warning.count })}
          </p>
        ))}

      {preview.without_phone > 0 ? (
        <p className="text-2xs leading-relaxed text-muted">
          {t('sales.import.preview.withoutPhone', { count: preview.without_phone })}
        </p>
      ) : null}

      {/* Codes as a SAMPLE rather than a count: seeing the first few tells the
          manager which period the file is from. */}
      {preview.unknown_partner_count > 0 ? (
        <div>
          <p className="text-2xs leading-relaxed text-muted">
            {t('sales.import.preview.unknownPartners', {
              count: preview.unknown_partner_count,
            })}
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {codes.slice(0, CODE_SAMPLE).map((code) => (
              <Badge key={code} tone="warn">
                {code}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}

      {/* Branches by NAME rather than by count: nothing can be done with
          "7 branches were not linked", while a list of names starts the work. */}
      {branches.length > 0 ? (
        <div>
          <p className="text-2xs leading-relaxed text-muted">
            {t('sales.import.unmatchedBranches', { count: branches.length })}
          </p>
          <div className="mt-1.5 flex max-h-24 flex-wrap gap-1.5 overflow-y-auto">
            {branches.map((branch) => (
              <Badge key={branch} tone="warn">
                {branch}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

/**
 * Step two — the estimate.
 *
 * Its only job: the user knows what will happen BEFORE pressing confirm. So
 * there is no guesswork here — every number comes from the file and from the
 * database.
 */
function PreviewView({ preview }: { preview: ImportPreview }) {
  /* Everything is already loaded — the COMMONEST case, because daily exports
     overlap — and it has to be said out loud, or "0 new" is read as a fault. */
  const nothingNew = preview.new_rows === 0
  const byType = preview.by_type ?? []
  const byDay = preview.by_day ?? []

  const period =
    preview.date_from && preview.date_to
      ? `${formatSaleDate(preview.date_from)} — ${formatSaleDate(preview.date_to)} · ${t(
          'sales.import.preview.dayCount',
          { count: dayCount(preview.date_from, preview.date_to) },
        )}`
      : null

  const hasWarnings =
    (preview.warnings ?? []).length > 0 ||
    preview.unknown_partner_count > 0 ||
    (preview.unmatched_branches ?? []).length > 0 ||
    preview.without_phone > 0

  return (
    <div className="space-y-4">
      {/* ── The file: kind, name, period ───────────────────── */}
      <div className="flex items-start gap-3 rounded-md bg-surface-2 p-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-md bg-accent-soft text-accent">
          <FileSpreadsheet className="size-5" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-text">{t(FILE_KIND_LABEL[preview.kind])}</p>
          <p className="mt-0.5 truncate text-2xs text-muted">{preview.filename}</p>
          {period ? (
            <p className="mt-1.5 flex items-center gap-1.5 text-2xs tabular-nums text-muted">
              <CalendarRange className="size-3.5 shrink-0" aria-hidden />
              {period}
            </p>
          ) : null}
        </div>
      </div>

      {/* ── Three big numbers ───────────────────────────────
          ⚠️ THEY DO NOT ADD UP. "Jami" is rows in the file; the first two
          count UNIQUE keys. One operation number occurs twice in a file
          (measured: 2,383 distinct numbers in 2,384 rows), so a difference is
          normal — and the warning block explains it. */}
      <div className="grid grid-cols-3 gap-2">
        <BigStat
          label={t('sales.import.preview.new')}
          value={preview.new_rows}
          tone={nothingNew ? 'muted' : 'good'}
        />
        <BigStat label={t('sales.import.preview.existing')} value={preview.existing_rows} />
        <BigStat label={t('sales.import.preview.total')} value={preview.rows} />
      </div>

      {nothingNew ? (
        <p className="flex items-start gap-2 rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
          <Info className="mt-px size-3.5 shrink-0" aria-hidden />
          {t('sales.import.preview.alreadyLoaded')}
        </p>
      ) : null}

      {byType.length > 0 ? (
        <section>
          <SectionTitle>{t(PREVIEW_SLICE_LABEL[preview.kind])}</SectionTitle>
          <div className="overflow-hidden rounded-md bg-surface-2">
            {byType.map((row) => {
              /* ⚠️ TRANSLATED FROM `type`, FALLING BACK TO `label`. `label` is
                 the word SAP itself printed and is RUSSIAN ON PURPOSE — in the
                 catalogue and balance files this slice is a group or a
                 department name, which is not ours to translate, and the
                 reader compares the count against SAP's own report. */
              const typeKey = OP_TYPE_LABEL[row.type]
              return (
              <div
                key={row.type}
                className="flex items-center gap-3 border-b border-border px-3 py-2 last:border-0"
              >
                <span className="min-w-0 flex-1 truncate text-xs text-text">
                  {typeKey ? t(typeKey) : row.label}
                </span>
                <span className="shrink-0 text-xs font-semibold tabular-nums text-text">
                  {formatCount(row.count)}
                </span>
                {row.amount_usd !== null && row.amount_usd !== undefined ? (
                  <span className="w-24 shrink-0 text-end text-2xs tabular-nums text-muted">
                    {formatUsd(row.amount_usd)}
                  </span>
                ) : null}
              </div>
              )
            })}
          </div>
        </section>
      ) : null}

      {byDay.length > 0 ? <DayChart days={byDay} /> : null}

      {hasWarnings ? <WarningBlock preview={preview} /> : null}
    </div>
  )
}

/**
 * The report.
 *
 * Every number answers a SEPARATE question and they are not added up: "read"
 * is rows in the file, "new"/"updated" what reached the database, the rest are
 * defects. That is why they are not squeezed into one total.
 */
function ReportView({ report }: { report: ImportReport }) {
  const clean =
    report.skipped === 0 &&
    report.unknown_partner === 0 &&
    report.unmatched_branches.length === 0

  const rows: { key: keyof ImportReport; label: MessageKey; tone?: 'good' | 'muted' }[] = [
    { key: 'read', label: 'sales.import.stat.read' },
    { key: 'created', label: 'sales.import.stat.created', tone: 'good' },
    { key: 'updated', label: 'sales.import.stat.updated' },
    { key: 'skipped', label: 'sales.import.stat.skipped', tone: 'muted' },
    { key: 'unknown_partner', label: 'sales.import.stat.unknown_partner', tone: 'muted' },
    { key: 'unknown_op_type', label: 'sales.import.stat.unknown_op_type', tone: 'muted' },
  ]

  return (
    <div className="space-y-4">
      <div
        className={cn(
          'flex items-start gap-3 rounded-md p-3',
          clean ? 'bg-good/10' : 'bg-warn/10',
        )}
      >
        <span className={cn('mt-0.5 shrink-0', clean ? 'text-good' : 'text-warn')}>
          {clean ? (
            <CheckCircle2 className="size-5" aria-hidden />
          ) : (
            <TriangleAlert className="size-5" aria-hidden />
          )}
        </span>
        <div className="min-w-0">
          <p className={cn('text-sm font-semibold', clean ? 'text-good' : 'text-warn')}>
            {t('sales.import.created', { count: report.created })}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            {t('sales.import.kindLine', {
              kind: t(FILE_KIND_LABEL[report.kind]),
              file: report.source,
            })}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {rows.map((row) => {
          const value = report[row.key] as number
          return (
            <div key={row.key} className="rounded-md bg-surface-2 px-3 py-2">
              <div className="text-2xs text-muted">{t(row.label)}</div>
              <div
                className={cn(
                  'mt-0.5 text-lg font-semibold tabular-nums text-text',
                  row.tone === 'good' && value > 0 && 'text-good',
                  row.tone === 'muted' && value > 0 && 'text-warn',
                )}
              >
                {formatCount(value)}
              </div>
            </div>
          )
        })}
      </div>

      {/* Links restored once the catalogue arrived. Hidden at zero: it is only
          meaningful when the register was loaded first, and noise otherwise. */}
      {report.linked_sales > 0 ? (
        <p className="rounded-md bg-good/10 px-3 py-2 text-2xs leading-relaxed text-good">
          {t('sales.import.linkedSales', { count: report.linked_sales })}
        </p>
      ) : null}

      {report.attributed_sales > 0 ? (
        <p className="rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
          {t('sales.import.attributedSales', { count: report.attributed_sales })}
        </p>
      ) : null}

      {report.phones_filled > 0 ? (
        <p className="rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
          {t('sales.import.phonesFilled', { count: report.phones_filled })}
        </p>
      ) : null}

      {/* ⚠️ MARKED INACTIVE, NEVER DELETED — deleting would take the exclusion
          decision with it. The line explains why the database holds fewer
          contractors than the file. */}
      {report.inactive_skipped > 0 || report.inactive_deactivated > 0 ? (
        <p className="rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
          {t('sales.import.inactive', {
            skipped: report.inactive_skipped,
            deactivated: report.inactive_deactivated,
          })}
        </p>
      ) : null}

      {report.unmatched_branches.length > 0 ? (
        <div className="rounded-md bg-warn/10 p-3">
          <div className="mb-2 text-2xs font-medium text-warn">
            {t('sales.import.unmatchedBranches', { count: report.unmatched_branches.length })}
          </div>
          <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
            {report.unmatched_branches.map((branch) => (
              <Badge key={branch} tone="warn">
                {branch}
              </Badge>
            ))}
          </div>
          <p className="mt-2 text-2xs leading-relaxed text-muted">
            {t('sales.import.unmatchedHint')}
          </p>
        </div>
      ) : null}
    </div>
  )
}

export function ImportModal({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const preview = usePreviewSalesImport()
  const write = useImportSales()

  const plan = preview.data
  const report = write.data
  // `status === 'pending'`, not `isPending`: the house lint rule bans the
  // latter inside a module because a PAGE that reads it is the start of twenty
  // different loading states. A submit button is not that, and every other
  // modal in this panel spells it the same way.
  const busy = preview.status === 'pending' || write.status === 'pending'
  const failure = write.error ?? preview.error

  function reset() {
    setFile(null)
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

  const title = report
    ? t('sales.import.doneTitle')
    : plan
      ? t('sales.import.previewTitle')
      : t('sales.import.title')

  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (!next) close()
        else onOpenChange(true)
      }}
      title={title}
      description={
        report ? undefined : plan ? t('sales.import.previewHint') : t('sales.import.hint')
      }
      className="w-[min(44rem,calc(100vw-2rem))]"
      onSubmit={
        report
          ? undefined
          : (event) => {
              event.preventDefault()
              if (!file) return
              // ⚠️ THE SAME in-memory `File` the estimate read, so what was
              // shown is what gets written.
              if (plan) write.mutate(file)
              else preview.mutate(file)
            }
      }
      submitLabel={
        plan
          ? write.status === 'pending'
            ? t('sales.import.running')
            : t('sales.import.confirm')
          : preview.status === 'pending'
            ? t('sales.import.checking')
            : t('sales.import.start')
      }
      submitting={busy}
      submitDisabled={!file || busy}
    >
      <div className="space-y-4">
        {failure ? <ErrorNote message={uploadFailure(failure)} /> : null}

        {report ? null : (
          <>
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              hidden
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null)
                // A new file invalidates the estimate AND any earlier failure:
                // leaving them on screen would describe the previous file.
                preview.reset()
                write.reset()
              }}
            />
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className={cn(
                'flex w-full items-center gap-3 rounded-md border border-dashed px-3 py-3 text-start',
                'transition-colors focus-visible:outline-none focus-visible:ring-2',
                'focus-visible:ring-accent/20',
                file ? 'border-accent bg-accent-soft' : 'border-border hover:border-accent',
              )}
            >
              <span
                className={cn(
                  'grid size-10 shrink-0 place-items-center rounded-md bg-surface-2',
                  file ? 'text-accent' : 'text-muted',
                )}
              >
                {file ? (
                  <FileSpreadsheet className="size-5" aria-hidden />
                ) : (
                  <Upload className="size-5" aria-hidden />
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-text">
                  {file?.name ?? t('sales.import.choose')}
                </span>
                <span className="mt-0.5 block text-2xs text-muted">
                  {file
                    ? t('sales.import.size', { value: (file.size / BYTES_PER_MB).toFixed(2) })
                    : t('sales.import.chooseHint')}
                </span>
              </span>
            </button>
          </>
        )}

        {report ? (
          <>
            <ReportView report={report} />
            <div className="flex justify-end gap-2">
              {/* Three files are loaded one after another — continuing from
                  here beats closing and reopening the dialog. */}
              <Button variant="secondary" size="sm" onClick={reset}>
                {t('sales.import.another')}
              </Button>
              <Button size="sm" onClick={close}>
                {t('common.close')}
              </Button>
            </div>
          </>
        ) : plan ? (
          <PreviewView preview={plan} />
        ) : (
          <>
            <p className="rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
              {t('sales.import.kindNote')}
            </p>
            {/* The promise "you see it first, then it is written" is made
                BEFORE the file is picked — afterwards the reader has already
                hesitated over the button. */}
            <p className="rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
              {t('sales.import.twoStepNote')}
            </p>
          </>
        )}
      </div>
    </Modal>
  )
}
