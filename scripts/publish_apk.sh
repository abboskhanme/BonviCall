#!/usr/bin/env bash
# Put a signed APK in front of the fleet.
#
# The panel's publishing screen was removed on 2026-09-14 at the client's
# request — it was a page an admin opens once a month — but the endpoints it
# drove are still there, still `appversions:write`, and still the ONLY way a
# build reaches a handset. This is that path, without the screen.
#
# Without it a fresh deployment has no published build at all: `/i/<code>`
# renders "APK not ready", and fifteen salespeople have nothing to install.
# That is the first thing anybody does on a new server, so it gets a script
# rather than a paragraph in a document.
#
# Upload and publish are two steps on the server and two steps here, in that
# order and for that reason: an uploaded build reaches nobody until it is
# published, which is what makes it safe to upload one and look at what the
# signature inspection says before committing the fleet to it.
#
#   scripts/publish_apk.sh \
#     --url https://call.bonvi.uz \
#     --login admin --password '…' \
#     --apk android/app/build/outputs/apk/legacy28/release/app-legacy28-release.apk \
#     --version 1.0.8 --version-code 108 --variant legacy28
#
# --version, --version-code and --variant may all be left out: they are read
# from android/app/build.gradle.kts and from the APK's own path, which is the
# only pairing that cannot disagree with the file being uploaded.
#
# Add --no-publish to upload and stop, and read the fingerprint first.
# Add --insecure only for a staging host with a certificate this machine does
# not trust — never for the server the handsets talk to.

set -euo pipefail

URL="" LOGIN="" PASSWORD="" APK="" VERSION="" VERSION_CODE="" VARIANT=""
NOTES="" MANDATORY=false PUBLISH=true INSECURE=false

die() { echo "error: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
	case "$1" in
		--url) URL="$2"; shift 2 ;;
		--login) LOGIN="$2"; shift 2 ;;
		--password) PASSWORD="$2"; shift 2 ;;
		--apk) APK="$2"; shift 2 ;;
		--version) VERSION="$2"; shift 2 ;;
		--version-code) VERSION_CODE="$2"; shift 2 ;;
		--variant) VARIANT="$2"; shift 2 ;;
		--notes) NOTES="$2"; shift 2 ;;
		--mandatory) MANDATORY=true; shift ;;
		--no-publish) PUBLISH=false; shift ;;
		# For a server whose certificate this machine has no reason to trust —
		# a staging host with an internal CA. NOT for the fleet's server: if
		# call.bonvi.uz needs this flag, the certificate is wrong and the
		# handsets, which cannot be told to skip verification, will not
		# connect at all.
		--insecure) INSECURE=true; shift ;;
		-h|--help) sed -n '2,28p' "$0"; exit 0 ;;
		*) die "unknown argument: $1" ;;
	esac
done

