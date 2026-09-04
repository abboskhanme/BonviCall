package uz.bonvi.call.capture

import uz.bonvi.call.domain.Decision
import java.io.File

/**
 * Finds the handset's own recording of a call.
 *
 * ⚠️ **This interface is the privacy boundary in its enforced form.** It takes
 * a [Decision.Capture] — the PROOF that the call was on the registered
 * subscription — and not a raw number, not a call id. A caller that has not
 * passed `PrivacyBoundary.evaluate()` cannot construct the argument, so the
 * file scan cannot be reached without having passed the boundary
 * (CONVENTIONS.md §8.2, SPEC §7.4). Do not add an overload that takes anything
 * weaker.
 *
 * The implementation may read ONLY files whose `lastModified` falls inside
 * `[answeredAt − PRE_BUFFER_MS, endedAt + POST_BUFFER_MS]`, are larger than
 * [MIN_FILE_BYTES], and carry an audio extension. It never lists the folder for
 * any other purpose, never copies an unmatched file, and **never moves,
 * modifies or deletes anything** — the files belong to the employee.
 *
 * Two implementations, chosen per flavour in `di/CaptureModule.kt`:
 * a raw-path locator on `legacy28` and a MediaStore locator on `modern34`.
 * Which one is a CAPABILITY question, not a version check
 * (`Capabilities.canReadOemRecordingsByPath()`).
 *
 * `OemLocatorPrivacyTest` — a private-SIM recording sitting in the same folder
 * is never returned — is one of the three undeletable tests (CONVENTIONS.md §8).
 */
fun interface OemRecordingLocator {

    /** The newest matching file, or null. Null is a normal answer and becomes
     *  `attribution_failed` on the call.
     *
     *  A `fun interface` deliberately: it keeps the SINGLE abstract method
     *  single. A second overload taking anything weaker than
     *  [Decision.Capture] would not compile, which is a cheaper guarantee than
     *  a review. */
    fun locate(capture: Decision.Capture): File?

    companion object {
        /** CallSentry's measured values (S1-RECORDING.md). Widening either of
         *  them widens the privacy boundary, so it is a one-line diff a
         *  reviewer can see. */
        const val PRE_BUFFER_MS: Long = 5_000L
        const val POST_BUFFER_MS: Long = 120_000L

        /** Below this a file is a stub the OEM writer has not filled yet. */
        const val MIN_FILE_BYTES: Long = 2_048L

        /** The OEM writer flushes late, so the match is retried. */
        const val RETRY_COUNT: Int = 4
        const val RETRY_INTERVAL_MS: Long = 1_000L
    }
}

/**
 * The locator that is in place until T71b writes the real ones.
 *
 * It returns null, which the caller already handles as `attribution_failed`.
 * Returning null is the FAIL-CLOSED answer: a scaffold that captured
 * everything by default would be the exact failure this package exists to
 * prevent.
 *
 * TODO(T71b): replace, per flavour. Do not widen the signature.
 */
class NoOpOemRecordingLocator(private val reason: String) : OemRecordingLocator {
    override fun locate(capture: Decision.Capture): File? = null
    override fun toString(): String = "NoOpOemRecordingLocator($reason)"
}
