package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * When it is safe to install an update (T82).
 *
 * Installing an APK kills the process. A restart mid-upload is recoverable —
 * the queue is on disk and the upload resumes. **A restart mid-capture is a
 * lost call**, and that is the one thing this product exists to keep.
 */
class UpdateReadinessTest {

    @Test
    fun `a call in progress blocks the update, with no override`() {
        // Even when the update is forced by the minimum-version gate. A lost
        // call cannot be recovered and an update can always wait five minutes.
        for (forced in listOf(false, true)) {
            assertThat(
                UpdateReadiness.decide(
                    available = true, callInProgress = true, pendingRecords = 0, forced = forced,
                ),
            ).isEqualTo(UpdateReadiness.Decision.WAIT_CALL_IN_PROGRESS)
        }
    }

    @Test
    fun `a draining queue defers a normal update`() {
        assertThat(
            UpdateReadiness.decide(true, callInProgress = false, pendingRecords = 3, forced = false),
        ).isEqualTo(UpdateReadiness.Decision.WAIT_QUEUE_DRAINING)
    }

    @Test
    fun `a forced update proceeds through a queue it cannot drain`() {
        // N34: the phone is being refused anyway. A device with no network for
        // a week would otherwise be permanently unupdatable — blocked by the
        // very backlog the new build might fix.
        assertThat(
            UpdateReadiness.decide(true, callInProgress = false, pendingRecords = 99, forced = true),
        ).isEqualTo(UpdateReadiness.Decision.INSTALL)
    }

    @Test
    fun `an idle phone with an empty queue installs`() {
        assertThat(
            UpdateReadiness.decide(true, callInProgress = false, pendingRecords = 0, forced = false),
        ).isEqualTo(UpdateReadiness.Decision.INSTALL)
    }

    @Test
    fun `nothing to install is not the same as not ready`() {
        assertThat(
            UpdateReadiness.decide(false, callInProgress = true, pendingRecords = 9, forced = true),
        ).isEqualTo(UpdateReadiness.Decision.NOT_NEEDED)
    }

    @Test
    fun `versions are compared on the CODE, never the name`() {
        // "1.2.10" < "1.2.9" as strings. N34's floor is numeric for a reason.
        assertThat(UpdateReadiness.isNewer(11, 10)).isTrue()
        assertThat(UpdateReadiness.isNewer(10, 10)).isFalse()
        assertThat(UpdateReadiness.isNewer(9, 10)).isFalse()
        assertThat(UpdateReadiness.isNewer(null, 10)).isFalse()
    }

    @Test
    fun `below the minimum version is the forcing condition`() {
        assertThat(UpdateReadiness.isBelowMinimum(minVersionCode = 5, installedVersionCode = 4))
            .isTrue()
        assertThat(UpdateReadiness.isBelowMinimum(minVersionCode = 5, installedVersionCode = 5))
            .isFalse()
    }
}
