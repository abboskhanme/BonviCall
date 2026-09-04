/**
 * Generate the panel's wire types from the committed contract.
 *
 * CONVENTIONS.md §1: the contract is code-first — Pydantic is the source of
 * truth, `make contract` writes contract/*.json, and the client types are
 * GENERATED from those files. A hand-written interface mirroring a response is
 * a violation, because a renamed field must be a compile error rather than a
 * runtime `undefined`.
 *
 * Two outputs, both committed so CI can diff them:
 *   src/shared/api/types.gen.ts       <- contract/openapi-panel-v1.json
 *   src/shared/api/errorCodes.gen.ts  <- contract/error-codes.json
 *
 * Run it with `make types` from the repository root.
 */
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import openapiTS, { astToString } from 'openapi-typescript'

const here = path.dirname(fileURLToPath(import.meta.url))
const panelRoot = path.resolve(here, '..')

/**
 * The contract directory. Inside the panel container the repository root is not
 * mounted, so `make types` mounts contract/ at /contract; on a developer
 * machine it sits next to panel/. CONTRACT_DIR overrides both.
 */
function resolveContractDir() {
  const candidates = [
    process.env.CONTRACT_DIR,
    '/contract',
    path.resolve(panelRoot, '..', 'contract'),
  ].filter(Boolean)
  for (const candidate of candidates) {
    if (existsSync(path.join(candidate, 'openapi-panel-v1.json'))) return candidate
  }
  throw new Error(
    `openapi-panel-v1.json not found. Looked in: ${candidates.join(', ')}. ` +
      'Run `make contract` first, or set CONTRACT_DIR.',
  )
}

const BANNER = `/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Source: contract/%SOURCE%
 * Regenerate: make types   (panel: npm run gen:types)
 *
 * Hand-editing this file is a CONVENTIONS.md §1 violation: the Pydantic schemas
 * are the source of truth and a hand-written copy drifts silently.
 */
`

async function generateOpenApiTypes(contractDir, outDir) {
  const source = path.join(contractDir, 'openapi-panel-v1.json')
  const ast = await openapiTS(new URL(`file://${source}`), {
    alphabetize: true,
    emptyObjectsUnknown: true,
  })
  const body = astToString(ast)
  const out = path.join(outDir, 'types.gen.ts')
  await writeFile(out, BANNER.replace('%SOURCE%', 'openapi-panel-v1.json') + '\n' + body, 'utf8')
  return out
}

async function generateErrorCodes(contractDir, outDir) {
  const source = path.join(contractDir, 'error-codes.json')
  const raw = JSON.parse(await readFile(source, 'utf8'))
  const codes = [...raw.codes].sort()
  const members = codes.map((code) => `  '${code}',`).join('\n')
  const body = `
/** Every error code the server can emit (server/src/core/errors.py::ErrorCode). */
export const ERROR_CODES = [
${members}
] as const

/** The stable machine contract clients branch on. Never branch on the message. */
export type ErrorCode = (typeof ERROR_CODES)[number]

export function isErrorCode(value: string): value is ErrorCode {
  return (ERROR_CODES as readonly string[]).includes(value)
}
`
  const out = path.join(outDir, 'errorCodes.gen.ts')
  await writeFile(out, BANNER.replace('%SOURCE%', 'error-codes.json') + body, 'utf8')
  return out
}

const contractDir = resolveContractDir()
const outDir = path.join(panelRoot, 'src', 'shared', 'api')
await mkdir(outDir, { recursive: true })
const written = [
  await generateOpenApiTypes(contractDir, outDir),
  await generateErrorCodes(contractDir, outDir),
]
console.log(`generated from ${contractDir}:`)
for (const file of written) console.log('  ' + path.relative(panelRoot, file))
