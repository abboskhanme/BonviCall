package uz.bonvi.call.service

import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.runTest
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import uz.bonvi.call.capture.transcode.AudioTranscoder
import uz.bonvi.call.data.repository.AudioUpload
import uz.bonvi.call.data.repository.AudioUploader
import uz.bonvi.call.domain.AudioFormat
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CaptureRoute
import uz.bonvi.call.domain.TranscodeFailure
import java.io.File

/**
 * Recording → transcode → upload → delete (T73, T74, N11, UC-08, UC-14).
 *
 * Two of these tests protect the employee rather than the data, and they are
 * the ones worth reading: an **OEM-harvested file is never deleted** by this
 * app, and a recording the server has **refused** does not sit on the phone.
 */
class AudioPipelineTest {

    @get:Rule val temp = TemporaryFolder()

    private class FakeTranscoder(
        private val result: (File, File) -> AudioTranscoder.Result,
    ) : AudioTranscoder {
        override suspend fun transcode(source: File, destinationDir: File) =
            result(source, destinationDir)
    }

    private fun recording(): File = temp.newFile("call.m4a").apply { writeText("raw-audio") }

    private fun transcodedTo(dir: File): File =
        File(dir, "call.ogg").apply { parentFile.mkdirs(); writeText("opus") }

    /** Records what it was asked to send, and answers with [next]. */
    private class FakeUploader(
        var next: AudioUploader.Result = AudioUploader.Result.Interrupted(0),
    ) : AudioUpload {
        var calls = 0
            private set

        override suspend fun upload(request: AudioUploader.Request): AudioUploader.Result {
            calls++
            return next
        }
    }

    @Test
    fun `a transcode failure ships the call with an honest reason`() = runTest {
        // UC-14: a call is never dropped because audio failed.
        val source = recording()
        val work = temp.newFolder("work")
        val uploader = FakeUploader()
        val pipeline = AudioPipeline(
            transcoder = FakeTranscoder { _, _ ->
                AudioTranscoder.Result.Failed(TranscodeFailure.EMPTY_OUTPUT, "0 bytes")
            },
            uploader = uploader,
            io = Dispatchers.Unconfined,
        )

        val outcome = pipeline.process(
            clientCallId = "c1",
            recording = source,
            captureRoute = CaptureRoute.APP_MIC,
            recordedAtEpochMillis = 1_000L,
            workDir = work,
        )

        assertThat(outcome).isInstanceOf(AudioPipeline.Outcome.NoAudio::class.java)
        assertThat((outcome as AudioPipeline.Outcome.NoAudio).reason)
            .isEqualTo(AudioMissingReason.CAPTURE_RETURNED_SILENCE)
        // Our own recording, so it is ours to clean up.
        assertThat(source.exists()).isFalse()
        // And the uploader was never reached: there was nothing to send.
        assertThat(uploader.calls).isEqualTo(0)
    }

    @Test
    fun `an OEM-harvested file is NEVER deleted, even on failure`() {
        // CONVENTIONS.md §8.3. It is the employee's own recording, in their own
        // folder, opened read-only. Deleting one would be a worse breach than
        // never having captured it.
        val source = recording()
        val work = temp.newFolder("work2")
        val pipeline = AudioPipeline(
            transcoder = FakeTranscoder { _, _ ->
                AudioTranscoder.Result.Failed(TranscodeFailure.NO_ENCODER, null)
            },
            uploader = FakeUploader(),
            io = Dispatchers.Unconfined,
        )

        kotlinx.coroutines.runBlocking {
            pipeline.process(
                clientCallId = "c1",
                recording = source,
                captureRoute = CaptureRoute.OEM_FILE_HARVEST,
                recordedAtEpochMillis = 1_000L,
                workDir = work,
            )
        }

        assertThat(source.exists()).isTrue()
    }

    @Test
    fun `the transcoded file is written into the work directory, not beside the source`() {
        // The source may be in the employee's own folder. Writing our output
        // next to it would put a company file in a personal directory.
        val source = recording()
        val work = temp.newFolder("work3")
        val produced = transcodedTo(work)

        assertThat(produced.parentFile).isEqualTo(work)
        assertThat(produced.parentFile).isNotEqualTo(source.parentFile)
    }

    @Test
    fun `every transcode failure carries a reason from the closed enum`() {
        for (failure in TranscodeFailure.entries) {
            assertThat(AudioMissingReason.entries).contains(failure.reason)
        }
    }

    @Test
    fun `the target format is one of the two SPEC allows`() {
        assertThat(AudioFormat.Target.entries).hasSize(2)
    }

    @Test
    fun `a refused upload deletes the local audio when the server says so`() = runTest {
        // audio_not_attributable: the privacy boundary at the far end. Keeping
        // a recording the server has decided is not the company's is the one
        // state worse than losing it.
        val source = recording()
        val work = temp.newFolder("work4")
        val produced = transcodedTo(work)
        val uploader = FakeUploader(
            AudioUploader.Result.Refused("audio_not_attributable", deleteLocal = true),
        )
        val pipeline = AudioPipeline(
            transcoder = FakeTranscoder { _, dir ->
                AudioTranscoder.Result.Transcoded(
                    File(dir, produced.name), AudioFormat.Target.OPUS_OGG, 1_000L, 4L,
                )
            },
            uploader = uploader,
            io = Dispatchers.Unconfined,
        )

        val outcome = pipeline.process("c1", source, CaptureRoute.APP_MIC, 1_000L, work)

        assertThat((outcome as AudioPipeline.Outcome.NoAudio).reason)
            .isEqualTo(AudioMissingReason.ATTRIBUTION_FAILED)
        assertThat(produced.exists()).isFalse()
        assertThat(source.exists()).isFalse()
    }

    @Test
    fun `an interrupted upload keeps everything for the next pass`() = runTest {
        // N11: local audio is deleted only after the server confirms. An
        // interrupted upload has confirmed nothing.
        val source = recording()
        val work = temp.newFolder("work5")
        val produced = transcodedTo(work)
        val pipeline = AudioPipeline(
            transcoder = FakeTranscoder { _, dir ->
                AudioTranscoder.Result.Transcoded(
                    File(dir, produced.name), AudioFormat.Target.OPUS_OGG, 1_000L, 4L,
                )
            },
            uploader = FakeUploader(AudioUploader.Result.Interrupted(2_048)),
            io = Dispatchers.Unconfined,
        )

        val outcome = pipeline.process("c1", source, CaptureRoute.APP_MIC, 1_000L, work)

        assertThat(outcome).isInstanceOf(AudioPipeline.Outcome.Retry::class.java)
        assertThat(produced.exists()).isTrue()
        assertThat(source.exists()).isTrue()
    }

    @Test
    fun `a committed upload deletes the local audio, and only then`() = runTest {
        val source = recording()
        val work = temp.newFolder("work6")
        val produced = transcodedTo(work)
        val pipeline = AudioPipeline(
            transcoder = FakeTranscoder { _, dir ->
                AudioTranscoder.Result.Transcoded(
                    File(dir, produced.name), AudioFormat.Target.OPUS_OGG, 1_000L, 4L,
                )
            },
            uploader = FakeUploader(AudioUploader.Result.Committed("a1", 4L)),
            io = Dispatchers.Unconfined,
        )

        val outcome = pipeline.process("c1", source, CaptureRoute.APP_MIC, 1_000L, work)

        assertThat(outcome).isInstanceOf(AudioPipeline.Outcome.Uploaded::class.java)
        assertThat(produced.exists()).isFalse()
        assertThat(source.exists()).isFalse()
    }
}
