/**
 * Rubric — TanStack Query hooks and nothing else (CONVENTIONS-CLIENT.md §1).
 *
 * Module mapping, as §1 requires when the names differ: the panel's `rubric`
 * module reads the server's **`analysis`** module — `server/src/api/panel/
 * rubric.py`, mounted under `/api/v1/analysis/rubric`. The rubric is the
 * criteria the TAHLIL section scores against rather than a section of its own,
 * so it lives under that prefix; the panel keeps it as a module of its own
 * because it is a page with its own state, its own modal and its own query
 * keys. (BonviZvonki had the same pair under two unrelated names — `rubric` in
 * the web app, `scoring` on the server — and nothing wrote it down.)
 *
 * Every type below comes from `types.gen.ts`; not one response shape is written
 * by hand (CONVENTIONS.md §1). That matters more here than anywhere else in the
 * panel: this module POSTS a rubric back, so a field the server renamed has to
 * be a compile error rather than a silently dropped criterion.
 *
 * Query keys are `['rubric', 'active' | 'versions' | 'prompt']`. Both mutations
 * invalidate `['rubric']`, so the header's version badge, the version history
 * and the prompt preview can never disagree about which version is live.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api } from '@/shared/api/client'
import { moduleKey, queryKey } from '@/shared/api/queryKeys'
import type { components } from '@/shared/api/types.gen'

export type Rubric = components['schemas']['RubricResponse']
export type RubricBlock = components['schemas']['RubricBlock']
export type RubricCriterion = components['schemas']['RubricCriterion']
export type RubricRedFlag = components['schemas']['RubricRedFlag']
export type RubricVersions = components['schemas']['RubricVersionListResponse']
export type RubricVersion = components['schemas']['RubricVersionSummary']
export type RubricPrompt = components['schemas']['RubricPromptResponse']
export type PublishRubricRequest = components['schemas']['PublishRubricRequest']

/** The one place the path is written. */
const RUBRIC_PATH = '/analysis/rubric'

/**
 * The rubric new scores are produced against.
 *
 * Answers 200 even on a database where nothing has been published: the body is
 * then the rubric pinned in the server's `rubric_default.py` with
 * `stored: false`, which is exactly what such a database scores with. The page
 * says so rather than pretending somebody published it.
 */
export function useActiveRubric(): UseQueryResult<Rubric> {
  return useQuery({
    queryKey: queryKey('rubric', 'active'),
    queryFn: () => api.get<Rubric>(RUBRIC_PATH),
  })
}

/** Every published version, newest first. Nothing is ever deleted from it. */
export function useRubricVersions(): UseQueryResult<RubricVersions> {
  return useQuery({
    queryKey: queryKey('rubric', 'versions'),
    queryFn: () => api.get<RubricVersions>(`${RUBRIC_PATH}/versions`),
  })
}

/**
 * What is actually sent to the model, assembled from the active rubric.
 *
 * **Fetched, never rebuilt here.** A second copy of the prompt in the panel
 * would drift from the one `prompt.py` builds, and the screen would then show
 * one text while the model received another — a bug with no symptom.
 *
 * Called from a component the page mounts only when the admin opens that
 * section, so the request is not made on every visit: the answer is ~13 000
 * characters and most readers never ask for it.
 */
export function useRubricPrompt(): UseQueryResult<RubricPrompt> {
  return useQuery({
    queryKey: queryKey('rubric', 'prompt'),
    queryFn: () => api.get<RubricPrompt>(`${RUBRIC_PATH}/prompt`),
  })
}

/**
 * `PUT /analysis/rubric` — **publish the next version**, never edit this one.
 *
 * There is no update call and no rubric id in the body. The version that scored
 * yesterday's calls stays exactly as it was, because `call_scores.rubric_version`
 * names it and that string has to keep meaning what it says.
 *
 * 422 `validation_error` comes back with a machine `reason` in the detail — the
 * blocks not totalling 100 is the first of them — and the rubric is not saved.
 * `messageOfInvalid` in `state.ts` turns that reason into the Uzbek sentence.
 */
export function usePublishRubric(): UseMutationResult<Rubric, unknown, PublishRubricRequest> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: PublishRubricRequest) => api.put<Rubric>(RUBRIC_PATH, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('rubric') })
    },
  })
}

/**
 * `POST /analysis/rubric/versions/{version}/activate` — go back to an earlier
 * version. The undo for a bad edit, and the only one: a published version
 * cannot be deleted.
 */
export function useActivateRubricVersion(): UseMutationResult<Rubric, unknown, number> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (version: number) =>
      api.post<Rubric>(`${RUBRIC_PATH}/versions/${version}/activate`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('rubric') })
    },
  })
}
