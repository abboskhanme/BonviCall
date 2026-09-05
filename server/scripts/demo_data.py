"""Demo data for a local BonviCall stack.

Drives the **real API** rather than writing rows directly, so everything it
creates has passed the same validation, RBAC and business rules a real device
and a real admin would hit. That makes it a smoke test as well as a fixture: if
this script runs clean, the enrolment chain, the ingest path and the three-step
resumable audio upload all work.

Audio is synthetic silence generated at the call's true length (see
``synthetic_audio``) and pushed through the real upload endpoints, so the panel's
player, the attribution gate, Range playback and the retention job all have
something behind them. The two handsets that cannot record upload nothing and
keep their real reasons — that difference is the product.

Never run against production — it creates accounts with a published password.

    make demo
"""

from __future__ import annotations

import hashlib
import os
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta, timezone

import httpx
import synthetic_audio

BASE = os.environ.get("DEMO_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.environ.get("DEMO_ADMIN_EMAIL", "admin@bonvi.uz")
ADMIN_PASSWORD = os.environ.get("DEMO_ADMIN_PASSWORD", "Bonvi2026!")
DEMO_PASSWORD = "Bonvi2026!"

TASHKENT_OFFSET = timedelta(hours=5)

# A fleet that looks like a real one: the models Uzbek sales teams actually
# carry, and deliberately not all capable of recording. The whole point of the
# panel is to make that difference visible.
FLEET = [
    # full name, employee code, number, manufacturer, model, android, api
    ("Aziz Karimov", "BV-001", "+998901112233", "Samsung", "SM-A546E", "14", 34),
    ("Sanjar Toshev", "BV-002", "+998935554433", "Samsung", "SM-A245F", "13", 33),
    ("Dilnoza Rahimova", "BV-003", "+998997776655", "Xiaomi", "Redmi Note 12", "13", 33),
    ("Bekzod Yusupov", "BV-004", "+998944443322", "Xiaomi", "Redmi 10C", "12", 31),
    ("Malika Ergasheva", "BV-005", "+998911239988", "vivo", "V2111", "12", 31),
]

# Which capture route each model actually produced, and why audio is missing
# where it is. This is the M0 table in miniature — the Samsungs harvest the
# handset's own recorder cleanly, the others do not.
CAPTURE = {
    "SM-A546E": ("oem_file_harvest", None),
    "SM-A245F": ("oem_file_harvest", None),
    "Redmi Note 12": ("app_voice_recognition", None),
    "Redmi 10C": ("none", "oem_recorder_off"),
    "V2111": ("none", "no_permission"),
}

#: Audio matches the call's real length so the player's scrubber agrees with the
#: duration column. At ~205 bytes per second of silence a five-minute call costs
#: about 60 KB and the whole fleet stays well under a megabyte, so calls are
#: capped here rather than the audio being capped and every call then tripping
#: ``audio_duration_mismatch``.
MAX_CALL_SEC = 300

#: One call is deliberately older than ``retention.audio_months`` (12) so that
#: running the retention job leaves the panel a genuinely expired recording to
#: render, rather than a state nobody can reach without editing the database.
EXPIRED_CALL_AGE_DAYS = 400

#: And one file is deliberately shorter than the call it belongs to, so UC-14's
#: mismatch warning has a real example. Exactly one — if every call tripped it
#: the panel would look broken instead of informative.
MISMATCHED_CLIP_MS = 4_000

# Every capability the app exercises at enrolment, in the state a healthy
# handset reports. `detail` is what the *check saw* — the app never reads a
# permission flag, it exercises the capability, which is what makes
# `granted_not_working` expressible at all (UC-03).
HEALTHY_CAPABILITIES: dict[str, tuple[str, str | None]] = {
    "phone_state": ("granted_working", "SIM 1 resolved, subscription id 1"),
    "call_log": ("granted_working", "read 20 entries in 40 ms"),
    "microphone": ("granted_working", "1s test capture, 32 kB"),
    # The permission is never requested: §8.1 promises in writing that the
    # contact book is never uploaded. Reported so the panel can show the
    # promise being kept rather than merely stated.
    "contacts": ("not_applicable", "never requested"),
    "notifications": ("granted_working", "foreground notification visible"),
    "call_phone": ("granted_working", "required for click-to-call"),
    "battery_exemption": ("granted_working", "exempt from optimisation"),
    "storage_access": ("granted_working", "recordings folder readable"),
    "oem_autostart": ("not_applicable", "no autostart manager on this OEM"),
    "foreground_service": ("granted_working", "service alive 4h12m"),
    "oem_recorder": ("granted_working", "call recording enabled in Phone app"),
    "subscription_resolution": ("granted_working", "PHONE_ACCOUNT_ID matched SIM 1"),
}

# What each handset actually reports, on top of the healthy baseline. The fleet
# already mixes capture routes; the capability matrix has to mix too, or the
# device page shows twelve green rows and the drift alert has no example.
CAPABILITY_OVERRIDES: dict[str, dict[str, tuple[str, str | None]]] = {
    # The Samsungs harvest the handset's own recorder and are fully healthy.
    "SM-A546E": {},
    "SM-A245F": {},
    # MIUI has an autostart manager, and this one was granted.
    "Redmi Note 12": {
        "oem_autostart": ("granted_working", "MIUI autostart allowed"),
        # `not_applicable`, not `denied`: this ROM has no call recorder to deny.
        # `denied` would be a transition into a broken state and would raise
        # `recording_route_lost` — "the recording method stopped working" — on a
        # phone that never had that method and is capturing perfectly well via
        # app_voice_recognition. Same reasoning as `contacts` above.
        "oem_recorder": ("not_applicable", "no call recorder in this ROM"),
    },
    "Redmi 10C": {
        "oem_autostart": ("granted_working", "MIUI autostart allowed"),
        "oem_recorder": ("granted_working", "call recording enabled in Phone app"),
    },
    "V2111": {
        "oem_autostart": ("granted_working", "iManager autostart allowed"),
        "oem_recorder": ("not_applicable", "no call recorder in this ROM"),
    },
}

# ...and then the OEM took something away. Posted as a *second* report so the
# server sees a transition and raises the drift alert (UC-06, UC-18) — which is
# the whole reason capability_states is a time series and not a snapshot. A
# demo where every capability has only ever been green cannot show the one
# screen this subsystem exists for.
CAPABILITY_DRIFT: dict[str, dict[str, tuple[str, str | None]]] = {
    "Redmi 10C": {
        # The reason its calls carry `oem_recorder_off`.
        "oem_recorder": ("denied", "call recording switched off in Phone app"),
        "battery_exemption": ("denied", "MIUI battery saver re-enabled"),
    },
    "V2111": {
        # The reason its calls carry `no_permission`. Permanently denied means
        # the OS will not ask again — the agent has to go into Settings.
        "microphone": ("denied_permanently", "SecurityException on test capture"),
        "call_log": ("denied", "permission revoked by the permission manager"),
    },
}

CONTACTS = [
    ("Oybek aka", "+998901234567"),
    ("Nodira opa", "+998977654321"),
    ("Jasur Mirzayev", "+998935551122"),
    ("Sardor ustoz", "+998909998877"),
    ("Kamola Yusupova", "+998941112244"),
    (None, "+998712001020"),
    (None, "+998950001122"),
]


def device_headers_for(installation_id: str) -> dict[str, str]:
    """Every device request identifies its installation and app version."""
    return {"X-Installation-Id": installation_id, "X-App-Version": "1.0.0"}


def sha256(value: str) -> str:
    """The wire wants a 64-char digest — a device fingerprint is hashed, never raw."""
    return hashlib.sha256(value.encode()).hexdigest()


def iso(moment: datetime) -> str:
    """ISO-8601 with an explicit offset — the server rejects a naive timestamp."""
    return moment.astimezone(timezone(TASHKENT_OFFSET)).isoformat()


class Api:
    """A thin client that fails loudly. A demo that half-works teaches nothing."""

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.token: str | None = None

    def call(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        token: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        headers = dict(headers or {})
        bearer = token if token is not None else self.token
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        response = self.client.request(method, path, json=json, headers=headers)
        if response.status_code >= 400:
            raise SystemExit(
                f"\n{method} {path} -> {response.status_code}\n{response.text[:600]}\n"
            )
        return response.json() if response.content else None

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, **kw):
        return self.call("POST", path, **kw)

    def put_bytes(self, path, *, content, params=None, token=None, headers=None):
        """A raw body, not JSON — an audio chunk is bytes on the wire (§4.5)."""
        headers = dict(headers or {})
        bearer = token if token is not None else self.token
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        headers["Content-Type"] = "application/octet-stream"
        response = self.client.put(path, content=content, params=params, headers=headers)
        if response.status_code >= 400:
            raise SystemExit(
                f"\nPUT {path} -> {response.status_code}\n{response.text[:600]}\n"
            )
        return response.json()


def make_call(
    *,
    started: datetime,
    direction: str,
    disposition: str,
    duration: int,
    variant: str,
    route: str,
    missing: str | None,
) -> dict:
    """One call record as the device puts it on the wire (SPEC §4.4)."""
    answered = disposition == "answered"
    answered_at = started + timedelta(seconds=random.randint(3, 20))
    ended_at = (answered_at if answered else started) + timedelta(seconds=duration)
    contact_name, remote = random.choice(CONTACTS)

    call = {
        "client_call_id": str(uuid.uuid4()),
        "started_at": iso(started),
        "ended_at": iso(ended_at),
        "direction": direction,
        "disposition": disposition,
        "duration_sec": duration,
        "remote_number": remote,
        "contact_name": contact_name,
        "device_epoch_ms": int(started.timestamp() * 1000),
        "device_timezone": "Asia/Tashkent",
        "app_variant": variant,
        "app_version": "1.0.0",
        "sim_slot": 0,
        "sim_subscription_id": 1,
    }
    if answered:
        call["answered_at"] = iso(answered_at)
        call["audio_expected"] = missing is None
        call["capture_route"] = route
        # Metadata always lands before audio (R7), so at ingest time even a
        # recording that is about to be uploaded is honestly "queued".
        call["audio_missing_reason"] = missing or "pending_upload"
    else:
        # UC-14: an unanswered call has no recording and that is not a failure.
        # Saying "not expected" keeps it out of the gap report's numerator.
        call["audio_expected"] = False
        call["capture_route"] = "none"
        call["audio_missing_reason"] = "not_expected"
    return call


def capability_report(model: str, drift: bool = False) -> list[dict]:
    """What one handset reports, as the app reports it (SPEC §4.3).

    ``drift=True`` returns only what *changed*, because that is what the phone
    sends: a re-check posts the capabilities it re-exercised, and the server
    turns a changed state into a transition and an alert.
    """
    if drift:
        changed = CAPABILITY_DRIFT.get(model, {})
        return [
            {
                "capability": name,
                "state": state,
                "checked_at": iso(datetime.now(UTC)),
                "detail": detail,
            }
            for name, (state, detail) in changed.items()
        ]

    states = dict(HEALTHY_CAPABILITIES)
    states.update(CAPABILITY_OVERRIDES.get(model, {}))
    return [
        {
            "capability": name,
            "state": state,
            "checked_at": iso(datetime.now(UTC) - timedelta(hours=6)),
            "detail": detail,
        }
        for name, (state, detail) in states.items()
    ]


def upload_audio(api: Api, device, call: dict, clip_ms: int) -> int:
    """Push one recording through the real three-step upload. Returns bytes.

    In **two** chunks on purpose: a single-shot upload never exercises the
    offset check, and the offset check is the whole reason this protocol exists
    instead of a re-POST.
    """
    token, headers, route = device
    blob = synthetic_audio.ogg_opus_silence(clip_ms)

    # Inside the attribution window [started_at - 5 s, ended_at + 120 s] (N28).
    # The handset's recorder finishes writing a moment after the call ends;
    # a file outside that window is refused and never stored, which is a
    # privacy boundary and not a validation nicety.
    recorded_at = datetime.fromisoformat(call["ended_at"]) + timedelta(seconds=2)

    session = api.post(
        f"/api/device/v1/calls/{call['client_call_id']}/audio/session",
        json={
            "bytes_total": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "codec": "opus",
            "container": "ogg",
            "sample_rate_hz": 48000,
            "channels": 1,
            "duration_ms": clip_ms,
            "capture_route": route,
            # The folder name only. A path from the phone would leak the
            # employee's directory layout (§8).
            "capture_route_detail": "Call" if route == "oem_file_harvest" else None,
            "recorded_at": iso(recorded_at),
        },
        token=token,
        headers=headers,
    )

    upload_id = session["upload_id"]
    # Resume from what the server says it has, not from zero — that is the
    # behaviour a real client needs and the one worth demonstrating.
    offset = session["received_bytes"]
    step = min(session["chunk_size"], max(1, -(-len(blob) // 2)))
    while offset < len(blob):
        chunk = blob[offset : offset + step]
        accepted = api.put_bytes(
            f"/api/device/v1/audio/{upload_id}/chunk",
            content=chunk,
            params={"offset": offset},
            token=token,
            headers={**headers, "X-Chunk-Sha256": hashlib.sha256(chunk).hexdigest()},
        )
        offset = accepted["received_bytes"]

    api.post(
        f"/api/device/v1/audio/{upload_id}/commit", token=token, headers=headers
    )
    return len(blob)


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        api = Api(client)

        print(f"→ {BASE}")
        login = api.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        api.token = login["access_token"]
        print(f"  admin sifatida kirildi: {ADMIN_EMAIL}")

        existing = api.get("/api/v1/agents")
        if existing.get("total", 0) > 0:
            print(f"  {existing['total']} ta xodim allaqachon bor — qo'shimcha yaratilmaydi")
            print("  bazani tozalash uchun: make clean-db (yoki qo'lda)")
            return 0

        now = datetime.now(UTC)
        created = []

        for full_name, code, e164, manufacturer, model, release, api_level in FLEET:
            hired_at = now - timedelta(days=random.randint(500, 900))
            agent = api.post(
                "/api/v1/agents",
                json={
                    "full_name": full_name,
                    "employee_code": code,
                    "hired_at": hired_at.date().isoformat(),
                },
            )
            number = api.post(
                "/api/v1/numbers",
                json={"e164": e164, "sim_owner": "company", "operator": "Beeline"},
            )
            api.post(
                f"/api/v1/numbers/{number['id']}/assignments",
                # They got the line when they were hired. Back-dating matters:
                # attribution runs against the assignment covering the call's
                # started_at (D-08), so an assignment starting today would leave
                # the retention-expired call below attributed out of range.
                json={"agent_id": agent["id"], "valid_from": iso(hired_at)},
            )
            enrolment = api.post(f"/api/v1/numbers/{number['id']}/enrolment-code")
            created.append((agent, number, enrolment, manufacturer, model, release, api_level))
            print(f"  xodim + raqam: {full_name:20} {e164}")

        print("\n  qurilmalar ro'yxatdan o'tmoqda…")
        installations = []
        for agent, number, enrolment, manufacturer, model, release, api_level in created:
            variant = "modern34" if api_level >= 33 else "legacy28"
            redeemed = api.post(
                "/api/device/v1/enrolment/redeem",
                json={
                    "code": enrolment["code"],
                    "device_fingerprint": sha256(f"fp-{model}-{number['e164']}"),
                    "device_epoch_ms": int(now.timestamp() * 1000),
                    "device_timezone": "Asia/Tashkent",
                    "app": {"variant": variant, "version": "1.0.0", "version_code": 1},
                    "device": {
                        "manufacturer": manufacturer,
                        "model": model,
                        "marketing_name": model,
                        "android_release": release,
                        "api_level": api_level,
                        "build_fingerprint_hash": sha256(f"build-{manufacturer}-{model}-{release}"),
                    },
                    "sim_slot": 0,
                    "sim_subscription_id": 1,
                },
                token="",
            )
            # Redeeming a code only gets a *provisional* token. The real pair
            # is issued once the handset proves it is on the registered number —
            # an unverified device can enrol but cannot upload a single call.
            provisional = redeemed["provisional_token"]
            verified = api.post(
                "/api/device/v1/enrolment/verify/msisdn",
                json={
                    "line1_number": number["e164"],
                    "subscription_id": 1,
                    "sim_slot": 0,
                    "carrier_name": "Beeline UZ",
                },
                token=provisional,
                headers=device_headers_for(redeemed["installation_id"]),
            )
            if not verified.get("tokens"):
                raise SystemExit(
                    f"raqam tasdiqlanmadi ({number['e164']}): {verified.get('state')} "
                    f"{verified.get('failure')}"
                )
            device_token = verified["tokens"]["access_token"]
            device_headers = {
                "X-Installation-Id": redeemed["installation_id"],
                "X-App-Version": "1.0.0",
            }
            installations.append((agent, number, device_token, device_headers, model, variant))
            print(f"    {model:16} {variant:9} tasdiqlandi")

        print("\n  qurilma imkoniyatlari tekshirilmoqda…")
        drifted = 0
        for _agent, _number, device_token, device_headers, model, _variant in installations:
            api.post(
                "/api/device/v1/capabilities",
                json={"capabilities": capability_report(model)},
                token=device_token,
                headers=device_headers,
            )
            # A second report, some hours later, for the handsets the OEM broke.
            # Two reports rather than one denied state: the alert is raised on
            # the *transition*, so a phone that was never healthy raises nothing
            # and the demo would show the failure without the story.
            changes = capability_report(model, drift=True)
            if changes:
                result = api.post(
                    "/api/device/v1/capabilities",
                    json={"capabilities": changes},
                    token=device_token,
                    headers=device_headers,
                )
                drifted += result["alerts_raised"]
                lost = ", ".join(c["capability"] for c in changes)
                print(f"    {model:16} ✗ {lost}")
            else:
                print(f"    {model:16} ✓ hammasi ishlayapti")
        print(f"    {drifted} ta ruxsat yo'qolishi signali")

        print("\n  qo'ng'iroqlar yuborilmoqda…")
        total = 0
        pending_audio = []
        specials_placed = False

        for agent, _number, device_token, device_headers, model, variant in installations:
            route, missing = CAPTURE[model]
            can_record = missing is None
            device = (device_token, device_headers, route)
            batch = []

            for _ in range(random.randint(6, 12)):
                started = now - timedelta(
                    days=random.randint(0, 6),
                    hours=random.randint(0, 9),
                    minutes=random.randint(0, 59),
                )
                direction = random.choice(["incoming", "outgoing"])
                answered = random.random() > 0.22
                # ck_calls_direction_disposition: an incoming call can be
                # missed or rejected, an outgoing one can only go unanswered.
                # There is no such thing as a "missed" outgoing call.
                if answered:
                    disposition = "answered"
                elif direction == "incoming":
                    disposition = random.choice(["missed", "rejected"])
                else:
                    disposition = "no_answer"
                duration = random.randint(20, MAX_CALL_SEC) if answered else 0

                call = make_call(
                    started=started,
                    direction=direction,
                    disposition=disposition,
                    duration=duration,
                    variant=variant,
                    route=route,
                    missing=missing,
                )
                batch.append(call)
                if answered and can_record:
                    pending_audio.append((device, call, duration * 1000))

            if can_record and not specials_placed:
                # Two states the panel has to render and that random data never
                # produces. They go on the first capable handset so one agent's
                # page shows both.
                specials_placed = True

                expired = make_call(
                    started=now - timedelta(days=EXPIRED_CALL_AGE_DAYS, hours=3),
                    direction="outgoing",
                    disposition="answered",
                    duration=95,
                    variant=variant,
                    route=route,
                    missing=None,
                )
                batch.append(expired)
                pending_audio.append((device, expired, 95_000))

                truncated = make_call(
                    started=now - timedelta(days=2, hours=5),
                    direction="incoming",
                    disposition="answered",
                    duration=180,
                    variant=variant,
                    route=route,
                    missing=None,
                )
                batch.append(truncated)
                pending_audio.append((device, truncated, MISMATCHED_CLIP_MS))

            api.post(
                "/api/device/v1/calls",
                json={"calls": batch},
                token=device_token,
                headers=device_headers,
            )
            total += len(batch)
            print(f"    {agent['full_name']:20} {len(batch):2} ta qo'ng'iroq  ({route})")

        print("\n  audio yuklanmoqda…")
        audio_bytes = 0
        for device, call, clip_ms in pending_audio:
            audio_bytes += upload_audio(api, device, call, clip_ms)
        print(
            f"    {len(pending_audio)} ta yozuv, {audio_bytes / 1024:.0f} KB "
            f"— uchta bosqichli yuklash orqali"
        )
        print(
            f"    1 tasi saqlash muddatidan o'tgan "
            f"({EXPIRED_CALL_AGE_DAYS} kun), 1 tasi qisqa (davomiylik mos emas)"
        )

        print("\n  qurilma holati yuborilmoqda…")
        for position, (
            _agent,
            _number,
            device_token,
            device_headers,
            model,
            variant,
        ) in enumerate(installations):
            # The last handset deliberately never reports: a silent device is
            # the signal R3 exists to surface, and a demo where everything is
            # healthy hides the one screen that matters.
            if position == len(installations) - 1:
                print(f"    {model:16} — ataylab jim (sukunat signali uchun)")
                continue
            api.post(
                "/api/device/v1/heartbeat",
                json={
                    "device_epoch_ms": int(datetime.now(UTC).timestamp() * 1000),
                    "device_timezone": "Asia/Tashkent",
                    "battery_level": random.randint(35, 95),
                    "battery_charging": random.random() > 0.6,
                    "battery_optimisation_exempt": position != 2,
                    "capture_enabled": True,
                    "service_running": True,
                    "network_type": random.choice(["wifi", "cellular"]),
                    "queue_records": random.randint(0, 4),
                    "parked_records": 0,
                    "free_storage_bytes": random.randint(2, 40) * 1024**3,
                    "app_variant": variant,
                    "app_version": "1.0.0",
                    "api_level": 34 if variant == "modern34" else 31,
                    "recording_route": CAPTURE[model][0],
                    "recording_route_ok": CAPTURE[model][1] is None,
                },
                token=device_token,
                headers=device_headers,
            )
            print(f"    {model:16} sog'lom")

        print("\n  panel foydalanuvchilari…")
        first_agent = created[0][0]
        for email, role, agent_id in [
            ("manager@bonvi.uz", "manager", None),
            ("sales@bonvi.uz", "sales", first_agent["id"]),
        ]:
            body = {
                "email": email,
                "password": DEMO_PASSWORD,
                "full_name": email.split("@")[0].title(),
                "role": role,
            }
            if agent_id:
                body["agent_id"] = agent_id
            try:
                api.post("/api/v1/users", json=body)
                print(f"    {email:22} {role}")
            except SystemExit as error:
                print(f"    {email:22} o'tkazib yuborildi ({str(error).strip()[:80]})")

        print(f"\n✓ tayyor — {len(FLEET)} xodim, {len(installations)} qurilma, {total} qo'ng'iroq")
        print("\n  panel: http://localhost:5190")
        print(f"  {'admin@bonvi.uz':24} {DEMO_PASSWORD}   (hammasi)")
        print(f"  {'manager@bonvi.uz':24} {DEMO_PASSWORD}   (hammasi, sozlamasiz)")
        print(
            f"  {'sales@bonvi.uz':24} {DEMO_PASSWORD}   "
            f"(faqat o'zinikini — {first_agent['full_name']})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
