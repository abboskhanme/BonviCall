package uz.bonvi.call.domain

/**
 * Why the device is or is not able to send (T79/N25, T83/N34).
 *
 * ═══ The rule these states exist to enforce ════════════════════════════════
 * **A device that cannot send must HOLD its queue and report why. It must never
 * discard.** N25 exists because the natural implementation of "the token
 * expired" is to clear local state and start again, and what that clears is
 * calls that happened and have not reached the server.
 *
 * The same is true of the version gate (N34): an app below the minimum version
 * is refused *after* its queue has drained, so the client must not pre-empt the
 * server by refusing to send. Both are the same rule — **refusing a client must
 * never destroy data** — and both are represented here so the home screen, the
 * heartbeat and the upload worker read one value rather than three booleans
 * that can disagree.
 */
enum class DeviceAuthState(val wire: String) {
    /** Normal. */
    ACTIVE("active"),

    /**
     * The refresh token was rejected. The queue is HELD, not dropped, and the
     * agent is told to contact an admin. Everything captured is still on the
     * phone and will upload the moment the device is re-enrolled.
     */
    AUTH_EXPIRED("auth_expired"),

    /**
     * The installation was revoked (UC-08). Capture stops; the queue is still
     * held until the server confirms what it wants deleted, because a revoke
     * that raced an upload must not silently lose the last calls.
     */
    REVOKED("revoked"),

    /**
     * This build is below the minimum version (N34). **Ingest continues** —
     * the server accepts the backlog and refuses only `auth/refresh` once the
     * queue is empty. The update screen is shown, and it says the calls are
     * safe, because the honest answer is that they are.
     */
    UPDATE_REQUIRED("update_required"),
    ;

    /** May the upload worker still send? */
    val canSend: Boolean
        get() = this == ACTIVE || this == UPDATE_REQUIRED

    /** Should new calls still be captured? */
    val canCapture: Boolean
        get() = this == ACTIVE || this == UPDATE_REQUIRED

    /** Is the queue kept regardless? Always. There is no state in which
     *  captured calls are thrown away by the client. */
    val holdsQueue: Boolean get() = true
}

/**
 * What a failed request means for the device's state.
 *
 * Kept pure and in one place because the wrong answer here is silent: a client
 * that treats `unauthorized` as "start again" deletes a queue, and nobody finds
 * out until the calls are missing from a report weeks later.
 */
object AuthStateRule {

    fun next(current: DeviceAuthState, status: Int, code: String?): DeviceAuthState = when {
        // N34. Refusal only ever arrives once the backlog is gone, and even
        // then the client keeps sending — the state changes what the UI says,
        // not what the queue does.
        status == 426 || code == "app_version_unsupported" -> DeviceAuthState.UPDATE_REQUIRED

        code == "installation_revoked" -> DeviceAuthState.REVOKED

        // A single 401 is a stale access token, which the refresh handles. Only
        // a refused REFRESH is auth_expired — see `onRefreshRefused`.
        else -> current
    }

    /**
     * The refresh itself was refused. This is the only path to
     * [DeviceAuthState.AUTH_EXPIRED].
     *
     * `refresh_reused` is treated the same way: the server considers the token
     * stolen, and the honest thing for the phone to do is stop, hold everything
     * and say so — not retry with a token the server has already judged.
     */
    fun onRefreshRefused(code: String?): DeviceAuthState = when (code) {
        "installation_revoked" -> DeviceAuthState.REVOKED
        else -> DeviceAuthState.AUTH_EXPIRED
    }
}
