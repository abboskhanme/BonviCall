# Pending wiring

Things that are **built and tested** but not yet connected to a shared file.

`src/main.py`'s router registration, `src/api/device/__init__.py`, the
permission registry and the Alembic head are edited sequentially by the
orchestrator, never by a unit working in parallel. Anything a unit finishes
that needs one of them is recorded here instead, with enough detail that the
wiring is mechanical.

---

## The three ported analytics menus — WIRED 2026-09-17

`Faollik`, `Analitika` and `Baholash mezonlari` were built in parallel by three
units, each forbidden from touching a shared panel file so they could not
overwrite one another. The wiring pass applied all of it in one go:

| File | What landed |
|---|---|
| `panel/src/app/router.tsx` | `/activity` (`calls:read` / `calls:read:own`), `/analytics` and `/rubric` (`analysis:read`). The three pages are `lazy()`, and `Suspense` sits INSIDE `Gate` so a refused user never fetches the chunk. |
| `panel/src/shared/layout/AppShell.tsx` | `/activity` in **Kundalik ish** right after `/calls`; `/analytics` first and `/rubric` last in **Tahlil**. Icons `Activity`, `BarChart3`, `ClipboardCheck` — `ListChecks` was already the queue's. |
| `panel/src/shared/i18n/uz.json` | `nav.activity`, `nav.rubric`, `common.loading` and the 86 `activity.*` keys. `modules/activity/labels.ts` — the temporary module-local catalogue — is **deleted**, and its four importers now take `t` from `@/shared/i18n`. |
| `docs/ASSUMPTIONS.md` | The eight lines the units owed, including both `core/reads.py` §2.1 exceptions. |

Two things the wiring pass fixed rather than recorded:

- **`AnalyticsService._block_max()` now reads the active rubric**, with the
  pinned constant as the fallback. The analytics unit divided block scores by a
  constant; the rubric unit made the rubric a table in the same hour. An admin
  moving five points between blocks would have left the radar chart dividing by
  a maximum nobody scores against — a bar past 100 %, which is the defect
  BonviZvonki shipped.
- **Three KPI cards on Faollik share their wording with a column of the table
  below** (one metric shown twice, deliberately). The cards are now labelled
  groups, so a reader — and a test — can tell the card from the column.

---

## Nothing else is pending.

Phase 6's server-side wiring is complete as of 2026-09-05. What was here:

| Item | Landed | Note |
|---|---|---|
| Device realtime socket `/api/device/v1/ws` | 2026-09-05 | `include_router(ws.router)`. The RBAC harness covers `WEBSOCKET /api/device/v1/ws`, verified by removing the guard and watching it fail. `test_every_router_module_is_registered` now walks `src/api/*/` so an unwired router cannot pass again — which is how this one sat finished and unreachable while its own tests passed. |
| App versions module | 2026-09-05 | `/api/v1/app/*` — list, upload, publish, discard, the public download, and the min-version impact + change. Migrations 003 (`installations.app_version_code`) and 004 (`app_version_uploaded` audit action). |
| FCM registration token | 2026-09-05 | `installations.push_token` (migration **002**), `DeviceHeartbeatIn.push_token`, and `CommandService.deliver()` sends it. A separate revision rather than an edit to 001: adding a *column* there would leave every database already at head 001 silently without it, because `upgrade head` is a no-op for them. |

## Waiting on another unit

**`app_version_code` on the heartbeat (Android). — LANDED 2026-09-05.**
`service/Heartbeat.kt` populates it from `BuildConfig.VERSION_CODE`, the same
value `EnrolmentRepository.appInfo()` sends at redeem.

Worth recording that the field was only half the gap: **nothing sent a
heartbeat at all**. `DeviceCallsApi.heartbeat` existed and had no caller, so
the fleet's `unknown_version_count` of 5/5 was the visible symptom of a device
that reported its version once, at enrolment, and never again.
`HeartbeatContractTest` now pins three things: the contract has the field, the
app populates it from `BuildConfig`, and enrolment and heartbeat read the same
constant — because if those two ever diverge the gate strands a phone that has
already updated.

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
