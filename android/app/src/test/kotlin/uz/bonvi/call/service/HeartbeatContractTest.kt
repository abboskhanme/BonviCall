package uz.bonvi.call.service

import com.google.common.truth.Truth.assertThat
import org.json.JSONObject
import org.junit.Test
import uz.bonvi.call.TestPaths

/**
 * The heartbeat carries the version **code** (T82's prerequisite, N34).
 *
 * ═══ The bug this pins ═════════════════════════════════════════════════════
 * The minimum-version gate decides which handsets keep reporting, and it needs
 * the numeric code. It used to be sent only at enrolment, so a phone that
 * updated afterwards reported a new version STRING against an old code — and
 * the gate protected nothing. On the live fleet `unknown_version_count` was
 * 5 of 5.
 *
 * The fix is a **named contract field** rather than a fourth header:
 * `X-App-Version` and `X-App-Variant` already ride on an interceptor, and
 * adding another is one more thing to remember on the next endpoint. A named
 * field renamed or dropped on the server is a compile error here.
 *
 * This test asserts the field exists in the contract and that the app sends it
 * from the same `BuildConfig.VERSION_CODE` the enrolment payload uses, so the
 * two cannot disagree.
 */
class HeartbeatContractTest {

    private val schemas: JSONObject by lazy {
        JSONObject(TestPaths.contractDir.resolve("openapi-device-v1.json").readText())
            .getJSONObject("components").getJSONObject("schemas")
    }

    @Test
    fun `the heartbeat schema has app_version_code`() {
        val properties = schemas.getJSONObject("DeviceHeartbeatIn").getJSONObject("properties")
        assertThat(properties.has("app_version_code")).isTrue()
    }

    @Test
    fun `the app populates it, and from BuildConfig`() {
        // Grepping the source is crude and it is the right check here: the
        // failure being prevented is a field left null, which no type system
        // catches because the schema allows null.
        val heartbeat = TestPaths.kotlinSources().single { it.name == "Heartbeat.kt" }.readText()
        assertThat(heartbeat).contains("appVersionCode = BuildConfig.VERSION_CODE")
    }

    @Test
    fun `enrolment and heartbeat send the same value`() {
        // If these ever diverge the gate strands a phone that has already
        // updated: a new string, an old code, and a minimum raised between them.
        val enrolment = TestPaths.kotlinSources()
            .single { it.name == "EnrolmentRepository.kt" }.readText()
        assertThat(enrolment).contains("versionCode = BuildConfig.VERSION_CODE")

        val heartbeat = TestPaths.kotlinSources().single { it.name == "Heartbeat.kt" }.readText()
        assertThat(heartbeat).contains("BuildConfig.VERSION_CODE")
    }

    @Test
    fun `the heartbeat reports queue depth in records AND bytes`() {
        // SPEC §5.2's device page needs both: "12 records" and "12 records,
        // 400 MB" are different conversations with an agent.
        val heartbeat = TestPaths.kotlinSources().single { it.name == "Heartbeat.kt" }.readText()
        assertThat(heartbeat).contains("queueRecords")
        assertThat(heartbeat).contains("queueBytes")
        assertThat(heartbeat).contains("parkedRecords")
    }
}
