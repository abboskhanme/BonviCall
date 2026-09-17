/**
 * `/rubric` — the scoring rubric, viewable and editable (SPEC-ANALYTICS §2.5).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **This page decides how every employee is scored.** Four things follow from
 * that, and each is visible on screen rather than left to a tooltip:
 *
 *   the running total      100 / 100, and the save button is dead until it is.
 *                          The server refuses anything else (422), so an editor
 *                          that let you fill the whole form first would be
 *                          teaching people to distrust the button.
 *   `optional`             marked on every criterion it is set on. It is why a
 *                          30-second "send me 50 of them" call is not scored
 *                          against a full sales script, and an admin who cannot
 *                          see the flag cannot explain the score.
 *   the prompt             readable, and only the admin's own section editable.
 *                          The language rules, the scoring order and the
 *                          response format are shown and locked: break one and
 *                          EVERY answer fails validation.
 *   the history            because publishing is versioned and every score
 *                          names the version that produced it. Going back is a
 *                          button here; deleting a version is not possible at
 *                          all.
 *
 * Reading needs `analysis:read` — a score whose criteria are invisible is a
 * number nobody can argue with. Editing needs `settings:write`, which is admin
 * only: this is a change that costs money on every call afterwards.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useState } from 'react'
import { AlertTriangle, Check, History, Lock, Pencil, Plus, RotateCcw } from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { messageForError } from '@/shared/api/errors'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageGrid, PageHeader } from '@/shared/layout/Page'
import { formatCount, formatDateTime } from '@/shared/lib/format'
import { cn } from '@/shared/lib/cn'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { Section } from '@/shared/ui/detail'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'

import {
  useActivateRubricVersion,
  useActiveRubric,
  usePublishRubric,
  useRubricPrompt,
  useRubricVersions,
  type Rubric,
  type RubricBlock,
  type RubricVersion,
} from './api'
import { PublishRubricModal } from './PublishRubricModal'
import { RubricEditModal, type RubricEditTarget } from './RubricEditModal'
import {
  blockTotal,
  draftOf,
  isDirty,
  isPublishable,
  rubricTotal,
  TOTAL_POINTS,
  type RubricDraft,
} from './state'

// ───────────────────────────────────────────────────────────────────────────
//  The toolbar: what it adds up to, and what may be done about it
// ───────────────────────────────────────────────────────────────────────────

function BalanceCard({
  rubric,
  draft,
  canEdit,
  dirty,
  onPublish,
}: {
  rubric: Rubric
  draft: RubricDraft
  canEdit: boolean
  dirty: boolean
  onPublish: () => void
}) {
  const total = rubricTotal(draft.blocks)
  const balanced = total === TOTAL_POINTS

  return (
    <Card className={cn('flex flex-wrap items-center gap-4 p-4', !balanced && 'border-bad/40')}>
      <span
        className={cn(
          'flex size-9 items-center justify-center rounded-md',
          balanced ? 'bg-good/10 text-good' : 'bg-bad/10 text-bad',
        )}
        aria-hidden
      >
        {balanced ? <Check className="size-4" /> : <AlertTriangle className="size-4" />}
      </span>

      <div className="min-w-[12rem] flex-1">
        <p className="text-sm font-medium text-text">
          {t('rubric.total')}:{' '}
          <span className="font-mono tabular-nums">
            {t('rubric.ofHundred', { total: formatCount(total) })}
          </span>
        </p>
        <p className="text-xs text-muted">
          {balanced ? t('rubric.balanced') : t('rubric.unbalanced')}
        </p>
      </div>

      <Badge tone={rubric.stored ? 'accent' : 'warn'}>
        <History className="me-1 size-3" aria-hidden />
        {rubric.label}
      </Badge>

      {canEdit ? (
        <Button disabled={!dirty || !isPublishable(draft)} onClick={onPublish}>
          {t('rubric.save')}
        </Button>
      ) : (
        <span className="inline-flex items-center gap-1.5 text-xs text-muted">
          <Lock className="size-3.5" aria-hidden />
          {t('rubric.adminOnly')}
        </span>
      )}
    </Card>
  )
}

// ───────────────────────────────────────────────────────────────────────────
//  One block, and the criteria under it
// ───────────────────────────────────────────────────────────────────────────

function BlockCard({
  block,
  index,
  canEdit,
  onEdit,
}: {
  block: RubricBlock
  index: number
  canEdit: boolean
  onEdit: (target: RubricEditTarget) => void
}) {
  const sum = blockTotal(block)
  const balanced = sum === block.max

  return (
    <Section
      title={block.label}
      description={t('rubric.blockHint', { sum, max: block.max })}
      actions={
        <>
          <Badge tone={balanced ? 'good' : 'bad'}>
            <span className="font-mono tabular-nums">
              {sum}/{block.max}
            </span>
          </Badge>
          {canEdit ? (
            <Button
              variant="ghost"
              size="sm"
              aria-label={t('rubric.editBlock')}
              onClick={() => onEdit({ kind: 'block', index })}
            >
              <Pencil className="size-3.5" aria-hidden />
            </Button>
          ) : null}
        </>
      }
    >
      <ul className="flex flex-col gap-1.5">
        {block.criteria.map((criterion, criterionIndex) => (
          <li key={criterion.id}>
            <button
              type="button"
              disabled={!canEdit}
              onClick={() =>
                onEdit({ kind: 'criterion', blockIndex: index, index: criterionIndex })
              }
              className={cn(
                'flex w-full items-start gap-3 rounded-md bg-surface-2 p-3 text-start',
                canEdit && 'hover:bg-border',
              )}
            >
              <Badge className="font-mono">{criterion.id}</Badge>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-text">{criterion.label}</span>
                  {/* An optional criterion must be VISIBLE: it is the answer to
                      "why was this criterion not scored on that call?" */}
                  {criterion.optional ? (
                    <Badge tone="neutral">{t('rubric.optionalBadge')}</Badge>
                  ) : null}
                </span>
                {criterion.description ? (
                  <span className="mt-0.5 block text-xs text-muted">{criterion.description}</span>
                ) : null}
              </span>
              <span className="font-mono text-sm font-semibold tabular-nums text-text">
                {criterion.points}
              </span>
            </button>
          </li>
        ))}
      </ul>

      {canEdit ? (
        <Button
          variant="secondary"
          size="sm"
          className="mt-2 w-full"
          onClick={() => onEdit({ kind: 'newCriterion', blockIndex: index })}
        >
          <Plus className="size-3.5" aria-hidden />
          {t('rubric.addCriterion')}
        </Button>
      ) : null}
    </Section>
  )
}

