package uz.bonvi.call.core

import com.google.common.truth.Truth.assertThat
import org.json.JSONObject
import org.junit.Test
import uz.bonvi.call.TestPaths

/**
 * The device client knows every error code the server can emit.
 *
 * `code` is machine contract (CONVENTIONS.md §9): the upload queue branches on
 * it to decide retry, park or drop, and a code it does not recognise is a
 * decision it cannot make. The catalogue is `contract/error-codes.json`,
 * generated from `server/src/core/errors.py`.
 *
 * [ErrorCode.fromWire] still returns null for an unknown string on purpose — a
 * newer server must not crash an APK we cannot force-update — but this test
 * makes "unknown" a build-time conversation rather than a runtime surprise.
 */
class ErrorCodeContractTest {

    private fun contractCodes(): Set<String> {
        val file = TestPaths.contractDir.resolve("error-codes.json")
        assertThat(file.isFile).isTrue()
        val codes = JSONObject(file.readText()).getJSONArray("codes")
        return (0 until codes.length()).map { codes.getString(it) }.toSet()
    }

    @Test
    fun `every server error code has a Kotlin constant`() {
        val known = ErrorCode.entries.map { it.wire }.toSet()
        assertThat(known).containsExactlyElementsIn(contractCodes())
    }

    @Test
    fun `an unknown code is null rather than an exception`() {
        // A server ahead of this APK must not take the fleet down.
        assertThat(ErrorCode.fromWire("a_code_from_a_newer_server")).isNull()
    }

    @Test
    fun `a 5xx is retryable and a 4xx is not`() {
        assertThat(ApiFailure(503, "internal_error", null).isRetryable).isTrue()
        assertThat(ApiFailure(429, "rate_limited", null).isRetryable).isTrue()
        // 426 must never be retried in a loop and must never destroy the queue:
        // an old client drains its backlog first and is refused afterwards.
        assertThat(ApiFailure(426, "app_version_unsupported", null).isRetryable).isFalse()
        assertThat(ApiFailure(409, "audio_not_attributable", null).isRetryable).isFalse()
    }
}
