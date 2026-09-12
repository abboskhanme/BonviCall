package uz.bonvi.call.live

import com.google.common.truth.Truth.assertThat
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import org.junit.BeforeClass
import org.junit.Test
import uz.bonvi.call.service.RealtimeChannel
import java.util.concurrent.CountDownLatch
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * The realtime socket, against a live server (SPEC §4.6, UC-16, D-03).
 *
 * ═══ Why this is worth a live test ═════════════════════════════════════════
 * The socket's frames are the one wire surface **not** in
 * `contract/openapi-device-v1.json` — OpenAPI does not describe WebSocket
 * frames — so nothing generates them and nothing else checks them. The server
 * validates every frame against an allow-list and **closes the socket on one it
 * does not recognise** (1003). A misspelt field would therefore not fail
 * loudly; it would look like a phone whose socket keeps dropping, which is
 * indistinguishable from bad reception.
 *
 * So this sends the app's own frame classes, serialised by the app's own
 * Moshi, and watches what a real server does with them.
 */
class LiveRealtimeSocketTest {

    companion object {
        @BeforeClass @JvmStatic fun serverUp() = LiveHarness.requireServer()

        private const val TIMEOUT_SECONDS = 15L
    }

    private val moshi = LiveHarness.moshi()

    /** Frames the server sent, and why the socket closed if it did. */
    private class Recorder : WebSocketListener() {
        val opened = CountDownLatch(1)
        val frames = LinkedBlockingQueue<String>()
        val closed = CountDownLatch(1)

        @Volatile var closeCode: Int? = null
        @Volatile var failure: Throwable? = null

        override fun onOpen(webSocket: WebSocket, response: Response) = opened.countDown()
        override fun onMessage(webSocket: WebSocket, text: String) { frames.put(text) }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            closeCode = code
            closed.countDown()
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            failure = t
            closeCode = response?.code
            closed.countDown()
        }

        fun nextFrame(seconds: Long = TIMEOUT_SECONDS): JSONObject? =
            frames.poll(seconds, TimeUnit.SECONDS)?.let(::JSONObject)
    }

    private fun open(session: FakeSession, recorder: Recorder): WebSocket {
        val client = LiveHarness.client(session).newBuilder()
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .build()
        val url = session.baseUrl.trimEnd('/') + "/api/device/v1/ws"
        return client.newWebSocket(Request.Builder().url(url).build(), recorder)
    }

    /**
     * WALL 1: the handshake authenticates the same way every REST call does —
     * the bearer token and `X-Installation-Id`, both added by the app's own
     * interceptors. No token in the query string (N26).
     */
    @Test
    fun `an enrolled phone can hold a socket open`() {
        val session = LiveAdmin.requireVerifiedSession()
        val recorder = Recorder()
        val socket = open(session, recorder)

        assertThat(recorder.opened.await(TIMEOUT_SECONDS, TimeUnit.SECONDS)).isTrue()
        assertThat(recorder.failure).isNull()
        socket.close(1000, null)
    }

    /**
     * WALL 2: **the app's own outbound frames are accepted.**
     *
     * A frame outside the server's allow-list closes the socket with 1003, so
     * "the socket is still open a second later" is the assertion that matters
     * here — not a status code, because there is none.
     */
    @Test
    fun `the presence and pong frames the app sends do not close the socket`() {
        val session = LiveAdmin.requireVerifiedSession()
        val recorder = Recorder()
        val socket = open(session, recorder)
        assertThat(recorder.opened.await(TIMEOUT_SECONDS, TimeUnit.SECONDS)).isTrue()

        val presence = moshi.adapter(RealtimeChannel.PresenceFrame::class.java).toJson(
            RealtimeChannel.PresenceFrame(
                state = "online",
                queueRecords = 3,
                at = java.time.OffsetDateTime.now().toString(),
            ),
        )
        val pong = moshi.adapter(RealtimeChannel.PongFrame::class.java).toJson(
            RealtimeChannel.PongFrame(at = java.time.OffsetDateTime.now().toString()),
        )
        assertThat(socket.send(presence)).isTrue()
        assertThat(socket.send(pong)).isTrue()

        // 1003 is "I do not understand what you sent". Nothing should arrive.
        assertThat(recorder.closed.await(2, TimeUnit.SECONDS)).isFalse()
        assertThat(recorder.closeCode).isNull()
        socket.close(1000, null)
    }

    /**
     * WALL 3: **the reason the socket exists at all.**
     *
     * A dial expires after two minutes, so the fifteen-minute heartbeat can
     * only ever collect one too late to ring. This is the path that makes
     * click-to-call a feature: panel button → frame on an open socket → ack on
     * the same socket → `acknowledged` in the panel.
     */
    @Test
    fun `a command issued in the panel arrives on the socket and is acknowledged there`() {
        val session = LiveAdmin.requireVerifiedSession()
        val recorder = Recorder()
        val socket = open(session, recorder)
        assertThat(recorder.opened.await(TIMEOUT_SECONDS, TimeUnit.SECONDS)).isTrue()

        val commandId = requireNotNull(
            LiveAdmin.issueCommand(session.installationId!!, "ping"),
        ) { "The panel would not issue a command" }

        // The server also pings every 30 s; take frames until the command
        // appears rather than assuming it is the first thing said.
        var command: JSONObject? = null
        while (command == null) {
            val frame = recorder.nextFrame() ?: break
            if (frame.optString("type") == "command") command = frame
        }

        assertThat(command).isNotNull()
        assertThat(command!!.getString("command_id")).isEqualTo(commandId)
        assertThat(command.getString("kind")).isEqualTo("ping")

        val ack = moshi.adapter(RealtimeChannel.AckFrame::class.java).toJson(
            RealtimeChannel.AckFrame(
                commandId = commandId,
                status = "acknowledged",
                failureReason = null,
                at = java.time.OffsetDateTime.now().toString(),
            ),
        )
        assertThat(socket.send(ack)).isTrue()

        // The panel's answer is the only one an admin ever sees. `sent` here
        // would mean the phone never answered.
        var status: String? = null
        repeat(TIMEOUT_ROUNDS) {
            status = LiveAdmin.commandStatus(commandId)
            if (status == "acknowledged") return@repeat
            Thread.sleep(POLL_MS)
        }
        assertThat(status).isEqualTo("acknowledged")
        socket.close(1000, null)
    }

    private val TIMEOUT_ROUNDS = 20
    private val POLL_MS = 200L
}
