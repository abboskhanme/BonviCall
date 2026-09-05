/**
 * `/calls/:id` — the call card (SPEC §5.2).
 *
 * Everything known about one call, in Uzbek, including **why there is no
 * recording** where there is none. A wrong owner answers 404 and not 403
 * (UC-21), so this page's error state is also the "not yours" state — and it
 * says the same thing for both, which is the point of the server's choice.
 *
 * **The player never uses a bare `<audio src>`.** N43 requires HTTP Range on
 * the audio endpoint and the endpoint requires an `Authorization` header,
 * which `<audio src>` cannot send — so a plain src would play from the start
 * and then fail to seek, a bug that looks like a working feature. The Service
 * Worker bridge in `public/audio-sw.js` adds the header in flight; see
 * `./audio.ts` for both routes and why the fallback is required too.
 */
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Pencil } from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { Page, PageHeader } from '@/shared/layout/Page'
import {
  formatDateTime,
  formatDateTimeOrDash,
  formatDuration,
  formatInstantTitle,
  formatPhone,
} from '@/shared/lib/format'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { Field, FieldGrid, Section } from '@/shared/ui/detail'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'

import { AudioPlayer } from './AudioPlayer'
import { useCall, useUpdateCallNote, type Call } from './api'
import {
  audioState,
  audioStateLabel,
  audioStateTone,
  CALL_TYPE_LABEL,
  CAPTURE_ROUTE_LABEL,
  DIRECTION_LABEL,
  DISPOSITION_LABEL,
  DISPOSITION_TONE,
  SOURCE_LABEL,
} from './labels'

function boolText(value: boolean): string {
  return value ? t('common.yes') : t('common.no')
}

/**
 * The recording, or the reason there is none — and there are three reasons,
 * not two.
 *
 * UC-14: the call is always logged, and a call without audio always carries a
 * reason from a closed enum. But `available === false` also covers a recording
 * that DID exist and was removed by the 12-month retention job, which is the
 * system working correctly and is nobody's fault. Those two get different
 * words and different colours here, deliberately — see `audioState()` in
 * ./labels. A dead play button answers none of it (SPEC §5.3).
 */
function AudioSection({ call }: { call: Call }) {
  const state = audioState(call.audio)
  const audio = call.audio

  return (
    <Card className="p-4">
      <h2 className="mb-3 text-sm font-semibold text-text">{t('callDetail.sectionAudio')}</h2>

      <div className="space-y-3">
        {/* The badge names the STATE; the paragraph below gives the reason.
            On the list the badge carries the reason itself, because a table
            cell has one line and the reason is the point there. */}
        <Badge tone={audioStateTone(state)}>
          {t(
            state.kind === 'available'
              ? 'calls.audio.present'
              : state.kind === 'expired'
                ? 'calls.audio.expired'
                : 'calls.audio.missing',
          )}
        </Badge>

        {/* A player ONLY when the recording is actually playable. The other
            two states get words, not a control that would answer 410 or
            simply do nothing. */}
        {state.kind === 'available' ? (
          <AudioPlayer callId={call.id} url={audio.url} />
        ) : null}

        {state.kind === 'expired' ? (
          /* The recording existed. Saying only "no recording" here would read
             as a capture failure, which it is not. */
          <p className="text-sm text-text">
            {t('callDetail.audioExpired', { date: formatDateTime(state.expiredAt) })}
          </p>
        ) : null}

        {state.kind === 'missing' || state.kind === 'unknown' ? (
          <p className="text-sm text-text">{t(audioStateLabel(state))}</p>
        ) : null}

        {audio.duration_mismatch ? (
          <p className="text-xs text-warn">{t('callDetail.durationMismatch')}</p>
        ) : null}

        <FieldGrid className="pt-1">
          {/* The capture route stays visible even when the audio is gone: the
              per-model capture rate is the M0 baseline and UC-23 compares
              against it, so "which mechanism ran on this handset" must remain
              answerable after retention has removed the file. */}
          <Field
            label={t('callDetail.captureRoute')}
            value={audio.capture_route ? t(CAPTURE_ROUTE_LABEL[audio.capture_route]) : null}
          />
          <Field
            label={t('callDetail.captureRouteDetail')}
            value={audio.capture_route_detail ?? null}
          />
          <Field
            label={t('callDetail.audioDuration')}
            value={
              audio.duration_ms === null || audio.duration_ms === undefined
                ? null
                : formatDuration(Math.round(audio.duration_ms / 1000))
            }
          />
        </FieldGrid>
      </div>
    </Card>
  )
}

