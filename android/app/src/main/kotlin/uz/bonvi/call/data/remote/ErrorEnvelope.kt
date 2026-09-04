package uz.bonvi.call.data.remote

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import retrofit2.Response
import timber.log.Timber
import uz.bonvi.call.core.ApiFailure

/**
 * The §9 error envelope, read off a non-2xx response.
 *
 * Not generated: the envelope is not a route's response schema, so it does not
 * appear in `contract/openapi-device-v1.json` as one. Its shape is fixed by
 * CONVENTIONS.md §9 and by `contract/error-codes.json`, and
 * `ErrorCodeContractTest` already checks the code catalogue against that file.
 *
 * Every screen in the enrolment flow branches on `code`. That is the difference
 * between "Bu kod allaqachon ishlatilgan" with a next action and a generic
 * error, and on a 15-minute unaided install (N40) it is most of the difference
 * between finishing and giving up.
 */
@JsonClass(generateAdapter = true)
data class ErrorEnvelope(
    @Json(name = "error") val error: ErrorBody?,
) {
    @JsonClass(generateAdapter = true)
    data class ErrorBody(
        @Json(name = "code") val code: String,
        @Json(name = "message") val message: String? = null,
        @Json(name = "request_id") val requestId: String? = null,
    )
}

/**
 * Turn a failed [Response] into an [ApiFailure].
 *
 * A body that is not the envelope still produces a failure with the status —
 * a response the client cannot parse is indistinguishable from a corrupted one,
 * and the queue has to be able to decide whether to retry either way.
 */
fun <T> Response<T>.toFailure(moshi: Moshi): ApiFailure {
    val raw = runCatching { errorBody()?.string() }.getOrNull()
    val envelope = raw?.let {
        runCatching { moshi.adapter(ErrorEnvelope::class.java).fromJson(it) }
            .onFailure { error -> Timber.w(error, "Response body was not the error envelope") }
            .getOrNull()
    }
    return ApiFailure(
        status = code(),
        code = envelope?.error?.code ?: "http_${code()}",
        message = envelope?.error?.message,
        requestId = envelope?.error?.requestId,
    )
}
