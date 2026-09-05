/**
 * Bulk roster import.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **Dry run first, always, and it is the server's default.** A roster import
 * that half-succeeded is worse than one that never ran: with fifteen people
 * you can see what happened, but you cannot tell which half without reading
 * every row, and the recovery is manual either way.
 *
 * So the dialog has two states — the diff, then the commit — and the second
 * is only reachable through the first. The admin sees per-row outcomes
 * (create / update / skip / error, each with its line number) before anything
 * is written.
 *
 * CSV as TEXT rather than a file upload, matching the endpoint: the realistic
 * source is a paste out of a spreadsheet or a chat message, and asking
 * somebody to save that as a file first is a step that earns nothing.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '@/shared/api/client'
import { messageForError } from '@/shared/api/errors'
import { moduleKey } from '@/shared/api/queryKeys'
import { t } from '@/shared/i18n'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { Badge } from '@/shared/ui/primitives'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'
import type { components } from '@/shared/api/types.gen'

type ImportResponse = components['schemas']['ImportAgentsResponse']
type ImportRow = components['schemas']['ImportRowResult']

/** `action` is a free string on the wire, so the tone is chosen defensively
 *  rather than through an exhaustive map that could not be exhaustive. */
function actionTone(action: string): 'good' | 'accent' | 'neutral' | 'bad' {
  switch (action) {
    case 'create':
      return 'good'
    case 'update':
      return 'accent'
    case 'skip':
      return 'neutral'
    default:
      return 'bad'
  }
}

function actionLabel(action: string): string {
  switch (action) {
    case 'create':
      return t('import.actionCreate')
    case 'update':
      return t('import.actionUpdate')
    case 'skip':
      return t('import.actionSkip')
    default:
      return t('import.actionError')
  }
}

export function ImportAgentsModal({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [csv, setCsv] = useState('')
  const [preview, setPreview] = useState<ImportResponse | null>(null)
  const [committed, setCommitted] = useState<ImportResponse | null>(null)
  const client = useQueryClient()

  const run = useMutation({
    mutationFn: (dryRun: boolean) =>
      api.post<ImportResponse>('/agents/import', { csv, dry_run: dryRun }),
    onSuccess: (response) => {
      if (response.dry_run) setPreview(response)
      else {
        setCommitted(response)
        void client.invalidateQueries({ queryKey: moduleKey('agents') })
      }
    },
  })

  useEffect(() => {
    if (open) {
      setCsv('')
      setPreview(null)
      setCommitted(null)
      run.reset()
    }
    // Re-running on every render would clear the diff the dialog exists to show.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const shown = committed ?? preview
  const busy = run.status === 'pending'

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (committed) return
    // The first submit previews; the second writes. There is no path that
    // writes without having shown the diff.
    run.mutate(preview !== null ? false : true)
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={t('import.title')}
      description={committed ? undefined : t('import.hint')}
      onSubmit={committed ? undefined : handleSubmit}
      submitting={busy}
      submitDisabled={csv.trim() === ''}
      submitLabel={preview ? t('import.commit') : t('import.preview')}
      className="w-[min(46rem,calc(100vw-2rem))]"
    >
      <ModalFields>
        {committed ? (
          <p className="text-sm text-good">
            {t('import.done', { created: committed.created, updated: committed.updated })}
          </p>
        ) : (
          <ModalField htmlFor="import-csv" label={t('import.fieldCsv')}>
            <textarea
              id="import-csv"
              rows={6}
              className="w-full rounded-md border border-border bg-surface px-3 py-2 font-mono text-xs text-text placeholder:text-muted"
              placeholder={'full_name,employee_code,hired_at\nAziz Karimov,BV-001,2024-07-24'}
              value={csv}
              onChange={(event) => {
                setCsv(event.target.value)
                // Editing invalidates the diff: committing a preview of
                // different text is exactly the half-import this guards.
                setPreview(null)
              }}
            />
            <p className="mt-1 text-2xs text-muted">{t('import.fieldCsvHint')}</p>
          </ModalField>
        )}

        {shown ? (
          <div className="space-y-2">
            <p className="flex flex-wrap gap-2 text-xs">
              <Badge tone="good">{t('import.created', { n: shown.created })}</Badge>
              <Badge tone="accent">{t('import.updated', { n: shown.updated })}</Badge>
              <Badge tone="neutral">{t('import.skipped', { n: shown.skipped })}</Badge>
              {shown.errors > 0 ? (
                <Badge tone="bad">{t('import.errors', { n: shown.errors })}</Badge>
              ) : null}
            </p>

            {shown.rows.length > 0 ? (
              <TableWrap className="max-h-64 overflow-y-auto">
                <Table>
                  <THead>
                    <tr>
                      <TH className="w-0">{t('import.colLine')}</TH>
                      <TH>{t('import.colName')}</TH>
                      <TH>{t('import.colCode')}</TH>
                      <TH>{t('import.colAction')}</TH>
                      <TH>{t('import.colReason')}</TH>
                    </tr>
                  </THead>
                  <TBody>
                    {shown.rows.map((row: ImportRow) => (
                      <TR key={`${row.line}-${row.full_name}`}>
                        <TD className="text-end font-mono text-xs text-muted">{row.line}</TD>
                        <TD>{row.full_name}</TD>
                        <TD className="font-mono text-xs text-muted">{row.employee_code ?? '—'}</TD>
                        <TD>
                          <Badge tone={actionTone(row.action)}>{actionLabel(row.action)}</Badge>
                        </TD>
                        <TD className="text-xs text-muted">{row.reason ?? ''}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </TableWrap>
            ) : null}

            {preview && !committed ? (
              <p className="text-xs text-warn">{t('import.previewOnly')}</p>
            ) : null}
          </div>
        ) : null}

        {run.error ? <p className="text-2xs text-bad">{messageForError(run.error)}</p> : null}
      </ModalFields>
    </Modal>
  )
}
