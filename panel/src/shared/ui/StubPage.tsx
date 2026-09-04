/**
 * A placeholder page body.
 *
 * T21 registers every route and nav entry of SPEC §5.2 up front so the fifteen
 * Phase 5 tasks can run in parallel without editing the route table, the nav or
 * each other. Each of those tasks replaces exactly one of these bodies; the
 * route, the gate and the menu entry above it are already settled.
 *
 * A page still holding this component is not "unfinished" — it is a route whose
 * owner has not started yet, and it says so rather than rendering an empty div.
 */
import { Hammer } from 'lucide-react'

import { Page, PageHeader } from '@/shared/layout/Page'
import { t, type MessageKey } from '@/shared/i18n'
import { Card } from '@/shared/ui/primitives'

export function StubPage({ titleKey, task }: { titleKey: MessageKey; task: string }) {
  return (
    <Page>
      <PageHeader title={t(titleKey)} />
      <Card className="flex flex-col items-center gap-2 p-10 text-center">
        <Hammer className="size-8 text-muted" aria-hidden />
        <p className="text-sm font-medium text-text">{t('common.underConstruction')}</p>
        <p className="max-w-md text-xs text-muted">{t('common.underConstructionHint')}</p>
        {/* The task id is English on purpose: it is a build artefact for the
            team, not a sentence a user is meant to read. */}
        <p className="font-mono text-2xs text-muted">{task}</p>
      </Card>
    </Page>
  )
}
