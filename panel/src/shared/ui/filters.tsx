/**
 * The filter bar primitives, shared by every list page.
 *
 * Extracted from `modules/calls/CallsPage.tsx`, which built them first. Every
 * list page in this product filters, and a filter bar that looks and behaves
 * differently on each page is the kind of inconsistency nobody files a bug
 * about and everybody notices.
 */
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { t, type MessageKey } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'

export const SELECT_CLASS = 'h-9 rounded-md border border-border bg-surface px-2 text-sm text-text'

/** One labelled control in the filter bar. */
export function FilterField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-2xs font-medium text-muted">{label}</span>
      {children}
    </label>
  )
}

/**
 * A closed-enum filter, built from the same label map the table renders with.
 *
 * Deriving the options from `Record<Enum, MessageKey>` rather than listing them
 * is what keeps the filter and the column in step: a value the server adds
 * appears in both at once, or in neither.
 */
export function EnumFilter<T extends string>({
  label,
  allLabel,
  labels,
  value,
  onChange,
}: {
  label: string
  allLabel: string
  labels: Record<T, MessageKey>
  value: T | undefined
  onChange: (value: string | null) => void
}) {
  return (
    <FilterField label={label}>
      <select
        className={SELECT_CLASS}
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value || null)}
      >
        <option value="">{allLabel}</option>
        {(Object.entries(labels) as [T, MessageKey][]).map(([key, messageKey]) => (
          <option key={key} value={key}>
            {t(messageKey)}
          </option>
        ))}
      </select>
    </FilterField>
  )
}

/**
 * A free-text filter that commits on Enter or blur rather than on keystroke.
 *
 * Deliberately not debounced: `q` is an ILIKE over contact names and
 * `remote_number` is matched on the 9-digit key, and firing either one per
 * keystroke sends a query for every prefix of what somebody is typing. Commit
 * on intent is both cheaper and more predictable — the list stops rearranging
 * itself under the reader's cursor.
 */
export function TextFilter({
  label,
  placeholder,
  value,
  onCommit,
}: {
  label: string
  placeholder?: string
  value: string | undefined
  onCommit: (value: string | null) => void
}) {
  const [draft, setDraft] = useState(value ?? '')

  // The URL is the source of truth: a "clear filters" click or a back button
  // must be reflected here, not overwritten by stale local state.
  useEffect(() => setDraft(value ?? ''), [value])

  const commit = () => {
    const trimmed = draft.trim()
    if (trimmed !== (value ?? '')) onCommit(trimmed === '' ? null : trimmed)
  }

  return (
    <FilterField label={label}>
      <input
        type="search"
        className={cn(SELECT_CLASS, 'w-44 placeholder:text-muted')}
        placeholder={placeholder}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            commit()
          }
        }}
      />
    </FilterField>
  )
}
