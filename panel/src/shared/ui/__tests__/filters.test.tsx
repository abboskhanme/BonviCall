/**
 * The filter-bar primitives (`../filters.tsx`).
 *
 * These are shared by every list page, so a regression here is a regression on
 * all of them at once. Three behaviours are worth pinning and none of them is
 * visible in a page test:
 *
 *  1. the search commits on INTENT — Enter or blur — and never per keystroke.
 *     `q` is an ILIKE over contact names; a query per keystroke is a table
 *     scan per keystroke;
 *  2. the URL stays the source of truth: a value arriving from outside
 *     overwrites what is in the box, not the other way round;
 *  3. the date field commits the moment a date is chosen — the opposite rule,
 *     for the opposite reason — and opens the real picker three ways, which is
 *     what the browser's 16-pixel glyph was removed in favour of. That is a
 *     claim about a native API, so it is asserted rather than eyeballed.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DateFilter, SearchFilter } from '@/shared/ui/filters'

/**
 * Neutral labels on purpose. These components are label-agnostic, the Uzbek
 * catalogue belongs to the pages that use them (CONVENTIONS.md §14 allows
 * Uzbek text in `uz.json` and nowhere else), and importing `t()` here would
 * couple a `shared/ui` test to `calls.*` keys that have nothing to do with it.
 */
const LABELS = {
  label: 'from',
  hint: 'unset',
  pickLabel: 'pick',
  clearLabel: 'clear date',
}

const SEARCH = { label: 'search', clearLabel: 'clear search' }

describe('SearchFilter', () => {
  it('does not commit while somebody is still typing', async () => {
    const onCommit = vi.fn()
    render(
      <SearchFilter label={SEARCH.label} value={undefined} onCommit={onCommit} clearLabel={SEARCH.clearLabel} />,
    )

    await userEvent.type(screen.getByRole('searchbox', { name: SEARCH.label }), 'Ada')

    expect(onCommit).not.toHaveBeenCalled()
  })

  it('commits on Enter', async () => {
    const onCommit = vi.fn()
    render(
      <SearchFilter label={SEARCH.label} value={undefined} onCommit={onCommit} clearLabel={SEARCH.clearLabel} />,
    )

    await userEvent.type(screen.getByRole('searchbox', { name: SEARCH.label }), 'Ada{Enter}')

    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith('Ada')
  })

  it('commits on blur, and trims what it commits', async () => {
    const onCommit = vi.fn()
    render(
      <SearchFilter label={SEARCH.label} value={undefined} onCommit={onCommit} clearLabel={SEARCH.clearLabel} />,
    )

    await userEvent.type(screen.getByRole('searchbox', { name: SEARCH.label }), '  Ada  ')
    await userEvent.tab()

    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith('Ada')
  })

  it('clears to null — "no filter", not "an empty string filter"', async () => {
    const onCommit = vi.fn()
    render(
      <SearchFilter label={SEARCH.label} value="Ada" onCommit={onCommit} clearLabel={SEARCH.clearLabel} />,
    )

    await userEvent.click(screen.getByRole('button', { name: SEARCH.clearLabel }))

    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith(null)
  })

  it('offers nothing to clear when there is nothing in the box', () => {
    render(
      <SearchFilter label={SEARCH.label} value={undefined} onCommit={vi.fn()} clearLabel={SEARCH.clearLabel} />,
    )

    expect(screen.queryByRole('button', { name: SEARCH.clearLabel })).toBeNull()
  })

  it('follows the value it is given — the URL wins over the local draft', async () => {
    const onCommit = vi.fn()
    const { rerender } = render(
      <SearchFilter label={SEARCH.label} value="Ada" onCommit={onCommit} clearLabel={SEARCH.clearLabel} />,
    )
    expect(screen.getByRole('searchbox', { name: SEARCH.label })).toHaveValue('Ada')

    // What a "clear filters" click or the back button looks like from here.
    rerender(
      <SearchFilter label={SEARCH.label} value={undefined} onCommit={onCommit} clearLabel={SEARCH.clearLabel} />,
    )

    expect(screen.getByRole('searchbox', { name: SEARCH.label })).toHaveValue('')
  })
})