/**
 * The note. `calls:note` only — a user without it never sees the button
 * (CONVENTIONS.md §11); the server refuses the PATCH regardless, which is the
 * check that decides anything.
 *
 * Editing happens in a Modal, never as an inline form on the page
 * (CONVENTIONS-CLIENT.md §3).
 */
function NoteSection({ call }: { call: Call }) {
  const can = useAuth((state) => state.can)
  const mayEdit = can(Perm.CALLS_NOTE)
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(call.note ?? '')
  const mutation = useUpdateCallNote(call.id)
  const submitting = mutation.status === 'pending'

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    mutation.mutate(draft.trim() === '' ? null : draft.trim(), {
      onSuccess: () => setOpen(false),
    })
  }

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-text">{t('callDetail.sectionNote')}</h2>
        {mayEdit ? (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setDraft(call.note ?? '')
              setOpen(true)
            }}
          >
            <Pencil className="size-3.5" aria-hidden />
            {t('callDetail.noteEdit')}
          </Button>
        ) : null}
      </div>

      {call.note ? (
        <p className="whitespace-pre-wrap text-sm text-text">{call.note}</p>
      ) : (
        <p className="text-sm text-muted">{t('callDetail.noteEmpty')}</p>
      )}

      {mayEdit ? (
        <Modal
          open={open}
          onOpenChange={setOpen}
          title={t('callDetail.noteEdit')}
          onSubmit={onSubmit}
          submitting={submitting}
        >
          <ModalFields>
            <ModalField
              htmlFor="call-note"
              label={t('callDetail.noteLabel')}
              error={mutation.error ? messageForError(mutation.error) : undefined}
            >
              <textarea
                id="call-note"
                rows={5}
                maxLength={4000}
                className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-muted"
                placeholder={t('callDetail.notePlaceholder')}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                disabled={submitting}
              />
            </ModalField>
          </ModalFields>
        </Modal>
      ) : null}
    </Card>
  )
}

/**
 * One side of the call: a person and the number they were on.
 *
 * Both sides share a shape so the eye can compare them, and the client side
 * survives a withheld number — that is a real and common case (SPEC §4.0
 * stores an unparseable or absent number rather than rejecting the call), and
 * an empty half would read as a rendering fault rather than as a fact about
 * the call.
 */
function Party({
  role,
  name,
  number,
  align = 'start',
}: {
  role: string
  name: string | null
  number: string | null
  align?: 'start' | 'end'
}) {
  const alignment = align === 'end' ? 'items-end text-end' : 'items-start text-start'
  return (
    <div className={cn('flex min-w-0 flex-col gap-0.5', alignment)}>
      <span className="text-2xs font-medium uppercase tracking-wide text-muted">{role}</span>
      <span className="truncate font-mono text-lg font-semibold text-text">
        {number ?? t('calls.numberWithheld')}
      </span>
      {name ? <span className="truncate text-sm text-muted">{name}</span> : null}
    </div>
  )
}

/**
 * The header: a call **between two people**, not a row of facts.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * The employee is on the left, the client on the right, and the direction is
 * an arrow between them — pointing right when the employee called out,
 * pointing left when the client called in. Direction is the first thing
 * anybody wants from a call record and it should not require reading a badge
 * to get.
 *
 * The arrow is decorative to a screen reader (`aria-hidden`); the direction
 * word travels in the `<figcaption>`-style label beside the duration, so the
 * information is never carried by shape alone.
 * ═══════════════════════════════════════════════════════════════════════════
 */
