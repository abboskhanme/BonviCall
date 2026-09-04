package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.json.JSONObject
import org.junit.Test
import uz.bonvi.call.TestPaths

/**
 * The domain enums say the same words as the wire contract.
 *
 * `contract/openapi-device-v1.json` is generated from the server's Pydantic
 * schemas by `make contract`. These enums are the pure-Kotlin vocabulary the
 * rest of the app reasons about (SPEC §7.1), and the two must not drift: a
 * `capture_route` value renamed on the server should fail the Android BUILD,
 * not become a 422 on a fleet of 15 phones that cannot be force-updated
 * (CONVENTIONS.md §1, §4).
 *
 * The check is deliberately exact in both directions. A value the server has
 * and Kotlin does not means the app cannot report something the panel expects;
 * a value Kotlin has and the server does not means the app can send something
 * the server will reject.
 */
class WireEnumContractTest {

    private val schemas: JSONObject by lazy {
        val file = TestPaths.contractDir.resolve("openapi-device-v1.json")
        assertThat(file.isFile).isTrue()
        JSONObject(file.readText()).getJSONObject("components").getJSONObject("schemas")
    }

    private fun contractValues(schema: String): Set<String> {
        assertThat(schemas.has(schema)).isTrue()
        val values = schemas.getJSONObject(schema).getJSONArray("enum")
        return (0 until values.length()).map { values.getString(it) }.toSet()
    }

    private fun assertMatches(schema: String, kotlinValues: Set<String>) {
        assertThat(kotlinValues).containsExactlyElementsIn(contractValues(schema))
    }

    @Test
    fun `CaptureRoute matches the contract`() {
        // The panel's device page and the M0 per-model baseline both read this
        // field; a mismatch makes both wrong and neither loud.
        assertMatches("CaptureRoute", CaptureRoute.entries.map { it.wire }.toSet())
    }

    @Test
    fun `AudioMissingReason matches the contract`() {
        // NOT NULL on the server and never free text (N5). The gap report
        // groups by this value, so an unknown one is a row nobody can explain.
        assertMatches("AudioMissingReason", AudioMissingReason.entries.map { it.wire }.toSet())
    }

    @Test
    fun `CallDirection matches the contract`() {
        assertMatches("CallDirection", CallDirection.entries.map { it.wire }.toSet())
    }

    @Test
    fun `CallDisposition matches the contract`() {
        assertMatches("CallDisposition", CallDisposition.entries.map { it.wire }.toSet())
    }

    @Test
    fun `CallSource matches the contract`() {
        assertMatches("CallSource", CallSource.entries.map { it.wire }.toSet())
    }

    @Test
    fun `AppVariant matches the contract and the two product flavours`() {
        val fromContract = contractValues("AppVariant")
        assertThat(AppVariant.entries.map { it.wire }.toSet()).containsExactlyElementsIn(fromContract)
        // The flavour names in app/build.gradle.kts are these strings. If a
        // flavour is renamed, BuildConfig.APP_VARIANT stops matching the wire
        // enum and per-variant capture rate becomes unqueryable.
        assertThat(fromContract).containsExactly("legacy28", "modern34")
    }
}
