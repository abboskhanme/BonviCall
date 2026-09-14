/**
 * The filter bar primitives, shared by every list page.
 *
 * Extracted from `modules/calls/CallsPage.tsx`, which built them first. Every
 * list page in this product filters, and a filter bar that looks and behaves
 * differently on each page is the kind of inconsistency nobody files a bug
 * about and everybody notices.
 */
import { useEffect, useRef, useState } from 'react'
import type { ReactNode, RefObject } from 'react'
import { CalendarDays, Search, X } from 'lucide-react'

import { t, type MessageKey } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'

export const SELECT_CLASS = 'h-9 rounded-md border border-border bg-surface px-2 text-sm text-text'

/**
 * The shell every filter control sits in: one height, one radius, one focus
 * treatment. `rounded-md` is 0.75rem here (tailwind.config.js), which is what
 * the rest of the product uses — the filter bar is not the place to invent a
 * second radius.
 *
 * The focus ring lives on the SHELL rather than on the input inside it: these
 * controls are boxes containing a borderless input, so the browser's own
 * outline would be drawn 2px outside the input and land on top of the shell's
 * border. The inner input suppresses its outline and this ring replaces it.
 */
const SHELL_CLASS =
  'flex items-center rounded-md border border-border bg-surface text-sm text-text ' +
  'transition-colors hover:border-muted/40 focus-within:border-accent focus-within:ring-2 ' +
  'focus-within:ring-accent/20'

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
 * A draft that commits on Enter or blur rather than on keystroke.
 *
 * Deliberately not debounced: `q` is an ILIKE over contact names and
 * `remote_number` is matched on the 9-digit key, and firing either one per
 * keystroke sends a query for every prefix of what somebody is typing. Commit
 * on intent is both cheaper and more predictable — the list stops rearranging
 * itself under the reader's cursor.
 *
 * Shared by `TextFilter` and `SearchFilter` so the two cannot drift into two
 * different answers to "when does a search actually run".
 */
function useCommittedDraft(value: string | undefined, onCommit: (value: string | null) => void) {
  const [draft, setDraft] = useState(value ?? '')

  // The URL is the source of truth: a "clear filters" click or a back button
  // must be reflected here, not overwritten by stale local state.
  useEffect(() => setDraft(value ?? ''), [value])

  const commit = (next: string = draft) => {
    const trimmed = next.trim()
    if (trimmed !== (value ?? '')) onCommit(trimmed === '' ? null : trimmed)
  }

  return {
    draft,
    setDraft,
    commit,
    clear: () => {
      setDraft('')
      commit('')
    },
  }
}

/** A free-text filter that commits on Enter or blur (see `useCommittedDraft`). */
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
  const { draft, setDraft, commit } = useCommittedDraft(value, onCommit)

  return (
    <FilterField label={label}>
      <input
        type="search"
        className={cn(SELECT_CLASS, 'w-44 placeholder:text-muted')}
        placeholder={placeholder}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => commit()}
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

/**
 * The one search box a list page leads with.
 *
 * Same commit-on-intent behaviour as `TextFilter` and deliberately taller and
 * wider: on a page where one control is reached for far more often than the
 * others, making it the same size as the rest is what produces a bar that
 * reads as a form somebody grew one field at a time. It carries no visible
 * label for the same reason — a magnifier and a placeholder say it, and
 * `aria-label` says it to a screen reader.
 */
