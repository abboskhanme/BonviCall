package uz.bonvi.call.live

import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.test.runTest
import org.junit.BeforeClass
import org.junit.Test
import uz.bonvi.call.data.remote.dto.AppInfoIn
import uz.bonvi.call.data.remote.dto.AppVariant
import uz.bonvi.call.data.remote.dto.DeviceCapabilityBatchIn
import uz.bonvi.call.data.remote.dto.DeviceCapabilityIn
import uz.bonvi.call.data.remote.dto.DeviceEventBatchIn
import uz.bonvi.call.data.remote.dto.DeviceEventDetailIn
import uz.bonvi.call.data.remote.dto.DeviceEventIn
import uz.bonvi.call.data.remote.dto.DeviceInfoIn
import uz.bonvi.call.data.remote.dto.DeviceMsisdnVerifyIn
import uz.bonvi.call.data.remote.dto.DeviceRedeemIn
import uz.bonvi.call.data.remote.toFailure
import java.time.OffsetDateTime
import uz.bonvi.call.data.remote.dto.Capability as CapabilityDto
import uz.bonvi.call.data.remote.dto.CapabilityState as CapabilityStateDto

/**
 * E1 → E6 against a live server, through the app's own wire layer.
 *
 * Each test states the wall it is looking for. A failure here is a real defect
 * on the path a person walks, not a broken assertion.
 */
class LiveEnrolmentTest {

    companion object {
        @BeforeClass @JvmStatic fun serverUp() = LiveHarness.requireServer()
    }

    private fun session() = FakeSession()

    private fun redeemBody(code: String) = DeviceRedeemIn(
        code = code,
        device = DeviceInfoIn(
            androidRelease = "9",
            apiLevel = 28,
            buildFingerprintHash = "a".repeat(64),
            manufacturer = "Xiaomi",
            model = "Redmi Note 8",
        ),
        app = AppInfoIn(variant = AppVariant.LEGACY28, version = "1.0.0", versionCode = 1),
        deviceFingerprint = "a".repeat(64),
        deviceEpochMs = System.currentTimeMillis(),
        deviceTimezone = "Asia/Tashkent",
        simSubscriptionId = 2,
        simSlot = 0,
    )

    /**
     * WALL 1: does a wrong code produce a code the UI can branch on, or a
     * generic error? E1's whole design is a specific sentence per failure.
     */
    @Test
    fun `an unknown code returns a branchable error code`() = runTest {
        val session = session()
        val response = LiveHarness.enrolment(session).redeem(redeemBody("ZZZZZZZZ"))

        assertThat(response.isSuccessful).isFalse()
        val failure = response.toFailure(LiveHarness.moshi())
        // Not `http_404`: that is what a body the client could not parse looks
        // like, and it is what the 422 defect produced everywhere.
        assertThat(failure.code).isNotEqualTo("http_${failure.status}")
        assertThat(failure.code).isEqualTo("enrolment_code_not_found")
        assertThat(failure.message).isNotEmpty()
    }

    /**
     * WALL 2: the redeem payload itself. Every field the app sends has to be
     * accepted — a serialisation mismatch here is invisible until a real
     * install, which is exactly how the afternoon was lost.
     */
    @Test
    fun `a real code redeems and returns a provisional token`() = runTest {
        val code = LiveAdmin.issueCode() ?: return@runTest
        val session = session()
        val response = LiveHarness.enrolment(session).redeem(redeemBody(code))

        assertThat(response.isSuccessful).isTrue()
        val body = response.body()!!
        assertThat(body.provisionalToken).isNotEmpty()
        assertThat(body.agent.fullName).isNotEmpty()
        assertThat(body.number.e164).startsWith("+998")
        // N41's sentence has to be renderable from this response alone.
        assertThat(body.number.display).isNotEmpty()
        // "installed" is not "done": verification is still required.
        assertThat(body.verification.required).isTrue()
    }

    /**
     * WALL 3a: **a retry from the same handset must not burn the code.**
     *
     * This is the behaviour that saves a person whose response was lost on a
     * dying tunnel — the case that produced an unrecoverable loop before
     * enrolment persisted its step. The server answers 201 with the SAME
     * installation id, so a replay and a first redeem are indistinguishable to
     * the app, exactly as `client_call_id` makes them for a call.
     *
     * My spec did not ask for this and the server is better than my spec. It is
     * pinned here because the app now depends on it: `AndroidDeviceFacts`
     * sends a hash of `Build.FINGERPRINT`, stable across reinstalls, so a retry
     * from the same phone always takes this path.
     */
    @Test
    fun `redeeming twice from the same handset is idempotent`() = runTest {
        val code = LiveAdmin.issueCode() ?: return@runTest

        val first = LiveHarness.enrolment(session()).redeem(redeemBody(code))
        val second = LiveHarness.enrolment(session()).redeem(redeemBody(code))

        assertThat(first.isSuccessful).isTrue()
        assertThat(second.isSuccessful).isTrue()
        assertThat(second.body()!!.installationId).isEqualTo(first.body()!!.installationId)
    }

