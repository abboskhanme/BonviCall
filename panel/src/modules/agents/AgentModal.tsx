/**
 * Edit an agent (CONVENTIONS-CLIENT.md §3 — never an inline form).
 *
 * Creating one is `CreateAgentModal`, which is a flow rather than a form: it
 * also registers the work number and issues the enrolment code, because
 * enrolling somebody used to take three separate places and the third was
 * invisible.
 *
 * An agent is a salesperson, not a login. This modal deliberately carries no
 * password, role or email field: `POST /agents` never creates a user, and a
 * form that mixed the two would invite exactly the conflation SPEC §3.2 spells
 * out. Login accounts are `/users`.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { Input } from '@/shared/ui/primitives'

import { useCreateAgent, useUpdateAgent, type Agent } from './api'

interface Draft {
  full_name: string
  employee_code: string
  hired_at: string
  note: string
  is_active: boolean
}

const EMPTY: Draft = {
  full_name: '',
  employee_code: '',
  hired_at: '',
  note: '',
  is_active: true,
}

function draftFrom(agent: Agent | null): Draft {
  if (!agent) return EMPTY
  return {
    full_name: agent.full_name,
    employee_code: agent.employee_code ?? '',
    hired_at: agent.hired_at ?? '',
    note: agent.note ?? '',
    is_active: agent.is_active,
  }
}

/** An empty optional field means "not set", which the API spells `null`. */
function orNull(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

export function AgentModal({
  open,
  onOpenChange,
  agent,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  agent: Agent | null
}) {
  const editing = agent !== null
  const [draft, setDraft] = useState<Draft>(() => draftFrom(agent))
  const [touched, setTouched] = useState(false)

  // Reopening for a different agent must not show the previous one's values.
  useEffect(() => {
    if (open) {
      setDraft(draftFrom(agent))
      setTouched(false)
    }
  }, [open, agent])

  const create = useCreateAgent()
  const update = useUpdateAgent(agent?.id ?? '')
  const mutation = editing ? update : create

  const nameMissing = draft.full_name.trim() === ''

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setTouched(true)
    if (nameMissing) return

    const shared = {
      full_name: draft.full_name.trim(),
      employee_code: orNull(draft.employee_code),
      hired_at: orNull(draft.hired_at),
      note: orNull(draft.note),
    }

    if (editing) {
      update.mutate(
        { ...shared, is_active: draft.is_active },
        { onSuccess: () => onOpenChange(false) },
      )
    } else {
      create.mutate(shared, { onSuccess: () => onOpenChange(false) })
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={editing ? t('agents.editTitle') : t('agents.createTitle')}
      description={editing ? undefined : t('agents.createHint')}
      onSubmit={handleSubmit}
      submitting={mutation.status === 'pending'}
      submitDisabled={nameMissing}
    >
      <ModalFields>
        <ModalField
          htmlFor="agent-name"
          label={t('agents.fieldName')}
          error={touched && nameMissing ? t('agents.nameRequired') : undefined}
        >
          <Input
            id="agent-name"
            value={draft.full_name}
            autoFocus
            onChange={(event) => setDraft({ ...draft, full_name: event.target.value })}
          />
        </ModalField>

        <ModalField htmlFor="agent-code" label={t('agents.fieldCode')}>
          <Input
            id="agent-code"
            value={draft.employee_code}
            placeholder={t('agents.fieldCodeHint')}
            onChange={(event) => setDraft({ ...draft, employee_code: event.target.value })}
          />
        </ModalField>

        <ModalField htmlFor="agent-hired" label={t('agents.fieldHired')}>
          <Input
            id="agent-hired"
            type="date"
            value={draft.hired_at}
            onChange={(event) => setDraft({ ...draft, hired_at: event.target.value })}
          />
        </ModalField>

        <ModalField htmlFor="agent-note" label={t('agents.fieldNote')}>
          <Input
            id="agent-note"
            value={draft.note}
            onChange={(event) => setDraft({ ...draft, note: event.target.value })}
          />
        </ModalField>

        {editing ? (
          <ModalField htmlFor="agent-active" label={t('agents.fieldActive')}>
            <label className="flex items-center gap-2 text-xs text-muted">
              <input
                id="agent-active"
                type="checkbox"
                checked={draft.is_active}
                onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })}
              />
              {t('agents.fieldActiveHint')}
            </label>
          </ModalField>
        ) : null}

        {mutation.error ? (
          <p className="text-2xs text-bad">{messageForError(mutation.error)}</p>
        ) : null}
      </ModalFields>
    </Modal>
  )
}
