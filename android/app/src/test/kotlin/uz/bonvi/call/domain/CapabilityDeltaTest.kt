package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * The rule that decides whether a permission granted after enrolment is ever
 * noticed — and whether noticing it costs an employee's data every fifteen
 * minutes.
 *
 * Both halves matter. A comparison that is too eager reports nine capabilities
 * on every heartbeat for ever; one that is too lax leaves the panel describing
 * the day the app was installed, which is the bug this was written for: a
 * handset recorded four calls as silence because all-files access was skipped,
 * the agent granted it, and nothing told the server.
 */
class CapabilityDeltaTest {

    private fun result(
        capability: Capability,
        state: CapabilityState,
        detail: String? = null,
    ) = CapabilityResult(capability, state, detail)

    @Test
    fun `nothing is reported when every answer is the same`() {
        val results = listOf(
            result(Capability.STORAGE_ACCESS, CapabilityState.DENIED, "all-files access not granted"),
            result(Capability.CALL_LOG, CapabilityState.GRANTED_WORKING, "1 row"),
        )
        val previous = CapabilityDelta.snapshotOf(results)

        assertThat(CapabilityDelta.changed(previous, results)).isEmpty()
    }

    @Test
    fun `a permission granted later is reported`() {
        val before = listOf(
            result(Capability.STORAGE_ACCESS, CapabilityState.DENIED, "all-files access not granted"),
        )
        val after = listOf(
            result(Capability.STORAGE_ACCESS, CapabilityState.GRANTED_WORKING, "127 file(s)"),
        )

        val changed = CapabilityDelta.changed(CapabilityDelta.snapshotOf(before), after)

        assertThat(changed).hasSize(1)
        assertThat(changed.first().capability).isEqualTo(Capability.STORAGE_ACCESS)
    }

    @Test
    fun `only the capability that moved is sent`() {
        val before = listOf(
            result(Capability.STORAGE_ACCESS, CapabilityState.DENIED),
            result(Capability.CALL_LOG, CapabilityState.GRANTED_WORKING),
            result(Capability.CONTACTS, CapabilityState.GRANTED_WORKING),
        )
        val after = listOf(
            result(Capability.STORAGE_ACCESS, CapabilityState.GRANTED_WORKING),
            result(Capability.CALL_LOG, CapabilityState.GRANTED_WORKING),
            result(Capability.CONTACTS, CapabilityState.GRANTED_WORKING),
        )

        val changed = CapabilityDelta.changed(CapabilityDelta.snapshotOf(before), after)

        assertThat(changed.map { it.capability }).containsExactly(Capability.STORAGE_ACCESS)
    }

    @Test
    fun `the same state with a different detail is a change`() {
        // `storage_access` stays `denied` while its folder report goes from
        // "unreadable" to "0 file(s)" — a permission problem becoming a
        // recorder that is switched off. Collapsing those two would hide the
        // only evidence an admin has for a phone they cannot reach.
        val before = listOf(
            result(Capability.STORAGE_ACCESS, CapabilityState.DENIED, "call_rec: unreadable"),
        )
        val after = listOf(
            result(Capability.STORAGE_ACCESS, CapabilityState.DENIED, "call_rec: 0 file(s)"),
        )

        assertThat(CapabilityDelta.changed(CapabilityDelta.snapshotOf(before), after)).hasSize(1)
    }

    @Test
    fun `an empty snapshot reports everything`() {
        val results = Capability.entries.map { result(it, CapabilityState.UNKNOWN) }

        assertThat(CapabilityDelta.changed(emptyMap(), results)).hasSize(results.size)
    }

    @Test
    fun `a stored snapshot survives a round trip`() {
        val snapshot = CapabilityDelta.snapshotOf(
            listOf(
                result(Capability.MICROPHONE, CapabilityState.GRANTED_WORKING, "peak 812"),
                result(Capability.OEM_AUTOSTART, CapabilityState.UNKNOWN, null),
            ),
        )

        assertThat(CapabilityDelta.decode(CapabilityDelta.encode(snapshot))).isEqualTo(snapshot)
    }

    @Test
    fun `a corrupt snapshot reads as empty rather than throwing`() {
        // It is read inside a background worker. "Report everything again" is
        // a cost; an exception there is a phone that stops reporting at all.
        assertThat(CapabilityDelta.decode("not a snapshot")).isEmpty()
        assertThat(CapabilityDelta.decode("")).isEmpty()
    }

    @Test
    fun `a detail containing the separators cannot corrupt the next entry`() {
        val snapshot = CapabilityDelta.snapshotOf(
            listOf(
                result(Capability.STORAGE_ACCESS, CapabilityState.DENIED, "odd  detail  here"),
                result(Capability.CALL_LOG, CapabilityState.GRANTED_WORKING, "1 row"),
            ),
        )

        val decoded = CapabilityDelta.decode(CapabilityDelta.encode(snapshot))

        assertThat(decoded).hasSize(2)
        assertThat(decoded[Capability.CALL_LOG.wire]).contains("1 row")
    }
}