    /**
     * WALL 3b: **a DIFFERENT handset must be refused.** One code, one phone —
     * UC-01's "a reused code fails visibly", and the difference between the two
     * halves is the device fingerprint.
     */
    @Test
    fun `redeeming from a different handset is refused with a code the UI can use`() = runTest {
        val code = LiveAdmin.issueCode() ?: return@runTest
        LiveHarness.enrolment(session()).redeem(redeemBody(code))

        val other = LiveHarness.enrolment(session()).redeem(
            redeemBody(code).copy(
                deviceFingerprint = "f".repeat(64),
                device = redeemBody(code).device.copy(buildFingerprintHash = "f".repeat(64)),
            ),
        )

        assertThat(other.isSuccessful).isFalse()
        val failure = other.toFailure(LiveHarness.moshi())
        assertThat(failure.status).isEqualTo(409)
        assertThat(failure.code).isAnyOf("enrolment_code_used", "installation_already_active")
        // E1 renders this message, so it has to be Uzbek and non-empty.
        assertThat(failure.message).isNotEmpty()
    }

    /**
     * WALL 4: capability reporting during E2. The panel's whole view of a stuck
     * enrolment comes from this, and it is the R17 case.
     */
    @Test
    fun `capabilities can be reported with a provisional token`() = runTest {
        val code = LiveAdmin.issueCode() ?: return@runTest
        val session = session()
        val redeemed = LiveHarness.enrolment(session).redeem(redeemBody(code)).body()!!
        session.installationId = redeemed.installationId.toString()
        session.accessToken = redeemed.provisionalToken

        val response = LiveHarness.enrolment(session).reportCapabilities(
            DeviceCapabilityBatchIn(
                capabilities = listOf(
                    DeviceCapabilityIn(
                        capability = CapabilityDto.MICROPHONE,
                        state = CapabilityStateDto.GRANTED_NOT_WORKING,
                        checkedAt = OffsetDateTime.now(),
                        detail = "1s capture was digital silence",
                    ),
                ),
            ),
        )

        // The Xiaomi case, reported while the agent is still on E2. If this is
        // refused the panel is blind to exactly the situation R17 exists for.
        assertThat(response.isSuccessful).isTrue()
    }

    /**
     * WALL 5: the event detail the generator upgrade restored. If `attempts`
     * or `by_user` fail to serialise, N40's measurement is silently empty.
     */
    @Test
    fun `step timing and stuck events serialise with their detail`() = runTest {
        val code = LiveAdmin.issueCode() ?: return@runTest
        val session = session()
        val redeemed = LiveHarness.enrolment(session).redeem(redeemBody(code)).body()!!
        session.installationId = redeemed.installationId.toString()
        session.accessToken = redeemed.provisionalToken

        val response = LiveHarness.enrolment(session).reportEvents(
            DeviceEventBatchIn(
                events = listOf(
                    DeviceEventIn(
                        kind = "step_timing",
                        at = OffsetDateTime.now(),
                        detail = DeviceEventDetailIn(attempts = 3),
                    ),
                    DeviceEventIn(
                        kind = "enrolment_stuck",
                        at = OffsetDateTime.now(),
                        detail = DeviceEventDetailIn(byUser = true),
                    ),
                ),
            ),
        )

        assertThat(response.isSuccessful).isTrue()
    }

    /**
     * WALL 6: route 1 with an EMPTY MSISDN, which is the common case on Uzbek
     * SIMs. The app must not treat "I don't know" as a match, and the server
     * must not either.
     */
    @Test
    fun `an empty msisdn never verifies`() = runTest {
        val code = LiveAdmin.issueCode() ?: return@runTest
        val session = session()
        val redeemed = LiveHarness.enrolment(session).redeem(redeemBody(code)).body()!!
        session.installationId = redeemed.installationId.toString()
        session.accessToken = redeemed.provisionalToken

        val response = LiveHarness.enrolment(session).verifyMsisdn(
            DeviceMsisdnVerifyIn(
                line1Number = null,
                subscriptionId = 2,
                simSlot = 0,
                carrierName = "Beeline",
            ),
        )

        if (response.isSuccessful) {
            val body = response.body()!!
            assertThat(body.state.value).isNotEqualTo("matched")
            assertThat(body.tokens).isNull()
        } else {
            val failure = response.toFailure(LiveHarness.moshi())
            assertThat(failure.code).isNotEqualTo("http_${failure.status}")
        }
    }

