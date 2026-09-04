/**
 * The recording, or the reason there is none.
 *
 * The player is only ever rendered for `audio.available`. The other two states
 * are handled by the caller and are **not** interchangeable:
 *
 *   expired — the recording existed and retention removed it. Neutral, and no
 *             player: offering a control that answers 410 `audio_expired`
 *             invites somebody to press it and conclude the system is broken.
 *   missing — it never existed. That is a capture failure and shows its
 *             reason.
 *
 * The URL is resolved and the token handed to the Service Worker BEFORE the
 * `<audio>` element is given a `src`. Rendering the element first and letting
 * it 401 would be the same bug the bridge exists to fix, one step later.
 */
import { useEffect, useRef, useState } from 'react'
import { Download, Loader2, TriangleAlert } from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Button } from '@/shared/ui/primitives'

import { AudioError, downloadCallAudio, openAudio, type BridgeMode } from './audio'

type State =
  | { kind: 'loading' }
  | { kind: 'ready'; url: string; mode: BridgeMode }
  | { kind: 'failed'; status: number }

/** The endpoint's own failures, in words the listener can act on. */
function messageForStatus(status: number): string {
  switch (status) {
    case 410:
      // Retention removed it between the list being drawn and Play being
      // pressed — rare, but it is the one 4xx that is not anybody's mistake.
      return t('calls.audio.expired')
    case 404:
      return t('errors.audio_not_found')
    case 401:
      return t('errors.unauthorized')
    default:
      return t('callDetail.playerFailed')
  }
}

export function AudioPlayer({ callId, url }: { callId: string; url: string | null | undefined }) {
  const can = useAuth((state) => state.can)
  const mayDownload = can(Perm.AUDIO_DOWNLOAD)
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const revokeRef = useRef<() => void>(() => {})

  useEffect(() => {
    let cancelled = false
    setState({ kind: 'loading' })

    void openAudio(callId, url)
      .then((source) => {
        if (cancelled) {
          // The card was closed mid-flight; release the blob rather than
          // leaving the whole file in memory until the tab closes.
          source.revoke()
          return
        }
        revokeRef.current = source.revoke
        setState({ kind: 'ready', url: source.url, mode: source.mode })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setState({ kind: 'failed', status: error instanceof AudioError ? error.status : 0 })
      })

    return () => {
      cancelled = true
      revokeRef.current()
      revokeRef.current = () => {}
    }
  }, [callId, url])

  if (state.kind === 'loading') {
    return (
      <div className="flex items-center gap-2 text-sm text-muted" data-testid="audio-loading">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        {t('callDetail.playerLoading')}
      </div>
    )
  }

  if (state.kind === 'failed') {
    return (
      <div className="flex items-start gap-2" data-testid="audio-failed">
        <TriangleAlert className="mt-0.5 size-4 shrink-0 text-bad" aria-hidden />
        <p className="text-sm text-text">{messageForStatus(state.status)}</p>
      </div>
    )
  }

  return (
    <div className="space-y-2" data-testid="audio-ready">
      {/* An ordinary src. The Service Worker adds the header in flight, so the
          player issues its own Range requests and seek is native. */}
      <audio controls preload="metadata" src={state.url} className="w-full">
        {t('callDetail.playerNoSupport')}
      </audio>

      <div className="flex flex-wrap items-center gap-3">
        {mayDownload ? (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setDownloadError(null)
              void downloadCallAudio(callId, url).catch((error: unknown) => {
                setDownloadError(
                  messageForStatus(error instanceof AudioError ? error.status : 0),
                )
              })
            }}
          >
            <Download className="size-3.5" aria-hidden />
            {t('callDetail.download')}
          </Button>
        ) : null}

        {/* Said out loud, because it changes what the listener experiences:
            on the fallback the whole file downloads before playback starts,
            and a twenty-minute recording takes a moment. */}
        {state.mode === 'blob' ? (
          <span className="text-2xs text-muted">{t('callDetail.playerFallback')}</span>
        ) : null}
      </div>

      {downloadError ? <p className="text-xs text-bad">{downloadError}</p> : null}
    </div>
  )
}
