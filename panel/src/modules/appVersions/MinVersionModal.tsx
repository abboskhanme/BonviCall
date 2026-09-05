/**
 * Raising the minimum supported version.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **This strands phones, and they are not the company's phones.**
 *
 * A handset below the floor drains its queue, is then refused with 426, and
 * stays refused until somebody physically reaches that salesperson (N34,
 * UC-28). So the flow is: pick a version → see who it costs → then confirm.
 * The count is not a footnote under the button, it is IN the confirmation,
 * with the names, because "3 devices" and "Aziz, Bekzod and Dilnoza" are
 * different sentences to the person clicking.
 *
 * Two things this dialog is careful about:
 *
 *   **`acknowledged_stranded`** is the number that was actually on screen. The
 *   server refuses if it has moved since — which happens exactly when a phone
 *   checked in between looking and deciding, i.e. when the picture stopped
 *   being true. Re-reading the live count here would defeat the check.
 *
 *   **`unknown_version_count`** is shown separately and never folded in. Those
 *   phones have never reported a version, the gate lets them through, and we
 *   cannot say whether they are below the floor — so counting them as safe
 *   would be a guess and counting them as stranded would be a lie.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { HelpCircle, TriangleAlert } from 'lucide-react'

import { isApiError, messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { formatCount } from '@/shared/lib/format'
import { relativeText } from '@/shared/lib/relativeText'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { Input } from '@/shared/ui/primitives'

import { useSetMinimumVersion, useVersionGateImpact } from './api'

export function MinVersionModal({
  open,
  onOpenChange,
  currentMinCode,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  currentMinCode: number
}) {
  const [code, setCode] = useState(String(currentMinCode))
  const mutation = useSetMinimumVersion()

  useEffect(() => {
    if (open) setCode(String(currentMinCode))
  }, [open, currentMinCode])

  const parsed = Number(code)
  const valid = Number.isInteger(parsed) && parsed >= 1
  const impact = useVersionGateImpact(valid ? parsed : null, open)
  const data = impact.data ?? null

  // Only what the admin can actually see counts as acknowledged.
  const canConfirm = valid && impact.status === 'success' && data !== null

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canConfirm || data === null) return
    mutation.mutate(
      { version_code: parsed, acknowledged_stranded: data.stranded_count },
      { onSuccess: () => onOpenChange(false) },
    )
  }

  const mismatch = isApiError(mutation.error) && mutation.error.code === 'stranded_count_mismatch'

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={t('appVersions.minVersionTitle')}
      description={t('appVersions.minVersionHint')}
      onSubmit={handleSubmit}
      submitting={mutation.status === 'pending'}
      submitDisabled={!canConfirm}
      submitLabel={
        data && data.stranded_count > 0
          ? t('appVersions.minVersionConfirmStranding', { n: data.stranded_count })
          : t('appVersions.minVersionConfirm')
      }
      danger={(data?.stranded_count ?? 0) > 0}
    >
      <ModalFields>
        <ModalField
          htmlFor="min-version-code"
          label={t('appVersions.fieldMinCode')}
          error={valid ? undefined : t('appVersions.codeInvalid')}
        >
          <Input
            id="min-version-code"
            type="number"
            min={1}
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
          <p className="mt-1 text-2xs text-muted">
            {t('appVersions.currentMin', { n: currentMinCode })}
          </p>
        </ModalField>

        {impact.status === 'pending' && valid ? (
          <p className="text-sm text-muted">{t('appVersions.impactLoading')}</p>
        ) : null}

        {impact.status === 'error' ? (
          // Never let a failure to count read as "nobody is affected".
          <p className="text-sm text-warn">{t('appVersions.impactFailed')}</p>
        ) : null}

        {data ? (
          <div className="space-y-3">
            {data.stranded_count === 0 ? (
              <p className="text-sm text-text">{t('appVersions.strandsNobody')}</p>
            ) : (
              <div className="space-y-2 rounded-md border border-bad/40 bg-bad/5 p-3">
                <p className="flex items-center gap-2 text-sm font-medium text-text">
                  <TriangleAlert className="size-4 shrink-0 text-bad" aria-hidden />
                  {t('appVersions.stranded', { n: formatCount(data.stranded_count) })}
                </p>
                {/* Names, not just a number: these are people whose phones
                    stop working until somebody reaches them. */}
                <ul className="space-y-1">
                  {data.stranded.map((device) => (
                    <li key={device.installation_id} className="text-xs text-text">
                      <Link
                        to={`/devices/${device.installation_id}`}
                        className="text-accent underline-offset-2 hover:underline"
                      >
                        {device.agent_name}
                      </Link>
                      {' · '}
                      {device.device}
                      {' · '}
                      {device.app_version ?? t('appVersions.unknownVersion')}
                      {device.last_heartbeat_at ? ` · ${relativeText(device.last_heartbeat_at)}` : ''}
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-muted">{t('appVersions.strandedExplain')}</p>
              </div>
            )}

            {data.unknown_version_count > 0 ? (
              /* Not folded into the count: the gate lets these through, and we
                 cannot say whether they are below the floor. */
              <p className="flex items-start gap-2 text-xs text-muted">
                <HelpCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                {t('appVersions.unknownVersions', { n: data.unknown_version_count })}
              </p>
            ) : null}
          </div>
        ) : null}

        {mismatch ? (
          // The number moved between looking and deciding, so what was on
          // screen was no longer true. Say that, rather than "conflict".
          <p className="text-2xs text-bad">{t('appVersions.strandedMoved')}</p>
        ) : mutation.error ? (
          <p className="text-2xs text-bad">{messageForError(mutation.error)}</p>
        ) : null}
      </ModalFields>
    </Modal>
  )
}
