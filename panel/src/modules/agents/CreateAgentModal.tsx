/**
 * `Xodim qo'shish` — one dialog, one outcome: a person who can be enrolled.
 *
 * Name, employee code, and the work number, and on success it issues the
 * enrolment code and shows it. The code is the point of the dialog, so the
 * dialog ENDS on it rather than closing and leaving the admin to go and find
 * what they just created — which is the state the client was in when they said
 * they could not work out where the code came from.
 *
 * The number is optional on purpose: the roster is also used for people who
 * have not been issued a line yet, and a required field would refuse a
 * legitimate case.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, X } from 'lucide-react'

import { messageForError } from '@/shared/api/errors'
import { moduleKey } from '@/shared/api/queryKeys'
import { t } from '@/shared/i18n'
import { formatPhone } from '@/shared/lib/format'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { Input } from '@/shared/ui/primitives'
import { SELECT_CLASS } from '@/shared/ui/filters'

import { EnrolmentCodeCard } from './EnrolmentCodeCard'
import { conflictingHolder, createAgentWithNumber, type FlowResult } from './createAgentFlow'

const SIM_OWNERS = ['company', 'employee'] as const
type SimOwner = (typeof SIM_OWNERS)[number]
const SIM_OWNER_LABEL: Record<SimOwner, 'numbers.simCompany' | 'numbers.simEmployee'> = {
  company: 'numbers.simCompany',
  employee: 'numbers.simEmployee',
}

/** One line of the outcome: what was done, or what was not and why. */
function Step({ done, label, detail }: { done: boolean; label: string; detail?: string }) {
  return (
    <li className="flex items-start gap-2 text-sm">
      {done ? (
        <Check className="mt-0.5 size-4 shrink-0 text-good" aria-hidden />
      ) : (
        <X className="mt-0.5 size-4 shrink-0 text-bad" aria-hidden />
      )}
      <span className={done ? 'text-text' : 'text-bad'}>
        {label}
        {detail ? <span className="block text-xs text-muted">{detail}</span> : null}
      </span>
    </li>
  )
}

/**
 * What actually happened, step by step.
 *
 * Rendered whenever the flow stopped early. An agent with no number is
 * recoverable in half a minute; an agent the admin believes failed but which
 * exists is how a roster grows a second Aziz Karimov — so the record of what
 * WAS done is as important as the error.
 */
function Outcome({ result }: { result: FlowResult }) {
  const holder = conflictingHolder(result.error)
  const wantedNumber = result.failedAt === 'number' || result.number !== null

  return (
    <div className="space-y-3">
      <ul className="space-y-2">
        <Step
          done={result.agent !== null}
          label={t('agents.stepAgent', { name: result.agent?.full_name ?? '' })}
        />
        {wantedNumber ? (
          <Step
            done={result.number !== null}
            label={
              result.number
                ? t(result.reusedNumber ? 'agents.stepNumberReused' : 'agents.stepNumber', {
                    number: formatPhone(result.number.e164) ?? result.number.e164,
                  })
                : t('agents.stepNumberFailed')
            }
          />
        ) : null}
        {result.number ? (
          <Step
            done={result.assigned}
            label={result.assigned ? t('agents.stepAssigned') : t('agents.stepAssignFailed')}
            detail={holder ? t('numbers.alreadyHeldBy', { name: holder }) : undefined}
          />
        ) : null}
        {result.assigned ? (
          <Step
            done={result.code !== null}
            label={result.code ? t('agents.stepCode') : t('agents.stepCodeFailed')}
          />
        ) : null}
      </ul>

      {result.failedAt && !holder ? (
        <p className="text-xs text-bad">{messageForError(result.error)}</p>
      ) : null}

      {/* What to do next, which is the only thing that turns a partial
          failure into a thirty-second fix rather than a mystery. */}
      {result.failedAt ? (
        <p className="text-xs text-muted">{t('agents.partialHint')}</p>
      ) : null}
    </div>
  )
}

export function CreateAgentModal({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [fullName, setFullName] = useState('')
  const [employeeCode, setEmployeeCode] = useState('')
  const [e164, setE164] = useState('')
  const [simOwner, setSimOwner] = useState<SimOwner>('company')
  const [touched, setTouched] = useState(false)
  const client = useQueryClient()

  const mutation = useMutation({
    mutationFn: createAgentWithNumber,
    onSettled: () => {
      // Everything may have moved, including on a partial failure — that is
      // exactly when a stale roster is most misleading.
      void client.invalidateQueries({ queryKey: moduleKey('agents') })
      void client.invalidateQueries({ queryKey: moduleKey('numbers') })
      void client.invalidateQueries({ queryKey: moduleKey('enrolment') })
    },
  })

  useEffect(() => {
    if (open) {
      setFullName('')
      setEmployeeCode('')
      setE164('')
      setSimOwner('company')
      setTouched(false)
      mutation.reset()
    }
    // `mutation` is stable enough for this; re-running on every render would
    // clear the result the dialog exists to show.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const result = mutation.data ?? null
  const nameMissing = fullName.trim() === ''

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setTouched(true)
    if (nameMissing) return
    mutation.mutate({
      agent: {
        full_name: fullName.trim(),
        employee_code: employeeCode.trim() === '' ? null : employeeCode.trim(),
      },
      ...(e164.trim() ? { e164: e164.trim(), simOwner } : {}),
    })
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={t('agents.createTitle')}
      description={result ? undefined : t('agents.createHint')}
      // Once the flow has run there is nothing left to submit: the dialog
      // becomes the receipt.
      onSubmit={result ? undefined : handleSubmit}
      submitting={mutation.status === 'pending'}
      submitDisabled={nameMissing}
      submitLabel={t('agents.createAction')}
    >
      <ModalFields>
        {result ? (
          <div className="space-y-4">
            <Outcome result={result} />
            {result.code ? <EnrolmentCodeCard code={result.code} /> : null}
          </div>
        ) : (
          <>
            <ModalField
              htmlFor="new-agent-name"
              label={t('agents.fieldName')}
              error={touched && nameMissing ? t('agents.nameRequired') : undefined}
            >
              <Input
                id="new-agent-name"
                value={fullName}
                autoFocus
                onChange={(event) => setFullName(event.target.value)}
              />
            </ModalField>

            <ModalField htmlFor="new-agent-code" label={t('agents.fieldCode')}>
              <Input
                id="new-agent-code"
                value={employeeCode}
                placeholder={t('agents.fieldCodeHint')}
                onChange={(event) => setEmployeeCode(event.target.value)}
              />
              {/* Named against the OTHER code, because these two got confused
                  in the field and the confusion cost an afternoon. */}
              <p className="mt-1 text-2xs text-muted">{t('agents.fieldCodeNotEnrolment')}</p>
            </ModalField>

            <ModalField htmlFor="new-agent-number" label={t('agents.fieldNumber')}>
              <Input
                id="new-agent-number"
                value={e164}
                placeholder="+998 90 111 22 33"
                onChange={(event) => setE164(event.target.value)}
              />
              <p className="mt-1 text-2xs text-muted">{t('agents.fieldNumberHint')}</p>
            </ModalField>

            {e164.trim() ? (
              <ModalField htmlFor="new-agent-sim" label={t('numbers.fieldSimOwner')}>
                <select
                  id="new-agent-sim"
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
            ) : null}

            {mutation.error ? (
              <p className="text-2xs text-bad">{messageForError(mutation.error)}</p>
            ) : null}
          </>
        )}
      </ModalFields>
    </Modal>
  )
}
