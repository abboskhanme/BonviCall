package uz.bonvi.call.domain

/**
 * When audio is allowed to use the cellular connection (T74, N14, N15, R14).
 *
 * ═══ The rule, and why it is not "Wi-Fi only" ══════════════════════════════
 * **Wi-Fi first, cellular after 24 hours regardless.** A recording that never
 * uploads because the phone is never on Wi-Fi is a recording that does not
 * exist — and a salesperson who spends the day in the field is precisely the
 * person whose calls matter most.
 *
 * N14's 1 GB monthly cap is the **ceiling, not the strategy**. At N17's 24 kbps
 * a full hour of speech is ~10.8 MB, so a heavy day is tens of megabytes: the
 * cap is there to catch a fault, not to ration normal use. Rationing normal use
 * would trade a visible cost (data) for an invisible one (missing calls), which
 * is the wrong way round for this product.
 */
object AudioUploadPolicy {

    /** After this, a recording goes over cellular rather than waiting longer. */
    const val CELLULAR_AFTER_MS: Long = 24 * 60 * 60 * 1000L

    /** N14. A ceiling that means something is wrong, not a budget to spend. */
    const val MONTHLY_CELLULAR_CAP_BYTES: Long = 1_024L * 1_024L * 1_024L

    enum class Decision {
        /** Send now. */
        SEND,

        /** Wi-Fi is not available and the recording is still young. */
        WAIT_FOR_WIFI,

        /** No usable connection at all. */
        WAIT_FOR_NETWORK,

        /**
         * The monthly cellular cap is spent. The recording is HELD, never
         * dropped: the cap limits what the app costs, not what it keeps.
         */
        HOLD_CAP_REACHED,
    }

    fun decide(
        recordedAtEpochMillis: Long,
        nowEpochMillis: Long,
        onWifi: Boolean,
        onCellular: Boolean,
        cellularBytesThisMonth: Long,
    ): Decision = when {
        onWifi -> Decision.SEND
        !onCellular -> Decision.WAIT_FOR_NETWORK
        nowEpochMillis - recordedAtEpochMillis < CELLULAR_AFTER_MS -> Decision.WAIT_FOR_WIFI
        cellularBytesThisMonth >= MONTHLY_CELLULAR_CAP_BYTES -> Decision.HOLD_CAP_REACHED
        else -> Decision.SEND
    }

    /**
     * Should this upload failure be retried at all?
     *
     * `audio_not_attributable` is the **privacy boundary at the far end**: the
     * server could not match the file to a registered-number call inside its
     * window, so it refused it and wrote no bytes. Retrying can never succeed —
     * the window does not reopen — and a client that retried it would spend the
     * employee's data in a loop, on a file the server has already decided is
     * not the company's. It is a permanent per-item failure: park it, report
     * it, and delete the local file, because keeping a recording the server
     * has refused is the one thing worse than losing it.
     */
    fun isPermanentFailure(code: String?): Boolean = code in PERMANENT_FAILURES

    private val PERMANENT_FAILURES = setOf(
        "audio_not_attributable",
        "audio_expired",
        "upload_expired",
        "checksum_mismatch",
    )

    /** Does this failure mean the recording should also be deleted locally? */
    fun shouldDeleteLocalAudio(code: String?): Boolean =
        code == "audio_not_attributable" || code == "audio_expired"
}
