package uz.bonvi.call.service

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import uz.bonvi.call.capture.CaptureRouter
import uz.bonvi.call.capture.CaptureRouterFactory
import uz.bonvi.call.domain.Decision
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import javax.inject.Inject
import javax.inject.Singleton

/**
 * What the call detector may ask of the capture path.
 *
 * A seam, so `CallDetector`'s privacy-boundary branches stay testable without
 * an Android runtime — those branches are the ones that decide whether a
 * private call is recorded, and they are the reason this whole package is
 * arranged the way it is.
 */
interface CallCapture {
    /** This call MAY be captured, and here is the proof. */
    fun prepare(callId: String, capture: Decision.Capture)

    /** The call was answered. */
    fun start(callId: String)

    /** The call ended. Null when nothing was ever started. */
    fun stop(callId: String): CaptureOutcome?

    /** Rejected, or the process is going down. */
    fun discard(callId: String)

    /** Where the transcoder may work. */
    fun workDir(): File
}

/** What one call's capture produced. `file == null` always carries a reason
 *  from the closed enum, never free text (N5). */
data class CaptureOutcome(
    val file: File?,
    val route: uz.bonvi.call.domain.CaptureRoute,
    val reason: uz.bonvi.call.domain.AudioMissingReason?,
)

/**
 * Runs one capture per call, and keeps the proof that it may (SPEC §7.3, T71).
 *
 * ═══ Why this class exists ═════════════════════════════════════════════════
 * `CaptureRouterFactory` and `CaptureRouter` were written, tested and **never
 * called**. Every call was therefore queued with `capture_route = none` and no
 * audio — on a product whose whole purpose is the recording. The strategies
 * worked; nothing asked them to.
 *
 * ═══ The boundary travels with the call ════════════════════════════════════
 * A router can only be built from a [Decision.Capture], which only
 * `PrivacyBoundary.evaluate` produces (CONVENTIONS.md §8.2). So the decision is
 * held here from the moment the call is judged until the moment capture stops,
 * and a call that was rejected has nothing to hold — [prepare] is never called
 * for it, so [start] finds nothing and records nothing.
 *
 * ═══ One router per call id — R5 ═══════════════════════════════════════════
 * Call waiting means two live calls, and a single "current recording" would
 * splice the second onto the first. Keyed by call id for the same reason
 * `CallSessionManager` is.
 */
@Singleton
class CaptureCoordinator @Inject constructor(
    @ApplicationContext private val context: Context,
    private val factory: CaptureRouterFactory,
) : CallCapture {

    private val prepared = ConcurrentHashMap<String, Decision.Capture>()
    private val running = ConcurrentHashMap<String, CaptureRouter>()

    /**
     * Remember that this call may be captured.
     *
     * ⚠️ The decision's `endedAtEpochMillis` is not known yet — the call is
     * still ringing — so it is the provisional bound the detector's guard used.
     * `OemHarvestStrategy` passes it to the locator as the harvest window, and
     * **T71b must bound that window itself** rather than trusting the upper
     * end. Nothing depends on it today: `NoOpOemRecordingLocator` returns null,
     * which is the fail-closed answer.
     */
    override fun prepare(callId: String, capture: Decision.Capture) {
        prepared[callId] = capture
    }

    /**
     * Begin recording, at the moment the call is answered.
     *
     * Not at the first ring: an incoming call that is never answered has no
     * conversation to record — it ships as `not_expected`, which is what keeps
     * the gap report's denominator honest — and a recorder started against a
     * ringtone competes with the dialler for the microphone.
     */
    override fun start(callId: String) {
        val capture = prepared.remove(callId) ?: return
        if (running.containsKey(callId)) return

        val router = factory.forCall(capture)
        @Suppress("TooGenericExceptionCaught")
        try {
            router.start { strategy -> targetFor(callId, strategy.route.wire) }
            running[callId] = router
        } catch (error: Exception) {
            // The router already swallows a strategy that will not start; this
            // is the layer below that — a filesystem that will not give us a
            // directory. A capture failure is data, never a lost call (UC-14).
            Timber.w(error, "Capture could not start for this call")
        }
    }

    /**
     * Stop, and say what was captured.
     *
     * Null when nothing was ever started — a call that was never answered, or
     * one the boundary rejected. The caller records the reason from
     * [CallRecordBuilder] in that case, which is the same honest answer.
     */
    override fun stop(callId: String): CaptureOutcome? {
        prepared.remove(callId)
        val router = running.remove(callId) ?: return null
        @Suppress("TooGenericExceptionCaught")
        return try {
            router.stop().let { CaptureOutcome(it.file, it.route, it.reason) }
        } catch (error: Exception) {
            Timber.w(error, "Capture could not be stopped cleanly")
            null
        }
    }

    /** The call was rejected, or the process is going down. */
    override fun discard(callId: String) {
        prepared.remove(callId)
        running.remove(callId)?.let {
            @Suppress("TooGenericExceptionCaught")
            try {
                it.stop()
            } catch (error: Exception) {
                Timber.w(error, "Capture could not be discarded cleanly")
            }
        }
    }

    /** Where the transcoder works. App-private, and cleared as it goes. */
    override fun workDir(): File = File(context.filesDir, WORK_DIR).apply { mkdirs() }

    /**
     * One file per strategy, per call.
     *
     * Two strategies writing one path is how a fallback silently truncates the
     * preferred route's output — the failure then looks like a corrupt
     * recording rather than a bug.
     */
    private fun targetFor(callId: String, route: String): File {
        val directory = File(context.filesDir, AUDIO_DIR).apply { mkdirs() }
        return File(directory, "$callId-$route.$RAW_EXTENSION")
    }

    private companion object {
        /** `Revocation` deletes everything under here, which is the point:
         *  these are recordings of the employee's calls. */
        const val AUDIO_DIR = "audio"
        const val WORK_DIR = "audio/work"

        /** The container `MediaRecorderAudioRecorder` writes. The transcoder
         *  reads the file, not the name, but a raw recording with an honest
         *  extension is one less thing to guess at during a support call. */
        const val RAW_EXTENSION = "m4a"
    }
}
