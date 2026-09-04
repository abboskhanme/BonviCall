# `data/remote/dto/` — GENERATED, never hand-written

`CONVENTIONS.md` §1 and `CONVENTIONS-CLIENT.md` §5: the Kotlin DTOs in this
package are machine-produced from `contract/openapi-device-v1.json`, which is
itself generated from the server's Pydantic schemas by `make contract`.
**A hand-written file in this package is a violation.**

The reason is specific to this client: the app runs on ~15 phones that cannot be
force-updated. A field renamed on the server must be a **compile error here**,
not a runtime null discovered after a month of calls failed to upload.

## Regenerating

    make contract     # server schemas -> contract/openapi-device-v1.json
    make android-dto  # contract       -> this package

`make android-dto` is wired and proven: it produces 46 models from the current
contract (`openapi-generator` 7.10.0, Moshi codegen, `@Json(name = "...")`
snake_case mapping intact). CI runs it and diffs, exactly as it does for
`contract/` itself.

## Why this package is still empty — TODO(AN-NET / T74)

**Nothing imports the DTOs yet.** T22 is the scaffold; AN-NET owns the Retrofit
layer that consumes them. Generated code with no caller rots between now and its
first use, and it is one `make android-dto` away whenever it is needed.

The second reason is **closed**. On 2026-09-05 this package would have imported a
`CONVENTIONS.md` §8.5 violation: `DeviceEventIn.detail` was
`Dict[str, str | int | bool | None]`, whose value types were constrained but
whose KEYS were not, so an arbitrary key/value pair could still leave the
handset. `build-backend` replaced it with `DeviceEventDetailIn` — named fields
only — and constrained `kind` to a lower-case identifier at the same time,
because an unbounded free-text field is itself a way off the phone.
`DeviceVerificationStatusOut.tokens` went the same way.

`DeviceContractPrivacyTest` enforces the rule against
`contract/openapi-device-v1.json` on every build. Its exception list is now
empty and stays in place: the next free-form map added to a device request fails
the build, and having to add a line to that list is the point at which somebody
has to justify it.

Until the DTOs land, `domain/WireEnums.kt` carries the enum vocabulary the rest
of the app reasons about, and `WireEnumContractTest` checks those values against
the contract on every build — so the enum half of the drift risk is already
closed.
