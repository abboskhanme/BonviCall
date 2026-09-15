package uz.bonvi.call.domain

/**
 * What changed since the phone last told the server, and how that is stored.
 *
 * Pure, and in `domain/` for the reason the whole layer exists: this decides
 * whether a background pass every fifteen minutes is free or is fifteen
 * minutes of pointless traffic on an employee's own data plan (N14), and it
 * decides whether a granted permission is ever noticed at all. Both are
 * testable as functions and neither is testable through a phone.
 */
object CapabilityDelta {

    /**
     * What counts as "the same answer as last time".
     *
     * The DETAIL is part of it on purpose: `storage_access` stays `denied`
     * while its folder report goes from "unreadable" to "0 file(s)", and the
     * difference between those two is the whole diagnosis on a handset nobody
     * can reach — one is a permission, the other is a recorder that is off.
     */
    fun fingerprint(result: CapabilityResult): String =
        "${result.state.wire}|${result.detail.orEmpty()}"

    /** The results worth sending, given what was sent before. */
    fun changed(
        previous: Map<String, String>,
        results: List<CapabilityResult>,
    ): List<CapabilityResult> = results.filter { result ->
        previous[result.capability.wire] != fingerprint(result)
    }

    fun snapshotOf(results: List<CapabilityResult>): Map<String, String> =
        results.associate { it.capability.wire to fingerprint(it) }

    // ═══ Storage format ════════════════════════════════════════════════════
    // A flat `capability=fingerprint` list rather than JSON: a corrupt entry
    // here must degrade to "report everything again", which a lenient split
    // gives for free, and never to an exception inside a background worker.

    /** Control characters, so neither can appear in an OEM's own detail text. */
    private const val RECORD = ""
    private const val FIELD = ""

    fun encode(snapshot: Map<String, String>): String =
        snapshot.entries.joinToString(RECORD) { (key, value) ->
            key.sanitised() + FIELD + value.sanitised()
        }

    fun decode(raw: String): Map<String, String> =
        raw.split(RECORD)
            .filter { it.isNotEmpty() }
            .mapNotNull { record ->
                val parts = record.split(FIELD, limit = 2)
                if (parts.size == 2) parts[0] to parts[1] else null
            }
            .toMap()

    private fun String.sanitised(): String = replace(RECORD, " ").replace(FIELD, " ")
}
