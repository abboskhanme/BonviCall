/**
 * The SAP upload, and the copy the panel owns.
 *
 * What it must not get wrong:
 *
 *  1. the estimate WRITES NOTHING. The file used to land in the database the
 *     moment it was picked, and two mistakes passed silently — the wrong file
 *     and a repeat upload — neither of which can be undone;
 *  2. the confirm step sends the SAME file the estimate read;
 *  3. warnings arrive as CODES and come out as Uzbek sentences. The server no
 *     longer ships ready-made strings, so an untranslated code is a blank line
 *     where a warning should be;
 *  4. an upload refusal names the actual problem. `messageForError` would
 *     render the generic "validation_error" line, which tells somebody holding
 *     the wrong spreadsheet nothing at all;
 *  5. the `by_type` label is translated from `type` and falls back to SAP's
 *     own Russian word, which is deliberate: the reader compares the count
 *     against SAP's own report.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ImportModal } from '@/modules/sales/ImportModal'
import { uploadFailure } from '@/modules/sales/uploadError'
import { ApiError } from '@/shared/api/client'
import { t } from '@/shared/i18n'

import { makePreview, makeReport } from './fixtures'

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function serving({ preview = makePreview(), report = makeReport() } = {}) {
  fetchMock.mockImplementation((input) => {
    const url =
      typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    if (url.includes('/sales/import/preview')) return Promise.resolve(jsonResponse(200, preview))
    if (url.includes('/sales/import')) return Promise.resolve(jsonResponse(200, report))
    return Promise.resolve(jsonResponse(200, {}))
  })
}

function renderModal() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ImportModal open onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
}

function xlsx(name = 'savdo-kunlik.xlsx') {
  return new File(['PK'], name, {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
}

function urls(): string[] {
  return fetchMock.mock.calls.map((call) => String(call[0]))
}

beforeEach(() => vi.stubGlobal('fetch', fetchMock))
afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

describe('the two steps', () => {
  it('estimates first, and the estimate writes nothing', async () => {
    serving()
    renderModal()
    await userEvent.upload(
      document.querySelector('input[type="file"]') as HTMLInputElement,
      xlsx(),
    )
    await userEvent.click(screen.getByRole('button', { name: t('sales.import.start') }))

    await waitFor(() => {
      expect(urls().some((url) => url.includes('/sales/import/preview'))).toBe(true)
      expect(urls().some((url) => /\/sales\/import$/.test(url))).toBe(false)
    })
  })

  it('shows the three numbers and says they do not add up', async () => {
    // ⚠️ "Jami" is rows in the file; the other two count UNIQUE keys. One
    // operation number occurs twice in a real file (2,383 in 2,384 rows).
    serving()
    renderModal()
    await userEvent.upload(
      document.querySelector('input[type="file"]') as HTMLInputElement,
      xlsx(),
    )
    await userEvent.click(screen.getByRole('button', { name: t('sales.import.start') }))

    expect(await screen.findByText(t('sales.import.preview.new'))).toBeInTheDocument()
    expect(
      screen.getByText(t('sales.import.warn.duplicate_keys_in_file', { count: 1 })),
    ).toBeInTheDocument()
  })

  it('writes only after the confirmation, with the SAME file', async () => {
    serving()
    renderModal()
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(input, xlsx())
    await userEvent.click(screen.getByRole('button', { name: t('sales.import.start') }))
    await screen.findByText(t('sales.import.preview.new'))

    await userEvent.click(screen.getByRole('button', { name: t('sales.import.confirm') }))
    await waitFor(() => {
      const written = fetchMock.mock.calls.find((call) => /\/sales\/import$/.test(String(call[0])))
      expect(written).toBeDefined()
      const body = written?.[1]?.body as FormData
      expect((body.get('file') as File).name).toBe('savdo-kunlik.xlsx')
    })
  })

  it('reports what it did rather than closing silently', async () => {
    serving()
    renderModal()
    await userEvent.upload(
      document.querySelector('input[type="file"]') as HTMLInputElement,
      xlsx(),
    )
    await userEvent.click(screen.getByRole('button', { name: t('sales.import.start') }))
    await screen.findByText(t('sales.import.preview.new'))
    await userEvent.click(screen.getByRole('button', { name: t('sales.import.confirm') }))

    expect(
      await screen.findByText(t('sales.import.created', { count: 1902 })),
    ).toBeInTheDocument()
    // A number that answers its own question: sales whose attributed
    // conversation changed because of this import.
    expect(
      screen.getByText(t('sales.import.attributedSales', { count: 12 })),
    ).toBeInTheDocument()
  })
})

describe('the warning codes', () => {
  it('turns every documented code into an Uzbek sentence', async () => {
    // ⚠️ The server sends `{code, count}` and the panel owns the wording. An
    // untranslated code renders NOTHING, which is why every code in the closed
    // set is checked here.
    const codes = [
      'rows_without_date',
      'rows_without_partner_code',
      'rows_without_amount',
      'duplicate_keys_in_file',
      'unknown_operation_types',
      'contractors_without_usable_phone',
      'inactive_contractors',
      'codes_absent_from_catalogue',
    ]
    serving({
      preview: makePreview({ warnings: codes.map((code) => ({ code, count: 3 })) }),
    })
    renderModal()
    await userEvent.upload(
      document.querySelector('input[type="file"]') as HTMLInputElement,
      xlsx(),
    )
    await userEvent.click(screen.getByRole('button', { name: t('sales.import.start') }))
    await screen.findByText(t('sales.import.preview.warnings'))

    for (const code of codes) {
      const key = `sales.import.warn.${code}` as Parameters<typeof t>[0]
      const sentence = t(key, { count: 3 })
      // A missing key returns the key itself — loud on purpose.
      expect(sentence).not.toBe(key)
      expect(screen.getByText(sentence)).toBeInTheDocument()
    }
  })

  it('skips a code it has no sentence for rather than printing the identifier', async () => {
    serving({ preview: makePreview({ warnings: [{ code: 'something_new', count: 2 }] }) })
    renderModal()
    await userEvent.upload(
      document.querySelector('input[type="file"]') as HTMLInputElement,
      xlsx(),
    )
    await userEvent.click(screen.getByRole('button', { name: t('sales.import.start') }))
    await screen.findByText(t('sales.import.preview.warnings'))
    expect(screen.queryByText(/something_new/)).toBeNull()
  })
})

describe('the operation-type slice', () => {
  it('translates from `type` and falls back to SAP\'s own word', async () => {
    // ⚠️ `label` is Russian ON PURPOSE — it is what SAP printed, and the
    // reader compares the count against SAP's own report.
    serving({
      preview: makePreview({
        by_type: [
          { type: 'sale', label: 'Продажа', count: 10, amount_usd: 100 },
          { type: 'Бирлашган гурух', label: 'Бирлашган гурух', count: 4, amount_usd: null },
        ],
      }),
    })
    renderModal()
    await userEvent.upload(
      document.querySelector('input[type="file"]') as HTMLInputElement,
      xlsx(),
    )
    await userEvent.click(screen.getByRole('button', { name: t('sales.import.start') }))

    expect(await screen.findByText(t('sales.import.opType.sale'))).toBeInTheDocument()
    expect(screen.getByText('Бирлашган гурух')).toBeInTheDocument()
    expect(screen.queryByText('Продажа')).toBeNull()
  })
})

// ── The refusals ──────────────────────────────────────────────

describe('uploadFailure', () => {
  function refusal(detail: Record<string, unknown>, status = 422): ApiError {
    return new ApiError(status, 'validation_error', '', detail, 'req-1')
  }

  it('names the actual problem for every documented reason', () => {
    const reasons = [
      'not_xlsx',
      'wrong_content_type',
      'empty_file',
      'unreadable_file',
      'unrecognised_export',
    ]
    for (const reason of reasons) {
      const message = uploadFailure(refusal({ reason }))
      expect(message).not.toBe(t('sales.import.failed'))
      expect(message.length).toBeGreaterThan(10)
    }
  })

  it('names the MISSING COLUMN, because that is the actionable part', () => {
    expect(uploadFailure(refusal({ reason: 'column_missing', column: 'Номер операции' }))).toContain(
      'Номер операции',
    )
  })

  it('translates the kinds in a wrong-export refusal rather than printing identifiers', () => {
    const message = uploadFailure(
      refusal({ reason: 'wrong_export_kind', found: 'balance', expected: 'register' }),
    )
    expect(message).toContain(t('sales.import.kind.balance'))
    expect(message).toContain(t('sales.import.kind.register'))
    expect(message).not.toContain('balance')
  })

  it('reports the size ceiling in megabytes on a 413', () => {
    expect(
      uploadFailure(
        new ApiError(413, 'payload_too_large', '', { max_bytes: 20 * 1024 * 1024 }, 'r'),
      ),
    ).toBe(t('sales.import.err.too_large', { limit: 20 }))
  })

  it('falls back to a generic line for anything it does not recognise', () => {
    expect(uploadFailure(refusal({ reason: 'something_new' }))).toBe(t('sales.import.failed'))
    expect(uploadFailure(new Error('boom'))).toBe(t('sales.import.failed'))
  })
})
