/**
 * Clients — TanStack Query hooks and nothing else (CONVENTIONS-CLIENT.md §1).
 *
 * Module mapping: the panel's `clients` module reads the server's `clients`
 * module (`server/src/api/panel/clients.py`) **one to one**. BonviZvonki hides
 * this behind a rename — its `contacts` page calls `modules/clients` — which is
 * one of the four silent mismatches §1 names; there is none here.
 *
 * Every type comes from `types.gen.ts`, generated from
 * `contract/openapi-panel-v1.json` by `make types`. Not one response shape is
 * written by hand (CONVENTIONS.md §1).
 *
 * Access: `calls:read` or `calls:read:own`. A salesperson passes the gate and
 * the SERVER narrows the rows to the customers they have spoken to; this module
 * never re-implements that rule, it only hides the agent filter, which is
 * presentation rather than access control (CONVENTIONS-CLIENT.md §2).
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'

import { api, type Query } from '@/shared/api/client'
import { queryKey } from '@/shared/api/queryKeys'
import type { components, operations } from '@/shared/api/types.gen'

export type ClientPage = components['schemas']['ClientPageResponse']
export type ClientRow = components['schemas']['ClientRowOut']
export type ClientDetail = components['schemas']['ClientDetailResponse']
export type ClientAgent = components['schemas']['ClientAgentRow']
export type ClientCallsPage = components['schemas']['ClientCallsResponse']
export type ClientCall = components['schemas']['ClientCallRow']
export type ClientScope = components['schemas']['ClientScope']
export type ClientSort = components['schemas']['ClientSort']

/** The query string `GET /api/v1/clients` accepts, from the contract. */
export type ClientListQuery = NonNullable<
  operations['list_clients_api_v1_clients_get']['parameters']['query']
>

/**
 * One page of customers.
 *
 * Fifty, with no page-size picker — the same decision `/calls` made and for the
 * same reason: two options would take up space on the bar without answering any
 * question anybody has asked.
 */
export const PAGE_SIZE = 50

/**
 * The sortable columns, and the direction each one opens in.
 *
 * "Most recent first" and "most calls first" are what a reader means by
 * clicking those headers; a name sorts A→Z. Written out rather than defaulted,
 * because a table that opens every column descending puts the alphabet
 * backwards.
 */
export const FIRST_ORDER: Record<ClientSort, 'asc' | 'desc'> = {
  last_call: 'desc',
  calls: 'desc',
  missed: 'desc',
  talk: 'desc',
  score: 'desc',
  name: 'asc',
}

function toQuery(params: Record<string, unknown>): Query {
  return params as Query
}

/**
 * The directory.
 *
 * `keepPreviousData` so paging and re-sorting do not blank the table: the rows
 * on screen stay put while the next page is in flight, which is what makes the
 * headers feel like controls rather than reloads.
 */
export function useClients(params: ClientListQuery): UseQueryResult<ClientPage> {
  return useQuery({
    queryKey: queryKey('clients', 'list', params),
    queryFn: () => api.get<ClientPage>('/clients', toQuery(params)),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  })
}

/**
 * One customer's card.
 *
 * ⚠️ Asked with the SAME filter the list was asked with. If the two drift, a
 * row reading "12 calls" opens onto a different number and the reader has no
 * way to know which to believe.
 */
export function useClient(
  key: string | undefined,
  params: Omit<ClientListQuery, 'cursor' | 'limit' | 'with_total' | 'sort' | 'order'>,
): UseQueryResult<ClientDetail> {
  return useQuery({
    queryKey: queryKey('clients', 'detail', { ...params, key }),
    queryFn: () => api.get<ClientDetail>(`/clients/${key}`, toQuery(params)),
    enabled: Boolean(key),
    staleTime: 60_000,
  })
}

/** This customer's conversations, newest first. */
export function useClientCalls(
  key: string | undefined,
  params: Omit<ClientListQuery, 'sort' | 'order'>,
): UseQueryResult<ClientCallsPage> {
  return useQuery({
    queryKey: queryKey('clients', 'calls', { ...params, key }),
    queryFn: () => api.get<ClientCallsPage>(`/clients/${key}/calls`, toQuery(params)),
    enabled: Boolean(key),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  })
}
