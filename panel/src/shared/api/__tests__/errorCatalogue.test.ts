/**
 * Every error code the server can emit has Uzbek text (SPEC §5.3, T100:
 * "No raw stack trace or English string reaches a user").
 *
 * The list comes from `contract/error-codes.json` through the generated
 * `errorCodes.gen.ts`, so a code added on the server fails this test until the
 * catalogue is updated — which is the point. The panel translates ALL of them,
 * including the codes the server keeps in English for the Android upload queue:
 * a machine reads them there, a person reads them here.
 */
import { describe, expect, it } from 'vitest'

import { ERROR_CODES } from '@/shared/api/errorCodes.gen'
import { messageForError } from '@/shared/api/errors'
import { ApiError } from '@/shared/api/errors'
import { messageKeys } from '@/shared/i18n'

describe('error catalogue', () => {
  it('has an entry for every code in contract/error-codes.json', () => {
    const keys = new Set(messageKeys())
    const missing = ERROR_CODES.filter((code) => !keys.has(`errors.${code}`))
    expect(missing).toEqual([])
  })

  it('resolves every code to Uzbek text rather than the code itself', () => {
    for (const code of ERROR_CODES) {
      const message = messageForError(new ApiError(400, code, ''))
      expect(message).not.toBe(`errors.${code}`)
      expect(message.length).toBeGreaterThan(0)
    }
  })
})
