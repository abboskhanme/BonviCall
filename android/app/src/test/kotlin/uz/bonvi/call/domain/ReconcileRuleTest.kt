package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * Reconciliation (T67, UC-13, SPEC §3.10).
 *
 * This rule decides whether a call is uploaded once or twice, and N2 puts the
 * acceptable duplicate rate at 0.
 */
class ReconcileRuleTest {

    private data class Row(
        val at: Long,
        val direction: CallDirection,
        val number: String?,
    )

    private fun match(live: ReconcileRule.Candidate, rows: List<Row>) =
        ReconcileRule.match(live, rows, Row::at, Row::direction, Row::number)

    @Test
    fun `a call-log row a second later is the same call`() {
        // The log records when the platform committed the row; the service
        // records when it saw the edge. They never agree exactly.
        val live = ReconcileRule.Candidate(10_000L, CallDirection.OUTGOING, "901112233")
        val rows = listOf(Row(11_000L, CallDirection.OUTGOING, "+998 90 111-22-33"))

        assertThat(match(live, rows)).isEqualTo(rows.single())
    }

    @Test
    fun `a row outside the window is not the same call`() {
        val live = ReconcileRule.Candidate(10_000L, CallDirection.OUTGOING, "901112233")
        val rows = listOf(Row(15_000L, CallDirection.OUTGOING, "901112233"))

        assertThat(match(live, rows)).isNull()
    }

    @Test
    fun `direction must agree`() {
        // An incoming and an outgoing call to the same number within the window
        // is a callback, not one call.
        val live = ReconcileRule.Candidate(10_000L, CallDirection.OUTGOING, "901112233")
        val rows = listOf(Row(10_100L, CallDirection.INCOMING, "901112233"))

        assertThat(match(live, rows)).isNull()
    }

    @Test
    fun `the number is compared on its nine-digit key, not its text`() {
        // Same function and same vectors as the server (N37). The log and the
        // dialer format numbers differently on the same handset.
        val live = ReconcileRule.Candidate(10_000L, CallDirection.INCOMING, "+998901112233")
        val rows = listOf(Row(10_500L, CallDirection.INCOMING, "901112233"))

        assertThat(match(live, rows)).isNotNull()
    }

    @Test
    fun `two calls to the same number a second apart pair with their own rows`() {
        // The failure this prevents: both live calls matching the first row,
        // one call uploaded twice and one never.
        val rows = listOf(
            Row(10_000L, CallDirection.OUTGOING, "901112233"),
            Row(11_200L, CallDirection.OUTGOING, "901112233"),
        )
        val first = ReconcileRule.Candidate(10_100L, CallDirection.OUTGOING, "901112233")
        val second = ReconcileRule.Candidate(11_300L, CallDirection.OUTGOING, "901112233")

        assertThat(match(first, rows)).isEqualTo(rows[0])
        assertThat(match(second, rows)).isEqualTo(rows[1])
    }

    @Test
    fun `a withheld caller id matches a withheld caller id`() {
        // Refusing to match here would upload every anonymous call twice: once
        // unreconciled, once by the recovery sweep.
        val live = ReconcileRule.Candidate(10_000L, CallDirection.INCOMING, null)
        val rows = listOf(Row(10_400L, CallDirection.INCOMING, ""))

        assertThat(match(live, rows)).isNotNull()
    }

    @Test
    fun `a withheld caller id does not match a known number`() {
        val live = ReconcileRule.Candidate(10_000L, CallDirection.INCOMING, null)
        val rows = listOf(Row(10_400L, CallDirection.INCOMING, "901112233"))

        assertThat(match(live, rows)).isNull()
    }

    @Test
    fun `no rows is a normal answer, not an error`() {
        // The log row can lag the call by minutes, which is why §3.10 gives it
        // fifteen before deriving the id from the live time.
        val live = ReconcileRule.Candidate(10_000L, CallDirection.OUTGOING, "901112233")

        assertThat(match(live, emptyList())).isNull()
    }

    @Test
    fun `the fifteen-minute deadline is what SPEC 3_10 rule 2 says`() {
        val ended = 1_000_000L
        assertThat(ReconcileRule.deadlinePassed(ended, ended + 14 * 60_000L)).isFalse()
        assertThat(ReconcileRule.deadlinePassed(ended, ended + 15 * 60_000L)).isTrue()
        assertThat(ClientCallId.RECONCILE_DEADLINE_MS).isEqualTo(15 * 60 * 1000L)
    }
}
