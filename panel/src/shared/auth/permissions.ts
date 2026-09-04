/**
 * The permission strings the panel gates on.
 *
 * **Mirror of `server/src/core/permissions.py::Perm`, and deliberately not a
 * role map.** `can()` reads the resolved permission list from `GET /auth/me`
 * (SPEC §5.1); a hard-coded role→permission matrix on the client would be a
 * second copy of the matrix and a second thing to forget to update.
 *
 * These are constants rather than literals at the call site for the reason
 * CONVENTIONS.md §11.2 gives for the server: a typo like `'call:read'` fails
 * closed and silently, forever. `Permission` being a closed union makes the
 * typo a compile error in both `<Gate anyOf>` and `NAV[].anyOf`.
 *
 * TODO(T103, wiring phase): generate this file. The permission registry is not
 * part of `contract/` today — `src/contract_export.py` exports the three
 * OpenAPI documents and `error-codes.json` only. Adding
 * `contract/permissions.json` there, and a branch in `panel/scripts/
 * gen-types.mjs`, removes this file's one weakness: it is the only list in the
 * panel that a server change can invalidate without breaking the build.
 * It is not hand-written *types mirroring a response* (CONVENTIONS.md §1) —
 * it is a constant list — but it is still a copy, and the copy should go.
 */
export const Perm = {
  USERS_READ: 'users:read',
  USERS_WRITE: 'users:write',

  AGENTS_READ: 'agents:read',
  AGENTS_WRITE: 'agents:write',
  AGENTS_ARCHIVE: 'agents:archive',

  NUMBERS_READ: 'numbers:read',
  NUMBERS_WRITE: 'numbers:write',

  ENROLMENT_READ: 'enrolment:read',
  ENROLMENT_WRITE: 'enrolment:write',
  ENROLMENT_ATTEST: 'enrolment:attest',

  INSTALLATIONS_READ: 'installations:read',
  INSTALLATIONS_REVOKE: 'installations:revoke',

  DEVICES_READ: 'devices:read',
  DEVICES_READ_OWN: 'devices:read:own',

  CALLS_READ: 'calls:read',
  CALLS_READ_OWN: 'calls:read:own',
  CALLS_NOTE: 'calls:note',

  AUDIO_PLAY: 'audio:play',
  AUDIO_PLAY_OWN: 'audio:play:own',
  AUDIO_DOWNLOAD: 'audio:download',

  COMMANDS_DIAL: 'commands:dial',

  ALERTS_READ: 'alerts:read',
  ALERTS_ACK: 'alerts:ack',

  REPORTS_READ: 'reports:read',
  REPORTS_EXPORT: 'reports:export',

  AUDIT_READ: 'audit:read',

  SETTINGS_READ: 'settings:read',
  SETTINGS_WRITE: 'settings:write',

  APPVERSIONS_READ: 'appversions:read',
  APPVERSIONS_WRITE: 'appversions:write',

  // Removed 2026-09-05 with the TV board, at the client's request:
  // `monitor:read` and the `viewer` role are gone from
  // server/src/core/permissions.py, so a constant for them here would gate on
  // a permission `GET /auth/me` can never return — which reads as "nobody has
  // it" rather than "this does not exist".

  EXPORT_READ: 'export:read',
  EXPORT_AUDIO: 'export:audio',
} as const

export type Permission = (typeof Perm)[keyof typeof Perm]

export const ALL_PERMISSIONS: readonly Permission[] = Object.values(Perm)
