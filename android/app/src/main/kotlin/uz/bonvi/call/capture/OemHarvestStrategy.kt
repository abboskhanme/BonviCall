package uz.bonvi.call.capture

import timber.log.Timber
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CaptureRoute
import uz.bonvi.call.domain.Decision
import java.io.File

/**
 * The preferred route: harvest the file the handset's own recorder wrote
 * (SPEC §7.3, S1).
 *
 * It is **post-hoc**. There is nothing to start — the OEM recorder is running
 * or it is not, and the app cannot switch it on. [start] only fixes the window
 * this call is allowed to look in; [stop] asks the locator for a file.
 *
 * ⚠️ **The privacy boundary passes through this class** (CONVENTIONS.md §8.2,
 * SPEC §7.4). It is constructed with a [Decision.Capture] — the PROOF that this
 * call was placed on the registered subscription — and hands that proof to
 * [OemRecordingLocator.locate]. There is no constructor and no method that
 * accepts a raw number or a call id, so a caller that has not passed
 * `PrivacyBoundary.evaluate()` cannot reach the folder scan at all. That
 * signature is the enforcement; do not add a weaker one.
 *
 * The real locators are T71b, blocked on S1 + M0. Until then
 * `NoOpOemRecordingLocator` returns null, which is the FAIL-CLOSED answer: a
 * placeholder that captured everything by default would be the exact failure
 * this package exists to prevent.
 */
class OemHarvestStrategy(
    private val capture: Decision.Capture,
    private val locator: OemRecordingLocator,
    /** `Capabilities` reports whether the OEM recorder is even reachable on
     *  this handset; the checker reports whether the user has it switched on
     *  (UC-03's `oem_recorder` capability). */
    private val recorderReachable: () -> Boolean,
) : RecordingStrategy {

    private var failure: AudioMissingReason? = null

    override val route: CaptureRoute = CaptureRoute.OEM_FILE_HARVEST

    override fun isSupported(): Boolean {
        if (!recorderReachable()) {
            failure = AudioMissingReason.OEM_RECORDER_OFF
            return false
        }
        return true
    }

    /**
     * Nothing starts. The parameter is ignored on purpose: this strategy never
     * writes a file, it finds one, and the OEM's files are opened read-only and
     * never moved, modified or deleted (CONVENTIONS.md §8.3).
     */
    override fun start(target: File) {
        failure = null
    }

    override fun stop(): File? {
        val file = locator.locate(capture)
        if (file == null) {
            // The window matched nothing. This is the boundary REFUSING, not a
            // bug: an unmatched recording in that folder is the employee's
            // private call, and it is discarded on the device rather than
            // uploaded and sorted out server-side.
            failure = AudioMissingReason.ATTRIBUTION_FAILED
            Timber.i("No OEM recording matched this call's window")
        }
        return file
    }

    override fun lastFailure(): AudioMissingReason? = failure
}
