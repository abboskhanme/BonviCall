# Device read API — what the phone needs to show an employee their own calls

**Written by `build-android` for `build-backend`, 2026-09-05.** The Android
side is built against this and is waiting on it.

The client's request: *"telefonda o'rnatiladigan appda ham shu xodim o'zining
callarini ko'rishi va eshitishi mumkin bo'lsin — bizni tizimga kirib
o'tirmaydi."* A salesperson should not need a panel login to see their own work.

`docs/QOLLANMA.md` already promises the employee transparency about what is
recorded. This is that promise becoming a screen, and it is N41 taken one step
further: not only *which number is recorded* but *what was recorded*.

---

## Why not the panel API

**A device token is not a panel session.** `GET /api/v1/calls` is scoped by a
user's permissions; issuing a handset something panel-scoped would mean a lost
or rooted phone carries a credential that reads the panel surface, and the blast
radius of a stolen phone stops being "one agent's calls" and becomes "whatever
that token can reach". The device surface is versioned, additive-only and
installation-bound for exactly this reason (`CONVENTIONS.md` §4).

So: two new routes on `/api/device/v1`, scoped by the installation.

---

## `GET /api/device/v1/calls`

Returns **only the calls of the agent this installation is bound to**, narrowed
server-side. Never a filter the client applies to a wider response — the client
is the thing we cannot trust.

**Auth:** the installation's access token, as every other device route.
**Scope:** `installation.agent_id`. An installation with no agent gets an empty
page, not a 403 — it is not an error, it is a phone that has not finished
enrolling.

### Query

| Param | Type | Notes |
|---|---|---|
| `limit` | int, default 50, max 100 | The screen is a phone; 1 000-row pages are the panel's problem |
| `cursor` | opaque | Keyset, same rule as SPEC §4.0: `received_at DESC, id DESC` |
| `since` | ISO-8601, optional | So the app can refresh cheaply rather than re-paging |

### Response

```jsonc
{
  "items": [
    {
      "id": "0193…",                     // server id, for the audio route
      "client_call_id": "364195cc-…",    // so the app can match its own row
      "direction": "outgoing",
      "disposition": "answered",
      "remote_number": "+998 90 777-66-55",
      "contact_name": "Aziz",            // null when none resolved
      "started_at": "2026-09-05T14:03:11.412+05:00",
      "duration_sec": 184,
      "has_audio": true,
      "audio_missing_reason": "pending_upload",   // NOT NULL, always (N5)
      "capture_route": "oem_file_harvest"
    }
  ],
  "next_cursor": "eyJ…",
  "has_more": true
}
```

Two fields matter more than they look:

- **`audio_missing_reason` is always present**, even when `has_audio` is true.
  The app renders the Uzbek sentence for it, and this screen is where an
  employee learns that *qayd etish* (the call is logged) and *yozib olish* (the
  audio is recorded) are different things. A null here would make the screen
  say nothing where it should explain.
- **`has_audio` must reflect what the server HOLDS**, not what the device
  thinks it uploaded. The whole point of reading this from the server is that
  the employee sees their record as the company sees it — a local list would
  show calls that never uploaded and hide calls recovered from the call log.

---

## `GET /api/device/v1/calls/{id}/audio`

The recording, for playback in the app.

**Auth:** installation token. **Scope:** the same `agent_id` narrowing — a call
id belonging to another agent returns **404, never 403** (SPEC §4.1 rule 2;
403 would confirm the call exists).

- Answers `Range` with **206 + `Content-Range`**, as the panel endpoint does
  (N43). ExoPlayer issues range requests and seek on a 20-minute file has to
  work without downloading the whole thing over cellular.
- `410 audio_expired` past retention — not a 500 and not an empty 200.
- `404 audio_not_found` when the call has no recording. The app already has the
  reason from the list and shows that instead of a dead control.

---

## What I am NOT asking for

- No search, no filters, no date range. A phone screen showing the last N calls
  is the request; anything more is the panel.
- No `note`, no audit trail, no other agents' anything.
- No new permission. The installation token's scope is the agent it is bound to,
  which is a property of the installation rather than a grant.

---

## Client state

Built and waiting: `domain/MyCall.kt`, `MyCallsGateway`, `MyCallsViewModel`,
`ui/calls/MyCallsScreen.kt`. The Retrofit implementation is a stub that returns
an empty page and is marked `TODO(device-read-api)`; when the contract lands,
`make android-dto` generates the DTOs and the stub is replaced by one Retrofit
interface. Nothing above it changes.