export function SearchFilter({
  label,
  placeholder,
  value,
  onCommit,
  clearLabel,
  className,
}: {
  label: string
  placeholder?: string
  value: string | undefined
  onCommit: (value: string | null) => void
  clearLabel: string
  className?: string
}) {
  const { draft, setDraft, commit, clear } = useCommittedDraft(value, onCommit)

  return (
    <div className={cn(SHELL_CLASS, 'h-10 shadow-xs', className)}>
      <Search className="ms-3 size-4 shrink-0 text-muted" aria-hidden />
      <input
        type="search"
        aria-label={label}
        className={cn(
          'h-full min-w-0 flex-1 bg-transparent px-2 text-sm text-text',
          'placeholder:text-muted focus:outline-none',
          // Our own clear button is rendered below; the WebKit one would be a
          // second X with different behaviour sitting next to it.
          '[&::-webkit-search-cancel-button]:hidden',
        )}
        placeholder={placeholder}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => commit()}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            commit()
          }
        }}
      />
      {draft === '' ? null : (
        <button
          type="button"
          aria-label={clearLabel}
          title={clearLabel}
          className="me-2 rounded-md p-1 text-muted transition-colors hover:bg-surface-2 hover:text-text"
          // Without this the button's own mousedown blurs the input first,
          // which commits the text a heartbeat before the click clears it —
          // two queries and a list that flickers on its way to empty.
          onMouseDown={(event) => event.preventDefault()}
          onClick={clear}
        >
          <X className="size-4" aria-hidden />
        </button>
      )}
    </div>
  )
}

/**
 * A native `<input type="date">`, dressed.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * The input stays native on purpose: it is keyboard-accessible, it speaks the
 * platform's own date format, and it opens the real picker on every OS. A
 * date-picker dependency would be several hundred kilobytes spent
 * re-implementing all three, worse. What IS replaced is how the browser
 * dresses it:
 *
 *  · the browser's own calendar glyph is removed and `DateFilter` draws a real
 *    BUTTON in its place — same affordance, but one somebody can reach with a
 *    keyboard and a screen reader can name;
 *
 *  · the picker also opens from `Alt+ArrowDown` (the platform gesture) and
 *    from a click on a field that is still EMPTY. It deliberately does NOT
 *    open on a click into a field that already holds a date: that click is
 *    somebody correcting the year, and a calendar landing on top of them is
 *    the behaviour they would have to press Escape to get rid of;
 *
 *  · `showPicker()` is a standard method rather than a CSS trick over a
 *    shadow-DOM pseudo-element, which also means all three routes can be
 *    TESTED, and are (`__tests__/filters.test.tsx`);
 *
 *  · while the field holds NOTHING AT ALL, the `mm/dd/yyyy` skeleton is hidden
 *    and a hint takes its place. "Nothing at all" is the careful part: Chrome
 *    reports `value === ''` for `09/dd/yyyy` too, and hiding the skeleton then
 *    would paint "from" over a half-typed date and tell the reader the field
 *    is empty when it is not. `validity.badInput` is what distinguishes them.
 *
 * The glyph and the skeleton are `::-webkit-` pseudo-elements, i.e. Chrome and
 * Edge — the two browsers this panel supports (SPEC §5). Elsewhere the field
 * keeps the platform's own furniture, which is the correct fallback.
 * ═══════════════════════════════════════════════════════════════════════════
 */
const DATE_INPUT_CLASS =
  'h-full w-[6.25rem] bg-transparent px-1 text-sm text-text tabular-nums ' +
  'focus:outline-none ' +
  '[&::-webkit-calendar-picker-indicator]:hidden'

/** Hide the `mm/dd/yyyy` skeleton while the field is empty and unfocused. */
const DATE_INPUT_EMPTY_CLASS = '[&:not(:focus)::-webkit-datetime-edit]:opacity-0'

/**
 * Open the native picker, if this browser has one.
 *
 * Guarded rather than assumed: `showPicker` is a real method in the browsers
 * this panel ships to and is absent in jsdom, and a filter bar that throws in a
 * test run is worse than one that opens no picker there.
 */
function openPicker(input: HTMLInputElement | null): void {
  if (!input || typeof input.showPicker !== 'function') return
  try {
    input.showPicker()
  } catch {
    // No user activation, or a browser that refuses. The field is still a
    // perfectly good date input; losing the picker is not worth an uncaught
    // error in the console.
  }
}

