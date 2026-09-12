package uz.bonvi.call.service

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import timber.log.Timber
import uz.bonvi.call.core.Clock
import uz.bonvi.call.data.repository.CallQueueRepository
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.domain.CommandKind
import uz.bonvi.call.domain.DeviceAuthState
import java.time.OffsetDateTime
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The device's realtime socket (SPEC §4.6, UC-16, D-03).
 *
 * ═══ Why a socket at all ═══════════════════════════════════════════════════
 * One number: **UC-16 wants a dial ringing within five seconds**, and a command
 * expires after two minutes. The heartbeat's fifteen-minute pass can collect a
 * command, but every dial it finds is already stale — so without this,
 * click-to-call is a feature that acknowledges failures rather than one that
 * rings a phone. Held open by the foreground service, which is the process that
 * already has to survive.
 *
 * ═══ What it carries ═══════════════════════════════════════════════════════
 * The same command lifecycle as REST, and deliberately so: [CommandRunner]
 * executes and this only moves bytes, so a command delivered here is
 * indistinguishable in the panel from one collected after a wake-up. The
 * acknowledgement goes back on the socket it arrived on.
 *
 * The server pings every 30 s and closes a socket that has not answered within
 * 15; any frame counts as an answer. A `logout` frame is the server letting the
 * socket go — `replaced` is routine (the app reconnected before the old socket
 * was noticed dead), `revoked` is UC-08 and stops capture on this handset.
 *
 * Reconnection backs off to a minute. A phone with no network, or a server with
 * no socket endpoint, must not spend its battery discovering that every second.
 */
