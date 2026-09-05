package uz.bonvi.call.arch

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.TestPaths
import java.io.File

/**
 * A generated DTO must actually carry its fields.
 *
 * ═══ The bug this exists for, and its actual cause ═════════════════════════
 * `DeviceEventDetailIn`'s optional fields generate as **named, empty Kotlin
 * classes** instead of `Int?`, `Boolean?`, `Long?`. The result compiles, so
 * nothing errors: the server is correct Python, the contract is valid OpenAPI,
 * and the client simply cannot set any of those fields.
 *
 * **The cause, and how it was closed.** Stripping the derived `title` was
 * necessary and not sufficient: with the titles gone the generator stopped
 * naming them `Attempts` and started naming them `DeviceEventDetailInAttempts`.
 * The real trigger was `additionalProperties: false` on the parent schema, and
 * the proof was byte-identical — `DeviceHeartbeatIn.queue_bytes` and
 * `DeviceEventDetailIn.queue_bytes` had the SAME schema, and only the second
 * minted a class, because only its parent was closed.
 *
 * Which meant the fix for one finding caused this one: `extra="forbid"` was
 * added to close the §8.5 free-form-map hole. **It was fixed by upgrading the
 * generator (v7.10.0 → v7.25.0), so `extra="forbid"` stays and the contract
 * still says the shape is closed.** The alternative — omitting
 * `additionalProperties: false` from the exported document — would have made
 * the contract say less than the server enforces, and was not needed.
 */
class GeneratedDtoShapeTest {

    private val dtoDir = File(
        TestPaths.appDir,
        "src/main/kotlin/uz/bonvi/call/data/remote/dto",
    )

    /**
     * Types that generate empty. ⚠️ This list only SHRINKS.
     *
     * **It is empty, and it emptied itself.** It held seven entries — every
     * optional field of `DeviceEventDetailIn`, unsettable from the client —
     * until `make android-dto` moved from openapi-generator v7.10.0 to
     * v7.25.0. The quirk is fixed upstream; nothing was weakened to get there,
     * and `extra="forbid"` stays exactly as it was.
     *
     * The first test below is the guard that remains: a NEW empty type fails
     * it, whatever mints it next.
     */
    private val knownEmpty = emptySet<String>()

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
            // The 422 body every screen branches on. Generated, not
            // hand-written, and it is now the shape the server actually sends.
            "ErrorResponse", "ErrorBody",
        )) {
            val file = File(dtoDir, "$name.kt")
            assertThat(file.isFile).isTrue()
            assertThat(file.readText()).contains("@Json")
        }
    }
}