function DateInput({
  label,
  hint,
  value,
  min,
  max,
  onChange,
  inputRef,
}: {
  label: string
  hint: string
  value: string | undefined
  min?: string
  max?: string
  onChange: (value: string | null) => void
  inputRef?: RefObject<HTMLInputElement>
}) {
  // Chrome holds a half-typed date internally and reports `value === ''`.
  // `badInput` is how the field says "there IS something here, it just is not
  // a date yet" — read on blur, which is the moment the hint would otherwise
  // lie about it.
  const [partial, setPartial] = useState(false)
  const showHint = !value && !partial

  return (
    <span className="relative flex h-full items-center">
      <input
        ref={inputRef}
        type="date"
        aria-label={label}
        className={cn('peer', DATE_INPUT_CLASS, showHint && 'cursor-pointer', !value && DATE_INPUT_EMPTY_CLASS)}
        value={value ?? ''}
        min={min}
        max={max}
        onChange={(event) => {
          setPartial(false)
          onChange(event.target.value || null)
        }}
        onBlur={(event) => setPartial(Boolean(event.currentTarget.validity?.badInput))}
        onClick={(event) => {
          if (showHint) openPicker(event.currentTarget)
        }}
        onKeyDown={(event) => {
          // The platform gesture, and the keyboard route to a picker whose
          // glyph this component removed.
          if (event.altKey && event.key === 'ArrowDown') {
            event.preventDefault()
            openPicker(event.currentTarget)
          }
        }}
      />
      {showHint ? (
        <span className="pointer-events-none absolute start-1 text-sm text-muted peer-focus:opacity-0">
          {hint}
        </span>
      ) : null}
    </span>
  )
}

/**
 * One date filter: a labelled field like any other in the bar.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * Two of these make a range, and they are deliberately NOT welded into one
 * control. Each bound stands on its own — a start with no end means "since
 * then", an end with no start means "up to then", and the server reads a
 * missing bound as open-ended — so making one wait for the other would invent
 * a rule that exists nowhere else in the product.
 *
 * **It applies the moment a date is chosen.** The commit is the input's own
 * `change`, which fires when a complete date is entered and when a day is
 * clicked in the picker. No blur, no Enter: clicking a day in a calendar IS
 * the act of choosing, and a filter that then sits there waiting is the dead
 * button people report as "the filter does not work". (The text filters above
 * commit on intent for the opposite reason — there is no moment in typing a
 * name that means "I have finished".)
 *
 * Not a `<label>` wrapper: the shell holds a button and an input, and an
 * implicit label points at exactly one control. The input carries the name.
 * ═══════════════════════════════════════════════════════════════════════════
 */
export function DateFilter({
  label,
  hint,
  pickLabel,
  clearLabel,
  value,
  min,
  max,
  onChange,
}: {
  label: string
  /** What an empty field says. Not the label again — the field is already
   *  labelled above it, and a box that repeats its own name twice tells the
   *  reader nothing about whether the bound is set. */
  hint: string
  pickLabel: string
  clearLabel: string
  value: string | undefined
  /** The other bound, so the picker cannot offer a backwards range. */
  min?: string
  max?: string
  onChange: (value: string | null) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <div className="flex flex-col gap-1">
      <span className="text-2xs font-medium text-muted">{label}</span>
      <div className={cn(SHELL_CLASS, 'h-9 ps-1')}>
        {/* The affordance the browser's own glyph used to be, and a real
            button so it is reachable by keyboard and announces itself. */}
        <button
          type="button"
          aria-label={pickLabel}
          title={pickLabel}
          className="rounded-md p-1 text-muted transition-colors hover:bg-surface-2 hover:text-text"
          onClick={() => openPicker(inputRef.current)}
        >
          <CalendarDays className="size-4 shrink-0" aria-hidden />
        </button>
        <DateInput
          label={label}
          hint={hint}
          value={value}
          min={min}
          max={max}
          onChange={onChange}
          inputRef={inputRef}
        />
        {value ? (
          <button
            type="button"
            aria-label={clearLabel}
            title={clearLabel}
            // Clears THIS bound and nothing else: it goes through the same
            // `onChange` the field commits with, so there is one path out of
            // this component and no way for one end to clear the other.
            className="me-1.5 rounded-md p-1 text-muted transition-colors hover:bg-surface-2 hover:text-text"
            onClick={() => onChange(null)}
          >
            <X className="size-3.5" aria-hidden />
          </button>
        ) : (
          // Keeps the shell the same width whether or not a date is set, so
          // the row does not shuffle sideways when somebody picks one.
          <span className="me-1.5 size-5" aria-hidden />
        )}
      </div>
    </div>
  )
}
