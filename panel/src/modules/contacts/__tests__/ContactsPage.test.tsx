/**
 * `/contacts` — the page and its two dialogs.
 *
 * What it must not get wrong, in order of how much damage it does:
 *
 *  1. the upload is TWO steps and the first one writes nothing. This list
 *     decides who a customer IS, and a wrong upload attaches conversations to
 *     the wrong code;
 *  2. the confirm button must send the mode that is selected and the file that
 *     was previewed — not a different file and not a different mode;
 *  3. the narrow mode is the default. A full phone export carries family,
 *     friends and the taxi driver, and defaulting to "everything" puts
 *     strangers' names in the company database on the first upload;
 *  4. a reader without `settings:write` gets no buttons — the server refuses
 *     either way, but a button that always 403s is a bug with a border.
 *
 * Plus the three `QueryBoundary` states, as CONVENTIONS-CLIENT.md §10 requires.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ContactsPage } from '@/modules/contacts/ContactsPage'
import { useAuth } from '@/modules/auth/store'
import { t } from '@/shared/i18n'
import { Perm } from '@/shared/auth/permissions'

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function signIn(permissions: string[]) {
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: '55555555-5555-4555-8555-555555555555',
      email: 'tester@bonvi.uz',
      full_name: 'Test User',
      role: 'admin',
      permissions,
      must_change_password: false,
      agent_id: null,
    },
    permissions: new Set(permissions),
    loginError: null,
  })
}

function makeRow(overrides: Record<string, unknown> = {}) {
  return {
    phone_key: '901112233',
    phone: '+998901112233',
    raw_name: 'K00150 Elyor aka',
    name: 'Elyor aka',
    code: 'К00150',
    kind: 'client',
    source_file: 'aziz.csv',
    calls: 0,
    code_numbers: 1,
    ...overrides,
  }
}

const SUMMARY = {
  total: 2,
  with_code: 1,
  by_kind: { client: 1, internal: 0, personal: 1, unknown: 0 },
}

const PREVIEW = {
  file: 'aziz.csv',
  read: 120,
  parsed: 44,
  no_phone: 70,
  bad_phone: 3,
  no_name: 2,
  duplicates: 1,
  with_code: 12,
  created: 12,
  updated: 0,
  unchanged: 0,
  calls_covered: 340,
  suggested: { unknown: 12, personal: 32 },
  would_import: { coded: 12, known: 14, all: 44 },
  would_cover: { coded: 300, known: 310, all: 340 },
  rows: [],
}

const REPORT = {
  file: 'aziz.csv',
  mode: 'coded',
  read: 120,
  created: 12,
  updated: 0,
  unchanged: 0,
  no_phone: 70,
  bad_phone: 3,
  no_name: 2,
  duplicates: 1,
  skipped_filter: 32,
}

/** Every path this page touches, each answering for itself. */
function serving(rows = [makeRow()]) {
  fetchMock.mockImplementation((input, init) => {
    const url =
      typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    if (url.includes('/contacts/import/preview')) return Promise.resolve(jsonResponse(200, PREVIEW))
    if (url.includes('/contacts/import')) return Promise.resolve(jsonResponse(200, REPORT))
    if (url.includes('/contacts/summary')) return Promise.resolve(jsonResponse(200, SUMMARY))
    if (init?.method === 'PATCH') return Promise.resolve(jsonResponse(200, makeRow()))
    return Promise.resolve(
      jsonResponse(200, {
        items: rows,
        next_cursor: null,
        has_more: false,
        total: rows.length,
      }),
    )
  })
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false, gcTime: 0 },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={['/contacts']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <ContactsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  signIn([Perm.SETTINGS_READ, Perm.SETTINGS_WRITE])
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

// ── The three QueryBoundary states ────────────────────────────

describe('the three non-success states', () => {
  it('renders a skeleton while the list is in flight', () => {
    fetchMock.mockImplementation(() => new Promise(() => {}))
    renderPage()
    expect(screen.getByTestId('query-loading')).toBeInTheDocument()
  })

  it('renders an error state when the request fails', async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(
        jsonResponse(500, {
          error: { code: 'internal_error', message: 'x', request_id: 'r' },
        }),
      ),
    )
    renderPage()
    expect(await screen.findByTestId('query-error')).toBeInTheDocument()
  })

  it('offers the upload from the empty state, because that is the way out', async () => {
    serving([])
    renderPage()
    expect(await screen.findByText(t('contacts.empty'))).toBeInTheDocument()
    const empty = screen.getByTestId('query-empty')
    expect(
      within(empty).getByRole('button', { name: t('contacts.import.button') }),
    ).toBeInTheDocument()
  })
})

// ── The row ───────────────────────────────────────────────────

describe('a dictionary row', () => {
  it('shows the cleaned name over the handset wording', async () => {
    // "Why is this name different?" must be answerable from the row rather
    // than by reopening the file.
    serving()
    renderPage()
    expect(await screen.findByText('Elyor aka')).toBeInTheDocument()
    expect(screen.getByText('K00150 Elyor aka')).toBeInTheDocument()
  })

  it('does not repeat the handset wording when nothing was cut out of it', async () => {
    serving([makeRow({ name: 'Shifokor', raw_name: 'Shifokor', code: null })])
    renderPage()
    expect(await screen.findAllByText('Shifokor')).toHaveLength(1)
  })

  it('marks a customer who has two of our numbers', async () => {
    // ⚠️ Two numbers for one customer is the ORDINARY case, not an error.
    // Without the badge the row reads as a duplicate.
    serving([makeRow({ code_numbers: 2 })])
    renderPage()
    expect(
      await screen.findByText(t('contacts.multiNumber', { count: 2 })),
    ).toBeInTheDocument()
  })
})