    /**
     * WALL 7: the callback route, which carries the weight when route 1 is
     * empty. A 503 here must be a code the UI can turn into "contact the
     * admin" rather than a spinner over a dead receiver.
     */
    @Test
    fun `the callback route answers with something the UI can branch on`() = runTest {
        val code = LiveAdmin.issueCode() ?: return@runTest
        val session = session()
        val redeemed = LiveHarness.enrolment(session).redeem(redeemBody(code)).body()!!
        session.installationId = redeemed.installationId.toString()
        session.accessToken = redeemed.provisionalToken

        val response = LiveHarness.enrolment(session).startCallback()

        if (response.isSuccessful) {
            val body = response.body()!!
            assertThat(body.callbackMsisdn).isNotEmpty()
            assertThat(body.verificationId.toString()).isNotEmpty()
        } else {
            val failure = response.toFailure(LiveHarness.moshi())
            assertThat(failure.code).isEqualTo("callback_receiver_down")
        }
    }

    /**
     * WALL 8: **the dead end, closed.**
     *
     * This is the wall the whole fleet was standing at. Route 1 is empty on
     * these SIMs, no callback receiver has ever been in service, and admin
     * attestation could not reach the phone — so every enrolment stopped at E5
     * and not one handset ever captured a call. If this test fails, the app is
     * back to being an install that finishes and records nothing.
     */
    @Test
    fun `a handset with no proving route can still finish enrolment`() = runTest {
        val code = LiveAdmin.issueCode() ?: return@runTest
        val session = session()
        val redeemed = LiveHarness.enrolment(session).redeem(redeemBody(code)).body()!!
        session.installationId = redeemed.installationId.toString()
        session.accessToken = redeemed.provisionalToken

        val response = LiveHarness.enrolment(session).verifySelfDeclared()

        assertThat(response.isSuccessful).isTrue()
        val body = response.body()!!
        assertThat(body.state.value).isEqualTo("self_declared")
        // The REAL pair. Without it the server accepts no call from this phone,
        // which is the state the flow has to leave behind.
        assertThat(body.tokens?.accessToken).isNotEmpty()
        assertThat(body.tokens?.refreshToken).isNotEmpty()
        assertThat(body.status?.value).isEqualTo("active")
    }

    /**
     * WALL 9: the status poll, which is how an admin's attestation reaches the
     * handset at all. Before it existed the phone held a provisional token and
     * no way to discover that the thing it was waiting for had already
     * happened.
     */
    @Test
    fun `a pending handset can ask where it stands without being handed tokens`() = runTest {
        val code = LiveAdmin.issueCode() ?: return@runTest
        val session = session()
        val redeemed = LiveHarness.enrolment(session).redeem(redeemBody(code)).body()!!
        session.installationId = redeemed.installationId.toString()
        session.accessToken = redeemed.provisionalToken

        val response = LiveHarness.enrolment(session).enrolmentStatus()

        assertThat(response.isSuccessful).isTrue()
        val body = response.body()!!
        assertThat(body.state.value).isEqualTo("pending")
        // Waiting is an answer; a credential is not.
        assertThat(body.tokens).isNull()
    }

    /**
     * WALL 10: and once it IS active, the same poll hands over the pair — so a
     * screen that was told "contact the admin" completes itself.
     */
    @Test
    fun `the status poll hands over the pair once the installation is active`() = runTest {
        val code = LiveAdmin.issueCode() ?: return@runTest
        val session = session()
        val redeemed = LiveHarness.enrolment(session).redeem(redeemBody(code)).body()!!
        session.installationId = redeemed.installationId.toString()
        session.accessToken = redeemed.provisionalToken
        LiveHarness.enrolment(session).verifySelfDeclared()

        val response = LiveHarness.enrolment(session).enrolmentStatus()

        assertThat(response.isSuccessful).isTrue()
        val body = response.body()!!
        assertThat(body.tokens?.accessToken).isNotEmpty()
        assertThat(body.status?.value).isEqualTo("active")
    }
}
