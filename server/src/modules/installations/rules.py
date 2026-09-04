"""The enrolment funnel, as a pure precedence list (T152, SPEC §10.1).

One function, nine stages, **first match wins**. The order is the rule and it
is not alphabetical: ``install_disappeared`` outranks ``capturing`` because a
phone Play Protect removed may have been capturing perfectly an hour ago, and
the more alarming answer has to win.

Two distinctions the panel depends on and that this function exists to keep:

* ``install_disappeared`` is **not** ``offline``. A phone in a lift comes back;
  an app Play Protect deleted does not. Rendering them the same is how a
  rollout looks fine while one person has silently dropped out (UC-02 AC).
* ``verified_by_admin`` is **not** ``number_verified``. Attested is weaker
  evidence than proven, and the identity anchor must never silently degrade
  (T142).
"""

from __future__ import annotations

#: A phone silent for longer than this, that was previously healthy, is gone
#: rather than merely offline (SPEC §10.1).
DISAPPEARED_AFTER_HOURS = 24


def resolve_funnel_stage(
    *,
    status: str,
    verification_method: str | None,
    capabilities_all_working: bool,
    service_running: bool,
    silent_hours: float | None,
    was_healthy: bool,
    needs_assistance: bool,
    has_live_code: bool,
) -> str:
    """The stage this installation is in. First matching rule wins.

    :param silent_hours: wall-clock hours since the last contact, or ``None``
        if it has never reported. Wall-clock and not working hours on purpose:
        "the app is gone" is not a business-hours question, unlike UC-27's
        silence alert.
    :param was_healthy: its last heartbeat reported working capture. Without
        this, a phone that never worked would be reported as one that stopped.
    """
    if status in ("revoked", "revoked_pending_confirmation"):
        return "revoked"

    if (
        status == "active"
        and was_healthy
        and silent_hours is not None
        and silent_hours > DISAPPEARED_AFTER_HOURS
    ):
        return "install_disappeared"

    if needs_assistance:
        return "needs_assisted_install"

    if status == "active" and capabilities_all_working and service_running:
        return "capturing"

    if status == "active" and verification_method == "admin_attested":
        return "verified_by_admin"

    if status == "active" and verification_method in ("sim_msisdn", "callback"):
        return "number_verified"

    if capabilities_all_working:
        # Permissions are done but the number is not proven. This is where an
        # agent sits while the callback route is failing, and it is the state
        # the rollout page must make visible.
        return "permitted"

    if status in ("pending", "active", "replaced"):
        return "installed"

    return "invited" if has_live_code else "installed"
