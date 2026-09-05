package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * The idempotency key (SPEC §3.10, D-05, **N2: duplicate rate must be 0**).
 *
 * The assertion that carries the most weight is `matches Python's uuid5`: the
 * server derives nothing — it only enforces `UNIQUE(client_call_id)` — but the
 * recovery sweep after a reinstall re-derives ids for calls already uploaded,
 * and if Kotlin and Python disagreed about UUIDv5 every one of those would
 * upload a second time. The JDK has no `uuid5`; `UUID.nameUUIDFromBytes` is
 * **version 3 (MD5)**, so the implementation is written out and pinned here
 * against a value produced by Python's `uuid.uuid5`.
 */
class ClientCallIdTest {

    private val registered = "+998901112233"

    @Test
    fun `matches Python's uuid5 for the same inputs`() {
        // Produced by:
        //   python3 -c "import uuid; print(uuid.uuid5(
        //     uuid.UUID('8f6e5a30-0d7e-5c9b-9d3f-6f1c0a5d4b21'),
        //     '901112233|outgoing|1772615791000|907776655'))"
        val id = ClientCallId.derive(
            registeredNumber = registered,
            direction = CallDirection.OUTGOING,
            startedAtEpochMillis = 1_772_615_791_000L,
            remoteNumber = "+998907776655",
        )

        assertThat(id).isEqualTo("364195cc-44ea-5df4-8f3f-b7612e26f32e")
    }

    @Test
    fun `it is a version 5 UUID, not version 3`() {
        // nameUUIDFromBytes would silently produce a v3 here and every id would
        // differ from the server's view of the same call.
        val id = ClientCallId.derive(registered, CallDirection.INCOMING, 1L, "901112233")
        assertThat(id[14]).isEqualTo('5')
        assertThat(id[19]).isIn(listOf('8', '9', 'a', 'b'))
    }

    @Test
    fun `the same call derives the same id after a reinstall`() {
        // The whole point: the recovery sweep rediscovers calls from the OS
        // call log with no app state at all, and must not mint new ids.
        val first = ClientCallId.derive(registered, CallDirection.OUTGOING, 1_700_000_000_000L, "901112233")
        val second = ClientCallId.derive(registered, CallDirection.OUTGOING, 1_700_000_000_000L, "901112233")

        assertThat(first).isEqualTo(second)
    }

    @Test
    fun `the number's format does not change the id`() {
        // A reinstall may store the registered number differently. The 9-digit
        // key is what goes into the name, so the id survives that.
        val ids = listOf("+998901112233", "998901112233", "901112233", "+998 90 111-22-33")
            .map { ClientCallId.derive(it, CallDirection.INCOMING, 5L, "(90) 777 66 55") }

        assertThat(ids.toSet()).hasSize(1)
    }

    @Test
    fun `each of the four facts changes the id`() {
        val base = ClientCallId.derive(registered, CallDirection.OUTGOING, 1_000L, "901112233")

        assertThat(ClientCallId.derive("+998907776655", CallDirection.OUTGOING, 1_000L, "901112233"))
            .isNotEqualTo(base)
        assertThat(ClientCallId.derive(registered, CallDirection.INCOMING, 1_000L, "901112233"))
            .isNotEqualTo(base)
        assertThat(ClientCallId.derive(registered, CallDirection.OUTGOING, 2_000L, "901112233"))
            .isNotEqualTo(base)
        assertThat(ClientCallId.derive(registered, CallDirection.OUTGOING, 1_000L, "907776655"))
            .isNotEqualTo(base)
    }

    @Test
    fun `a withheld caller id is stable and distinct, not a collision`() {
        // Two anonymous calls a second apart are two calls. `unknown` in the
        // name keeps them distinct via the timestamp rather than collapsing
        // them into one id.
        val first = ClientCallId.derive(registered, CallDirection.INCOMING, 1_000L, null)
        val second = ClientCallId.derive(registered, CallDirection.INCOMING, 2_000L, null)
        val alsoUnknown = ClientCallId.derive(registered, CallDirection.INCOMING, 1_000L, "")

        assertThat(first).isNotEqualTo(second)
        assertThat(first).isEqualTo(alsoUnknown)
    }

    @Test
    fun `the unreconciled path truncates to whole seconds`() {
        // Milliseconds from a live capture and from a call-log DATE never
        // agree, so the unreconciled id is derived from whole seconds — rule 2.
        assertThat(ClientCallId.truncateToSecond(1_772_615_791_412L))
            .isEqualTo(1_772_615_791_000L)
        assertThat(ClientCallId.truncateToSecond(1_772_615_791_999L))
            .isEqualTo(1_772_615_791_000L)
    }

    @Test
    fun `the namespace is the one the whole fleet shares`() {
        // Changing it re-mints every id in the fleet and duplicates the entire
        // call history.
        assertThat(ClientCallId.NAMESPACE.toString())
            .isEqualTo("8f6e5a30-0d7e-5c9b-9d3f-6f1c0a5d4b21")
    }
}
