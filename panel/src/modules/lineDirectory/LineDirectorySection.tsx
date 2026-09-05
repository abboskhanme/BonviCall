/**
 * The line directory, on the roster page.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * It lives here rather than in a nav entry of its own because `/agents` is
 * already the page that answers "who is us": agents are our people, and this
 * is our other lines — the office, the warehouse, a second mobile. Same
 * question, same page, and it is far too small to be a section of the menu.
 *
 * It is gated on `settings:read` / `settings:write`, which is narrower than
 * the page's own `agents:read`, so a manager sees the roster and not this.
 *
 * **Adding a rule rewrites history.** Calls that already happened are
 * reclassified, so the result says how many changed — a directory edit is not
 * a preference, it is a correction applied backwards.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useState } from 'react'
import type { FormEvent } from 'react'
import { ChevronDown, ChevronRight, Plus, Trash2 } from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { messageForError } from '@/shared/api/errors'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { formatCount } from '@/shared/lib/format'
import { Badge, Button, Card, Input } from '@/shared/ui/primitives'
import { SELECT_CLASS } from '@/shared/ui/filters'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import {
  ruleExample,
  useAddDirectoryEntry,
  useLineDirectory,
  useRemoveDirectoryEntry,
  type DirectoryRuleKind,
} from './api'
import { RULE_KINDS, RULE_KIND_HINT, RULE_KIND_LABEL } from './labels'

export function LineDirectorySection() {
  const can = useAuth((state) => state.can)
  const mayRead = can(Perm.SETTINGS_READ)
  const mayWrite = can(Perm.SETTINGS_WRITE)

  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<DirectoryRuleKind>('suffix')
  const [pattern, setPattern] = useState('')
  const [label, setLabel] = useState('')
  const [reclassified, setReclassified] = useState<number | null>(null)

  const directoryQuery = useLineDirectory(mayRead && open)
  const add = useAddDirectoryEntry()
  const remove = useRemoveDirectoryEntry()

  if (!mayRead) return null

  const entries = directoryQuery.data?.items ?? []
  const digits = pattern.replace(/\D/g, '')
  const invalid = digits.length === 0

  function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (invalid) return
    add.mutate(
      { kind, pattern: digits, label: label.trim() === '' ? null : label.trim() },
      {
        onSuccess: (response) => {
          setPattern('')
          setLabel('')
          setReclassified(response.calls_reclassified)
        },
      },
    )
  }

  return (
    <Card className="p-4">
      <button
        type="button"
        className="flex w-full items-center gap-2 text-start"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="size-4 shrink-0 text-muted" aria-hidden />
        ) : (
          <ChevronRight className="size-4 shrink-0 text-muted" aria-hidden />
        )}
        <span className="text-sm font-semibold text-text">{t('lineDirectory.title')}</span>
        {open ? null : (
          <span className="text-xs text-muted">{t('lineDirectory.collapsedHint')}</span>
        )}
      </button>

      {open ? (
        <div className="mt-3 space-y-4">
          <p className="text-xs text-muted">{t('lineDirectory.subtitle')}</p>

          {/* The starvation warning. An empty directory does not fail loudly:
              it files every internal call as external, and the number that
              comes out looks like more business rather than like a bug. */}
          {directoryQuery.status === 'success' && entries.length === 0 ? (
            <p className="rounded-md border border-warn/40 bg-warn/5 p-3 text-xs text-text">
              {t('lineDirectory.emptyWarning')}
            </p>
          ) : null}

          {entries.length > 0 ? (
            <TableWrap>
              <Table>
                <THead>
                  <tr>
                    <TH>{t('lineDirectory.colPattern')}</TH>
                    <TH>{t('lineDirectory.colKind')}</TH>
                    <TH>{t('lineDirectory.colLabel')}</TH>
                    {mayWrite ? <TH className="w-0" /> : null}
                  </tr>
                </THead>
                <TBody>
                  {entries.map((entry) => (
                    <TR key={entry.id}>
                      <TD className="whitespace-nowrap font-mono">
                        {ruleExample(entry.kind, entry.pattern)}
                      </TD>
                      <TD className="whitespace-nowrap">
                        <Badge tone="neutral">{t(RULE_KIND_LABEL[entry.kind])}</Badge>
                      </TD>
                      <TD className="text-muted">{entry.label ?? '—'}</TD>
                      {mayWrite ? (
                        <TD>
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-label={t('lineDirectory.remove')}
                            title={t('lineDirectory.removeHint')}
                            disabled={remove.status === 'pending'}
                            onClick={() =>
                              remove.mutate(entry.id, {
                                onSuccess: (response) =>
                                  setReclassified(response.calls_reclassified),
                              })
                            }
                          >
                            <Trash2 className="size-3.5" aria-hidden />
                          </Button>
                        </TD>
                      ) : null}
                    </TR>
                  ))}
                </TBody>
              </Table>
            </TableWrap>
          ) : null}

          {mayWrite ? (
            <form className="flex flex-wrap items-end gap-3" onSubmit={handleAdd}>
              <label className="flex flex-col gap-1">
                <span className="text-2xs font-medium text-muted">
                  {t('lineDirectory.fieldKind')}
                </span>
                <select
                  className={SELECT_CLASS}
                  value={kind}
                  onChange={(event) => setKind(event.target.value as DirectoryRuleKind)}
                >
                  {RULE_KINDS.map((value) => (
                    <option key={value} value={value}>
                      {t(RULE_KIND_LABEL[value])}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-1">
                <span className="text-2xs font-medium text-muted">
                  {t('lineDirectory.fieldPattern')}
                </span>
                <Input
                  className="w-40"
                  value={pattern}
                  placeholder="700"
                  onChange={(event) => setPattern(event.target.value)}
                />
              </label>

              <label className="flex flex-col gap-1">
                <span className="text-2xs font-medium text-muted">
                  {t('lineDirectory.fieldLabel')}
                </span>
                <Input
                  className="w-52"
                  value={label}
                  placeholder={t('lineDirectory.fieldLabelHint')}
                  onChange={(event) => setLabel(event.target.value)}
                />
              </label>

              <Button type="submit" size="sm" disabled={invalid || add.status === 'pending'}>
                <Plus className="size-4" aria-hidden />
                {t('lineDirectory.add')}
              </Button>

              {/* What this rule will match, before it is saved. "Suffix" is
                  jargon; `…700` is not. */}
              <p className="w-full text-xs text-muted">
                {t('lineDirectory.willMatch', { example: ruleExample(kind, pattern) })}
                {' · '}
                {t(RULE_KIND_HINT[kind])}
              </p>
            </form>
          ) : null}

          {/* A directory change is only half done until the calls agree with
              it, so the count of rewritten calls is the receipt. */}
          {reclassified !== null ? (
            <p className="text-xs text-good">
              {t('lineDirectory.reclassified', { n: formatCount(reclassified) })}
            </p>
          ) : null}

          {add.error ? <p className="text-xs text-bad">{messageForError(add.error)}</p> : null}
          {remove.error ? <p className="text-xs text-bad">{messageForError(remove.error)}</p> : null}
          {directoryQuery.error ? (
            <p className="text-xs text-bad">{messageForError(directoryQuery.error)}</p>
          ) : null}
        </div>
      ) : null}
    </Card>
  )
}
