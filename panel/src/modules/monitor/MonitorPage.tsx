/**
 * The sales-room TV board — stub. T96 replaces this body.
 *
 * Rendered OUTSIDE the AppShell and full screen (SPEC §5.2): a sidebar, a user
 * menu and a theme switch are furniture nobody in the room can click. Numbers
 * are masked to the last 4 digits SERVER-side, so nothing here reveals a client
 * to a visitor walking past.
 */
import { t } from '@/shared/i18n'

export function MonitorPage() {
  return (
    <div className="grid min-h-screen place-items-center bg-bg p-10 text-center">
      <div className="space-y-2">
        <h1 className="text-4xl font-semibold text-text">{t('page.monitor')}</h1>
        <p className="text-sm text-muted">{t('common.underConstruction')}</p>
        <p className="font-mono text-2xs text-muted">T96</p>
      </div>
    </div>
  )
}
