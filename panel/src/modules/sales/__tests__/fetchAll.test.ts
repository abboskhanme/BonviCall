/**
 * The walk over the whole selection — `modules/sales/fetchAll.ts`.
 *
 * This is the file that decides whether an exported spreadsheet tells the
 * truth, so what it must not get wrong is short and absolute:
 *
 *  1. it must collect EVERY page, or the file states "12 suspicious sales"
 *     for a filter holding 451;
 *  2. it must follow the CURSOR, never a page number — this list is keyset
 *     paged and an offset walk loses a row every time somebody decides on a
 *     sale while the walk is running;
 *  3. it must stop. A server that repeats a cursor or answers an empty page
 *     while still claiming `has_more` must not spin the tab for ever;
 *  4. a cut list must SAY it was cut.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchAllCompliance } from '@/modules/sales/fetchAll'

import { makeItem, makeList } from './fixtures'

const fetchMock = vi.fn<typeof fetch>()

/**
 * A FRESH response per call.
 *
 * ⚠️ `mockResolvedValue(new Response(...))` hands the same object to every
 * call, and a `Response` body can only be read once — the second read gives
 * `null` and the walk reads it as "the server answered nothing". The mistake
 * costs an afternoon, so the repeating pages below build one each time.
 */
function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** An endless server: the same page, but a new response every time. */
function serving(body: unknown): void {
  fetchMock.mockImplementation(() => Promise.resolve(jsonResponse(body)))
}

/** The query string of every request made, in order. */
function queries(): URLSearchParams[] {
  return fetchMock.mock.calls.map(
    (call) => new URLSearchParams(String(call[0]).split('?')[1] ?? ''),
  )
}

/** The nth request, or a failure naming the one that was never made. */
function queryAt(index: number): URLSearchParams {
  const query = queries()[index]
  if (!query) throw new Error(`request ${index} was never made`)
  return query
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

describe('the walk', () => {
  it('follows the cursor to the end and returns every row', async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(
          makeList([makeItem({ id: 'a' })], {
            has_more: true,
            next_cursor: 'c1',
            total: 3,
          }),
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          makeList([makeItem({ id: 'b' })], {
            has_more: true,
            next_cursor: 'c2',
            total: null,
          }),
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          makeList([makeItem({ id: 'c' })], { has_more: false, next_cursor: null, total: null }),
        ),
      )

    const result = await fetchAllCompliance({ review: 'all' })

    expect(result.rows.map((row) => row.id)).toEqual(['a', 'b', 'c'])
    expect(result.truncated).toBe(false)
    // The count is asked for ONCE and kept: later pages answer null, and a
    // header that turned into a dash would read as a number that got lost.
    expect(result.total).toBe(3)
  })

  it('starts from the beginning and pays for the count only once', async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(makeList([makeItem()], { has_more: true, next_cursor: 'c1' })),
      )
      .mockResolvedValueOnce(jsonResponse(makeList([makeItem()], { has_more: false })))

    // The screen's own cursor must not travel into the file: the export is the
    // filter's rows from the first one, not the page somebody is standing on.
    await fetchAllCompliance({ review: 'all', cursor: 'page-five' })

    const first = queryAt(0)
    const second = queryAt(1)
    expect(first.get('cursor')).toBeNull()
    expect(first.get('with_total')).toBe('true')
    expect(second.get('cursor')).toBe('c1')
    expect(second.get('with_total')).toBe('false')
  })

  it('stops at the cap and says the list was cut', async () => {
    serving(
      makeList([makeItem({ id: 'a' }), makeItem({ id: 'b' })], {
        has_more: true,
        next_cursor: 'c1',
      }),
    )

    const result = await fetchAllCompliance({ review: 'all' }, { batch: 2, maxRows: 3 })

    expect(result.rows).toHaveLength(3)
    expect(result.truncated).toBe(true)
  })
})

describe('a server that never ends', () => {
  it('stops when the cursor repeats', async () => {
    serving(makeList([makeItem()], { has_more: true, next_cursor: 'same' }))

    const result = await fetchAllCompliance({ review: 'all' })

    expect(result.rows).toHaveLength(2)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('stops on an empty page that still claims there is more', async () => {
    serving(makeList([], { has_more: true, next_cursor: 'c1', total: 40 }))

    const result = await fetchAllCompliance({ review: 'all' })

    expect(result.rows).toHaveLength(0)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
