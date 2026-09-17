/**
 * The one dialog the rubric editor has (CONVENTIONS-CLIENT.md §3: create and
 * edit happen only inside a Modal).
 *
 * One modal for five targets — edit a criterion, add a criterion, edit a block,
 * edit a red flag, add a red flag — because they are the same form with
 * different fields showing, and five near-identical modals would drift apart
 * field by field. Ported from BonviZvonki's `EditModal`, with its two
 * deliberate refusals kept:
 *
 *  * **a new red flag never sets `zeroes_score`.** It is the heaviest sanction
 *    in the product — the whole score goes to 0 — and one miscategorised rule
 *    added in a hurry would zero an employee's month. Changing an existing flag
 *    to zero the score is a decision somebody makes on purpose, in the server's
 *    payload, not a checkbox beside a fresh label;
 *  * **`optional` defaults to false** on a new criterion, so a criterion nobody
 *    thought about is assessed rather than quietly droppable.
 *
 * Nothing here talks to the server. The dialog hands a changed draft back and
 * the page publishes it as a whole — a rubric is saved in one piece, because
 * half a rubric is a rubric whose blocks do not total 100.
 */
import { useState } from 'react'
import { Trash2 } from 'lucide-react'

import { t, type MessageKey } from '@/shared/i18n'
import { Button, Input } from '@/shared/ui/primitives'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'

import type { RubricBlock, RubricCriterion, RubricRedFlag } from './api'
import {
  addCriterion,
  flagKeyState,
  nextCriterionId,
  removeCriterion,
  replaceBlock,
  replaceCriterion,
  replaceFlag,
  slugify,
  type RubricDraft,
} from './state'

export type RubricEditTarget =
  | { kind: 'criterion'; blockIndex: number; index: number }
  | { kind: 'newCriterion'; blockIndex: number }
  | { kind: 'block'; index: number }
  | { kind: 'flag'; index: number }
  | { kind: 'newFlag' }

const TITLE: Record<RubricEditTarget['kind'], MessageKey> = {
  criterion: 'rubric.editCriterion',
  newCriterion: 'rubric.addCriterion',
  block: 'rubric.editBlock',
  flag: 'rubric.editFlag',
  newFlag: 'rubric.addFlag',
}

interface Form {
  id: string
  label: string
  points: number
  max: number
  penalty: number
  description: string
  optional: boolean
}

function formOf(target: RubricEditTarget, draft: RubricDraft): Form {
  const empty: Form = {
    id: '',
    label: '',
    points: 0,
    max: 0,
    penalty: -10,
    description: '',
    optional: false,
  }
  // Every index below is checked rather than asserted. The target always points
  // at something that exists — but a draft edited in another dialog could have
  // removed it, and a crash in a modal loses everything the admin typed.
  if (target.kind === 'criterion') {
    const criterion = draft.blocks[target.blockIndex]?.criteria[target.index]
    if (!criterion) return empty
    return {
      ...empty,
      id: criterion.id,
      label: criterion.label,
      points: criterion.points,
      description: criterion.description ?? '',
      optional: Boolean(criterion.optional),
    }
  }
  if (target.kind === 'newCriterion') {
    const block = draft.blocks[target.blockIndex]
    return { ...empty, id: block ? nextCriterionId(block) : '' }
  }
  if (target.kind === 'block') {
    const block = draft.blocks[target.index]
    if (!block) return empty
    return { ...empty, label: block.label, max: block.max }
  }
  if (target.kind === 'flag') {
    const flag = draft.redFlags[target.index]
    if (!flag) return empty
    return {
      ...empty,
      label: flag.label,
      penalty: flag.penalty,
      description: flag.description ?? '',
    }
  }
  return empty
}

