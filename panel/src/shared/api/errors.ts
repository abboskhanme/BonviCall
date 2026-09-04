/**
 * The error envelope, client side (CONVENTIONS.md §9, SPEC §4.0, N35).
 *
 * Every non-2xx response the server produces — including 500 — carries
 *
 *     {"error": {"code": "...", "message": "...", "detail": {...},
 *                "request_id": "..."}}
 *
 * `code` is the machine contract: snake_case, stable forever, generated into
 * `errorCodes.gen.ts` from `contract/error-codes.json`. Branch on `code`, never
 * on `message` (SPEC §4.0).
 */
import { isErrorCode, type ErrorCode } from './errorCodes.gen'
import { t, type MessageKey } from '@/shared/i18n'

/**
 * Codes that never come from the server because they describe a failure that
 * happened before a response existed. Kept apart from the generated catalogue
 * so nobody mistakes one for wire contract.
 */
export const CLIENT_ERROR_CODE = {
  /** fetch() rejected: DNS, TLS, offline, CORS. */
  NETWORK: 'client_network_error',
  /** A response arrived but was not the envelope. */
  MALFORMED: 'client_malformed_response',
} as const

export type ClientErrorCode = (typeof CLIENT_ERROR_CODE)[keyof typeof CLIENT_ERROR_CODE]

/** The optional machine-readable part of the envelope. */
export type ErrorDetail = Record<string, unknown>

export class ApiError extends Error {
  readonly status: number
  /** The envelope's `code`. An `ErrorCode` in practice; typed wide so that a
   *  code added on the server before the panel regenerates is still surfaced
   *  rather than swallowed. Use {@link hasCode} to branch on it safely. */
  readonly code: string
  readonly detail: ErrorDetail | null
  readonly requestId: string | null

  constructor(
    status: number,
    code: string,
    message: string,
    detail: ErrorDetail | null = null,
    requestId: string | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
    this.requestId = requestId
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}

/**
 * Type-safe branching on an error code.
 *
 * `hasCode(error, 'number_already_assigned')` is a compile error when the code
 * is misspelled, which a bare `error.code === '…'` comparison is not. That is
 * the same reasoning as the server's `Perm.CALLS_READ` constants (§11.2): a
 * typo in a code fails closed and silently, forever.
 */
export function hasCode(error: unknown, code: ErrorCode | ClientErrorCode): boolean {
  return isApiError(error) && error.code === code
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Parse the §9 envelope out of an already-decoded JSON body. */
export function parseEnvelope(
  body: unknown,
): { code: string; message: string | null; detail: ErrorDetail | null; requestId: string | null } | null {
  if (!isRecord(body)) return null
  const envelope = body.error
  if (!isRecord(envelope)) return null
  const code = envelope.code
  if (typeof code !== 'string' || code.length === 0) return null
  return {
    code,
    message: typeof envelope.message === 'string' ? envelope.message : null,
    detail: isRecord(envelope.detail) ? envelope.detail : null,
    requestId: typeof envelope.request_id === 'string' ? envelope.request_id : null,
  }
}

/** The catalogue key for a server code. Typed, so a code with no Uzbek entry
 *  is a TypeScript error rather than a dotted identifier on screen. */
function catalogueKey(code: ErrorCode): MessageKey {
  return `errors.${code}`
}

/**
 * What the user reads (SPEC §5.3, T100).
 *
 * Order: the Uzbek catalogue keyed by `code`; then the server's own `message`,
 * which is Uzbek for everything a panel user can reach; then a generic line.
 * No raw stack trace and no English string ever reaches a user.
 */
export function messageForError(error: unknown): string {
  if (!isApiError(error)) return t('errors.unknown')
  if (error.code === CLIENT_ERROR_CODE.NETWORK) return t('errors.network')
  if (isErrorCode(error.code)) return t(catalogueKey(error.code))
  if (error.message) return error.message
  return t('errors.unknown')
}
