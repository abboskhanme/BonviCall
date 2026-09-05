package uz.bonvi.call.domain

/**
 * The audio the phone uploads (N17, N18, N21, SPEC §7.6).
 *
 * ═══ Why these numbers and not louder ones ═════════════════════════════════
 * The prototype recorded at 44.1 kHz / 128 kbps stereo. That is roughly five
 * times the size of the target below, and at ~15 000 calls a month it works out
 * near **6 GB per agent per month of mobile data — spent from a personal
 * phone's plan** (R14, D6). Nobody would say why they uninstalled it; they
 * would just uninstall it.
 *
 * So the transcode happens **on the device, before upload**, which makes the
 * cellular budget and the storage budget the same number: ~10.8 MB/hour of
 * speech, ~17 GB/month across the fleet (N18).
 *
 * ═══ The quality floor ═════════════════════════════════════════════════════
 * "Small" is bounded below by N21: the audio has to survive being fed to
 * speech-to-text later **without a second lossy transcode**. Mono 16 kHz is the
 * standard ASR input rate — resampling down to it is free, and starting below
 * it cannot be undone. 24 kbps Opus at 16 kHz is comfortably above the
 * intelligibility floor for speech; dropping to 12 or 16 kbps would save little
 * and cost the thing the recording is for.
 */
object AudioFormat {

    /** ASR's native input rate. Below this is unrecoverable. */
    const val SAMPLE_RATE_HZ = 16_000

    /** Speech, not music. A second channel doubles the bill for nothing. */
    const val CHANNELS = 1

    /** N17's ceiling. ~10.8 MB per hour of audio. */
    const val BITRATE_BPS = 24_000

    /** Bytes per hour at [BITRATE_BPS], for the storage and data projections. */
    const val BYTES_PER_HOUR: Long = BITRATE_BPS.toLong() * 3_600L / 8L

    /**
     * The two shapes that ship, and why there are two.
     *
     * Opus in Ogg is the target. `MediaMuxer` only gained Ogg output at
     * **API 29**, and the `legacy28` variant has to run on API 26–28 — which is
     * the variant S1 says captures both voices, so it cannot simply be dropped.
     *
     * The decided fallback (SPEC §7.6) is AAC-LC at the same 24 kbps mono
     * 16 kHz in MP4. The panel plays it natively in Chrome and Edge, ASR
     * engines accept it, and the storage budget is unchanged — so the fallback
     * costs nothing except being counted, which it is: `capture_route` and the
     * codec both travel with every recording, so "how many recordings used the
     * fallback" is a query rather than an experiment somebody remembers running.
     */
    enum class Target(val codec: String, val container: String, val extension: String) {
        OPUS_OGG("opus", "ogg", "ogg"),
        AAC_MP4("aac_lc", "mp4", "m4a"),
    }
}

/**
 * Why a recording was not transcoded.
 *
 * A transcode failure must **never** be the reason a call is lost: the call
 * still ships with an honest [AudioMissingReason] and the record is complete
 * (UC-14). These map onto the closed enum rather than inventing a parallel one.
 */
enum class TranscodeFailure(val reason: AudioMissingReason) {
    /** No encoder for either target on this handset. Vanishingly rare — AAC-LC
     *  is mandatory from API 16 — but it is a device fact, not a bug. */
    NO_ENCODER(AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE),

    /** The input file was empty or unreadable by the decoder. */
    UNREADABLE_INPUT(AudioMissingReason.CAPTURE_RETURNED_SILENCE),

    /** The encoder ran and produced nothing usable. */
    EMPTY_OUTPUT(AudioMissingReason.CAPTURE_RETURNED_SILENCE),

    /** No room to write the output. The queue is already full or the phone is. */
    NO_SPACE(AudioMissingReason.QUEUE_SPACE_EXHAUSTED),
}
