package uz.bonvi.call.capture.transcode

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.runInterruptible
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.core.Capabilities
import uz.bonvi.call.core.Clock
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
 * ═══ It never loses a call, and it never blocks the queue ══════════════════
 * Every failure returns [AudioTranscoder.Result.Failed] with a reason from the
 * closed enum. The caller ships the call regardless (UC-14). Nothing here
 * throws into the capture path, and the SOURCE file is never modified or
 * deleted — on the harvest route it belongs to the employee
 * (CONVENTIONS.md §8.3).
 *
 * ⚠️ **It also cannot hang.** The first version could, and did, on the first
 * real handset (2026-09-12): the end-of-stream marker was handed to the encoder
 * with a single `dequeueInputBuffer` that returned -1 when the encoder's input
 * queue happened to be full, so the marker was DROPPED, the encoder never
 * signalled its own end, and `while (!sawEncoderEnd)` spun for ever. Five
 * recordings sat in `audio_jobs` with `attempts = 0`; every upload pass hung on
 * the first one until WorkManager cancelled it, the cancellation was never
 * observed, and the codecs it held leaked. Three rules now hold: a buffer that
 * cannot be queued is RETRIED after draining the encoder, never dropped; a
 * loop that makes no progress for [STALL_TIMEOUT_MS] fails the transcode
 * instead of the queue; and a cancelled worker interrupts the loop, which
 * releases the codecs through `finally`.
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
            // `runInterruptible`: a cancelled upload pass interrupts the thread
            // this loop blocks on, so `pump` sees it at its next progress check
            // and unwinds through `finally`. Without it the loop outlived the
            // worker that started it, holding two codecs and a muxer each time.
            val startedAt = Clock.elapsedRealtimeMillis()
            val durationMs = runInterruptible { run(source, destination, target) }
            val elapsedMs = Clock.elapsedRealtimeMillis() - startedAt
            when {
                durationMs == null -> failed(TranscodeFailure.NO_ENCODER, "no encoder for ${target.codec}")
                destination.length() < MIN_OUTPUT_BYTES -> {
                    destination.delete()
                    failed(TranscodeFailure.EMPTY_OUTPUT, "output was ${destination.length()} bytes")
                }
                else -> {
                    // The one number that says whether this loop is fast: a
                    // call's worth of audio must take a few seconds, not a
                    // call's worth of time. Durations only — never the source
                    // name, which on the OEM route is the customer's number.
                    Timber.i("Transcoded %d ms of audio in %d ms", durationMs, elapsedMs)
                    AudioTranscoder.Result.Transcoded(
                        file = destination,
                        target = target,
                        durationMs = durationMs,
                        bytes = destination.length(),
                    )
                }
            }
        } catch (cancelled: CancellationException) {
            // The worker was cancelled, not the transcode failed. The partial
            // output is worthless; the job row stays and the next pass redoes
            // it from the source, which is untouched.
            destination.delete()
            throw cancelled
        } catch (error: Exception) {
            // Broad, and the specific failures are MediaCodec's:
            // IllegalStateException from an encoder that will not configure or
            // a loop that stalled, IOException from a full filesystem, and
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
     * Everything the encoder side of the loop has to remember between calls.
     *
     * One object rather than five locals so [drainEncoder] can be called from
     * three places — the main loop, a full encoder input queue, and the
     * end-of-stream hand-off — and every one of them advances the same muxer
     * and the same progress clock.
     */
    private class EncoderSide(private val muxer: MediaMuxer) {
        var track = -1
        var started = false
        var lastPresentationUs = 0L
        var sawEnd = false
        var lastProgressAtMillis = Clock.elapsedRealtimeMillis()

        fun touch() {
            lastProgressAtMillis = Clock.elapsedRealtimeMillis()
        }

        fun startMuxer(format: MediaFormat) {
            track = muxer.addTrack(format)
            muxer.start()
            started = true
            touch()
        }

        fun write(encoded: ByteBuffer, info: MediaCodec.BufferInfo) {
            muxer.writeSampleData(track, encoded, info)
            lastPresentationUs = info.presentationTimeUs
            touch()
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

        val side = EncoderSide(muxer)
        var sawInputEnd = false
        var sawDecoderEnd = false
        val info = MediaCodec.BufferInfo()
        // Built from the decoder's own output format the first time a buffer
        // comes out: an OEM recorder's file is whatever rate and channel count
        // the handset chose, and the encoder was told 16 kHz mono.
        var resampler: PcmResampler? = null

        // ═══ Why this loop never waits while there is work ═══════════════════
        // The first version stepped one buffer per pass and blocked up to
        // 10 ms on EACH of three queues when that queue had nothing — up to
        // 30 ms of waiting per decoded frame that carries 24 ms of audio. The
        // result was a transcode that ran at the speed the call was spoken:
        // a 35 s call took 43 s, a 76 s call 81 s (measured 2026-09-12), and
        // that one number was the whole gap between us and Moi Zvonki's
        // "seconds after hang-up". Now every queue is emptied without waiting,
        // and the loop blocks — once, for 10 ms, on the encoder's output —
        // only in a pass where nothing at all moved.
        try {
            while (!side.sawEnd) {
                checkAlive(side)
                var moved = false

                // Feed the decoder everything it will take right now.
                while (!sawInputEnd) {
                    val index = decoder.dequeueInputBuffer(NO_WAIT_US)
                    if (index < 0) break
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
                    side.touch()
                    moved = true
                }

                // Take every decoded buffer that is ready.
                while (!sawDecoderEnd) {
                    val index = decoder.dequeueOutputBuffer(info, NO_WAIT_US)
                    if (index == MediaCodec.INFO_TRY_AGAIN_LATER) break
                    if (index < 0) {
                        // Output format or buffers changed: progress, nothing to read.
                        moved = true
                        continue
                    }
                    val pcm = decoder.getOutputBuffer(index)
                    if (info.size > 0 && pcm != null) {
                        val converter = resampler
                            ?: PcmResampler.forDecoder(decoder.getOutputFormat(index)).also { resampler = it }
                        val converted = converter.convert(pcm, info.offset, info.size)
                        if (converted.remaining() > 0) {
                            feedEncoder(encoder, converted, info.presentationTimeUs, side)
                        }
                    }
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) {
                        signalEncoderEnd(encoder, side)
                        sawDecoderEnd = true
                    }
                    decoder.releaseOutputBuffer(index, false)
                    side.touch()
                    moved = true
                }

                // Take everything the encoder has ready, without waiting...
                if (drainEncoder(encoder, side, firstWaitUs = NO_WAIT_US)) moved = true

                // ...and wait only in a pass where nothing at all moved: the
                // codecs are busy, and the encoder's output is what comes next.
                if (!moved && !side.sawEnd) drainEncoder(encoder, side, firstWaitUs = TIMEOUT_US)
            }
            return side.lastPresentationUs / 1_000L
        } finally {
            @Suppress("TooGenericExceptionCaught")
            try {
                if (side.started) muxer.stop()
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

    /**
     * Take EVERYTHING the encoder has ready, not one buffer.
     *
     * One decoded AAC frame (1 024 samples) becomes three Opus frames, so a
     * loop that drained one output per input let the encoder's output queue
     * fill, which stopped it consuming input, which is how the input queue was
     * full at the moment the end-of-stream marker needed a slot.
     */
    /**
     * @param firstWaitUs how long the FIRST dequeue may block; every later one
     *        in the same drain is immediate. Zero from the main loop while
     *        there is work elsewhere; [TIMEOUT_US] when the loop is idle or a
     *        full input queue is waiting on this output.
     * @return whether anything moved.
     */
    private fun drainEncoder(encoder: MediaCodec, side: EncoderSide, firstWaitUs: Long): Boolean {
        val info = MediaCodec.BufferInfo()
        var waitUs = firstWaitUs
        var moved = false
        while (!side.sawEnd) {
            val index = encoder.dequeueOutputBuffer(info, waitUs)
            waitUs = NO_WAIT_US
            when {
                index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                    side.startMuxer(encoder.outputFormat)
                    moved = true
                }

                // Deprecated and still returned by some codecs. Progress, not
                // a reason to stop draining.
                @Suppress("DEPRECATION")
                index == MediaCodec.INFO_OUTPUT_BUFFERS_CHANGED -> moved = true

                index >= 0 -> {
                    val encoded = encoder.getOutputBuffer(index)
                    val isConfig = info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0
                    if (encoded != null && info.size > 0 && side.started && !isConfig) {
                        side.write(encoded, info)
                    }
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) {
                        side.sawEnd = true
                    }
                    encoder.releaseOutputBuffer(index, false)
                    side.touch()
                    moved = true
                }

                // INFO_TRY_AGAIN_LATER: nothing ready right now.
                else -> return moved
            }
        }
        return moved
    }

    /**
     * Queue a decoded buffer into the encoder — ALL of it.
     *
     * A full input queue is not a reason to drop the remainder (the first
     * version did, silently, which shortened recordings); it is a reason to
     * drain the encoder's output, which frees an input slot, and try again.
     */
    private fun feedEncoder(
        encoder: MediaCodec,
        pcm: ByteBuffer,
        presentationTimeUs: Long,
        side: EncoderSide,
    ) {
        val start = pcm.position()
        val size = pcm.remaining()
        var remaining = size
        while (remaining > 0) {
            val index = encoder.dequeueInputBuffer(TIMEOUT_US)
            if (index < 0) {
                drainEncoder(encoder, side, firstWaitUs = TIMEOUT_US)
                checkAlive(side)
                continue
            }
            val target = encoder.getInputBuffer(index) ?: return
            // Whole samples only: a 16-bit sample split across two buffers is
            // a click at best and a desynchronised stream at worst.
            val chunk = minOf(remaining, target.capacity()) and 1.inv()
            val slice = pcm.duplicate().apply {
                position(start + (size - remaining))
                limit(position() + chunk)
            }
            target.clear()
            target.put(slice)
            encoder.queueInputBuffer(index, 0, chunk, presentationTimeUs, 0)
            remaining -= chunk
            side.touch()
        }
    }

    /**
     * Hand the encoder its end-of-stream marker, and do not take -1 for an
     * answer. This single call, made once and not retried, is the hang that
     * blocked the whole upload queue.
     */
    private fun signalEncoderEnd(encoder: MediaCodec, side: EncoderSide) {
        while (true) {
            val index = encoder.dequeueInputBuffer(TIMEOUT_US)
            if (index >= 0) {
                encoder.queueInputBuffer(index, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                side.touch()
                return
            }
            drainEncoder(encoder, side, firstWaitUs = TIMEOUT_US)
            checkAlive(side)
        }
    }

    /**
     * The two ways out of a loop that is not going to finish.
     *
     * Interrupted: the upload pass was cancelled (`runInterruptible`), and
     * unwinding here is what releases the codecs. Stalled: no buffer has moved
     * in [STALL_TIMEOUT_MS], which a working codec pair never does — the
     * transcode fails, the call ships without audio, and the NEXT job runs.
     */
    private fun checkAlive(side: EncoderSide) {
        if (Thread.currentThread().isInterrupted) {
            throw InterruptedException("transcode cancelled")
        }
        val idleMillis = Clock.elapsedRealtimeMillis() - side.lastProgressAtMillis
        check(idleMillis < STALL_TIMEOUT_MS) { "transcode made no progress for $idleMillis ms" }
    }

    private fun encoderMime(encoder: MediaCodec): String =
        encoder.codecInfo.supportedTypes.firstOrNull { it.startsWith("audio/") }
            ?: MediaFormat.MIMETYPE_AUDIO_AAC

    private fun failed(failure: TranscodeFailure, detail: String) =
        AudioTranscoder.Result.Failed(failure, detail)

    private companion object {
        const val TIMEOUT_US = 10_000L
        const val NO_WAIT_US = 0L
        const val MAX_INPUT_SIZE = 16 * 1024

        /** Below this the recorder wrote a container header and no audio. */
        const val MIN_INPUT_BYTES = 2_048L
        const val MIN_OUTPUT_BYTES = 512L

        /**
         * How long the loop may go without a single buffer moving before the
         * transcode is declared dead. A healthy codec pair answers in
         * milliseconds; thirty seconds is two orders of magnitude of margin on
         * the slowest handset in the fleet, and it is the ceiling on how long
         * one broken recording can hold every other recording behind it.
         */
        const val STALL_TIMEOUT_MS = 30_000L
    }
}

private fun AudioFormat.Target.mimeType(): String = when (this) {
    AudioFormat.Target.OPUS_OGG -> MediaFormat.MIMETYPE_AUDIO_OPUS
    AudioFormat.Target.AAC_MP4 -> MediaFormat.MIMETYPE_AUDIO_AAC
}

/**
 * Downmixes and resamples 16-bit PCM to the encoder's mono 16 kHz.
 *
 * ═══ Why it exists ═════════════════════════════════════════════════════════
 * The first OEM-harvested recording to reach the server (2026-09-12, a 36 s
 * call) played for 1 min 48 s: the handset's recorder writes 48 kHz MP3 and
 * the pump handed those samples to an encoder configured for 16 kHz, which
 * took every three samples for one — three times the length, a third of the
 * pitch. The app's own recordings never showed it because
 * `MediaRecorderAudioRecorder` records at exactly the encoder's rate. The
 * comment at the top of this file promised "decode → resample → encode"; this
 * is the middle word.
 *
 * Linear interpolation, in software, one pass. Speech at 16 kHz is the
 * product's own budget (N17) and a linear resampler's roll-off is inaudible
 * against a 24 kbps codec; anything cleverer would be a dependency for a
 * problem the codec already hides. Channels are averaged. The last frame of
 * every buffer is carried into the next, so a recording is one continuous
 * stream rather than a series of clicks at buffer edges.
 */
internal class PcmResampler(
    private val sourceRateHz: Int,
    private val sourceChannels: Int,
    private val targetRateHz: Int = AudioFormat.SAMPLE_RATE_HZ,
) {
    init {
        require(sourceRateHz > 0 && sourceChannels > 0 && targetRateHz > 0)
    }

    /** Read position, in source frames, within the virtual stream
     *  `[carried frame] + this buffer's frames`. */
    private var position = 0.0
    private val step = sourceRateHz.toDouble() / targetRateHz
    private var carried = 0
    private var hasCarried = false

    val passThrough: Boolean = sourceRateHz == targetRateHz && sourceChannels == 1

    /**
     * @return a buffer positioned at its first converted sample with its limit
     *         at the last — the input itself when nothing needs converting.
     */
    fun convert(pcm: ByteBuffer, offset: Int, size: Int): ByteBuffer {
        if (passThrough) {
            return pcm.duplicate().apply { position(offset); limit(offset + size) }
        }
        val input = pcm.duplicate().order(java.nio.ByteOrder.nativeOrder())
        val frames = size / (2 * sourceChannels)

        // The virtual stream for this call: the carried frame, then this
        // buffer's frames, downmixed to mono.
        val lead = if (hasCarried) 1 else 0
        val src = IntArray(lead + frames)
        if (hasCarried) src[0] = carried
        for (frame in 0 until frames) {
            var sum = 0
            for (channel in 0 until sourceChannels) {
                sum += input.getShort(offset + (frame * sourceChannels + channel) * 2).toInt()
            }
            src[lead + frame] = sum / sourceChannels
        }

        val out = ByteBuffer.allocate(((src.size / step).toInt() + 2) * 2)
            .order(java.nio.ByteOrder.nativeOrder())
        var written = 0
        while (true) {
            val base = position.toInt()
            if (base + 1 > src.size - 1) break
            val fraction = position - base
            val left = src[base]
            val right = src[base + 1]
            val sample = (left + (right - left) * fraction).toInt().coerceIn(-32768, 32767)
            out.putShort(written * 2, sample.toShort())
            written++
            position += step
        }
        if (src.isNotEmpty()) {
            // The last frame becomes index 0 of the next call's stream.
            position -= (src.size - 1)
            carried = src[src.size - 1]
            hasCarried = true
        }
        out.limit(written * 2)
        out.position(0)
        return out
    }

    companion object {
        fun forDecoder(format: MediaFormat): PcmResampler = PcmResampler(
            sourceRateHz = format.getInteger(MediaFormat.KEY_SAMPLE_RATE),
            sourceChannels = format.getInteger(MediaFormat.KEY_CHANNEL_COUNT),
        )
    }
}
