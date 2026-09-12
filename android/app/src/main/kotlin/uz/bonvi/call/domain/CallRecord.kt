package uz.bonvi.call.domain

/**
 * A captured call, as the rest of the app understands it. Pure Kotlin — no
 * Android types, no Room annotations, no Moshi annotations — so the rules that
 * operate on it are testable without a phone.
 *
 * Three timestamps, never merged (CONVENTIONS.md §6): the device's own
 * wall-clock times are DATA, `deviceEpochMillis` is EVIDENCE of skew, and the
 * server's `received_at` is the only thing that orders anything. Durations come
 * from the monotonic clock, never from subtracting two wall-clock readings.
 */
data class CallRecord(
    /**
     * The client-generated UUIDv4 that makes the upload idempotent
     * (CONVENTIONS.md §5). It lives in the BODY, not a header, because it must
     * survive as a Room column across app restarts and retry plumbing drops
     * headers. The server answers 200 with the same id for a replay, so a first
     * write and a retry are indistinguishable.
     */
    val clientCallId: String,
    val direction: CallDirection,
    val disposition: CallDisposition,
    val source: CallSource,
    /** Raw, as the device saw it. The server normalises and derives the key. */
    val remoteNumber: String?,
    val startedAtEpochMillis: Long,
    val answeredAtEpochMillis: Long?,
    val endedAtEpochMillis: Long,
    /** Measured with the monotonic clock (`Clock.durationSeconds`). */
    val durationSec: Int,
    val deviceEpochMillis: Long,
    val deviceTimezone: String,
    val captureRoute: CaptureRoute,
    /** The contact's display name, resolved FRESH from the phone at upload
     *  time and never cached (N28) -- so a renamed contact shows its new name
     *  on the next call, which is the Moi Zvonki defect this product was built
     *  to avoid. Null when there is no match or CONTACTS was not granted. */
    val contactName: String? = null,
    /** Never null: "we do not know" is a value, not an absence (N5). */
    val audioMissingReason: AudioMissingReason,
)
