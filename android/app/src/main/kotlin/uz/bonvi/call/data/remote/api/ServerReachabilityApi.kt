package uz.bonvi.call.data.remote.api

import retrofit2.Response
import retrofit2.http.GET
import retrofit2.http.Url

/**
 * "Is there a BonviCall server at this address?"
 *
 * `@Url` takes an absolute address, so this bypasses the configured base URL
 * and the interceptor that rewrites it — the whole point is to test an address
 * **before** committing to it. A typo has to surface as a typo here rather
 * than as "no internet" three screens later, which is a failure that already
 * happened on real hardware and cost an afternoon.
 *
 * `/healthz` is public and unauthenticated, so this works before enrolment and
 * on a phone whose token is the thing that is broken.
 */
interface ServerReachabilityApi {
    @GET
    suspend fun healthz(@Url absoluteUrl: String): Response<Unit>
}
