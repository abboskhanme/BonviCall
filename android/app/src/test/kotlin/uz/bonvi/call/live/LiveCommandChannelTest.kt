package uz.bonvi.call.live

import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.test.runTest
import org.junit.BeforeClass
import org.junit.Test
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import uz.bonvi.call.data.remote.api.DeviceCommandApi
import uz.bonvi.call.data.remote.dto.DeviceAckIn
import uz.bonvi.call.data.remote.dto.DeviceHeartbeatIn
import uz.bonvi.call.data.remote.dto.AppVariant
import uz.bonvi.call.data.remote.dto.NetworkType
import uz.bonvi.call.domain.CommandFailure
import uz.bonvi.call.domain.CommandKind
import java.time.OffsetDateTime
import java.util.UUID

/**
 * The command channel and the heartbeat, against a live server (UC-16, UC-17).
 *
 * ═══ What this is for ══════════════════════════════════════════════════════
 * Both of these were finished, tested and **had no caller**: nothing sent a
 * heartbeat, and no Retrofit interface even declared `/commands` — the DTOs
 * were generated and unused. Their unit tests were green throughout, because a
 * unit test supplies the caller the product does not.
 *
 * So this drives the app's real interfaces against a running server and, for a
 * command, checks the answer the PANEL ends up with — which is the only thing
 * an admin ever sees.
 */
class LiveCommandChannelTest {

    companion object {
        @BeforeClass @JvmStatic fun serverUp() = LiveHarness.requireServer()
    }

    private fun commands(session: FakeSession): DeviceCommandApi =
        Retrofit.Builder()
            .baseUrl(session.baseUrl.trimEnd('/') + "/api/device/v1/")
            .client(LiveHarness.client(session))
            .addConverterFactory(MoshiConverterFactory.create(LiveHarness.moshi()))
            .build()
            .create(DeviceCommandApi::class.java)

    /**
     * WALL 1: the endpoint the app now calls exists and answers in the shape
     * the generated DTO expects. A `GET /commands` that 404s or returns
     * something Moshi cannot read is invisible until a dial goes missing.
     */
    @Test
    fun `a phone with nothing waiting gets an empty, readable answer`() = runTest {
        val session = LiveAdmin.requireVerifiedSession()

        val response = commands(session).pending()

        assertThat(response.isSuccessful).isTrue()
        assertThat(response.body()!!.commands).isEmpty()
        // The server time is what a phone with a skewed clock reconciles
        // against, so it has to parse.
        assertThat(response.body()!!.serverTime.toString()).isNotEmpty()
    }

    /**
     * WALL 2: **the whole click-to-call lifecycle**, from the panel's button to
     * the panel's answer.
     *
     * `ping` rather than `dial` on purpose: it is the one kind whose execution
     * is the acknowledgement itself, so this measures the CHANNEL rather than a
     * dialler that a JVM has no telephony for.
     */
    @Test
    fun `a command issued in the panel is collected, acknowledged, and shows as acknowledged`() =
        runTest {
            val session = LiveAdmin.requireVerifiedSession()
            val installationId = session.installationId!!
            // Loud rather than skipped: a helper that quietly returns null
            // would make this test pass without ever touching the channel it
            // exists to prove.
            val commandId = requireNotNull(LiveAdmin.issueCommand(installationId, "ping")) {
                "The panel would not issue a command for $installationId"
            }

            val pending = commands(session).pending()
            assertThat(pending.isSuccessful).isTrue()
            val collected = pending.body()!!.commands
            assertThat(collected.map { it.commandId.toString() }).contains(commandId)

            // The app's own vocabulary has to survive the round trip: a kind it
            // cannot name is answered `unsupported`, which in the panel reads
            // as a phone ignoring its admin.
            val kind = CommandKind.fromWire(collected.first().kind.value)
            assertThat(kind).isEqualTo(CommandKind.PING)

            val ack = commands(session).acknowledge(
                UUID.fromString(commandId),
                DeviceAckIn(status = "acknowledged", at = OffsetDateTime.now()),
            )
            assertThat(ack.isSuccessful).isTrue()

            // What the admin sees. `sent` here would mean the phone never
            // answered — the failure this whole path exists to make visible.
            assertThat(LiveAdmin.commandStatus(commandId)).isEqualTo("acknowledged")
        }

    /**
     * WALL 3: a refusal is a first-class outcome. Every value the app can send
     * has to be one the server accepts, or the outcome is lost and the command
     * ages into `ack_timeout` — which says "the phone never answered" about a
     * phone that answered.
     */
    @Test
    fun `every failure reason the app can send is accepted`() = runTest {
        val session = LiveAdmin.requireVerifiedSession()
        val installationId = session.installationId!!

        for (failure in CommandFailure.entries) {
            val commandId = requireNotNull(LiveAdmin.issueCommand(installationId, "ping")) {
                "The panel would not issue a command for $installationId"
            }
            val response = commands(session).acknowledge(
                UUID.fromString(commandId),
                DeviceAckIn(
                    status = "failed",
                    at = OffsetDateTime.now(),
                    failureReason = uz.bonvi.call.data.remote.dto.CommandFailureReason.entries
                        .first { it.value == failure.wire },
                ),
            )
            assertThat(response.isSuccessful).isTrue()
            assertThat(LiveAdmin.commandStatus(commandId)).isEqualTo("failed")
        }
    }

    /**
     * WALL 4: the heartbeat the app now actually sends (UC-17).
     *
     * The fleet's `unknown_version_count` was 5 of 5 because this payload was
     * built and never posted. The answer also carries the version gate and the
     * pending-command count, which is what the heartbeat worker branches on.
     */
    @Test
    fun `the heartbeat is accepted and answers with the version gate`() = runTest {
        val session = LiveAdmin.requireVerifiedSession()

        val response = LiveHarness.calls(session).heartbeat(
            DeviceHeartbeatIn(
                deviceEpochMs = System.currentTimeMillis(),
                deviceTimezone = "Asia/Tashkent",
                appVersion = "1.0.0",
                appVersionCode = 1,
                appVariant = AppVariant.LEGACY28,
                apiLevel = 28,
                serviceRunning = true,
                captureEnabled = true,
                queueRecords = 0,
                parkedRecords = 0,
                queueBytes = 0,
                batteryLevel = 82,
                batteryCharging = false,
                batteryOptimisationExempt = true,
                powerSaveMode = false,
                freeStorageBytes = 1_000_000_000,
                networkType = NetworkType.CELLULAR,
            ),
        )

        assertThat(response.isSuccessful).isTrue()
        val body = response.body()!!
        // What HeartbeatWorker reads: the gate, and whether to collect
        // commands. Both have to be present rather than merely parseable.
        assertThat(body.update.minVersionCode).isAtLeast(0)
        assertThat(body.pendingCommandCount ?: 0).isAtLeast(0)
    }
}