# Pairs rather than `${name,,}`: lower-casing a variable name that way needs
# bash 4, and macOS still ships 3.2.
# ═══════════════════════════════════════════════════════════════════════════
# The version is READ from the build file unless it is given.
#
# The server does not open the APK's manifest — `inspect_apk` checks that it is
# a signed zip and nothing else — so `version_code` is whatever this call says
# it is. Get it wrong and the update gate compares the wrong number: every
# handset is either offered a build it already has, for ever, or refused as
# under-version while running the newest one. Neither fails loudly.
#
# `android/app/build.gradle.kts` is what the APK was actually built from, so
# reading it is the one source that cannot disagree with the file.
# ═══════════════════════════════════════════════════════════════════════════
GRADLE="android/app/build.gradle.kts"
if [ -z "$VERSION_CODE" ] && [ -f "$GRADLE" ]; then
	VERSION_CODE=$(sed -n 's/^[[:space:]]*versionCode[[:space:]]*=[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$GRADLE" | head -1)
	[ -n "$VERSION_CODE" ] && echo "    version-code $VERSION_CODE (from $GRADLE)"
fi
if [ -z "$VERSION" ] && [ -f "$GRADLE" ]; then
	VERSION=$(sed -n 's/^[[:space:]]*versionName[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$GRADLE" | head -1)
	[ -n "$VERSION" ] && echo "    version      $VERSION (from $GRADLE)"
fi
# The variant is in the path `assembleRelease` writes to.
if [ -z "$VARIANT" ]; then
	case "$APK" in
		*/legacy28/*) VARIANT=legacy28 ;;
		*/modern34/*) VARIANT=modern34 ;;
	esac
	[ -n "$VARIANT" ] && echo "    variant      $VARIANT (from the path)"
fi

for pair in "URL:--url" "LOGIN:--login" "PASSWORD:--password" "APK:--apk" \
            "VERSION:--version" "VERSION_CODE:--version-code" "VARIANT:--variant"; do
	name="${pair%%:*}"
	[ -n "${!name}" ] || die "${pair#*:} is required (see --help)"
done
[ -f "$APK" ] || die "no such file: $APK"
case "$VARIANT" in legacy28|modern34) ;; *) die "--variant must be legacy28 or modern34" ;; esac

# `unsigned` in the name is the shape `make android-release` produces when
# android/keystore.properties is missing: it does not fail, it just hands back
# a build no handset will install. Catching it here costs nothing.
case "$APK" in *unsigned*) die "$APK looks unsigned — see docs/APK-SIGNING.md" ;; esac

URL="${URL%/}"
CURL=(curl -fsS)
[ "$INSECURE" = true ] && CURL+=(--insecure)

# python3 rather than jq: it is on every machine this repository is cloned to,
# and the deployment host is not somewhere to be installing tools.
json_field() { python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }

echo "==> signing in to $URL as $LOGIN"
# The body is built by python3 rather than interpolated into a heredoc, so a
# password containing a quote or a backslash is sent as typed.
BODY=$(python3 -c 'import json,sys; print(json.dumps({"email": sys.argv[1], "password": sys.argv[2]}))' \
	"$LOGIN" "$PASSWORD")
# Two steps, not one pipeline: piping a failed curl into python3 buries the
# HTTP error under a JSON traceback, and the first thing anybody needs to know
# is whether the server answered.
LOGIN_RESPONSE=$("${CURL[@]}" -X POST "$URL/api/v1/auth/login" \
	-H 'Content-Type: application/json' --data-binary "$BODY") \
	|| die "login failed — check the address, the login and the password"
TOKEN=$(printf '%s' "$LOGIN_RESPONSE" | json_field access_token)

echo "==> uploading $(basename "$APK") ($VERSION / $VERSION_CODE / $VARIANT)"
UPLOAD=$("${CURL[@]}" -X POST "$URL/api/v1/app/versions" \
	-H "Authorization: Bearer $TOKEN" \
	-F "apk=@$APK" \
	-F "version=$VERSION" \
	-F "version_code=$VERSION_CODE" \
	-F "variant=$VARIANT" \
	-F "is_mandatory=$MANDATORY" \
	${NOTES:+-F "release_notes_uz=$NOTES"}) || die "upload failed"

VERSION_ID=$(printf '%s' "$UPLOAD" | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"]["id"])')
SIGNER=$(printf '%s' "$UPLOAD" | json_field signer_sha256)
VERIFIED=$(printf '%s' "$UPLOAD" | json_field signer_verified)

echo "    id        $VERSION_ID"
echo "    signer    $SIGNER"
echo "    verified  $VERIFIED"
if [ "$VERIFIED" != "True" ]; then
	# Not fatal: APK_SIGNING_SHA256 is often unset on a first deployment. But
	# a build signed with a different key cannot install over an existing one,
	# and the phone reports that as a bare failure — so the fingerprint is
	# printed to be compared against docs/APK-SIGNING.md by eye.
	echo "    (no configured fingerprint to compare against — check it by eye)"
fi

if [ "$PUBLISH" != true ]; then
	echo "==> uploaded, NOT published. It reaches nobody until it is."
	exit 0
fi

echo "==> publishing"
"${CURL[@]}" -X POST "$URL/api/v1/app/versions/$VERSION_ID/publish" \
	-H "Authorization: Bearer $TOKEN" >/dev/null || die "publish failed"

echo "==> published. Every $VARIANT handset is offered $VERSION from now on,"
echo "    and /i/<code> now hands out this build."
