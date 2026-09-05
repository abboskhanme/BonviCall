package uz.bonvi.call.arch

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.TestPaths
import java.io.File

/**
 * A generated DTO must actually carry its fields.
 *
 * ═══ The bug this exists for ═══════════════════════════════════════════════
 * `DeviceEventDetailIn`'s thirteen fields each generated as a **named, empty
 * Kotlin class** — `Attempts`, `ByUser`, `QueueBytes` — instead of `Int?`,
 * `Boolean?`, `Long?`. Pydantic puts a `title` on every inline
 * `anyOf: [T, null]` property, and openapi-generator treats a titled inline
 * schema as a type worth minting. The result compiles, so nothing errors: the
 * server is correct Python, the contract is valid OpenAPI, and the client
 * simply cannot set any of those fields.
 *
 * Same family as the `int64` and `uuid5` bugs — a defect that exists only in
 * the gap between two systems that are each right on their own, and invisible
 * from either side.
 *
 * **The server-side fix** is to drop the auto-generated `title` from inline
 * property schemas in `src/contract_export.py` before writing, or to give those
 * fields a named `Annotated` alias. Either way this test goes quiet on its own,
 * and until it does the list below names exactly what is broken.
 */
class GeneratedDtoShapeTest {

    private val dtoDir = File(
        TestPaths.appDir,
        "src/main/kotlin/uz/bonvi/call/data/remote/dto",
    )

    /**
     * Types that currently generate empty. ⚠️ This list only SHRINKS.
     *
     * Every one is a property of `DeviceEventDetailIn`, so `POST /events`
     * cannot carry any detail today: `step_timing` and `enrolment_stuck` still
     * fire with `kind` and `at`, which is what N40's measurement and the
     * assisted-install signal need, and the numeric detail is lost until the
     * contract stops minting a type per field.
     *
     * `ValidationErrorLocInner` is FastAPI's own `anyOf: [str, int]` and is not
     * ours to fix; it is never constructed by this app.
     */
    private val knownEmpty = setOf(
        "Attempts", "ByUser", "ClientCallId", "DeletedBytes", "DeletedRecords",
        "DeviceEventDetailInAudioMissingReason", "DeviceEventDetailInCaptureRoute",
        "DiscardedCount", "FreeStorageBytes", "FromVersion", "QueueBytes",
        "QueueRecords", "ToVersion", "ValidationErrorLocInner",
    )

    private fun emptyGeneratedTypes(): List<String> = dtoDir.listFiles()
        .orEmpty()
        .filter { it.extension == "kt" }
        .filter { file ->
            val text = file.readText()
            // A class with no @Json-annotated property is a type the generator
            // minted from a title rather than from a schema with fields.
            Regex("""\bclass ${Regex.escape(file.nameWithoutExtension)}\s*\(""")
                .containsMatchIn(text) && !text.contains("@Json") && !text.contains("enum class")
        }
        .map { it.nameWithoutExtension }
        .sorted()

    @Test
    fun `no NEW generated type is empty`() {
        val unexpected = emptyGeneratedTypes().filterNot { it in knownEmpty }

        assertThat(unexpected).isEmpty()
    }

    @Test
    fun `a listed type that gained its fields means the entry can go`() {
        // The self-deleting half, same shape as Int64WireContractTest: when the
        // contract stops minting these, this fails and the entry — eventually
        // the whole list and this class — is removed.
        val stillEmpty = emptyGeneratedTypes().toSet()
        val fixed = knownEmpty.filterNot { it in stillEmpty }

        assertThat(fixed).isEmpty()
    }

    @Test
    fun `the DTOs the app actually sends are all intact`() {
        // The list above is tolerable only because nothing on the capture or
        // enrolment path depends on those types. These are the ones that would
        // stop a call reaching the server.
        for (name in listOf(
            "DeviceCallIn", "DeviceCallOut", "DeviceHeartbeatIn", "DeviceRedeemIn",
            "OpenUploadIn", "DeviceCapabilityIn", "DeviceCallListOut",
        )) {
            val file = File(dtoDir, "$name.kt")
            assertThat(file.isFile).isTrue()
            assertThat(file.readText()).contains("@Json")
        }
    }
}
