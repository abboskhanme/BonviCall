package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * A device that cannot send **holds** its queue (T79/N25, T83/N34).
 *
 * The failure these tests exist to prevent is silent: the natural
 * implementation of "the token expired" is to clear local state and start
 * again, and what that clears is calls that happened and never reached the
 * server. The phone still looks healthy; the panel simply has fewer calls than
 * the handset made, and nobody finds out for weeks.
 */
class DeviceAuthStateTest {

    @Test
    fun `no state ever discards the queue`() {
        // The single most important assertion in this file. If a state is ever
        // added with holdsQueue = false, this is what stops it.
        for (state in DeviceAuthState.entries) {
            assertThat(state.holdsQueue).isTrue()
        }
    }

    @Test
    fun `an out-of-date client keeps sending`() {
        // N34's order is the rule: the server accepts a stale client's queued
        // records and refuses it only once the backlog is empty. A client that
        // stopped sending would strand exactly the data the gate protects.
        assertThat(DeviceAuthState.UPDATE_REQUIRED.canSend).isTrue()
        assertThat(DeviceAuthState.UPDATE_REQUIRED.canCapture).isTrue()
    }

    @Test
    fun `an expired session stops sending but keeps everything`() {
        assertThat(DeviceAuthState.AUTH_EXPIRED.canSend).isFalse()
        assertThat(DeviceAuthState.AUTH_EXPIRED.holdsQueue).isTrue()
    }

    @Test
    fun `a revoked installation stops capturing and still holds the queue`() {
        // UC-08. A revoke that raced an upload must not silently lose the last
        // calls; the server decides what is deleted, not the phone.
        assertThat(DeviceAuthState.REVOKED.canCapture).isFalse()
        assertThat(DeviceAuthState.REVOKED.canSend).isFalse()
        assertThat(DeviceAuthState.REVOKED.holdsQueue).isTrue()
    }

    @Test
    fun `a 401 on a normal request does not expire the session`() {
        // A single 401 is a stale access token, which the refresh handles.
        // Only a refused REFRESH is auth_expired.
        assertThat(AuthStateRule.next(DeviceAuthState.ACTIVE, 401, "unauthorized"))
            .isEqualTo(DeviceAuthState.ACTIVE)
    }

    @Test
    fun `a 426 anywhere means update required`() {
        assertThat(AuthStateRule.next(DeviceAuthState.ACTIVE, 426, "app_version_unsupported"))
            .isEqualTo(DeviceAuthState.UPDATE_REQUIRED)
        assertThat(AuthStateRule.next(DeviceAuthState.ACTIVE, 200, "app_version_unsupported"))
            .isEqualTo(DeviceAuthState.UPDATE_REQUIRED)
    }

    @Test
    fun `only a refused refresh produces auth_expired`() {
        assertThat(AuthStateRule.onRefreshRefused("unauthorized"))
            .isEqualTo(DeviceAuthState.AUTH_EXPIRED)
        // The server considers the token stolen. Retrying with it would be
        // worse than stopping, so the phone stops and says so.
        assertThat(AuthStateRule.onRefreshRefused("refresh_reused"))
            .isEqualTo(DeviceAuthState.AUTH_EXPIRED)
        assertThat(AuthStateRule.onRefreshRefused("installation_revoked"))
            .isEqualTo(DeviceAuthState.REVOKED)
    }

    @Test
    fun `a revoke seen on a normal request is recorded`() {
        assertThat(AuthStateRule.next(DeviceAuthState.ACTIVE, 401, "installation_revoked"))
            .isEqualTo(DeviceAuthState.REVOKED)
    }

    @Test
    fun `every state has a wire name the panel can render`() {
        assertThat(DeviceAuthState.entries.map { it.wire }).containsExactly(
            "active", "auth_expired", "revoked", "update_required",
        )
    }

    /**
     * The two states in which a handset holds an installation id and can do
     * nothing with it.
     *
     * `EnrolmentViewModel` keys its "resume past E1" decision on exactly this,
     * because keying it on the id alone made the documented recovery — a new
     * code on the same number — unreachable from the app. A live Redmi Note 14
     * sat on a home screen claiming to capture, with 39 calls held and no way
     * to enter the code that would have freed them.
     */
    @Test
    fun `a dead credential is not a usable one`() {
        assertThat(DeviceAuthState.AUTH_EXPIRED.canCapture).isFalse()
        assertThat(DeviceAuthState.REVOKED.canCapture).isFalse()
        // And the two that ARE usable, so the fix cannot swing the other way
        // and send a healthy phone back to the code screen on every launch.
        assertThat(DeviceAuthState.ACTIVE.canCapture).isTrue()
        assertThat(DeviceAuthState.UPDATE_REQUIRED.canCapture).isTrue()
    }

    @Test
    fun `a refused refresh always lands somewhere unusable`() {
        // Whatever the server said, the phone must not stay in a state that
        // lets the home screen claim it is capturing.
        for (code in listOf("refresh_reused", "unauthorized", "installation_revoked", null)) {
            assertThat(AuthStateRule.onRefreshRefused(code).canCapture).isFalse()
        }
    }
}
