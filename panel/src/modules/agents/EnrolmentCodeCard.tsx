/**
 * The enrolment code, shown so it cannot be confused with anything else.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * The client typed the **employee code** (`BV-001`) into the app when it asked
 * for the **enrolment code** (`W4WH6KRA`). Two codes, similar names, and the
 * app's own screen said only "enter the code from the link the administrator
 * sent". That is not a mistake anybody should be blamed for.
 *
 * So wherever the enrolment code appears in the panel it is labelled by what
 * it DOES — the code the salesperson types into the app — and its shape is
 * stated beside it: eight characters, letters and digits. Shape is what lets
 * somebody notice that `BV-001` cannot be the thing being asked for, without
 * having to remember which code is which.
 *
 * Large enough to read aloud over a phone, because that is how it gets to the
 * salesperson: an admin reading it to somebody standing in a shop.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useState } from 'react'
import { Check, Copy } from 'lucide-react'

import { t } from '@/shared/i18n'
import { formatDateTime, formatInstantTitle } from '@/shared/lib/format'
import { Button } from '@/shared/ui/primitives'

import { installUrl } from '@/modules/numbers/installUrl'
import type { EnrolmentCode } from '@/modules/numbers/api'

export function EnrolmentCodeCard({ code }: { code: EnrolmentCode }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(t('enrol.smsTemplate', { url: installUrl(code.code) }))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      // Refused on an insecure origin and in some browsers without a gesture.
      // The code is on screen either way, so this fails quietly rather than
      // with an alarming dialog.
      setCopied(false)
    }
  }

  return (
    <div className="space-y-3 rounded-md border border-accent/40 bg-accent-soft p-4 text-center">
      <p className="text-2xs font-medium uppercase tracking-wide text-accent">
        {t('enrol.codeCardTitle')}
      </p>

      {/* Read aloud over a phone: wide tracking so adjacent characters do not
          run together, and a monospace face so 0/O and 1/I are separable. */}
      <p className="font-mono text-3xl font-bold tracking-[0.3em] text-text">{code.code}</p>

      {/* The shape, so `BV-001` is visibly not this. */}
      <p className="text-xs text-muted">{t('enrol.codeShape')}</p>

      <p className="text-xs text-muted" title={formatInstantTitle(code.expires_at)}>
        {t('enrol.codeExpires', { at: formatDateTime(code.expires_at) })}
      </p>

      <Button variant="secondary" size="sm" onClick={() => void copy()}>
        {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
        {copied ? t('enrol.copied') : t('enrol.copyLink')}
      </Button>
    </div>
  )
}