describe('DateFilter', () => {
  const showPicker = vi.fn()

  beforeEach(() => {
    // jsdom has no `showPicker`; the browsers this panel ships to do. Defining
    // it here is what lets the click behaviour be asserted at all.
    Object.defineProperty(HTMLInputElement.prototype, 'showPicker', {
      value: showPicker,
      configurable: true,
      writable: true,
    })
    showPicker.mockClear()
  })

  afterEach(() => {
    Reflect.deleteProperty(HTMLInputElement.prototype, 'showPicker')
  })

  function renderField(value?: string, bounds: { min?: string; max?: string } = {}) {
    const onChange = vi.fn()
    render(<DateFilter {...LABELS} {...bounds} value={value} onChange={onChange} />)
    return onChange
  }

  it('names itself and shows the date it was given', () => {
    renderField('2026-09-01')

    expect(screen.getByLabelText(LABELS.label)).toHaveValue('2026-09-01')
  })

  /**
   * ══════════════════════════════════════════════════════════════════════
   * It applies the moment a date is chosen.
   *
   * The field's own `change` is the commit — which is what the picker fires
   * when somebody clicks a day. Waiting for blur, for Enter, or for the other
   * bound to be filled would be the dead button people report as "the filter
   * does not work".
   * ══════════════════════════════════════════════════════════════════════
   */
  it('commits on change, not on blur', () => {
    const onChange = renderField()

    fireEvent.change(screen.getByLabelText(LABELS.label), { target: { value: '2026-09-01' } })

    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith('2026-09-01')
  })

  it('clears to null, and only itself', async () => {
    const onChange = renderField('2026-09-01')

    await userEvent.click(screen.getByRole('button', { name: LABELS.clearLabel }))

    // One `onChange` out of this component, so one bound moves. The other end
    // is a separate field with a separate handler and cannot be touched here.
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('offers nothing to clear until a date is set', () => {
    renderField()

    expect(screen.queryByRole('button', { name: LABELS.clearLabel })).toBeNull()
  })

  it('carries the other bound through, so a backwards range cannot be picked', () => {
    renderField('2026-09-01', { max: '2026-09-05' })

    expect(screen.getByLabelText(LABELS.label)).toHaveAttribute('max', '2026-09-05')
  })

  /**
   * ══════════════════════════════════════════════════════════════════════
   * Three ways to the picker, because this component hides the browser's own
   * 16-pixel glyph and owes the reader a replacement for it.
   * ══════════════════════════════════════════════════════════════════════
   */
  it('opens the picker from the calendar button — the visible affordance', async () => {
    renderField()

    await userEvent.click(screen.getByRole('button', { name: LABELS.pickLabel }))

    expect(showPicker).toHaveBeenCalledTimes(1)
  })

  it('opens the picker from a click on an EMPTY field', async () => {
    renderField()

    await userEvent.click(screen.getByLabelText(LABELS.label))

    expect(showPicker).toHaveBeenCalledTimes(1)
  })

  /**
   * The other half of that rule. A click into a field that already holds a
   * date is somebody correcting the year; a calendar landing on top of them is
   * something they then have to press Escape to get rid of.
   */
  it('does not reopen the picker when the field already holds a date', async () => {
    renderField('2026-09-01')

    await userEvent.click(screen.getByLabelText(LABELS.label))

    expect(showPicker).not.toHaveBeenCalled()
  })

  it('opens the picker from Alt+ArrowDown, the platform keyboard gesture', async () => {
    renderField('2026-09-01')

    screen.getByLabelText(LABELS.label).focus()
    await userEvent.keyboard('{Alt>}{ArrowDown}{/Alt}')

    // A set field ignores a click and still answers the keyboard: the picker
    // is reachable without a mouse at all.
    expect(showPicker).toHaveBeenCalledTimes(1)
  })

  it('survives a browser that refuses to open it', async () => {
    showPicker.mockImplementation(() => {
      throw new Error('NotAllowedError')
    })
    renderField()

    await userEvent.click(screen.getByLabelText(LABELS.label))

    // No uncaught error, and the field is still usable as a date input.
    expect(screen.getByLabelText(LABELS.label)).toBeInTheDocument()
  })

  it('shows its own hint instead of the browser skeleton while empty', () => {
    renderField()

    // What an unset bound says, rather than `mm/dd/yyyy` — and not the label
    // over again, which the field already carries.
    expect(screen.getByText(LABELS.hint)).toBeInTheDocument()
  })

  it('drops the hint once it holds a date', () => {
    renderField('2026-09-01')

    expect(screen.queryByText(LABELS.hint)).toBeNull()
  })

  /**
   * ══════════════════════════════════════════════════════════════════════
   * A half-typed date is NOT an empty one.
   *
   * Chrome reports `value === ''` while it is holding `09/dd/yyyy`, so an
   * `empty = !value` test paints the hint over a date somebody is in the
   * middle of typing and tells them the field is blank. `validity.badInput`
   * is the field saying "there is something here, it just is not a date yet".
   * ══════════════════════════════════════════════════════════════════════
   */
  it('stops claiming to be empty once something half-typed is in it', async () => {
    renderField()
    const field = screen.getByLabelText(LABELS.label)
    expect(screen.getByText(LABELS.hint)).toBeInTheDocument()

    // What Chrome looks like with one segment filled in: no value, bad input.
    Object.defineProperty(field, 'validity', {
      value: { badInput: true },
      configurable: true,
    })
    field.focus()
    await userEvent.tab()

    expect(screen.queryByText(LABELS.hint)).toBeNull()
  })
})
