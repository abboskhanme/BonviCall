# Pending wiring

Things that are **built and tested** but not yet connected to a shared file.

`src/main.py`'s router registration, `src/api/device/__init__.py`, the
permission registry and the Alembic head are edited sequentially by the
orchestrator, never by a unit working in parallel. Anything a unit finishes
that needs one of them is recorded here instead, with enough detail that the
wiring is mechanical.

---

## 1. ~~Device realtime socket~~ — wired 2026-09-05

`router.include_router(ws.router)` is in `src/api/device/__init__.py`.
`test_every_registered_route_is_protected_or_declared_public` now covers
`WEBSOCKET /api/device/v1/ws` (verified by removing the guard and watching it
fail), and `test_command_channel.py` no longer mounts the router itself.

No permission entry, no migration and no OpenAPI change were needed, for the
reasons recorded when it was built: a device principal holds no permissions,
the socket writes only columns that already exist, and OpenAPI does not
describe WebSocket routes — `contract/device-ws-frames.json` carries the frames
instead.

---

## 2. FCM registration token — has nowhere to live (T55, SPEC §4.6 step 2)

The wake-up path is built and honest, but it cannot actually wake anything,
and the missing pieces are **schema and contract**, not code:

1. **No column holds the token.** `installations` has no `push_token`.
2. **No wire field carries it.** No device DTO lets the app send one, and §8
   rule 5 means a field the contract does not name cannot be sent.

Until both land, `LoggingPushSender.wake()` returns `False` and says why. That
is deliberate: a sender that returned `True` would let a command sit in `sent`
until the ack timeout and be reported as *a phone that ignored us*, when in
fact nothing was ever sent. Those are different faults and the panel has to
tell them apart. The behaviour today — socket down, command `failed` /
`device_offline` after 15 s — is the truthful description of a fleet with no
FCM project configured.

**To wire, when FCM is provisioned:**

- `installations.push_token` (`TEXT NULL`) — a credential, so it is never
  logged and never returned on any panel DTO (N26).
- A named field on the heartbeat or enrolment DTO for the app to send it.
- `CommandService.deliver()` passes it instead of `push_token=None`
  (one line, already marked).
- An `FcmPushSender` implementing `core.push.PushSender`, registered with
  `push.set_sender()` in `main.py`. The interface takes **no payload
  argument** and must keep it that way — SPEC §4.6 sends `{"cmd":"poll"}` and
  never the dial target, and a signature that cannot express a payload cannot
  leak one.

---

## 3. `backup_verify` stays unregistered (T151)

Not an oversight and not pending. Verifying a backup means restoring it
somewhere, and there is nowhere to restore it to yet; a job that checked a file
exists and reported "backup verified" would be worse than no job. Left out of
`ALL_JOBS` on purpose.
