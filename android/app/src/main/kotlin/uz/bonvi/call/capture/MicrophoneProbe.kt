package uz.bonvi.call.capture

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.core.content.ContextCompat
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.Capability
import uz.bonvi.call.domain.CapabilityResult
import uz.bonvi.call.domain.CapabilityState
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The microphone capability check: **a real one-second capture** (SPEC §7.8).
 *
 * This is the check UC-03 was written for. An OEM permission manager can report
 * RECORD_AUDIO as granted and still hand back silence, so the flag is worthless
 * and only bytes prove anything. The result distinguishes three cases the agent
 * has to act on differently:
 *
 *  • not granted            → the system dialog will help;
 *  • granted, bytes arrive  → done;
 *  • granted, **all zero or nothing** → `granted_not_working`, and the system
 *    dialog will never fix it. The UI sends the agent to the OEM's own screen
 *    instead of asking them to press the same button again.
 *
 * It lives under `capture/` because it touches `AudioRecord`, and media APIs
 * appear in exactly one package (SPEC §7.1, `ArchitectureRulesTest`).
 * Nothing is written to disk: the buffer is inspected in memory and dropped.
 */
@Singleton
class MicrophoneProbe @Inject constructor(
    @ApplicationContext private val context: Context,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    suspend fun probe(): CapabilityResult = withContext(io) {
        if (!hasPermission()) {
            return@withContext result(CapabilityState.DENIED, "RECORD_AUDIO not granted")
        }

        val minBuffer = AudioRecord.getMinBufferSize(SAMPLE_RATE_HZ, CHANNEL, ENCODING)
        if (minBuffer <= 0) {
            return@withContext result(
                CapabilityState.GRANTED_NOT_WORKING,
                "no usable audio buffer at ${SAMPLE_RATE_HZ}Hz",
            )
        }

        var recorder: AudioRecord? = null
        @Suppress("TooGenericExceptionCaught")
        try {
            recorder = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE_HZ,
                CHANNEL,
                ENCODING,
                maxOf(minBuffer, BUFFER_BYTES),
            )
            if (recorder.state != AudioRecord.STATE_INITIALIZED) {
                return@withContext result(
                    CapabilityState.GRANTED_NOT_WORKING,
                    "recorder would not initialise",
                )
            }

            recorder.startRecording()
            val buffer = ShortArray(BUFFER_BYTES / 2)
            var read = 0
            val deadline = System.nanoTime() + PROBE_NANOS
            var loudest = 0
            while (System.nanoTime() < deadline) {
                val count = recorder.read(buffer, 0, buffer.size)
                if (count <= 0) break
                read += count
                for (index in 0 until count) {
                    val magnitude = kotlin.math.abs(buffer[index].toInt())
                    if (magnitude > loudest) loudest = magnitude
                }
            }
            recorder.stop()

            when {
                read < MIN_SAMPLES -> result(
                    CapabilityState.GRANTED_NOT_WORKING,
                    "capture returned $read samples in 1s",
                )
                // All-zero is the OEM-blocking signature: the API succeeds and
                // the audio is silence. A quiet room is not all-zero.
                loudest == 0 -> result(
                    CapabilityState.GRANTED_NOT_WORKING,
                    "1s capture was digital silence",
                )
                else -> result(
                    CapabilityState.GRANTED_WORKING,
                    "1s test capture, $read samples, peak $loudest",
                )
            }
        } catch (error: Exception) {
            // Broad, and this is the specific failure it catches: a
            // SecurityException from an OEM permission manager that granted the
            // permission and refuses the API, or IllegalStateException when the
            // microphone is held by the dialer. Both are `granted_not_working`
            // — the agent has to change a setting, not press the dialog again.
            Timber.w(error, "Microphone probe failed")
            result(CapabilityState.GRANTED_NOT_WORKING, error.javaClass.simpleName)
        } finally {
            @Suppress("TooGenericExceptionCaught")
            try {
                recorder?.release()
            } catch (error: Exception) {
                // A recorder that will not release must not fail the check that
                // already produced its answer.
                Timber.w(error, "Microphone probe release failed")
            }
        }
    }

    private fun hasPermission(): Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    private fun result(state: CapabilityState, detail: String) =
        CapabilityResult(Capability.MICROPHONE, state, detail)

    private companion object {
        const val SAMPLE_RATE_HZ = 16_000
        const val CHANNEL = AudioFormat.CHANNEL_IN_MONO
        const val ENCODING = AudioFormat.ENCODING_PCM_16BIT
        const val BUFFER_BYTES = 4_096
        const val PROBE_NANOS = 1_000_000_000L

        /** A tenth of a second of audio. Below this the API answered without
         *  actually capturing. */
        const val MIN_SAMPLES = SAMPLE_RATE_HZ / 10
    }
}