// ── Access ────────────────────────────────────────────────────

describe('without settings:write', () => {
  beforeEach(() => signIn([Perm.SETTINGS_READ]))

  it('offers no upload button', async () => {
    serving()
    renderPage()
    await screen.findByText('Elyor aka')
    expect(screen.queryByRole('button', { name: t('contacts.import.button') })).toBeNull()
  })

  it('shows the kind as text rather than as an editable picker', async () => {
    serving()
    renderPage()
    await screen.findByText('Elyor aka')
    expect(
      screen.queryByLabelText(t('contacts.kindOf', { name: 'K00150 Elyor aka' })),
    ).toBeNull()
    // Scoped to the ROW: "Mijoz" is also an option in the kind filter above.
    const row = screen.getByText('Elyor aka').closest('tr')!
    expect(within(row).getByText(t('contacts.kind.client'))).toBeInTheDocument()
  })
})

describe('with settings:write', () => {
  it('lets an admin re-classify a contact in place', async () => {
    // ⚠️ The classification is the admin's and the upload never overwrites it.
    // Making it editable from the list is what stops it being re-done after
    // every import.
    serving()
    renderPage()
    await screen.findByText('Elyor aka')
    await userEvent.selectOptions(
      screen.getByLabelText(t('contacts.kindOf', { name: 'K00150 Elyor aka' })),
      'personal',
    )

    await waitFor(() => {
      const patched = fetchMock.mock.calls.find((call) => call[1]?.method === 'PATCH')
      expect(patched).toBeDefined()
      expect(String(patched?.[0])).toContain('/contacts/901112233')
      expect(String(patched?.[1]?.body)).toContain('personal')
    })
  })
})

// ── The upload ────────────────────────────────────────────────

async function openImport() {
  serving()
  renderPage()
  await screen.findByText('Elyor aka')
  await userEvent.click(screen.getByRole('button', { name: t('contacts.import.button') }))
}

function csv(name = 'aziz.csv') {
  return new File(['Ism,Telefon\nK00150 Elyor,+998901112233\n'], name, { type: 'text/csv' })
}

describe('the upload', () => {
  it('previews before it writes, and the preview writes nothing', async () => {
    await openImport()
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(input, csv())

    await waitFor(() => {
      const posted = fetchMock.mock.calls.map((call) => String(call[0]))
      expect(posted.some((url) => url.includes('/contacts/import/preview'))).toBe(true)
      expect(posted.some((url) => /\/contacts\/import(\?|$)/.test(url))).toBe(false)
    })
  })

  it('counts a missing number and a bad number apart', async () => {
    // ⚠️ Measured: 7,316 rows with NO number against 11 with an unusable one.
    // One line reading "7,327 bad rows" would be a false conclusion about
    // somebody's data.
    await openImport()
    await userEvent.upload(
      document.querySelector('input[type="file"]') as HTMLInputElement,
      csv(),
    )
    expect(
      await screen.findByText(t('contacts.import.noPhone', { count: 70 })),
    ).toBeInTheDocument()
    expect(screen.getByText(t('contacts.import.badPhone', { count: 3 }))).toBeInTheDocument()
  })

  it('opens on the NARROW mode', async () => {
    // A full phone export carries family, friends and the taxi driver.
    await openImport()
    await userEvent.upload(
      document.querySelector('input[type="file"]') as HTMLInputElement,
      csv(),
    )
    const coded = await screen.findByRole('radio', { name: /Faqat kodi yozilganlari/ })
    expect(coded).toBeChecked()
    expect(
      screen.getByRole('button', { name: t('contacts.import.confirm', { count: 12 }) }),
    ).toBeInTheDocument()
  })

  it('shows the CALLS each mode covers, not only the row count', async () => {
    // ⚠️ A row count flatters the wide mode: the narrow set is spoken to far
    // more often, and the decision is taken on that number.
    await openImport()
    await userEvent.upload(
      document.querySelector('input[type="file"]') as HTMLInputElement,
      csv(),
    )
    expect(
      await screen.findByText(t('contacts.import.modeCover', { count: 300 })),
    ).toBeInTheDocument()
    expect(screen.getByText(t('contacts.import.modeCover', { count: 340 }))).toBeInTheDocument()
  })

  it('writes with the mode that is selected', async () => {
    await openImport()
    await userEvent.upload(
      document.querySelector('input[type="file"]') as HTMLInputElement,
      csv(),
    )
    await screen.findByRole('radio', { name: /Faqat kodi yozilganlari/ })
    await userEvent.click(screen.getByRole('radio', { name: /Hammasi/ }))
    await userEvent.click(
      screen.getByRole('button', { name: t('contacts.import.confirm', { count: 44 }) }),
    )

    await waitFor(() => {
      const written = fetchMock.mock.calls
        .map((call) => String(call[0]))
        .find((url) => /\/contacts\/import\?/.test(url))
      expect(written).toContain('mode=all')
    })
  })

  it('reports what it did rather than closing silently', async () => {
    await openImport()
    await userEvent.upload(
      document.querySelector('input[type="file"]') as HTMLInputElement,
      csv(),
    )
    await userEvent.click(
      await screen.findByRole('button', {
        name: t('contacts.import.confirm', { count: 12 }),
      }),
    )
    expect(
      await screen.findByText(t('contacts.import.done', { created: 12, updated: 0 })),
    ).toBeInTheDocument()
    expect(screen.getByText(t('contacts.import.skippedFilter'))).toBeInTheDocument()
  })
})
