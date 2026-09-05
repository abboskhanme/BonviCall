/**
 * Upload a signed APK.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **The signing fingerprint is the point of the result screen.** Android
 * refuses an update signed by a different key, and BonviCall has no store to
 * re-publish through — so a build signed by the wrong key cannot be installed
 * over the existing one at all. The only remedy is uninstall-and-reinstall on
 * every handset, which destroys each phone's unsent upload queue
 * (`docs/APK-SIGNING.md`).
 *
 * That failure is invisible at upload time and expensive at install time. So
 * when the server has no configured fingerprint to check against, this dialog
 * puts the certificate's SHA-256 on screen and asks the person to compare it
 * by eye BEFORE they publish — which is the last moment it is still cheap.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { CheckCircle2, ShieldAlert } from 'lucide-react'

import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { formatBytes } from '@/shared/lib/format'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { Input } from '@/shared/ui/primitives'
import { SELECT_CLASS } from '@/shared/ui/filters'

import { useUploadVersion, type AppVariant, type UploadRelease } from './appVersions'

const VARIANTS: readonly AppVariant[] = ['legacy28', 'modern34']

export function UploadVersionModal({
  open,
  onOpenChange,
  signingConfigured,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** False means the server accepts uploads without checking the key. */
  signingConfigured: boolean
}) {
  const [apk, setApk] = useState<File | null>(null)
  const [version, setVersion] = useState('')
  const [versionCode, setVersionCode] = useState('')
  const [variant, setVariant] = useState<AppVariant>('modern34')
  const [notes, setNotes] = useState('')
  const [mandatory, setMandatory] = useState(false)
  const [result, setResult] = useState<UploadRelease | null>(null)

  const upload = useUploadVersion()

  useEffect(() => {
    if (open) {
      setApk(null)
      setVersion('')
      setVersionCode('')
      setVariant('modern34')
      setNotes('')
      setMandatory(false)
      setResult(null)
    }
  }, [open])

  const code = Number(versionCode)
  const codeValid = Number.isInteger(code) && code > 0
  const invalid = apk === null || version.trim() === '' || !codeValid

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (invalid || apk === null) return
    upload.mutate(
      {
        apk,
        version: version.trim(),
        version_code: code,
        variant,
        is_mandatory: mandatory,
        ...(notes.trim() ? { release_notes_uz: notes.trim() } : {}),
      },
      { onSuccess: (response) => setResult(response) },
    )
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={t('appVersions.uploadTitle')}
      description={t('appVersions.uploadHint')}
      // Once it is uploaded there is nothing left to submit; the dialog turns
      // into the fingerprint check.
      onSubmit={result ? undefined : handleSubmit}
      submitting={upload.status === 'pending'}
      submitDisabled={invalid}
      submitLabel={t('appVersions.uploadAction')}
    >
      <ModalFields>
        {result ? (
          <div className="space-y-3">
            <p className="text-sm text-text">
              {t('appVersions.uploaded', {
                version: result.version.version,
                code: result.version.version_code,
              })}
            </p>

            {result.signer_verified ? (
              <p className="flex items-start gap-2 text-sm text-good">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden />
                {t('appVersions.signerVerified')}
              </p>
            ) : (
              /* The one moment where checking is still cheap. */
              <div className="space-y-2 rounded-md border border-warn/40 bg-warn/5 p-3">
                <p className="flex items-start gap-2 text-sm font-medium text-text">
                  <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
                  {t('appVersions.signerUnverified')}
                </p>
                <p className="break-all font-mono text-2xs text-text">{result.signer_sha256}</p>
                <p className="text-xs text-muted">{t('appVersions.signerCompare')}</p>
              </div>
            )}

            <p className="text-xs text-muted">{t('appVersions.notPublishedYet')}</p>
          </div>
        ) : (
          <>
            <ModalField htmlFor="apk-file" label={t('appVersions.fieldApk')}>
              <input
                id="apk-file"
                type="file"
                accept=".apk,application/vnd.android.package-archive"
                className="w-full text-sm text-text file:me-3 file:rounded-md file:border-0 file:bg-surface-2 file:px-3 file:py-1.5 file:text-sm file:text-text"
                onChange={(event) => setApk(event.target.files?.[0] ?? null)}
              />
              {apk ? (
                <p className="mt-1 text-2xs text-muted">
                  {apk.name} · {formatBytes(apk.size)}
                </p>
              ) : null}
            </ModalField>

            <ModalField htmlFor="apk-version" label={t('appVersions.fieldVersion')}>
              <Input
                id="apk-version"
                value={version}
                placeholder="1.4.0"
                onChange={(event) => setVersion(event.target.value)}
              />
            </ModalField>

            <ModalField
              htmlFor="apk-code"
              label={t('appVersions.fieldVersionCode')}
              error={versionCode !== '' && !codeValid ? t('appVersions.codeInvalid') : undefined}
            >
              <Input
                id="apk-code"
                type="number"
                min={1}
                value={versionCode}
                onChange={(event) => setVersionCode(event.target.value)}
              />
              {/* A mistyped code holds that number forever unless the build is
                  discarded before it is published. */}
              <p className="mt-1 text-2xs text-muted">{t('appVersions.codeHint')}</p>
            </ModalField>

            <ModalField htmlFor="apk-variant" label={t('appVersions.fieldVariant')}>
              <select
                id="apk-variant"
                className={`${SELECT_CLASS} w-full`}
                value={variant}
                onChange={(event) => setVariant(event.target.value as AppVariant)}
              >
                {VARIANTS.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </ModalField>

            <ModalField htmlFor="apk-notes" label={t('appVersions.fieldNotes')}>
              <Input
                id="apk-notes"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
            </ModalField>

            <ModalField htmlFor="apk-mandatory" label={t('appVersions.fieldMandatory')}>
              <label className="flex items-center gap-2 text-xs text-muted">
                <input
                  id="apk-mandatory"
                  type="checkbox"
                  checked={mandatory}
                  onChange={(event) => setMandatory(event.target.checked)}
                />
                {t('appVersions.fieldMandatoryHint')}
              </label>
            </ModalField>

            {!signingConfigured ? (
              <p className="text-xs text-warn">{t('appVersions.noSigningConfigured')}</p>
            ) : null}
          </>
        )}

        {upload.error ? (
          <p className="text-2xs text-bad">{messageForError(upload.error)}</p>
        ) : null}
      </ModalFields>
    </Modal>
  )
}
