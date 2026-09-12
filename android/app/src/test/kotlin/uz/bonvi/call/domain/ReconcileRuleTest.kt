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
    fun `a live side that knows no number matches the log row anyway`() {
        // ⚠️ The inverse of the test that stood here, which asserted this must
        // NOT match. That was right only while the live source could see
        // numbers — and from API 31 it cannot: `TelephonyCallback` reports a
        // state and nothing else, so the live number is ALWAYS null on every
        // handset in this fleet. The log has the number, the keys never
        // agreed, and **every live-detected call failed to reconcile**: it
        // waited out the fifteen minutes and arrived as an unreconciled
        // duplicate of a row the recovery sweep had already written.
        //
        // Measured on a Xiaomi 13 Lite, 2026-09-11 — detected live, recorded,
        // and still delivered as `call_log_recovery` / `app_not_running`.
        //
        // Null from the live side means "we were not told", not "it was
        // withheld". Direction and a two-second window identify the call.
        val live = ReconcileRule.Candidate(10_000L, CallDirection.INCOMING, null)
        val rows = listOf(Row(10_400L, CallDirection.INCOMING, "901112233"))

        assertThat(match(live, rows)).isNotNull()
    }

    @Test
    fun `two numbers that are both known and different never match`() {
        // The half of the old rule that must survive: when the live side DOES
        // know a number, disagreeing with the log is still a different call,
        // and matching them would file a conversation under the wrong person.
        val live = ReconcileRule.Candidate(10_000L, CallDirection.OUTGOING, "901112233")
        val rows = listOf(Row(10_400L, CallDirection.OUTGOING, "935554433"))

        assertThat(match(live, rows)).isNull()
    }

    @Test
    fun `a number-less live call still takes the closest row in time`() {
        // The safety the relaxed rule leans on: two calls inside one window
        // pair with their own rows rather than both with the first.
        val live = ReconcileRule.Candidate(10_000L, CallDirection.OUTGOING, null)
        val rows = listOf(
            Row(11_500L, CallDirection.OUTGOING, "901112233"),
            Row(10_100L, CallDirection.OUTGOING, "935554433"),
        )

        assertThat(match(live, rows)?.number).isEqualTo("935554433")
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

    // ── answeredAt: the log decides whether anybody picked up ─────────────

    @Test
    fun `a zero-duration row means nobody answered, whatever the live path saw`() {
        // OFFHOOK on an outgoing call is dialling, and the live path recorded
        // it as the answer. Sent as `answered` with duration 0 the server
        // refused the call by constraint (2026-09-12).
        assertThat(
            ReconcileRule.answeredAt(
                liveAnsweredAtEpochMillis = 10_500L,
                logStartedAtEpochMillis = 10_000L,
                logDurationSec = 0,
            ),
        ).isNull()
    }

    @Test
    fun `an answered row keeps the live answer time when there is one`() {
        assertThat(ReconcileRule.answeredAt(10_500L, 10_000L, 40)).isEqualTo(10_500L)
    }

    @Test
    fun `an answered row without a live answer time falls back to the log start`() {
        assertThat(ReconcileRule.answeredAt(null, 10_000L, 40)).isEqualTo(10_000L)
    }
}
