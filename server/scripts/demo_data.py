"""Demo data for a local BonviCall stack.

Drives the **real API** rather than writing rows directly, so everything it
creates has passed the same validation, RBAC and business rules a real device
and a real admin would hit. That makes it a smoke test as well as a fixture: if
this script runs clean, the enrolment chain and the ingest path work.

Never run against production — it creates accounts with a published password.

    make demo
"""

from __future__ import annotations

import os
import hashlib
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx

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

        now = datetime.now(timezone.utc)
        created = []

        for full_name, code, e164, manufacturer, model, release, api_level in FLEET:
            agent = api.post(
                "/api/v1/agents",
                json={
                    "full_name": full_name,
                    "employee_code": code,
                    "hired_at": (now - timedelta(days=random.randint(90, 900))).date().isoformat(),
                },
            )
            number = api.post(
                "/api/v1/numbers",
                json={"e164": e164, "sim_owner": "company", "operator": "Beeline"},
            )
            api.post(
                f"/api/v1/numbers/{number['id']}/assignments",
                json={"agent_id": agent["id"]},
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

        print("\n  qo'ng'iroqlar yuborilmoqda…")
        total = 0
        for agent, number, device_token, device_headers, model, variant in installations:
            route, missing = CAPTURE[model]
            batch = []
            for index in range(random.randint(6, 12)):
                started = now - timedelta(
                    days=random.randint(0, 6),
                    hours=random.randint(0, 9),
                    minutes=random.randint(0, 59),
                )
                contact_name, remote = random.choice(CONTACTS)
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
                duration = random.randint(25, 900) if answered else 0
                answered_at = started + timedelta(seconds=random.randint(3, 20))
                ended_at = (answered_at if answered else started) + timedelta(seconds=duration)

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
                    if missing:
                        call["audio_missing_reason"] = missing
                    else:
                        # No audio has been uploaded yet by this script, so the
                        # honest state is "queued", not "recorded".
                        call["audio_missing_reason"] = "pending_upload"
                else:
                    # UC-14: an unanswered call has no recording and that is not
                    # a failure. Saying "not expected" keeps it out of the gap
                    # report's numerator.
                    call["audio_expected"] = False
                    call["capture_route"] = "none"
                    call["audio_missing_reason"] = "not_expected"
                batch.append(call)

            api.post(
                "/api/device/v1/calls",
                json={"calls": batch},
                token=device_token,
                headers=device_headers,
            )
            total += len(batch)
            print(f"    {agent['full_name']:20} {len(batch):2} ta qo'ng'iroq  ({route})")

        print("\n  qurilma holati yuborilmoqda…")
        for position, (
            agent,
            number,
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
                    "device_epoch_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
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
        print(f"  {'sales@bonvi.uz':24} {DEMO_PASSWORD}   (faqat o'zinikini — {first_agent['full_name']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