// ───────────────────────────────────────────────────────────────────────────
//  The prompt, read-only
// ───────────────────────────────────────────────────────────────────────────

function PromptView() {
  const promptQuery = useRubricPrompt()

  return (
    <QueryBoundary query={promptQuery} skeletonRows={4}>
      {(prompt) => (
        <Section
          title={t('rubric.promptTitle')}
          description={t('rubric.promptHint')}
          actions={
            <Badge tone="neutral">
              <span className="font-mono tabular-nums">
                {t('rubric.promptSize', {
                  chars: formatCount(prompt.char_count),
                  tokens: formatCount(prompt.approx_tokens),
                })}
              </span>
            </Badge>
          }
        >
          <div className="flex flex-col gap-2">
            {prompt.sections
              // An empty section is not rendered: an empty frame reads as
              // "something is missing here".
              .filter((section) => section.text.trim().length > 0)
              .map((section) => (
                <div
                  key={section.key}
                  className={cn(
                    'rounded-md p-3',
                    section.editable ? 'bg-accent-soft' : 'bg-surface-2',
                  )}
                >
                  <div className="mb-1.5 flex items-center gap-2">
                    <Badge tone={section.editable ? 'accent' : 'neutral'}>
                      {section.editable ? (
                        <Pencil className="me-1 size-3" aria-hidden />
                      ) : (
                        <Lock className="me-1 size-3" aria-hidden />
                      )}
                      {t(section.editable ? 'rubric.promptEditable' : 'rubric.promptLocked')}
                    </Badge>
                    <span className="font-mono text-2xs text-muted">{section.key}</span>
                  </div>
                  <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-2xs leading-relaxed text-muted">
                    {section.text.trim()}
                  </pre>
                </div>
              ))}
            <p className="text-2xs leading-relaxed text-muted">{t('rubric.promptNote')}</p>
          </div>
        </Section>
      )}
    </QueryBoundary>
  )
}

