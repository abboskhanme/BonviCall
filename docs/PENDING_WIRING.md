# Pending wiring

Things that are **built and tested** but not yet connected to a shared file.

`src/main.py`'s router registration, `src/api/device/__init__.py`, the
permission registry and the Alembic head are edited sequentially by the
orchestrator, never by a unit working in parallel. Anything a unit finishes
that needs one of them is recorded here instead, with enough detail that the
wiring is mechanical.

---

## Nothing is pending.

Phase 6's server-side wiring is complete as of 2026-09-05. What was here:

| Item | Landed | Note |
|---|---|---|
| Device realtime socket `/api/device/v1/ws` | 2026-09-05 | `include_router(ws.router)`. The RBAC harness covers `WEBSOCKET /api/device/v1/ws`, verified by removing the guard and watching it fail. `test_every_router_module_is_registered` now walks `src/api/*/` so an unwired router cannot pass again — which is how this one sat finished and unreachable while its own tests passed. |
| App versions module | 2026-09-05 | `/api/v1/app/*` — list, upload, publish, discard, the public download, and the min-version impact + change. Migrations 003 (`installations.app_version_code`) and 004 (`app_version_uploaded` audit action). |
| FCM registration token | 2026-09-05 | `installations.push_token` (migration **002**), `DeviceHeartbeatIn.push_token`, and `CommandService.deliver()` sends it. A separate revision rather than an edit to 001: adding a *column* there would leave every database already at head 001 silently without it, because `upgrade head` is a no-op for them. |

## Waiting on another unit

**`app_version_code` on the heartbeat (Android).** The field is in the contract
(`DeviceHeartbeatIn.app_version_code`) and the server stores it, so the Kotlin
DTO gains it on the next generation — but something has to *populate* it with
`BuildConfig.VERSION_CODE`, the same value `EnrolmentRepository.appInfo()`
already sends at redeem.

Until then the gate works from the enrolment-time code and goes stale the
moment a handset updates: the phone would report a new `app_version` string and
an old code, and raising the minimum would strand a phone that had already
updated. Enrolment is correct today, so this is not urgent — but it is the
half that decides who stops reporting.

**`APK_SIGNING_SHA256` (ops).** Blank until the release key is generated
(`docs/APK-SIGNING.md`). While blank the server extracts each upload's signer
and returns it, but cannot refuse a wrong one.

---

**Still deliberately absent — not pending:**

- **An `FcmPushSender`.** The seam (`core/push.py`), the column and the wire
  field are all in place, so the only missing piece is an FCM project and its
  credentials. Until one exists, `LoggingPushSender` returns `False` and says
  whether it had a token, which is the honest distinction between "we have no
  address for this phone" and "we have no transport at all". A sender that
  returned `True` would let a command sit in `sent` until the ack timeout and
  be reported as a phone that ignored us. When the project is provisioned:
  implement `PushSender`, register it with `push.set_sender()` in `main.py`,
  and change nothing else. **The interface takes no payload argument and must
  keep it that way** — SPEC §4.6 sends `{"cmd":"poll"}` and never the dial
  target, and a signature that cannot express a payload cannot leak one.
- **`backup_verify` is unregistered.** Verifying a backup means restoring it
  somewhere, and there is nowhere to restore it to yet. A job that checked a
  file exists and reported "backup verified" would be worse than no job.

Remaining Phase 6 tasks belong to other units: **T103** (panel route table and
nav), **T145** (Android Hilt graph and navigation), **T105** (Uzbek string
catalogue pass across panel and app) and **T106** (the N35/pagination
conformance sweep, owned by `qa-review`).