function CallHeader({ call }: { call: Call }) {
  const outgoing = call.direction === 'outgoing'
  const Arrow = outgoing ? ArrowRight : ArrowLeft

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-4 sm:flex-nowrap">
        <Party
          role={t('callDetail.employeeSide')}
          name={call.agent_name}
          number={formatPhone(call.number_e164)}
        />

        {/* The visual middle: which way the call went, and how long it ran. */}
        <div className="flex shrink-0 flex-col items-center gap-1 px-2">
          <Arrow
            className={cn('size-6', outgoing ? 'text-accent' : 'text-good')}
            aria-hidden
          />
          <span className="whitespace-nowrap text-2xs font-medium uppercase tracking-wide text-muted">
            {t(DIRECTION_LABEL[call.direction])}
          </span>
          <span className="font-mono text-base tabular-nums text-text">
            {formatDuration(call.duration_sec)}
          </span>
        </div>

        <Party
          role={t('callDetail.clientSide')}
          name={call.contact_name}
          number={formatPhone(call.remote_number)}
          align="end"
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <Badge tone={DISPOSITION_TONE[call.disposition]}>
          {t(DISPOSITION_LABEL[call.disposition])}
        </Badge>
        <Badge>{t(CALL_TYPE_LABEL[call.call_type])}</Badge>
      </div>
    </Card>
  )
}

function CallCard({ call }: { call: Call }) {
  return (
    <div className="flex flex-col gap-4">
      <CallHeader call={call} />

      <AudioSection call={call} />

      <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
        <Section title={t('callDetail.sectionTiming')}>
          <FieldGrid className="xl:grid-cols-2">
            <Field
              label={t('callDetail.startedAt')}
              value={formatDateTimeOrDash(call.started_at)}
              title={formatInstantTitle(call.started_at)}
            />
            <Field
              label={t('callDetail.answeredAt')}
              value={call.answered_at ? formatDateTimeOrDash(call.answered_at) : null}
              title={call.answered_at ? formatInstantTitle(call.answered_at) : undefined}
            />
            <Field
              label={t('callDetail.endedAt')}
              value={call.ended_at ? formatDateTimeOrDash(call.ended_at) : null}
              title={call.ended_at ? formatInstantTitle(call.ended_at) : undefined}
            />
            <Field
              label={t('callDetail.receivedAt')}
              value={formatDateTimeOrDash(call.received_at)}
              title={formatInstantTitle(call.received_at)}
            />
            <Field label={t('callDetail.duration')} value={formatDuration(call.duration_sec)} />
            <Field
              label={t('callDetail.ringSec')}
              value={call.ring_sec === null ? null : formatDuration(call.ring_sec)}
            />
            <Field label={t('callDetail.deviceTimezone')} value={call.device_timezone} />
            <Field
              label={t('callDetail.clockSkew')}
              value={t('callDetail.clockSkewValue', { seconds: call.clock_skew_sec })}
            />
          </FieldGrid>
        </Section>

        <Section title={t('callDetail.sectionOrigin')}>
          <FieldGrid className="xl:grid-cols-2">
            {/* The agent and the work number are NOT repeated here: the
                header above already names both, on the side of the card that
                belongs to the employee. Printing them twice is what made this
                section long enough to need its own row per field. */}
            <Field label={t('callDetail.deviceModel')} value={call.device_model ?? null} />
            <Field label={t('callDetail.source')} value={t(SOURCE_LABEL[call.source])} />
            <Field
              label={t('callDetail.reconciled')}
              value={boolText(call.reconciled_with_call_log)}
            />
            <Field
              label={t('callDetail.appVersion')}
              value={`${call.app_version} · ${call.app_variant}`}
            />
            <Field
              label={t('callDetail.installation')}
              value={call.installation_id}
              title={call.installation_id}
              mono
            />
            <Field label={t('callDetail.seq')} value={String(call.seq)} mono />
          </FieldGrid>
        </Section>
      </div>

      <NoteSection call={call} />
    </div>
  )
}

export function CallDetailPage() {
  const { id } = useParams<{ id: string }>()
  const callQuery = useCall(id)

  return (
    <Page>
      <PageHeader
        title={t('page.callDetail')}
        actions={
          <Link
            to="/calls"
            className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium text-muted transition-colors hover:bg-surface-2 hover:text-text"
          >
            <ArrowLeft className="size-4" aria-hidden />
            {t('callDetail.back')}
          </Link>
        }
      />
      <QueryBoundary query={callQuery}>{(call) => <CallCard call={call} />}</QueryBoundary>
    </Page>
  )
}
