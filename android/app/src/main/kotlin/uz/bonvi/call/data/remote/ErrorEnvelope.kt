package uz.bonvi.call.data.remote

import com.squareup.moshi.Moshi
import retrofit2.Response
import timber.log.Timber
import uz.bonvi.call.core.ApiFailure
import uz.bonvi.call.data.remote.dto.ErrorResponse

/**
 * The §9 error envelope, read off a non-2xx response.
 *
 * ═══ It is GENERATED now, and that closed a real hole ══════════════════════
 * This file used to declare `ErrorEnvelope` by hand, because the envelope was
 * not in the contract as a response schema. It is now: `ErrorResponse` and
 * `ErrorBody` are generated like everything else, so a renamed field is a
 * compile error rather than a null (CONVENTIONS.md §1).
 *
 * What made the hand-written version worse than it looked: FastAPI documented
 * every route's 422 as `HTTPValidationError` — `{"detail": [...]}` — a shape
 * **this server has never sent**, because `validation_error_handler` answers
 * with the N35 envelope like everything else. A client generated faithfully
 * against the old contract would have failed to parse *the one response that
 * tells it what it got wrong*. The hand-written parser worked only because it
 * ignored the documented shape and matched reality.
 *
 * Every screen in the enrolment flow branches on `code`. That is the difference
 * between "Bu kod allaqachon ishlatilgan" with a next action and a generic
 * error, and on a 15-minute unaided install it is most of the difference
 * between finishing and giving up.
 */

/**
 * Turn a failed [Response] into an [ApiFailure].
 *
 * A body that is not the envelope still produces a failure carrying the status:
 * a response the client cannot parse is indistinguishable from a corrupted one,
 * and the upload queue has to be able to decide whether to retry either way.
 */
fun <T> Response<T>.toFailure(moshi: Moshi): ApiFailure {
    val raw = runCatching { errorBody()?.string() }.getOrNull()
    val envelope = raw?.let {
        runCatching { moshi.adapter(ErrorResponse::class.java).fromJson(it) }
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
