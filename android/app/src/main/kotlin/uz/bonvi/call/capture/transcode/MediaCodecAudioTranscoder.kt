package uz.bonvi.call.capture.transcode

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.core.Capabilities
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.AudioFormat
import uz.bonvi.call.domain.TranscodeFailure
import java.io.File
import java.nio.ByteBuffer
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Decode → resample → encode, on the phone, before upload (T73, N17).
 *
 * ═══ What this is worth ════════════════════════════════════════════════════
 * The prototype uploaded 44.1 kHz / 128 kbps: about **6 GB per agent per month
 * of mobile data**, from a personal phone's plan (R14, D6). This converts to
 * mono 16 kHz at 24 kbps first, so the cellular bill and the storage bill are
 * the same ~10.8 MB/hour number, and the app does not get uninstalled for a
 * reason nobody reports.
 *
 * ═══ Two targets, chosen by capability ═════════════════════════════════════
 * Opus in Ogg where `MediaMuxer` can write it (API 29+), AAC-LC in MP4
 * otherwise — which is most of the `legacy28` fleet, the variant S1 says
 * captures both voices. Both are 24 kbps mono 16 kHz, so the budget is
 * identical and the fallback costs only being counted, which it is.
 *
 * ═══ It never loses a call ═════════════════════════════════════════════════
 * Every failure returns [AudioTranscoder.Result.Failed] with a reason from the
 * closed enum. The caller ships the call regardless (UC-14). Nothing here
 * throws into the capture path, and the SOURCE file is never modified or
 * deleted — on the harvest route it belongs to the employee
 * (CONVENTIONS.md §8.3).
 */
