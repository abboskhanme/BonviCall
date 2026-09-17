/**
 * Why an upload was refused, in Uzbek.
 *
 * ⚠️ NOT `messageForError`. That renders the catalogue line for
 * `validation_error`, which tells somebody holding the wrong spreadsheet
 * nothing at all. The server's `detail.reason` names the actual problem and
 * the extra keys name the specific column or kind — so the reader learns which
 * file to pick instead, which is the only useful thing a failed upload can say.
 *
 * ⚠️ THE WORDING IS THE PANEL'S. The source's backend shipped ready-made Uzbek
 * sentences that the panel printed blind — user-facing text living on the far
 * side of the wire, where nobody who writes copy could find it. Here the server
 * sends a code (CONVENTIONS.md §14).
 *
 * In its own file rather than beside the dialog so `ImportModal.tsx` keeps
 * exporting components only, which is what React Fast Refresh needs to swap a
 * component without remounting the tree — the same reason `buttonStyles.ts`
 * sits apart from `primitives.tsx`.
 */
import { isApiError } from '@/shared/api/errors'
import { t, type MessageKey } from '@/shared/i18n'

import { FILE_KIND_LABEL, UPLOAD_REASON_LABEL, type ImportPreview } from './api'

/** The ceiling the server enforces, for the message only. */
const BYTES_PER_MB = 1024 * 1024
const DEFAULT_MAX_MB = 20

/** A file kind, translated — never printed as the raw identifier. */
function kindName(value: unknown): string {
  if (typeof value !== 'string') return '?'
  const label = FILE_KIND_LABEL[value as ImportPreview['kind']]
  return label ? t(label) : value
}

export function uploadFailure(error: unknown): string {
  if (!isApiError(error)) return t('sales.import.failed')

  // Over the ceiling, which arrives as a STATUS rather than a reason.
  if (error.status === 413) {
    const max = error.detail?.max_bytes
    return t('sales.import.err.too_large', {
      limit: typeof max === 'number' ? Math.round(max / BYTES_PER_MB) : DEFAULT_MAX_MB,
    })
  }

  const reason = error.detail?.reason
  const key: MessageKey | undefined =
    typeof reason === 'string' ? UPLOAD_REASON_LABEL[reason] : undefined
  // A reason with no sentence falls back to the generic line: an English
  // identifier on screen would be worse than saying less.
  if (!key) return t('sales.import.failed')

  if (reason === 'column_missing') {
    const column = error.detail?.column
    return t(key, { column: typeof column === 'string' ? column : '?' })
  }

  if (reason === 'wrong_export_kind') {
    return t(key, {
      found: kindName(error.detail?.found),
      expected: kindName(error.detail?.expected),
    })
  }

  return t(key)
}