// ───────────────────────────────────────────────────────────────────────────
//  The history, and going back
// ───────────────────────────────────────────────────────────────────────────

function VersionRow({ version, canEdit }: { version: RubricVersion; canEdit: boolean }) {
  const activate = useActivateRubricVersion()
  const pending = activate.status === 'pending'

  return (
    <li className="flex flex-wrap items-center gap-3 rounded-md bg-surface-2 px-3 py-2.5">
      <Badge tone={version.is_active ? 'accent' : 'neutral'} className="font-mono">
        {version.label}
      </Badge>
      <span className="min-w-0 flex-1 truncate text-sm text-text">{version.name}</span>
      <span className="text-2xs text-muted">{formatDateTime(version.created_at)}</span>
      {version.is_active ? (
        <Badge tone="good">{t('rubric.activeBadge')}</Badge>
      ) : canEdit ? (
        <Button
          variant="secondary"
          size="sm"
          disabled={pending}
          onClick={() => activate.mutate(version.version)}
        >
          <RotateCcw className="size-3.5" aria-hidden />
          {pending ? t('rubric.restoring') : t('rubric.restore')}
        </Button>
      ) : null}
      {activate.error ? (
        <span className="text-2xs text-bad">{messageForError(activate.error)}</span>
      ) : null}
    </li>
  )
}

function VersionHistory({ canEdit }: { canEdit: boolean }) {
  const versionsQuery = useRubricVersions()

  return (
    <QueryBoundary
      query={versionsQuery}
      isEmpty={(data) => data.total === 0}
      emptyTitle={t('rubric.historyEmpty')}
      emptyHint={t('rubric.historyEmptyHint')}
      skeletonRows={2}
    >
      {(versions) => (
        <Section title={t('rubric.history')} description={t('rubric.historyHint')}>
          <ul className="flex flex-col gap-1.5">
            {versions.items.map((version) => (
              <VersionRow key={version.version} version={version} canEdit={canEdit} />
            ))}
          </ul>
        </Section>
      )}
    </QueryBoundary>
  )
}

// ───────────────────────────────────────────────────────────────────────────
//  The editor
// ───────────────────────────────────────────────────────────────────────────