@Singleton
class MediaCodecAudioTranscoder @Inject constructor(
    @IoDispatcher private val io: CoroutineDispatcher,
) : AudioTranscoder {

    override suspend fun transcode(
        source: File,
        destinationDir: File,
    ): AudioTranscoder.Result = withContext(io) {
        if (!source.isFile || source.length() < MIN_INPUT_BYTES) {
            return@withContext failed(TranscodeFailure.UNREADABLE_INPUT, "source is ${source.length()} bytes")
        }
        if (!destinationDir.exists() && !destinationDir.mkdirs()) {
            return@withContext failed(TranscodeFailure.NO_SPACE, "cannot create ${destinationDir.name}")
        }

        val target = preferredTarget()
        val destination = File(destinationDir, "${source.nameWithoutExtension}.${target.extension}")

        @Suppress("TooGenericExceptionCaught")
        return@withContext try {
            val durationMs = run(source, destination, target)
            when {
                durationMs == null -> failed(TranscodeFailure.NO_ENCODER, "no encoder for ${target.codec}")
                destination.length() < MIN_OUTPUT_BYTES -> {
                    destination.delete()
                    failed(TranscodeFailure.EMPTY_OUTPUT, "output was ${destination.length()} bytes")
                }
                else -> AudioTranscoder.Result.Transcoded(
                    file = destination,
                    target = target,
                    durationMs = durationMs,
                    bytes = destination.length(),
                )
            }
        } catch (error: Exception) {
            // Broad, and the specific failures are MediaCodec's:
            // IllegalStateException from an encoder that will not configure,
            // IOException from a full filesystem, and
            // MediaCodec.CodecException on an OEM whose encoder rejects the
            // format. None of them may take the CALL down with the recording.
            Timber.w(error, "Transcode failed; the call ships without audio")
            destination.delete()
            failed(TranscodeFailure.EMPTY_OUTPUT, error.javaClass.simpleName)
        }
    }

    /**
     * Opus where the muxer supports it, AAC otherwise.
     *
     * Asked as a capability, never as a version at this call site
     * (CONVENTIONS-CLIENT.md §7): `legacy28` and `modern34` differ here and a
     * version check in the capture path is how the two silently diverge.
     */
    fun preferredTarget(): AudioFormat.Target =
        if (Capabilities.canMuxOpusOgg()) AudioFormat.Target.OPUS_OGG else AudioFormat.Target.AAC_MP4

    /** @return the duration written, or null when no encoder exists. */
    private fun run(source: File, destination: File, target: AudioFormat.Target): Long? {
        val extractor = MediaExtractor().apply { setDataSource(source.absolutePath) }
        try {
            val trackIndex = (0 until extractor.trackCount).firstOrNull { index ->
                extractor.getTrackFormat(index)
                    .getString(MediaFormat.KEY_MIME)
                    ?.startsWith("audio/") == true
            } ?: return null
            extractor.selectTrack(trackIndex)
            val inputFormat = extractor.getTrackFormat(trackIndex)

            val decoder = MediaCodec.createDecoderByType(
                inputFormat.getString(MediaFormat.KEY_MIME) ?: return null,
            )
            val encoder = MediaCodec.createEncoderByType(target.mimeType()) ?: return null
            // The guard is written out HERE rather than hidden in a helper, so
            // lint can see `Capabilities.canMuxOpusOgg()` — which is
            // `@ChecksSdkIntAtLeast(Q)` — wrapping the API 29 constant. Same
            // capability that chose the target; asking it twice is cheaper than
            // a `@SuppressLint` that would forbid nothing.
            val muxerFormat = if (Capabilities.canMuxOpusOgg()) {
                MediaMuxer.OutputFormat.MUXER_OUTPUT_OGG
            } else {
                MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4
            }
            val muxer = MediaMuxer(destination.absolutePath, muxerFormat)

            return pump(extractor, inputFormat, decoder, encoder, muxer)
        } finally {
            extractor.release()
        }
    }

    /**
     * The decode→encode loop.
     *
     * Deliberately synchronous and buffer-by-buffer rather than using
     * `MediaCodec.Callback`: a call recording is minutes long and this runs on
     * the IO dispatcher after the call has ended, so throughput does not
     * matter and a straight-line loop is a loop somebody can debug at 2 a.m.
     */
    @Suppress("LongParameterList", "CyclomaticComplexMethod", "NestedBlockDepth")
    private fun pump(
        extractor: MediaExtractor,
        inputFormat: MediaFormat,
        decoder: MediaCodec,
        encoder: MediaCodec,
        muxer: MediaMuxer,
    ): Long {
        val encoderFormat = MediaFormat.createAudioFormat(
            encoder.name.let { encoderMime(encoder) },
            AudioFormat.SAMPLE_RATE_HZ,
            AudioFormat.CHANNELS,
        ).apply {
            setInteger(MediaFormat.KEY_BIT_RATE, AudioFormat.BITRATE_BPS)
            setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, MAX_INPUT_SIZE)
        }

        decoder.configure(inputFormat, null, null, 0)
        encoder.configure(encoderFormat, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        decoder.start()
        encoder.start()

        var muxerTrack = -1
        var muxerStarted = false
        var lastPresentationUs = 0L
        var sawInputEnd = false
        var sawDecoderEnd = false
        var sawEncoderEnd = false
        val info = MediaCodec.BufferInfo()

        try {
            while (!sawEncoderEnd) {
                if (!sawInputEnd) {
                    val index = decoder.dequeueInputBuffer(TIMEOUT_US)
                    if (index >= 0) {
                        val buffer = decoder.getInputBuffer(index) ?: ByteBuffer.allocate(0)
                        val size = extractor.readSampleData(buffer, 0)
                        if (size < 0) {
                            decoder.queueInputBuffer(
                                index, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM,
                            )
                            sawInputEnd = true
                        } else {
                            decoder.queueInputBuffer(index, 0, size, extractor.sampleTime, 0)
                            extractor.advance()
                        }
                    }
                }

                if (!sawDecoderEnd) {
                    val index = decoder.dequeueOutputBuffer(info, TIMEOUT_US)
                    if (index >= 0) {
                        val pcm = decoder.getOutputBuffer(index)
                        if (info.size > 0 && pcm != null) feedEncoder(encoder, pcm, info)
                        if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) {
                            signalEncoderEnd(encoder)
                            sawDecoderEnd = true
                        }
                        decoder.releaseOutputBuffer(index, false)
                    }
                }

                val index = encoder.dequeueOutputBuffer(info, TIMEOUT_US)
                when {
                    index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                        muxerTrack = muxer.addTrack(encoder.outputFormat)
                        muxer.start()
                        muxerStarted = true
                    }

                    index >= 0 -> {
                        val encoded = encoder.getOutputBuffer(index)
                        val isConfig = info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0
                        if (encoded != null && info.size > 0 && muxerStarted && !isConfig) {
                            muxer.writeSampleData(muxerTrack, encoded, info)
                            lastPresentationUs = info.presentationTimeUs
                        }
                        if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) {
                            sawEncoderEnd = true
                        }
                        encoder.releaseOutputBuffer(index, false)
                    }
                }
            }
            return lastPresentationUs / 1_000L
        } finally {
            @Suppress("TooGenericExceptionCaught")
            try {
                if (muxerStarted) muxer.stop()
                muxer.release()
            } catch (error: Exception) {
                // A muxer that will not stop has already written what it wrote;
                // the output-size check below decides whether it is usable.
                Timber.w(error, "Muxer would not close cleanly")
            }
            decoder.stop(); decoder.release()
            encoder.stop(); encoder.release()
        }
    }

    private fun feedEncoder(encoder: MediaCodec, pcm: ByteBuffer, info: MediaCodec.BufferInfo) {
        var remaining = info.size
        while (remaining > 0) {
            val index = encoder.dequeueInputBuffer(TIMEOUT_US)
            if (index < 0) return
            val target = encoder.getInputBuffer(index) ?: return
            val chunk = minOf(remaining, target.capacity())
            val slice = pcm.duplicate().apply {
                position(info.offset + (info.size - remaining))
                limit(position() + chunk)
            }
            target.clear()
            target.put(slice)
            encoder.queueInputBuffer(index, 0, chunk, info.presentationTimeUs, 0)
            remaining -= chunk
        }
    }

    private fun signalEncoderEnd(encoder: MediaCodec) {
        val index = encoder.dequeueInputBuffer(TIMEOUT_US)
        if (index >= 0) {
            encoder.queueInputBuffer(index, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
        }
    }

    private fun encoderMime(encoder: MediaCodec): String =
        encoder.codecInfo.supportedTypes.firstOrNull { it.startsWith("audio/") }
            ?: MediaFormat.MIMETYPE_AUDIO_AAC

    private fun failed(failure: TranscodeFailure, detail: String) =
        AudioTranscoder.Result.Failed(failure, detail)

    private companion object {
        const val TIMEOUT_US = 10_000L
        const val MAX_INPUT_SIZE = 16 * 1024

        /** Below this the recorder wrote a container header and no audio. */
        const val MIN_INPUT_BYTES = 2_048L
        const val MIN_OUTPUT_BYTES = 512L
    }
}

private fun AudioFormat.Target.mimeType(): String = when (this) {
    AudioFormat.Target.OPUS_OGG -> MediaFormat.MIMETYPE_AUDIO_OPUS
    AudioFormat.Target.AAC_MP4 -> MediaFormat.MIMETYPE_AUDIO_AAC
}
