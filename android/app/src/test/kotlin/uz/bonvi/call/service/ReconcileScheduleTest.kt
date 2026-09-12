package uz.bonvi.call.service

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.service.work.ReconcileWorker

/**
 * The sweep's timing after a call — the larger half of the metadata delay
 * until 2026-09-12, when it was a flat 20 s on a fleet whose call-log row
 * appears in about two.
 */
class ReconcileScheduleTest {

    @Test
    fun `the first sweep after hang-up is four seconds`() {
        assertThat(ReconcileWorker.delaySeconds(0)).isEqualTo(4L)
        assertThat(ReconcileWorker.FIRST_DELAY_SECONDS).isEqualTo(4L)
    }

    @Test
    fun `a late call-log row is retried on an escalating schedule, capped at a minute`() {
        assertThat((1..6).map { ReconcileWorker.delaySeconds(it) })
            .containsExactly(8L, 16L, 32L, 60L, 60L, 60L)
            .inOrder()
        assertThat(ReconcileWorker.delaySeconds(40)).isEqualTo(60L) // no shift overflow
    }
}