@Singleton
class RealtimeChannel @Inject constructor(
    client: OkHttpClient,
    private val moshi: Moshi,
    private val session: SessionStore,
    private val commands: CommandRunner,
    private val revocation: Revocation,
    private val queue: CallQueueRepository,
) {

    /**
     * The shared client's read timeout would close an idle socket after thirty
     * seconds of quiet, which on this channel is the normal state. The ping
     * interval is OkHttp's own keep-alive and is unrelated to the server's JSON
     * ping — both are wanted: one keeps NAT open, the other proves the app is
     * still listening.
     */
    private val socketClient: OkHttpClient = client.newBuilder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .pingInterval(PING_SECONDS, TimeUnit.SECONDS)
        .build()

    private var loop: Job? = null

    @Volatile
    private var socket: WebSocket? = null

    /** True while a socket is open. The heartbeat reports presence separately —
     *  a live socket is "reachable", never "healthy" (SPEC §4.6). */
    @Volatile
    var connected: Boolean = false
        private set

    /**
     * Hold a socket open for as long as [scope] lives.
     *
     * Idempotent: the capture service can be started again while it is already
     * running, and a second loop would mean two sockets, of which the server
     * closes one — with a `replaced` frame that would look like an error.
     */
    fun connect(scope: CoroutineScope) {
        if (loop?.isActive == true) return
        loop = scope.launch {
            var backoffMs = MIN_BACKOFF_MS
            while (isActive) {
                if (!eligible()) {
                    // Not enrolled yet, or revoked. Neither is an error and
                    // neither is worth a socket.
                    delay(IDLE_POLL_MS)
                    continue
                }
                val closed = CompletableDeferred<Boolean>()
                val opened = open(scope, closed)
                if (opened == null) {
                    backoffMs = nextBackoff(backoffMs)
                    delay(backoffMs)
                    continue
                }

                // Suspends here for as long as the socket lives — which on a
                // healthy phone is hours.
                val clean = closed.await()
                opened.cancel()
                socket = null
                connected = false
                backoffMs = if (clean) MIN_BACKOFF_MS else nextBackoff(backoffMs)
                delay(backoffMs)
            }
        }
    }

    /** Called from the service's `onDestroy`. */
    fun disconnect() {
        loop?.cancel()
        loop = null
        socket?.close(NORMAL_CLOSURE, null)
        socket = null
        connected = false
    }

    /** An installation that is bound, verified and not revoked. */
    private fun eligible(): Boolean =
        session.snapshot.installationId != null &&
            session.snapshot.accessToken != null &&
            session.authStateSnapshot().canCapture

    private fun open(scope: CoroutineScope, closed: CompletableDeferred<Boolean>): WebSocket? {
        val url = session.snapshot.baseUrl.trimEnd('/') + WS_PATH
        val request = @Suppress("TooGenericExceptionCaught") try {
            Request.Builder().url(url).build()
        } catch (error: Exception) {
            // A base URL that is not a URL. The diagnostics screen is where
            // that gets fixed; retrying every minute in the meantime is free.
            Timber.w("Realtime: %s is not an address", url)
            return null
        }

        return socketClient.newWebSocket(request, listener(scope, closed)).also { socket = it }
    }

    private fun listener(scope: CoroutineScope, closed: CompletableDeferred<Boolean>) =
        object : WebSocketListener() {

            override fun onOpen(webSocket: WebSocket, response: Response) {
                connected = true
                Timber.i("Realtime: connected")
                // Presence first: the panel's "reachable" answer and the queue
                // depth an admin asks about during an assisted install.
                scope.launch {
                    webSocket.send(
                        presenceAdapter.toJson(
                            PresenceFrame(
                                state = "online",
                                queueRecords = queue.depth().pending,
                                at = Clock.toWire(Clock.epochMillis()),
                            ),
                        ),
                    )
                }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val frame = @Suppress("TooGenericExceptionCaught") try {
                    serverFrameAdapter.fromJson(text)
                } catch (error: Exception) {
                    // A frame this build does not understand is not a reason to
                    // drop a working socket; the next dial would then have to
                    // go the slow way round.
                    Timber.w("Realtime: unreadable frame")
                    null
                } ?: return

                when (frame.type) {
                    "ping" -> webSocket.send(
                        pongAdapter.toJson(PongFrame(at = Clock.toWire(Clock.epochMillis()))),
                    )

                    "command" -> scope.launch { runCommand(webSocket, frame) }

                    "logout" -> scope.launch {
                        Timber.w("Realtime: server let the socket go (%s)", frame.reason)
                        when (frame.reason) {
                            // UC-08: capture stops and the audio on this
                            // handset goes.
                            "revoked" -> revocation.revokeLocally()
                            // N34. Ingest continues — the queue is never held
                            // back by the client — but the home screen now has
                            // a reason to show, and the heartbeat's update path
                            // is what resolves it.
                            "version_unsupported" ->
                                session.saveAuthState(DeviceAuthState.UPDATE_REQUIRED.wire)
                        }
                        // `replaced` is routine: the app reconnected before the
                        // old socket was noticed dead, so coming straight back
                        // is correct. The other two are the server saying stop,
                        // and reconnecting every five seconds into a refusal is
                        // how an app burns a battery arguing.
                        closed.complete(frame.reason == "replaced")
                    }

                    else -> Timber.w("Realtime: ignoring a %s frame", frame.type)
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                // Every reconnect lands here: no network, a server without the
                // endpoint, a token the handshake refused. Info rather than
                // error — on a phone in a lift this is the normal case.
                Timber.i("Realtime: disconnected (%s)", t.javaClass.simpleName)
                closed.complete(false)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                closed.complete(true)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                closed.complete(true)
            }
        }

    private suspend fun runCommand(webSocket: WebSocket, frame: ServerFrame) {
        val commandId = frame.commandId?.let(::parseUuid) ?: return
        // A command with no readable timestamp is treated as issued now: the
        // server has already refused to hand out expired commands, and
        // discarding a dial because its clock string was unparseable would fail
        // a call for a reason nobody could see.
        val issuedAt = frame.issuedAt?.let(::parseInstant) ?: Clock.epochMillis()

        val ack = commands.execute(
            CommandRunner.Incoming(
                commandId = commandId,
                kind = CommandKind.fromWire(frame.kind),
                number = frame.number,
                issuedAtEpochMillis = issuedAt,
            ),
        )

        // Answered on the socket it arrived on. UC-16's five-second bar is
        // measured from this frame, so a round trip through REST here would be
        // measuring the wrong thing.
        val sent = webSocket.send(
            ackAdapter.toJson(
                AckFrame(
                    commandId = commandId.toString(),
                    status = ack.status,
                    failureReason = ack.failure?.wire,
                    at = Clock.toWire(Clock.epochMillis()),
                ),
            ),
        )
        // The socket died between the command and the answer. REST carries the
        // same ack, and a command with no outcome is indistinguishable from one
        // that never arrived.
        if (!sent) commands.acknowledge(commandId, ack)
    }

    private fun parseInstant(value: String): Long? =
        @Suppress("TooGenericExceptionCaught") try {
            OffsetDateTime.parse(value).toInstant().toEpochMilli()
        } catch (error: Exception) {
            null
        }

    private fun parseUuid(value: String): UUID? =
        @Suppress("TooGenericExceptionCaught") try {
            UUID.fromString(value)
        } catch (error: Exception) {
            Timber.w("Realtime: a command id that is not a UUID")
            null
        }

    private fun nextBackoff(current: Long): Long =
        (current * 2).coerceAtMost(MAX_BACKOFF_MS)

    /**
     * Everything the server may say, as named fields.
     *
     * One inbound type rather than five: the discriminator is `type`, the
     * fields are optional per kind, and an unknown `type` is ignored rather
     * than fatal — a newer server must not be able to knock this app's socket
     * over. It is inbound only, so §8.5's rule about free-form maps (which is
     * about data LEAVING the phone) is not in play, and there is no map here
     * anyway.
     */
    @JsonClass(generateAdapter = true)
    data class ServerFrame(
        val type: String,
        @Json(name = "command_id") val commandId: String? = null,
        val kind: String? = null,
        val number: String? = null,
        @Json(name = "issued_at") val issuedAt: String? = null,
        @Json(name = "expires_at") val expiresAt: String? = null,
        val reason: String? = null,
        val at: String? = null,
    )

    /** app → server: still here, and this much is queued. */
    @JsonClass(generateAdapter = true)
    data class PresenceFrame(
        val type: String = "presence",
        val state: String,
        @Json(name = "queue_records") val queueRecords: Int?,
        val at: String,
    )

    /** app → server, answering the 30-second ping. */
    @JsonClass(generateAdapter = true)
    data class PongFrame(val type: String = "pong", val at: String)

    /** app → server: the outcome of a command, and implicitly its latency. */
    @JsonClass(generateAdapter = true)
    data class AckFrame(
        val type: String = "ack",
        @Json(name = "command_id") val commandId: String,
        val status: String,
        @Json(name = "failure_reason") val failureReason: String?,
        val at: String,
    )

    private val serverFrameAdapter by lazy { moshi.adapter(ServerFrame::class.java) }
    private val presenceAdapter by lazy { moshi.adapter(PresenceFrame::class.java) }
    private val pongAdapter by lazy { moshi.adapter(PongFrame::class.java) }
    private val ackAdapter by lazy { moshi.adapter(AckFrame::class.java) }

    private companion object {
        /** Path versioning, never a header (CONVENTIONS.md §4.1). */
        const val WS_PATH = "/api/device/v1/ws"

        const val PING_SECONDS = 30L
        const val NORMAL_CLOSURE = 1000

        const val MIN_BACKOFF_MS = 5_000L
        const val MAX_BACKOFF_MS = 60_000L

        /** How often "not enrolled yet" is re-asked. Enrolment finishing
         *  starts the service anyway, so this is a floor, not the mechanism. */
        const val IDLE_POLL_MS = 60_000L
    }
}
