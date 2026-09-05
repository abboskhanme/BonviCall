package uz.bonvi.call.domain

import uz.bonvi.call.core.Phone
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.UUID

/**
 * The idempotency key (SPEC §3.10, D-05, N2: duplicate rate must be **0**).
 *
 * ═══ Why not a random UUID ═════════════════════════════════════════════════
 * The prototype used a Room autoincrement, which restarts at 1 after a
 * reinstall and collides (R5). A random UUIDv4 per call fixes collisions but
 * not the reinstall case: once the app's database is gone, the call-log
 * recovery sweep (UC-13) rediscovers the same calls and would mint new ids,
 * uploading every call a second time.
 *
 * So the id is a **UUIDv5 over facts that survive a reinstall**, because they
 * come from the OS call log rather than from app state. Two independent
 * installs on the same handset derive the same id for the same call, and the
 * server's `UNIQUE(client_call_id)` turns the second upload into an upsert.
 *
 * ═══ The rules that make it work ═══════════════════════════════════════════
 * 1. `startedAtEpochMillis` is the **call log's `DATE` value, verbatim** — the
 *    only timestamp two independent installs will agree on.
 * 2. A record is not uploaded until it has been reconciled against the call
 *    log, or 15 minutes have passed with no matching row. In that second case
 *    the id uses the live start time truncated to whole seconds and the record
 *    carries `reconciled_with_call_log = false`.
 * 3. **The id is computed once and stored forever.** If reconciliation later
 *    corrects the start time, the app sends a correction to the SAME id — it
 *    never derives a new one. That is what stops a ±1 s difference producing
 *    two rows.
 */
object ClientCallId {

    /** The fixed BonviCall namespace from SPEC §3.10. Changing it re-mints
     *  every id in the fleet and duplicates the entire call history. */
    val NAMESPACE: UUID = UUID.fromString("8f6e5a30-0d7e-5c9b-9d3f-6f1c0a5d4b21")

    /** Rule 2's deadline: after this long with no call-log row, derive from the
     *  live start time and mark the record unreconciled. */
    const val RECONCILE_DEADLINE_MS: Long = 15 * 60 * 1000L

    /**
     * @param registeredNumber the number this installation records. Its 9-digit
     *        key is used, so the id does not change if the number is stored in a
     *        different format after a reinstall.
     * @param startedAtEpochMillis the call log's `DATE`, verbatim, or the live
     *        start time truncated to whole seconds when unreconciled.
     * @param remoteNumber as the device saw it; `unknown` when unkeyable, so a
     *        withheld caller id still yields a stable, distinct value.
     */
    fun derive(
        registeredNumber: String,
        direction: CallDirection,
        startedAtEpochMillis: Long,
        remoteNumber: String?,
    ): String {
        val registeredKey = Phone.phoneKey(registeredNumber) ?: UNKNOWN
        val remoteKey = Phone.phoneKey(remoteNumber) ?: UNKNOWN
        val name = "$registeredKey|${direction.wire}|$startedAtEpochMillis|$remoteKey"
        return uuidV5(NAMESPACE, name).toString()
    }

    /** Rule 2: the live start time, truncated to whole seconds. Milliseconds
     *  from a live capture and from a call-log row never agree. */
    fun truncateToSecond(epochMillis: Long): Long = (epochMillis / 1000L) * 1000L

    /**
     * RFC 4122 §4.3 name-based UUID, SHA-1 variant.
     *
     * Written out because the JDK has no `uuid5` — `UUID.nameUUIDFromBytes` is
     * **version 3 (MD5)** and would disagree with the server's `uuid.uuid5`.
     * A silent disagreement here means every call uploaded twice, which is N2's
     * one number.
     */
    private fun uuidV5(namespace: UUID, name: String): UUID {
        val digest = MessageDigest.getInstance("SHA-1")
        digest.update(toBytes(namespace))
        digest.update(name.toByteArray(StandardCharsets.UTF_8))
        val hash = digest.digest()

        hash[6] = ((hash[6].toInt() and 0x0F) or 0x50).toByte() // version 5
        hash[8] = ((hash[8].toInt() and 0x3F) or 0x80).toByte() // RFC 4122 variant

        var most = 0L
        var least = 0L
        for (index in 0 until 8) most = (most shl 8) or (hash[index].toLong() and 0xFF)
        for (index in 8 until 16) least = (least shl 8) or (hash[index].toLong() and 0xFF)
        return UUID(most, least)
    }

    private fun toBytes(uuid: UUID): ByteArray {
        val bytes = ByteArray(16)
        var most = uuid.mostSignificantBits
        var least = uuid.leastSignificantBits
        for (index in 7 downTo 0) {
            bytes[index] = (most and 0xFF).toByte()
            most = most shr 8
        }
        for (index in 15 downTo 8) {
            bytes[index] = (least and 0xFF).toByte()
            least = least shr 8
        }
        return bytes
    }

    private const val UNKNOWN = "unknown"
}
