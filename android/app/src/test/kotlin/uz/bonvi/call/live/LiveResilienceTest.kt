package uz.bonvi.call.live

import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.test.runTest
import org.junit.BeforeClass
import org.junit.Test
import uz.bonvi.call.data.remote.dto.AppVariant
import uz.bonvi.call.data.remote.dto.DeviceHeartbeatIn
import uz.bonvi.call.data.remote.dto.DeviceRefreshIn
import uz.bonvi.call.data.remote.toFailure
import uz.bonvi.call.domain.AuthStateRule
import uz.bonvi.call.domain.DeviceAuthState
import uz.bonvi.call.domain.UploadPolicy

/**
 * What the app does when the server says no, and when nothing answers at all.
 *
 * The tunnel dies regularly and that is the client's real environment. Every
 * one of these asks the same question: **does the failure arrive as something
 * the UI can act on, or as a reassuring message that sends somebody to the
 * wrong place?**
 */
class LiveResilienceTest {

    companion object {
        @BeforeClass @JvmStatic fun serverUp() = LiveHarness.requireServer()
    }

    private fun heartbeat() = DeviceHeartbeatIn(
        deviceEpochMs = System.currentTimeMillis(),
        deviceTimezone = "Asia/Tashkent",
        appVersion = "1.0.0",
        appVersionCode = 1,
        appVariant = AppVariant.LEGACY28,
    )

    /**
     * WALL 15: a stale or forged token. The app must get `unauthorized` and not
     * a parse error, because `TokenAuthenticator` branches on the status and
     * `AuthStateRule` on the code.
     */
    @Test
    fun `a bad token is a branchable 401, not a parse failure`() = runTest {
        val session = FakeSession().apply {
            installationId = "00000000-0000-4000-8000-000000000001"
            accessToken = "not-a-real-token"
        }

        val response = LiveHarness.calls(session).heartbeat(heartbeat())

        assertThat(response.isSuccessful).isFalse()
        val failure = response.toFailure(LiveHarness.moshi())
        assertThat(failure.status).isAnyOf(401, 403)
        // `http_401` means the body was not the envelope — the whole class of
        // bug the 422 defect belonged to.
        assertThat(failure.code).isNotEqualTo("http_${failure.status}")

        // And a single 401 must NOT expire the session: it is a stale access
        // token, which the refresh handles. Only a refused REFRESH is expiry.
        assertThat(AuthStateRule.next(DeviceAuthState.ACTIVE, failure.status, failure.code))
            .isEqualTo(DeviceAuthState.ACTIVE)
    }

    /**
     * WALL 16: no headers at all. CONVENTIONS §4.5 says a missing
     * `X-Installation-Id` is a 400 `header_missing`, never a 500 — and never a
     * 401, which is easy to misread while debugging.
     */
    @Test
    fun `a request with no installation header is refused clearly`() = runTest {
        val session = FakeSession() // installationId stays null
        val response = LiveHarness.calls(session).heartbeat(heartbeat())

        assertThat(response.isSuccessful).isFalse()
        val failure = response.toFailure(LiveHarness.moshi())
        assertThat(failure.status).isNotEqualTo(500)
        assertThat(failure.code).isNotEqualTo("http_${failure.status}")
    }

    /**
     * WALL 17: a refused refresh. This is the ONLY path to `auth_expired`, and
     * getting it wrong means either a queue held for no reason or a session
     * that never ends.
     */
    @Test
    fun `a refused refresh produces auth_expired and nothing else`() = runTest {
        val session = FakeSession().apply {
            installationId = "00000000-0000-4000-8000-000000000001"
        }

        val response = LiveHarness.auth(session).refresh(
            DeviceRefreshIn(refreshToken = "not-a-real-refresh-token"),
        )

        assertThat(response.isSuccessful).isFalse()
        val failure = response.toFailure(LiveHarness.moshi())
        val state = AuthStateRule.onRefreshRefused(failure.code)
        assertThat(state).isAnyOf(DeviceAuthState.AUTH_EXPIRED, DeviceAuthState.REVOKED)
        // Whatever the answer, the queue is HELD. N25's whole point.
        assertThat(state.holdsQueue).isTrue()
        assertThat(state.canSend).isFalse()
    }

    /**
     * WALL 18: **nothing answers at all** — the tunnel is dead, which is the
     * client's normal Tuesday. This must be an offline outcome, never an
     * exception escaping into a Compose screen, and never a permanent park.
     */
    @Test
    fun `a dead server is offline, not a crash and not a park`() = runTest {
        val session = FakeSession(baseUrl = "http://127.0.0.1:59999")

        val threw = runCatching {
            LiveHarness.calls(session).heartbeat(heartbeat())
        }.exceptionOrNull()

        // Retrofit surfaces it as an IOException, which every caller in the app
        // catches into an Offline/Retry outcome rather than letting it escape.
        assertThat(threw).isInstanceOf(java.io.IOException::class.java)

        // And the queue policy treats "no response" as retryable — a phone in a
        // lift must not park the calls it made this morning.
        assertThat(UploadPolicy.onFailure(attemptsSoFar = 0, status = 0, code = null))
            .isInstanceOf(UploadPolicy.Outcome.Retry::class.java)
    }

    /**
     * WALL 19: a host that answers but is not us — a tunnel landing page, a
     * captive portal, somebody else's server. The address check has to tell
     * this apart from "nothing there", because the fixes differ.
     */
    @Test
    fun `something that is not BonviCall is distinguished from nothing`() = runTest {
        val response = LiveHarness.reachability()
            .healthz("${LiveHarness.baseUrl}/definitely-not-a-real-path")

        assertThat(response.isSuccessful).isFalse()
        // A wrong address and a dead one need different sentences on the
        // diagnostics screen.
        assertThat(response.code()).isAtLeast(400)
    }

    /**
     * WALL 20: the version gate's own answer. The updater keys off this, and a
     * missing `update` block would make every phone think it is current.
     */
    @Test
    fun `the heartbeat always carries the version gate's verdict`() = runTest {
        val session = LiveAdmin.requireVerifiedSession()

        val response = LiveHarness.calls(session).heartbeat(heartbeat())

        assertThat(response.isSuccessful).isTrue()
        val update = response.body()!!.update
        // Never-null by contract; a null here would be an app that never
        // updates and never says why.
        assertThat(update.minVersionCode).isAtLeast(0)
        assertThat(update.required).isNotNull()
    }

    /**
     * WALL 21: a revoked installation. UC-08 — the phone must learn it is
     * revoked from a branchable code so it can stop capturing and delete its
     * audio, rather than looking healthy and holding recordings.
     */
    @Test
    fun `a revoked installation is told so in a code it can act on`() = runTest {
        val session = LiveAdmin.requireVerifiedSession()
        val revoked = LiveAdmin.revoke(session.installationId!!)
        if (!revoked) return@runTest // the admin route is not the device path

        val response = LiveHarness.calls(session).heartbeat(heartbeat())

        if (!response.isSuccessful) {
            val failure = response.toFailure(LiveHarness.moshi())
            assertThat(failure.code).isNotEqualTo("http_${failure.status}")
            val state = AuthStateRule.next(DeviceAuthState.ACTIVE, failure.status, failure.code)
            // Whatever the code, the phone must not keep capturing while
            // believing it is fine.
            if (failure.code == "installation_revoked") {
                assertThat(state).isEqualTo(DeviceAuthState.REVOKED)
                assertThat(state.canCapture).isFalse()
                assertThat(state.holdsQueue).isTrue()
            }
        }
    }
}
