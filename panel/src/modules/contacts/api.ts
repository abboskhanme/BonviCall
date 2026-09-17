/**
 * Contacts — TanStack Query hooks and nothing else (CONVENTIONS-CLIENT.md §1).
 *
 * Module mapping: the panel's `contacts` module reads the server's `contacts`
 * module (`server/src/api/panel/contacts.py`) one to one.
 *
 * Access: `settings:read` to read, `settings:write` to change — the same gate
 * the other number→meaning dictionary in this product already carries (the line
 * directory, `api/panel/catalog.py`). The server's own docstring gives the
 * reasoning; this module only hides the buttons, which is presentation rather
 * than access control (CONVENTIONS-CLIENT.md §2).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api, type Query } from '@/shared/api/client'
import type { MessageKey } from '@/shared/i18n'
import { moduleKey, queryKey } from '@/shared/api/queryKeys'
import type { components, operations } from '@/shared/api/types.gen'

export type ContactPage = components['schemas']['ContactPageResponse']
export type ContactRow = components['schemas']['ContactRowOut']
export type ContactDetail = components['schemas']['ContactDetailResponse']
export type ContactSummary = components['schemas']['ContactSummaryResponse']
export type ContactPreview = components['schemas']['ContactPreviewResponse']
export type ContactImportReport = components['schemas']['ContactImportResponse']
export type ContactKind = components['schemas']['ContactKind']
export type ImportMode = components['schemas']['ImportMode']

export type ContactListQuery = NonNullable<
  operations['list_contacts_api_v1_contacts_get']['parameters']['query']
>

export const PAGE_SIZE = 50

/** The four kinds, in the order the filter and the picker offer them. */
export const KINDS: readonly ContactKind[] = ['client', 'internal', 'personal', 'unknown']

/**
 * What each kind is called, and what each one means.
 *
 * Here rather than beside the table for a mechanical reason — a `.tsx` file
 * that exports both a component and a constant breaks fast refresh — and for a
 * better one: the filter, the inline picker and the card all render these, and
 * a second copy is how two of them end up disagreeing.
 *
 * The wording matters more than it looks. The field exists because an
 * employee's phone holds customers, colleagues, warehouses and PRIVATE
 * acquaintances all mixed together, and leaving them all labelled "customer"
 * leaks a private person's name into company reports.
 */
export const KIND_LABEL: Record<ContactKind, MessageKey> = {
  client: 'contacts.kind.client',
  internal: 'contacts.kind.internal',
  personal: 'contacts.kind.personal',
  unknown: 'contacts.kind.unknown',
}

export const KIND_HINT: Record<ContactKind, MessageKey> = {
  client: 'contacts.kindHint.client',
  internal: 'contacts.kindHint.internal',
  personal: 'contacts.kindHint.personal',
  unknown: 'contacts.kindHint.unknown',
}

/** The three import modes, narrowest first — which is also the safest first. */
export const MODES: readonly ImportMode[] = ['coded', 'known', 'all']

function toQuery(params: Record<string, unknown>): Query {
  return params as Query
}

export function useContacts(params: ContactListQuery): UseQueryResult<ContactPage> {
  return useQuery({
    queryKey: queryKey('contacts', 'list', params),
    queryFn: () => api.get<ContactPage>('/contacts', toQuery(params)),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

export function useContactsSummary(): UseQueryResult<ContactSummary> {
  return useQuery({
    queryKey: queryKey('contacts', 'summary'),
    queryFn: () => api.get<ContactSummary>('/contacts/summary'),
    staleTime: 30_000,
  })
}

export function useContactDetail(phoneKey: string | null): UseQueryResult<ContactDetail> {
  return useQuery({
    queryKey: queryKey('contacts', 'detail', { phoneKey }),
    queryFn: () => api.get<ContactDetail>(`/contacts/${phoneKey}`),
    enabled: Boolean(phoneKey),
  })
}

/**
 * Step one of the upload: read the file and say what WOULD happen.
 *
 * ⚠️ A MUTATION, not a query, and deliberately never cached. Picking the same
 * file twice can legitimately produce a different answer — if a real import
 * happened in between, `created` drops to zero — and a cached preview would
 * then promise work that has already been done.
 */
export function usePreviewContacts(): UseMutationResult<ContactPreview, Error, File> {
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      // `Content-Type` is deliberately not set: the browser owns the multipart
      // boundary (`shared/api/client.ts`).
      return api.postForm<ContactPreview>('/contacts/import/preview', form)
    },
  })
}

/**
 * Step two: write the list.
 *
 * ⚠️ It is handed the SAME in-memory `File` the preview read, so what was
 * promised is what gets written. Cancelling sends no request at all.
 *
 * Invalidates `clients` as well as `contacts`: an upload changes the NAME and
 * the code a customer is shown under in the directory, and leaving that page
 * stale would show the old names until somebody reloaded.
 */
export function useImportContacts(): UseMutationResult<
  ContactImportReport,
  Error,
  { file: File; mode: ImportMode }
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ file, mode }) => {
      const form = new FormData()
      form.append('file', file)
      return api.postForm<ContactImportReport>('/contacts/import', form, { mode })
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('contacts') })
      void client.invalidateQueries({ queryKey: moduleKey('clients') })
    },
  })
}

/** An admin's correction. The UI only ever sends one field at a time. */
export function useUpdateContact(): UseMutationResult<
  ContactRow,
  Error,
  { phoneKey: string; kind?: ContactKind; code?: string; name?: string }
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ phoneKey, ...body }) =>
      api.patch<ContactRow>(`/contacts/${phoneKey}`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('contacts') })
      void client.invalidateQueries({ queryKey: moduleKey('clients') })
    },
  })
}

export function useDeleteContact(): UseMutationResult<void, Error, string> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (phoneKey: string) => api.delete<void>(`/contacts/${phoneKey}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('contacts') })
      void client.invalidateQueries({ queryKey: moduleKey('clients') })
    },
  })
}
