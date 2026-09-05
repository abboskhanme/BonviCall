package uz.bonvi.call.domain

/**
 * One of the employee's own calls, **as the server holds it** (client request,
 * N41).
 *
 * ═══ Why this is not the local queue ═══════════════════════════════════════
 * The point of the screen is the employee seeing their own record **as the
 * company sees it**. A list built from the local queue would show calls that
 * never uploaded — which the company does not have — and hide calls the
 * recovery sweep found in the OS call log, which it does. Those two errors
 * point in opposite directions and both destroy the value of the screen.
 */
data class MyCall(
    val id: String,
    val clientCallId: String,
    val direction: CallDirection,
    val disposition: CallDisposition,
    val remoteNumber: String?,
    /** Resolved on the device at capture time, one number to one name (T139). */
    val contactName: String?,
    val startedAtEpochMillis: Long,
    val durationSec: Int,
    /**
     * What the employee is shown, and the ONLY thing the play control keys off.
     *
     * ⚠️ **Derived server-side and never re-derived here.** It needs
     * `call_audio.deleted_at`, which the call row does not carry — a client
     * computing it from `has_audio` alone would offer a play button for a
     * recording retention has already removed, and the employee would learn
     * that the app is broken when it is behaving exactly as designed.
     */
    val audioState: AudioState,
    /**
     * Why there is no recording. **Null unless [audioState] is
     * [AudioState.MISSING]** — every member of the enum means audio is absent,
     * so a value beside a recording that exists would make the name a lie.
     */
    val audioMissingReason: AudioMissingReason?,
    val captureRoute: CaptureRoute?,
) {
    /** A play control appears here and nowhere else. A button that answers 410
     *  teaches somebody the app is broken when it is working correctly. */
    val playable: Boolean get() = audioState == AudioState.RECORDED
}

/**
 * What happened to this call's audio (server-derived).
 *
 * One field to switch on, one Uzbek sentence out. The distinction that matters
 * most is that **[EXPIRED] is not a failure**: the recording existed and
 * retention removed it, which is the system working as designed and must not
 * read like a fault. Only [MISSING] carries a reason, and that is where the
 * ten-value `AudioMissingReason` enum earns its place.
 */
enum class AudioState(val wire: String) {
    /** Stored and playable. */
    RECORDED("recorded"),

    /** It existed and retention deleted it. Not a fault. */
    EXPIRED("expired"),

    /** On its way — captured, not yet uploaded or not yet committed. */
    QUEUED("queued"),

    /** There was never a conversation to record: an unanswered call. Excluded
     *  from the gap report's denominator for the same reason (SPEC §3.9). */
    NOT_EXPECTED("not_expected"),

    /** Something went wrong, and `audioMissingReason` says what. */
    MISSING("missing"),
    ;

    companion object {
        fun fromWire(wire: String): AudioState =
            entries.firstOrNull { it.wire == wire } ?: MISSING
    }
}

/** A page of them. Keyset, because the panel's rule applies here too. */
data class MyCallsPage(
    val items: List<MyCall>,
    val nextCursor: String?,
    val hasMore: Boolean,
)

/**
 * Reads the employee's own calls from the server.
 *
 * The narrowing to this agent's calls is done **server-side**, by `agent_id`
 * and not by `installation_id` — the two look equally correct and the second
 * would silently empty an employee's entire history the day they got a
 * replacement handset, because SPEC §9.3 rebinds the number to a new
 * installation. There is no client-side filter here and there must never be
 * one: the client is the thing that cannot be trusted to do it.
 */
interface MyCallsGateway {

    sealed interface Result {
        data class Page(val page: MyCallsPage) : Result
        data class Failed(val code: String?) : Result
        data object Offline : Result
    }

    suspend fun page(cursor: String?, limit: Int = DEFAULT_LIMIT): Result

    /** An absolute URL the player can stream with `Range`. Null when the
     *  server holds no audio for this call. */
    suspend fun audioUrl(callId: String): String?

    companion object {
        /** A phone screen. 1 000-row pages are the panel's problem. */
        const val DEFAULT_LIMIT = 50
    }
}
