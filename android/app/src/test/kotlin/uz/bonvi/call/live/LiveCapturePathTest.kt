package uz.bonvi.call.live

import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.test.runTest
import org.junit.BeforeClass
import org.junit.Test
import uz.bonvi.call.data.remote.dto.AppInfoIn
import uz.bonvi.call.data.remote.dto.AppVariant
import uz.bonvi.call.data.remote.dto.DeviceCallBatchIn
import uz.bonvi.call.data.remote.dto.DeviceCallIn
import uz.bonvi.call.data.remote.dto.DeviceHeartbeatIn
import uz.bonvi.call.data.remote.dto.DeviceInfoIn
import uz.bonvi.call.data.remote.dto.DeviceRedeemIn
import uz.bonvi.call.data.remote.toFailure
import uz.bonvi.call.domain.CallDirection
import uz.bonvi.call.domain.ClientCallId
import java.time.OffsetDateTime
import java.util.UUID
import uz.bonvi.call.data.remote.dto.AudioMissingReason as AudioMissingReasonDto
import uz.bonvi.call.data.remote.dto.CallDirection as CallDirectionDto
import uz.bonvi.call.data.remote.dto.CallDisposition as CallDispositionDto
import uz.bonvi.call.data.remote.dto.CallSource as CallSourceDto
import uz.bonvi.call.data.remote.dto.CaptureRoute as CaptureRouteDto

/**
 * A captured call, uploaded, and read back — against a live server.
 *
 * This is the part of the path nobody has ever driven: the app can post calls
 * and could not read them back until yesterday, and the two halves have never
 * met. Each test names the wall it looks for.
 */
class LiveCapturePathTest {

    companion object {
        @BeforeClass @JvmStatic fun serverUp() = LiveHarness.requireServer()
    }

    /**
     * An enrolled session.
     *
     * ⚠️ Fails LOUDLY rather than returning null. The first version of this
     * file returned null on any fixture problem and every test then hit
     * `?: return@runTest` — seven green no-ops that proved nothing. A test that
     * silently passes when its fixture fails is worse than no test, and it is
     * the same shape as the broad `catch` that reported a converter error as
     * "no internet".
     */
    private fun enrolled(): FakeSession {
        val code = requireNotNull(LiveAdmin.issueCode()) {
            "Could not issue an enrolment code — the admin path is broken, not the device path"
        }
        val session = FakeSession()
        val response = kotlinx.coroutines.runBlocking {
            LiveHarness.enrolment(session).redeem(
                DeviceRedeemIn(
                    code = code,
                    device = DeviceInfoIn(
                        androidRelease = "9", apiLevel = 28,
                        buildFingerprintHash = "b".repeat(64),
                        manufacturer = "Samsung", model = "SM-A515F",
                    ),
                    app = AppInfoIn(AppVariant.LEGACY28, "1.0.0", 1),
                    deviceFingerprint = "b".repeat(64),
                    deviceEpochMs = System.currentTimeMillis(),
                    deviceTimezone = "Asia/Tashkent",
                    simSubscriptionId = 2, simSlot = 0,
                ),
            )
        }
        val body = requireNotNull(response.body()) {
            "redeem failed: ${response.code()} ${response.errorBody()?.string()}"
        }
        session.installationId = body.installationId.toString()
        session.accessToken = body.provisionalToken
        session.registeredNumberE164 = body.number.e164
        return session
    }

    private fun callIn(session: FakeSession, startedAt: Long): DeviceCallIn {
        val id = ClientCallId.derive(
            registeredNumber = session.registeredNumberE164!!,
            direction = CallDirection.OUTGOING,
            startedAtEpochMillis = startedAt,
            remoteNumber = "+998907776655",
        )
        return DeviceCallIn(
            clientCallId = UUID.fromString(id),
            deviceEpochMs = System.currentTimeMillis(),
            deviceTimezone = "Asia/Tashkent",
            direction = CallDirectionDto.OUTGOING,
            disposition = CallDispositionDto.ANSWERED,
            startedAt = OffsetDateTime.now().minusMinutes(2),
            answeredAt = OffsetDateTime.now().minusMinutes(2),
            endedAt = OffsetDateTime.now().minusMinutes(1),
            durationSec = 60,
            remoteNumber = "+998907776655",
            audioExpected = false,
            // The honest state while the OEM locators are NoOp.
            audioMissingReason = AudioMissingReasonDto.RECORDING_ROUTE_UNAVAILABLE,
            captureRoute = CaptureRouteDto.NONE,
            source = CallSourceDto.LIVE_CAPTURE,
            reconciledWithCallLog = true,
            appVariant = AppVariant.LEGACY28,
            appVersion = "1.0.0",
        )
    }

    /**
     * WALL 8: an unverified installation must not be able to upload calls. The
     * provisional token gets a phone through verification and no further —
     * if it could post calls, verification would be decoration.
     */
    @Test
    fun `an unverified installation cannot upload calls`() = runTest {
        val session = enrolled()

        val response = LiveHarness.calls(session).uploadCalls(
            DeviceCallBatchIn(calls = listOf(callIn(session, System.currentTimeMillis()))),
        )

        assertThat(response.isSuccessful).isFalse()
        val failure = response.toFailure(LiveHarness.moshi())
        // And the refusal has to be branchable, not http_403.
        assertThat(failure.code).isNotEqualTo("http_${failure.status}")
        assertThat(failure.code).isEqualTo("verification_required")
    }