function RubricEditor({ rubric }: { rubric: Rubric }) {
  const can = useAuth((state) => state.can)
  const canEdit = can(Perm.SETTINGS_WRITE)

  const [draft, setDraft] = useState<RubricDraft>(() => draftOf(rubric))
  const [target, setTarget] = useState<RubricEditTarget | null>(null)
  const [promptOpen, setPromptOpen] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const publish = usePublishRubric()

  const dirty = isDirty(draft, rubric)

  return (
    <>
      <BalanceCard
        rubric={rubric}
        draft={draft}
        canEdit={canEdit}
        dirty={dirty}
        onPublish={() => setPublishing(true)}
      />

      {/* Nothing published yet: the page says which rubric is really scoring
          rather than pretending somebody chose it. */}
      {!rubric.stored ? (
        <Card className="flex items-start gap-3 border-warn/40 bg-warn/5 p-3">
          <History className="size-4 shrink-0 text-warn" aria-hidden />
          <div>
            <p className="text-sm font-medium text-text">{t('rubric.pinned')}</p>
            <p className="text-xs text-muted">{t('rubric.pinnedHint')}</p>
          </div>
        </Card>
      ) : null}

      <PageGrid>
        {draft.blocks.map((block, index) => (
          <BlockCard
            key={block.key}
            block={block}
            index={index}
            canEdit={canEdit}
            onEdit={setTarget}
          />
        ))}
      </PageGrid>

      <Section
        title={t('rubric.redFlags')}
        description={t('rubric.redFlagsHint')}
        actions={
          canEdit ? (
            <Button variant="secondary" size="sm" onClick={() => setTarget({ kind: 'newFlag' })}>
              <Plus className="size-3.5" aria-hidden />
              {t('rubric.addFlag')}
            </Button>
          ) : null
        }
      >
        <ul className="grid gap-1.5 xl:grid-cols-2">
          {draft.redFlags.map((flag, index) => (
            <li key={flag.type}>
              <button
                type="button"
                // A flag that zeroes the whole score is not edited from a list
                // row: changing it is a decision, not a click on the way past.
                disabled={!canEdit || flag.zeroes_score}
                onClick={() => setTarget({ kind: 'flag', index })}
                className={cn(
                  'flex w-full items-center gap-3 rounded-md bg-surface-2 p-3 text-start',
                  canEdit && !flag.zeroes_score && 'hover:bg-border',
                )}
              >
                <AlertTriangle className="size-4 shrink-0 text-bad" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-text">{flag.label}</span>
                  <span className="block font-mono text-2xs text-muted">{flag.type}</span>
                </span>
                {flag.zeroes_score ? (
                  <Badge tone="bad">{t('rubric.zeroesScore')}</Badge>
                ) : (
                  <span className="font-mono text-sm font-semibold tabular-nums text-bad">
                    {flag.penalty}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </Section>

      <Section
        title={t('rubric.extraRules')}
        description={t('rubric.extraRulesHint')}
        actions={
          <Button variant="ghost" size="sm" onClick={() => setPromptOpen((open) => !open)}>
            {t(promptOpen ? 'rubric.promptHide' : 'rubric.promptShow')}
          </Button>
        }
      >
        {canEdit ? (
          <>
            <textarea
              id="rubric-extra-rules"
              rows={8}
              maxLength={rubric.extra_rules_limit}
              aria-label={t('rubric.extraRules')}
              placeholder={t('rubric.extraRulesPlaceholder')}
              className="w-full resize-y rounded-md border border-border bg-surface px-3 py-2 text-xs leading-relaxed text-text placeholder:text-muted"
              value={draft.extraRules}
              onChange={(event) => setDraft({ ...draft, extraRules: event.target.value })}
            />
            {/* The counter is not decoration: this text rides on EVERY call, so
                its length is money. The limit is the server's, sent with the
                rubric, so the two cannot disagree. */}
            <p className="mt-2 text-2xs text-muted">
              {t('rubric.extraRulesCount', {
                count: draft.extraRules.length,
                limit: rubric.extra_rules_limit,
              })}
            </p>
          </>
        ) : (
          <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted">
            {draft.extraRules || t('rubric.extraRulesEmpty')}
          </p>
        )}
      </Section>

      {promptOpen ? <PromptView /> : null}

      <VersionHistory canEdit={canEdit} />

      {target ? (
        <RubricEditModal
          key={JSON.stringify(target)}
          target={target}
          draft={draft}
          onApply={(next) => {
            setDraft(next)
            setTarget(null)
          }}
          onClose={() => setTarget(null)}
        />
      ) : null}

      {publishing ? (
        <PublishRubricModal
          // Nothing published yet means the FIRST version is about to exist —
          // the pinned default is not a row, so the server numbers it 1 and the
          // suggested name must say so.
          nextVersion={rubric.stored ? rubric.version + 1 : 1}
          pending={publish.status === 'pending'}
          error={publish.error}
          onClose={() => setPublishing(false)}
          onPublish={(fields) =>
            publish.mutate(
              {
                ...fields,
                blocks: draft.blocks,
                red_flags: draft.redFlags,
                // An empty box means "no instructions": an empty string would
                // leave the prompt with a heading and nothing under it.
                extra_rules: draft.extraRules.trim() || null,
              },
              { onSuccess: () => setPublishing(false) },
            )
          }
        />
      ) : null}
    </>
  )
}

export function RubricPage() {
  const rubricQuery = useActiveRubric()

  return (
    <Page>
      <PageHeader title={t('page.rubric')} description={t('rubric.subtitle')} />
      <QueryBoundary query={rubricQuery} skeletonRows={6}>
        {(rubric) => (
          // Remounted when the active version changes, so the draft is
          // re-initialised from the server's answer after publishing or going
          // back — no effect syncing two sources of the same state.
          <RubricEditor key={`${rubric.label}-${String(rubric.stored)}`} rubric={rubric} />
        )}
      </QueryBoundary>
    </Page>
  )
}
