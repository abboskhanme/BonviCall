package uz.bonvi.call.arch

import com.google.common.truth.Truth.assertThat
import org.json.JSONObject
import org.junit.Test
import uz.bonvi.call.TestPaths

/**
 * **The wire schema is the allow-list** (CONVENTIONS.md §8.5, N28).
 *
 * "A device DTO may not contain a free-form map. A field the contract does not
 * name cannot leave the phone."
 *
 * The rule is checked here against `contract/openapi-device-v1.json` rather
 * than against generated Kotlin, for two reasons. It works before the DTOs are
 * generated, and when it fails it can name the SERVER schema that has to
 * change — the generator only ever reproduces what the contract says.
 *
 * Only device→server schemas are in scope. A map in a RESPONSE is a shape the
 * phone receives, not data leaving it, so it is not a privacy question.
 */
class DeviceContractPrivacyTest {

    /**
     * Known violations, each attached to the task that removes it.
     *
     * ⚠️ This list only shrinks. An entry here is debt with a name on it, not a
     * permission — the rule applies to every schema not listed, from today.
     *
     * **It is empty, and it got there the way it was supposed to.** On
     * 2026-09-05 it held `DeviceEventIn.detail`, which was
     * `Dict[str, str | int | bool | None]`: the value types were constrained,
     * the KEYS were not, so an arbitrary key/value pair could still leave the
     * handset. `build-backend` replaced it with `DeviceEventDetailIn` — named
     * fields only — and constrained `kind` to a lower-case identifier at the
     * same time, because an unbounded free-text field is itself a way off the
     * phone. `DeviceVerificationStatusOut.tokens` went the same way.
     *
     * Keep this property. The next free-form map added to a device request
     * fails the build, and having to add a line here is the point at which
     * somebody has to justify it.
     */
    private val knownViolations = emptySet<String>()

    private val schemas: JSONObject by lazy {
        val file = TestPaths.contractDir.resolve("openapi-device-v1.json")
        assertThat(file.isFile).isTrue()
        JSONObject(file.readText()).getJSONObject("components").getJSONObject("schemas")
    }

    /** Device→server bodies. FastAPI names them `...In` by our own convention
     *  (CONVENTIONS.md §12: `Device<Noun>In` / `Device<Noun>Out`). */
    private fun inboundSchemaNames(): List<String> =
        schemas.keys().asSequence().filter { it.endsWith("In") }.toList()

    private fun freeFormProperties(schemaName: String): List<String> {
        val schema = schemas.getJSONObject(schemaName)
        val properties = schema.optJSONObject("properties") ?: return emptyList()
        return properties.keys().asSequence().mapNotNull { property ->
            val definition = properties.getJSONObject(property)
            val variants = buildList {
                add(definition)
                for (key in listOf("anyOf", "oneOf")) {
                    val list = definition.optJSONArray(key) ?: continue
                    for (index in 0 until list.length()) add(list.getJSONObject(index))
                }
            }
            val isMap = variants.any {
                it.optString("type") == "object" && it.has("additionalProperties")
            }
            if (isMap) "$schemaName.$property" else null
        }.toList()
    }

    @Test
    fun `no device request schema carries a free-form map`() {
        val offenders = inboundSchemaNames()
            .flatMap { freeFormProperties(it) }
            .filterNot { it in knownViolations }

        assertThat(offenders).isEmpty()
    }

    @Test
    fun `the known-violation list is accurate and only shrinks`() {
        // A stale entry is worse than none: it silences a rule for a field that
        // no longer exists, and the next field with that name inherits the
        // exemption without anybody deciding to grant it.
        val actual = inboundSchemaNames().flatMap { freeFormProperties(it) }.toSet()
        val stale = knownViolations - actual
        assertThat(stale).isEmpty()
    }

    @Test
    fun `every schema the app sends is described by name`() {
        // Sanity: the contract must actually contain the device surface, or
        // this whole test passes by scanning nothing.
        assertThat(inboundSchemaNames()).contains("DeviceCallIn")
    }
}