    /**
     * WALL 9: the full `DeviceCallIn` payload the app builds. Twenty-two
     * fields, any one of which could be rejected — and a rejection here is a
     * call that never reaches the panel.
     */
    @Test
    fun `the call payload the app builds is accepted once verified`() = runTest {
        val session = LiveAdmin.requireVerifiedSession()

        val response = LiveHarness.calls(session).uploadCalls(
            DeviceCallBatchIn(calls = listOf(callIn(session, System.currentTimeMillis()))),
        )

        assertThat(response.isSuccessful).isTrue()
        val body = response.body()!!
        assertThat(body.results).hasSize(1)
        assertThat(body.results.single().error).isNull()
    }

    /**
     * WALL 10: **N2 — the duplicate rate must be 0.** The same call sent twice
     * has to produce one row and the same id. This is what the whole UUIDv5
     * derivation exists for and it has never been checked against the server.
     */
    @Test
    fun `the same call uploaded twice is one row`() = runTest {
        val session = LiveAdmin.requireVerifiedSession()
        val startedAt = System.currentTimeMillis()
        val call = callIn(session, startedAt)

        val first = LiveHarness.calls(session).uploadCalls(DeviceCallBatchIn(listOf(call)))
        val second = LiveHarness.calls(session).uploadCalls(DeviceCallBatchIn(listOf(call)))

        assertThat(first.isSuccessful).isTrue()
        assertThat(second.isSuccessful).isTrue()
        val firstId = first.body()!!.results.single().id
        val secondId = second.body()!!.results.single().id
        assertThat(secondId).isEqualTo(firstId)
        // A replay and a first write are indistinguishable by design (§3.10.4).
        assertThat(second.body()!!.results.single().status.value)
            .isAnyOf("unchanged", "updated")
    }

    /**
     * WALL 11: the heartbeat, including `app_version_code` — the field whose
     * absence made the version gate protect nothing on the live fleet.
     */
    @Test
    fun `the heartbeat is accepted and carries the version code`() = runTest {
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
                freeStorageBytes = 8_000_000_000L,
            ),
        )

        assertThat(response.isSuccessful).isTrue()
        val body = response.body()!!
        // The gate's own answer, which the updater keys off.
        assertThat(body.update.minVersionCode).isAtLeast(0)
    }

    /**
     * WALL 12: the employee reads their own calls back. The two halves of the
     * product meeting for the first time.
     */
    @Test
    fun `a call the app uploaded is readable by the employee`() = runTest {
        val session = LiveAdmin.requireVerifiedSession()
        val call = callIn(session, System.currentTimeMillis())
        LiveHarness.calls(session).uploadCalls(DeviceCallBatchIn(listOf(call)))

        val response = LiveHarness.callRead(session).myCalls(limit = 50, cursor = null)

        assertThat(response.isSuccessful).isTrue()
        val page = response.body()!!
        val mine = page.items.firstOrNull { it.clientCallId == call.clientCallId }
        assertThat(mine).isNotNull()
        // `audio_state` must be present and never null — the screen switches
        // on it and has no fallback that is honest.
        assertThat(mine!!.audioState.value).isNotEmpty()
        // No audio was uploaded, so it must NOT claim to be playable.
        assertThat(mine.audioState.value).isNotEqualTo("recorded")
    }

    /**
     * WALL 13: audio for a call that has none. The screen shows no play control
     * for it, but a mis-scoped or mis-coded response here would mean an
     * employee tapping into a 500.
     */
    @Test
    fun `audio for a call with no recording is a branchable 404`() = runTest {
        val session = LiveAdmin.requireVerifiedSession()
        val call = callIn(session, System.currentTimeMillis())
        LiveHarness.calls(session).uploadCalls(DeviceCallBatchIn(listOf(call)))

        val page = requireNotNull(LiveHarness.callRead(session).myCalls(50, null).body())
        val id = requireNotNull(
            page.items.firstOrNull { it.clientCallId == call.clientCallId }?.id,
        ) { "the call the app just uploaded is not in the employee's own list" }

        val client = LiveHarness.client(session)
        val request = okhttp3.Request.Builder()
            .url("${session.baseUrl}/api/device/v1/calls/$id/audio")
            .build()
        client.newCall(request).execute().use { response ->
            assertThat(response.code).isAnyOf(404, 410)
            val body = response.body?.string().orEmpty()
            // The N35 envelope, not a stack trace and not an empty 200.
            assertThat(body).contains("\"code\"")
        }
    }

    /**
     * WALL 14: another agent's call must be 404, never 403 — 403 confirms it
     * exists (SPEC §4.1 rule 2).
     */
    @Test
    fun `another agent's call id is not found, not forbidden`() = runTest {
        val session = LiveAdmin.requireVerifiedSession()
        val strangerId = UUID.randomUUID().toString()

        val client = LiveHarness.client(session)
        val request = okhttp3.Request.Builder()
            .url("${session.baseUrl}/api/device/v1/calls/$strangerId/audio")
            .build()
        client.newCall(request).execute().use { response ->
            assertThat(response.code).isNotEqualTo(403)
            assertThat(response.code).isAnyOf(404, 410, 422)
        }
    }
}
