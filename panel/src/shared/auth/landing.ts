/**
 * Where a user belongs when the panel has to choose for them: after a login
 * with no remembered destination, and after a `<Gate>` refuses a route.
 *
 * The TV board was removed on 2026-09-05 at the client's request, which took
 * the only page the `viewer` role could see with it. Everyone who can log in
 * now lands on the dashboard, so this is a constant — kept as a function
 * because the two call sites (post-login redirect and gate refusal) should keep
 * asking one question rather than each hard-coding an answer.
 *
 * The `viewer` role and `monitor:read` still exist server-side and are being
 * removed there; until they are, a `viewer` would land on a dashboard whose
 * tiles all 403. That is a reason to finish removing the role, not a reason to
 * reintroduce a page for it.
 */
import { Perm, type Permission } from './permissions'

/**
 * The permissions behind the dashboard's tiles (SPEC §5.2: calls captured
 * today, devices online/offline, open alerts by severity, storage used). T85
 * must keep this list and the tiles it renders in step — a tile whose
 * permission is missing here renders a 403 into somebody's landing page.
 */
export const DASHBOARD_PERMISSIONS: readonly Permission[] = [
  Perm.CALLS_READ,
  Perm.CALLS_READ_OWN,
  Perm.DEVICES_READ,
  Perm.DEVICES_READ_OWN,
  Perm.ALERTS_READ,
  Perm.REPORTS_READ,
]

export const DEFAULT_LANDING = '/'

/** The first page any signed-in user should see. */
export function landingPath(): string {
  return DEFAULT_LANDING
}
