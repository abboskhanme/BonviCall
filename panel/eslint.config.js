import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

/**
 * The forbidden list of CONVENTIONS-CLIENT.md §11, made mechanical wherever a
 * lint rule can express it. What lint cannot see (hex colours in class names,
 * a hand-written response interface) stays a review item.
 */
export default tseslint.config(
  { ignores: ['dist', 'coverage', 'src/shared/api/*.gen.ts'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.node },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // §11: no `any`, no `@ts-ignore`, no `@ts-expect-error`.
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/ban-ts-comment': [
        'error',
        { 'ts-ignore': true, 'ts-expect-error': true, 'ts-nocheck': true },
      ],
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports', fixStyle: 'inline-type-imports' },
      ],
      'no-restricted-syntax': [
        'error',
        {
          // §2: all HTTP goes through shared/api/client.ts. The audio Service
          // Worker (T153) is plain JS in public/ and is not linted here.
          selector: "CallExpression[callee.name='fetch']",
          message:
            'Bare fetch() is forbidden outside shared/api/client.ts (CONVENTIONS-CLIENT.md §2).',
        },
      ],
    },
  },
  {
    // The JSON client (CONVENTIONS-CLIENT.md §2).
    files: ['src/shared/api/client.ts'],
    rules: { 'no-restricted-syntax': 'off' },
  },
  {
    // §2: loading/empty/error have one answer. A page that reads isPending
    // itself is the start of twenty different empty states.
    files: ['src/modules/**/*.tsx', 'src/modules/**/*.ts'],
    ignores: ['src/modules/**/*.test.tsx', 'src/modules/**/*.test.ts'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: "CallExpression[callee.name='fetch']",
          message:
            'Bare fetch() is forbidden outside shared/api/client.ts (CONVENTIONS-CLIENT.md §2).',
        },
        {
          selector:
            "MemberExpression[property.name=/^(isLoading|isPending|isFetching)$/]",
          message:
            'Use <QueryBoundary> instead of handling the loading state inside a page (CONVENTIONS-CLIENT.md §2).',
        },
      ],
    },
  },
  {
    /**
     * CONVENTIONS.md §11 fixes WHERE the two frontend permission checks live:
     * the route table in app/router.tsx and NAV in shared/layout/AppShell.tsx.
     * Both files therefore export data next to components, which costs fast
     * refresh on those two files (they full-reload instead). Moving the
     * constants elsewhere to please the linter would move the rule out of the
     * file the convention names, so the linter loses.
     */
    files: ['src/app/router.tsx', 'src/shared/layout/AppShell.tsx'],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
  {
    /**
     * The audio bridge, exempted AFTER the `src/modules/**` block above —
     * which re-declares `no-restricted-syntax` and would otherwise win.
     *
     * This is the exception CONVENTIONS-CLIENT.md §4 already anticipates: a
     * binary stream carrying a `Range` header, whose `Content-Disposition`
     * has to be read off the response. None of that is what the JSON client
     * models, and routing it through `api.get` would mean teaching that
     * client about blobs and byte ranges to satisfy a rule about JSON.
     * `export.ts` is the same exception for the same reason: a streamed CSV
     * with a `Content-Disposition` to read off the response.
     * `public/audio-sw.js` is plain JS outside `src/` and is not linted here.
     */
    files: ['src/modules/calls/audio.ts', 'src/modules/calls/export.ts'],
    rules: { 'no-restricted-syntax': 'off' },
  },
  {
    files: ['**/*.test.ts', '**/*.test.tsx', 'vitest.setup.ts'],
    languageOptions: { globals: { ...globals.node } },
  },
)
