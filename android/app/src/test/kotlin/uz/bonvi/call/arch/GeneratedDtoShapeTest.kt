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
 * **Stripping the derived `title` was necessary and not sufficient.** With the
 * titles gone the generator stopped naming them `Attempts` and started naming
 * them `DeviceEventDetailInAttempts` — same defect, different name. The real
 * trigger is `additionalProperties: false` on the parent schema:
 *
 *   `DeviceHeartbeatIn.queue_bytes` and `DeviceEventDetailIn.queue_bytes` have
 *   BYTE-IDENTICAL schemas. The first generates as `kotlin.Long?`. The second
 *   generates as a minted empty class. The only difference between the two
 *   parents is that `DeviceEventDetailIn` declares
 *   `additionalProperties: false`.
 *
 * Which means **the fix for one finding caused this one**: `extra="forbid"` was
 * added to close the §8.5 free-form-map hole — correctly, and it should stay —
 * and openapi-generator responds to it by minting a model for every `anyOf`
 * property of that schema. Both decisions are right on their own; the defect is
 * only where they meet, which is the fifth time that has been true here.
 *
 * **Options for the server**, in the order I would try them: emit the closed
 * shape without `additionalProperties: false` in the exported document while
 * keeping `extra="forbid"` in Pydantic (the runtime still rejects extras, and
 * `DeviceContractPrivacyTest` checks for free-form MAPS rather than for the
 * keyword); or upgrade openapi-generator, which may simply not have this quirk
 * any more. Either way this test goes quiet on its own.
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
     * generator stops minting a type per field.
     *
     * It was nineteen entries before `make android-dto` learned to CLEAN the
     * output directory. openapi-generator does not delete files for schemas the
     * contract has dropped, so a stale DTO from a previous shape survived,
     * still compiled, and was indistinguishable from a current one. Seven is
     * the real number.
     *
     * `ValidationErrorLocInner` and `HTTPValidationError` are gone: the 422
     * shape is the N35 envelope now, generated as `ErrorResponse`/`ErrorBody`,
     * and this app parses the response it can actually receive.
     */
    private val knownEmpty = setOf(
        "DeviceEventDetailInAttempts",
        "DeviceEventDetailInAudioMissingReason",
        "DeviceEventDetailInByUser",
        "DeviceEventDetailInCaptureRoute",
        "DeviceEventDetailInClientCallId",
        "DeviceEventDetailInDeletedBytes",
        "DeviceEventDetailInFromVersion",
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
