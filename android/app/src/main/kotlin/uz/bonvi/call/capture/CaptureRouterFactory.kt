package uz.bonvi.call.capture

import uz.bonvi.call.core.Capabilities
import uz.bonvi.call.domain.Decision
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Builds a [CaptureRouter] for one call.
 *
 * A router is per-call because `OemHarvestStrategy` holds that call's
 * [Decision.Capture] — which is the point: there is no way to build the capture
 * path for a call without the proof that the call is ours.
 *
 * The ORDER is fixed here, once: the handset's own recorder first (S1: it is
 * what captures both voices), the app's own recording second. Both are started;
 * whichever produced a file at the end wins, in this order.
 */
@Singleton
class CaptureRouterFactory @Inject constructor(
    private val locator: OemRecordingLocator,
    private val capabilityChecker: CaptureCapabilityChecker,
) {
    fun forCall(capture: Decision.Capture): CaptureRouter = CaptureRouter(
        listOf(
            OemHarvestStrategy(
                capture = capture,
                locator = locator,
                recorderReachable = capabilityChecker::oemRecorderReachable,
            ),
            MediaRecorderStrategy(
                recorderFactory = { MediaRecorderAudioRecorder() },
                canUseVoiceRecognition = Capabilities::canUseVoiceRecognitionSource,
                microphoneAvailable = capabilityChecker::microphoneWorking,
            ),
        ),
    )
}

/**
 * What the capture path needs to know about this device, asked as capabilities
 * rather than as permissions.
 *
 * UC-03's finding is the reason this is an interface and not a permission
 * check: an OEM permission manager can report RECORD_AUDIO as granted while a
 * test capture returns nothing, and `granted_not_working` is a reportable state
 * rather than an impossible one. T62 implements the real checkers.
 */
interface CaptureCapabilityChecker {
    fun microphoneWorking(): Boolean
    fun oemRecorderReachable(): Boolean
}
