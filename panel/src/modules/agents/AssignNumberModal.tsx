/**
 * Hand a work number to an agent, or register a new line and hand it over.
 *
 * Both paths live in one modal because they are one intent: "this person needs
 * a number". Making the admin visit a separate section to create the line
 * first was the navigation overhead the client asked us to remove.
 *
 * 409 `number_already_assigned` **names the current holder** in the envelope's
 * `detail` (UC-01's acceptance criterion), so this surfaces who has it rather
 * than a generic conflict. "That number is taken" is not actionable; "Sanjar
 * Toshev holds it" is.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import { isApiError, messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { formatPhone } from '@/shared/lib/format'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { Input } from '@/shared/ui/primitives'
import { SELECT_CLASS } from '@/shared/ui/filters'

import { useAssignNumber, useCreateNumber, useNumbers } from '@/modules/numbers/api'
import type { Agent } from './api'

const NEW_NUMBER = '__new__'

/**
 * Who owns the SIM (R10).
 *
 * Not a generated union: the server declares `sim_owner` as a string with a
 * `^(company|employee)$` pattern rather than an enum, so `types.gen.ts` offers
 * only `string`. Declared here as a closed list with the values the pattern
 * allows; an enum on the server would make this constant unnecessary.
 *
 * It is asked rather than defaulted because the answer decides whether a
 * recording is Bonvi's to keep at all: a call on an employee's personal SIM is
 * a different legal position from one on a company line.
 */
const SIM_OWNERS = ['company', 'employee'] as const
type SimOwner = (typeof SIM_OWNERS)[number]
const SIM_OWNER_LABEL: Record<SimOwner, 'numbers.simCompany' | 'numbers.simEmployee'> = {
  company: 'numbers.simCompany',
  employee: 'numbers.simEmployee',
}

/** The holder named by a 409, when the server sent one. */
function holderFrom(error: unknown): string | null {
  if (!isApiError(error) || error.code !== 'number_already_assigned') return null
  const detail = error.detail
  const holder = detail?.holder ?? detail?.agent_name ?? detail?.current_holder
  return typeof holder === 'string' && holder.length > 0 ? holder : null
}

export function AssignNumberModal({
  open,
  onOpenChange,
  agent,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  agent: Agent
}) {
  const numbersQuery = useNumbers(true)
  const [selected, setSelected] = useState('')
  const [newNumber, setNewNumber] = useState('')
  const [simOwner, setSimOwner] = useState<SimOwner>('company')
  const [note, setNote] = useState('')
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    if (open) {
      setSelected('')
      setNewNumber('')
      setSimOwner('company')
      setNote('')
      setTouched(false)
    }
  }, [open])

  const createNumber = useCreateNumber()
  const assign = useAssignNumber()

  const creatingNew = selected === NEW_NUMBER
  const missing = selected === '' || (creatingNew && newNumber.trim() === '')
  const submitting = createNumber.status === 'pending' || assign.status === 'pending'
  const error = assign.error ?? createNumber.error
  const holder = holderFrom(assign.error)

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setTouched(true)
    if (missing) return

    const body = { agent_id: agent.id, note: note.trim() === '' ? null : note.trim() }
    const done = { onSuccess: () => onOpenChange(false) }

    if (creatingNew) {
      // Register the line, then hand it over. Two calls because they are two
      // separate facts — the number exists, and this person holds it from now
      // — and only the second one can fail with "somebody else has it".
      createNumber.mutate(
        { e164: newNumber.trim(), sim_owner: simOwner },
        { onSuccess: (created) => assign.mutate({ numberId: created.id, body }, done) },
      )
      return
    }

    assign.mutate({ numberId: selected, body }, done)
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={t('numbers.assignTitle')}
      description={t('numbers.assignHint', { name: agent.full_name })}
      onSubmit={handleSubmit}
      submitting={submitting}
      submitDisabled={missing}
      submitLabel={t('numbers.assignAction')}
    >
      <ModalFields>
        <ModalField
          htmlFor="assign-number"
          label={t('numbers.fieldNumber')}
          error={touched && selected === '' ? t('numbers.numberRequired') : undefined}
        >
          <select
            id="assign-number"
            className={`${SELECT_CLASS} w-full`}
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
          >
            <option value="">{t('numbers.choose')}</option>
            {(numbersQuery.data?.items ?? []).map((number) => (
              <option key={number.id} value={number.id}>
                {formatPhone(number.e164) ?? number.e164}
              </option>
            ))}
            <option value={NEW_NUMBER}>{t('numbers.registerNew')}</option>
          </select>
        </ModalField>

        {creatingNew ? (
          <>
            <ModalField
              htmlFor="assign-new-number"
              label={t('numbers.fieldNewNumber')}
              error={touched && newNumber.trim() === '' ? t('numbers.numberRequired') : undefined}
            >
              <Input
                id="assign-new-number"
                value={newNumber}
                placeholder="+998 90 111 22 33"
                onChange={(event) => setNewNumber(event.target.value)}
              />
            </ModalField>
            <ModalField htmlFor="assign-sim-owner" label={t('numbers.fieldSimOwner')}>
              <select
                id="assign-sim-owner"
                className={`${SELECT_CLASS} w-full`}
                value={simOwner}
                onChange={(event) => setSimOwner(event.target.value as SimOwner)}
              >
                {SIM_OWNERS.map((owner) => (
                  <option key={owner} value={owner}>
                    {t(SIM_OWNER_LABEL[owner])}
                  </option>
                ))}
              </select>
            </ModalField>
          </>
        ) : null}

        <ModalField htmlFor="assign-note" label={t('numbers.fieldNote')}>
          <Input
            id="assign-note"
            value={note}
            placeholder={t('numbers.fieldNoteHint')}
            onChange={(event) => setNote(event.target.value)}
          />
        </ModalField>

        {holder ? (
          <p className="text-2xs text-bad">{t('numbers.alreadyHeldBy', { name: holder })}</p>
        ) : error ? (
          <p className="text-2xs text-bad">{messageForError(error)}</p>
        ) : null}
      </ModalFields>
    </Modal>
  )
}
