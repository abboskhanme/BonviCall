package uz.bonvi.call.arch

import com.google.common.truth.Truth.assertThat
import org.json.JSONObject
import org.junit.Test
import uz.bonvi.call.TestPaths

/**
 * 64-bit wire fields must say so (CONVENTIONS.md §6 and §10).
 *
 * Pydantic's `int` is unbounded, so a field declared `int` serialises fine in
 * Python and reaches OpenAPI as `{"type": "integer"}` with **no format**.
 * openapi-generator maps a formatless integer to `kotlin.Int` — 32 bits.
 *
 * `System.currentTimeMillis()` is about 1.77e12. `Int.MAX_VALUE` is 2.1e9.
 * Every `device_epoch_ms` on the wire is three orders of magnitude too large
 * for the type the contract asks the client to use, and free storage on a
 * 128 GB handset (1.28e11) is the same story. The server stores all of them as
 * BIGINT, so the data model is right and only the wire schema is
 * under-specified.
 *
 * `android/scripts/widen_int64.py` patches the generated DTOs as a stopgap.
 * **This test is how that stopgap dies:** a listed field that gains
 * `format: int64` fails here, which is the signal to delete its entry, and the
 * script goes with the last one.
 *
 * The fix on the server:
 *
 *     Int64 = Annotated[int, Field(json_schema_extra={"format": "int64"})]
 *     device_epoch_ms: Int64
 *
 * Raised for build-backend on 2026-09-05.
 */
class Int64WireContractTest {

    /**
     * Fields whose real range exceeds 32 bits and whose contract type does not
     * say so. ⚠️ This list only SHRINKS.
     */
    private val awaitingInt64Format = setOf(
        "DeviceRedeemIn.device_epoch_ms",
        "DeviceCallIn.device_epoch_ms",
        "DeviceHeartbeatIn.device_epoch_ms",
        "DeviceHeartbeatIn.free_storage_bytes",
        "DeviceHeartbeatIn.queue_bytes",
        "DeviceHeartbeatIn.cellular_bytes_month",
        "DeviceEventDetailIn.free_storage_bytes",
        "DeviceEventDetailIn.queue_bytes",
        "DeviceEventDetailIn.deleted_bytes",
    )

    /**
     * Formatless `*_bytes` fields that genuinely FIT in 32 bits, with the
     * reason. Kept separate from [awaitingInt64Format] because that list means
     * "cannot hold its range", and these can: every one of them counts the
     * bytes of a SINGLE audio file. A 20-minute recording at N17's 24 kbps is
     * about 3.6 MB, and `upload.max_chunk_bytes` is 4 MiB — three orders of
     * magnitude below Int.MAX_VALUE.
     *
     * They are still listed rather than silently skipped, so that a decision
     * was made about each one.
     */
    private val acceptedAsInt32 = setOf(
        "UploadStatusOut.received_bytes",
        "ChunkAcceptedOut.received_bytes",
        "OpenUploadOut.received_bytes",
    )

    private val schemas: JSONObject by lazy {
        val file = TestPaths.contractDir.resolve("openapi-device-v1.json")
        assertThat(file.isFile).isTrue()
        JSONObject(file.readText()).getJSONObject("components").getJSONObject("schemas")
    }

    private fun integerFormat(qualified: String): String? {
        val (schemaName, property) = qualified.split('.', limit = 2)
        val schema = schemas.optJSONObject(schemaName) ?: return MISSING
        val definition = schema.optJSONObject("properties")?.optJSONObject(property)
            ?: return MISSING
        val variants = buildList {
            add(definition)
            definition.optJSONArray("anyOf")?.let { list ->
                for (index in 0 until list.length()) add(list.getJSONObject(index))
            }
        }
        val integer = variants.firstOrNull { it.optString("type") == "int" + "eger" }
            ?: return MISSING
        return integer.optString("format").ifEmpty { null }
    }

    @Test
    fun `a listed field that gained int64 means the workaround can go`() {
        val fixed = awaitingInt64Format.filter { integerFormat(it) == "int64" }

        assertThat(fixed).isEmpty()
    }

    @Test
    fun `the two lists do not overlap`() {
        // One says "cannot hold its range", the other says "can". A field in
        // both would mean nobody decided.
        assertThat(awaitingInt64Format.intersect(acceptedAsInt32)).isEmpty()
    }

    @Test
    fun `every listed field still exists on the wire`() {
        // A stale entry silences the check for a field that is gone, and the
        // next field with that name inherits the exemption without anybody
        // deciding to grant it.
        val missing = (awaitingInt64Format + acceptedAsInt32)
            .filter { integerFormat(it) == MISSING }

        assertThat(missing).isEmpty()
    }

    @Test
    fun `no NEW formatless 64-bit-looking field appears without being listed`() {
        // Catches the next one. A field named *_epoch_ms or *_bytes with no
        // format is the same bug arriving again.
        val suspects = mutableListOf<String>()
        for (schemaName in schemas.keys()) {
            val properties = schemas.getJSONObject(schemaName).optJSONObject("properties")
                ?: continue
            for (property in properties.keys()) {
                if (!property.endsWith("_epoch_ms") && !property.endsWith("_bytes")) continue
                val qualified = "$schemaName.$property"
                if (qualified in awaitingInt64Format || qualified in acceptedAsInt32) continue
                if (integerFormat(qualified) == null) suspects += qualified
            }
        }

        assertThat(suspects).isEmpty()
    }

    private companion object {
        /** Distinguishes "no format" from "no such field". */
        const val MISSING = "<missing>"
    }
}
