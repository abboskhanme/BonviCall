/** The three rule kinds, in Uzbek. Exhaustive over the generated union. */
import type { MessageKey } from '@/shared/i18n'
import type { components } from '@/shared/api/types.gen'

type DirectoryRuleKind = components['schemas']['DirectoryRuleKind']

export const RULE_KIND_LABEL: Record<DirectoryRuleKind, MessageKey> = {
  exact: 'lineDirectory.kindExact',
  prefix: 'lineDirectory.kindPrefix',
  suffix: 'lineDirectory.kindSuffix',
}

/** What each one means, in a sentence, because "suffix" is jargon. */
export const RULE_KIND_HINT: Record<DirectoryRuleKind, MessageKey> = {
  exact: 'lineDirectory.kindExactHint',
  prefix: 'lineDirectory.kindPrefixHint',
  suffix: 'lineDirectory.kindSuffixHint',
}

export const RULE_KINDS: readonly DirectoryRuleKind[] = ['exact', 'prefix', 'suffix']
