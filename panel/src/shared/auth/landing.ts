/**
 * Where a user belongs when the panel has to choose for them: after a login
 * with no remembered destination, and after a `<Gate>` refuses a route.
 *
 * `viewer` holds `monitor:read` and nothing else, so the dashboard's tiles —
 * calls today, devices online, open alerts, enrolment progress, storage — would
 * every one of them come back 403. A page whose whole contents 403 is not a
 * page, it is a bug with a route, so that user goes to the board they are for.
 *
 * This is NOT a role map (SPEC §5.1). It asks the same question the dashboard
 * itself asks — "is there a single tile this user may see?" — against the
 * permission list `GET /auth/me` resolved on the server.
 */
import { Perm, type Permission } from './permissions'

/**
 * The permissions behind the dashboard's tiles (SPEC §5.2: calls captured
 * today, devices online/offline, open alerts by severity, enrolment progress,
 * storage used). T85 must keep this list and the tiles it renders in step.
 */
export const DASHBOARD_PERMISSIONS: readonly Permission[] = [
  Perm.CALLS_READ,
  Perm.CALLS_READ_OWN,
  Perm.DEVICES_READ,
  Perm.DEVICES_READ_OWN,
  Perm.ALERTS_READ,
  Perm.ENROLMENT_READ,
  Perm.REPORTS_READ,
]

export const DEFAULT_LANDING = '/'
export const MONITOR_LANDING = '/monitor'

/** The first page this permission set should see. */
export function landingPath(held: ReadonlySet<string>): string {
  if (DASHBOARD_PERMISSIONS.some((permission) => held.has(permission))) return DEFAULT_LANDING
  if (held.has(Perm.MONITOR_READ)) return MONITOR_LANDING
  return DEFAULT_LANDING
}