export function RubricEditModal({
  target,
  draft,
  onApply,
  onClose,
}: {
  target: RubricEditTarget
  draft: RubricDraft
  onApply: (draft: RubricDraft) => void
  onClose: () => void
}) {
  const [form, setForm] = useState<Form>(() => formOf(target, draft))

  const isCriterion = target.kind === 'criterion' || target.kind === 'newCriterion'
  const isFlag = target.kind === 'flag' || target.kind === 'newFlag'

  // The key of a NEW flag is derived from its label: the admin thinks in
  // sentences, the model needs `shaxsiy_raqamga_ogdirish`. An existing flag
  // keeps its key — changing it would orphan every score that recorded it.
  const derivedKey = slugify(form.label)
  const keyState = flagKeyState(derivedKey, draft.redFlags)
  const labelOk = form.label.trim().length >= 2
  const idOk = !isCriterion || form.id.trim().length > 0
  const canSubmit = labelOk && idOk && (target.kind !== 'newFlag' || keyState === 'ok')

  const apply = () => {
    if (isCriterion) {
      const criterion: RubricCriterion = {
        id: form.id.trim(),
        label: form.label.trim(),
        points: form.points,
        description: form.description.trim() || null,
        optional: form.optional,
      }
      const blocks =
        target.kind === 'newCriterion'
          ? addCriterion(draft.blocks, target.blockIndex, criterion)
          : replaceCriterion(draft.blocks, target.blockIndex, target.index, criterion)
      onApply({ ...draft, blocks })
      return
    }
    if (target.kind === 'block') {
      const blocks: RubricBlock[] = replaceBlock(draft.blocks, target.index, {
        label: form.label.trim(),
        max: form.max,
      })
      onApply({ ...draft, blocks })
      return
    }
    if (target.kind === 'flag') {
      const existing = draft.redFlags[target.index]
      if (!existing) {
        onApply(draft)
        return
      }
      const flag: RubricRedFlag = {
        ...existing,
        label: form.label.trim(),
        penalty: form.penalty,
        description: form.description.trim() || null,
      }
      onApply({ ...draft, redFlags: replaceFlag(draft.redFlags, target.index, flag) })
      return
    }
    const added: RubricRedFlag = {
      type: derivedKey,
      label: form.label.trim(),
      penalty: form.penalty,
      // Never true on a new flag. See the file docstring.
      zeroes_score: false,
      description: form.description.trim() || null,
    }
    onApply({ ...draft, redFlags: [...draft.redFlags, added] })
  }

  const remove = () => {
    if (target.kind !== 'criterion') return
    onApply({
      ...draft,
      blocks: removeCriterion(draft.blocks, target.blockIndex, target.index),
    })
  }

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
      title={t(TITLE[target.kind])}
      onSubmit={(event) => {
        event.preventDefault()
        apply()
      }}
      submitDisabled={!canSubmit}
    >
      <ModalFields>
        {isCriterion ? (
          <ModalField htmlFor="rubric-criterion-id" label={t('rubric.criterionId')}>
            <Input
              id="rubric-criterion-id"
              className="font-mono"
              value={form.id}
              onChange={(event) => setForm({ ...form, id: event.target.value })}
            />
          </ModalField>
        ) : null}

        <ModalField htmlFor="rubric-label" label={t('rubric.label')}>
          <Input
            id="rubric-label"
            autoFocus
            value={form.label}
            onChange={(event) => setForm({ ...form, label: event.target.value })}
          />
        </ModalField>

        {isCriterion ? (
          <ModalField htmlFor="rubric-points" label={t('rubric.points')}>
            <Input
              id="rubric-points"
              type="number"
              min={0}
              max={100}
              value={String(form.points)}
              onChange={(event) => setForm({ ...form, points: Number(event.target.value) })}
            />
          </ModalField>
        ) : null}

        {isCriterion ? (
          <ModalField htmlFor="rubric-optional" label={t('rubric.optional')}>
            <label className="flex items-start gap-2 text-xs text-muted">
              <input
                id="rubric-optional"
                type="checkbox"
                checked={form.optional}
                onChange={(event) => setForm({ ...form, optional: event.target.checked })}
              />
              {t('rubric.optionalHint')}
            </label>
          </ModalField>
        ) : null}

        {target.kind === 'block' ? (
          <ModalField htmlFor="rubric-max" label={t('rubric.blockMax')}>
            <Input
              id="rubric-max"
              type="number"
              min={1}
              max={100}
              value={String(form.max)}
              onChange={(event) => setForm({ ...form, max: Number(event.target.value) })}
            />
          </ModalField>
        ) : null}

        {target.kind === 'newFlag' ? (
          <ModalField
            htmlFor="rubric-flag-key"
            label={t('rubric.flagKey')}
            error={
              form.label && keyState !== 'ok'
                ? t(
                    keyState === 'duplicate'
                      ? 'rubric.flagKeyDuplicate'
                      : 'rubric.flagKeyInvalid',
                  )
                : undefined
            }
          >
            {/* The key is shown and not typed: it goes to the model and into
                every score, and a key nobody can see is one nobody can debug. */}
            <p id="rubric-flag-key" className="font-mono text-xs text-text">
              {derivedKey || '—'}
            </p>
            <p className="mt-1 text-2xs text-muted">{t('rubric.flagKeyHint')}</p>
          </ModalField>
        ) : null}

        {isFlag ? (
          <ModalField htmlFor="rubric-penalty" label={t('rubric.penalty')}>
            <Input
              id="rubric-penalty"
              type="number"
              min={-100}
              max={0}
              value={String(form.penalty)}
              onChange={(event) => setForm({ ...form, penalty: Number(event.target.value) })}
            />
            <p className="mt-1 text-2xs text-muted">{t('rubric.penaltyHint')}</p>
          </ModalField>
        ) : null}

        {isCriterion || target.kind === 'flag' ? (
          <ModalField htmlFor="rubric-description" label={t('rubric.description')}>
            <Input
              id="rubric-description"
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
            />
          </ModalField>
        ) : null}

        {target.kind === 'criterion' ? (
          <Button variant="ghost" size="sm" className="text-bad" onClick={remove}>
            <Trash2 className="size-3.5" aria-hidden />
            {t('rubric.removeCriterion')}
          </Button>
        ) : null}
      </ModalFields>
    </Modal>
  )
}
