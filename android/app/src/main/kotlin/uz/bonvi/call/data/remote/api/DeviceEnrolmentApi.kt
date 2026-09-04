package uz.bonvi.call.data.remote.api

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Query
import uz.bonvi.call.data.remote.dto.DeviceCallbackStartOut
import uz.bonvi.call.data.remote.dto.DeviceCapabilityBatchIn
import uz.bonvi.call.data.remote.dto.DeviceCapabilityBatchOut
import uz.bonvi.call.data.remote.dto.DeviceEventBatchIn
import uz.bonvi.call.data.remote.dto.DeviceEventBatchOut
import uz.bonvi.call.data.remote.dto.DeviceMsisdnVerifyIn
import uz.bonvi.call.data.remote.dto.DeviceRedeemIn
import uz.bonvi.call.data.remote.dto.DeviceRedeemOut
import uz.bonvi.call.data.remote.dto.DeviceVerificationStatusOut

/**
 * The enrolment surface of the device API (SPEC §4.2, §8, §9).
 *
 * Path-versioned (`/api/device/v1`, never a header) and additive-only inside
 * the major version: the fleet is ~15 phones that cannot be force-updated
 * (CONVENTIONS.md §4). The DTOs are generated from
 * `contract/openapi-device-v1.json`, so a field renamed on the server is a
 * compile error here rather than a runtime null.
 *
 * `Response<T>` rather than a bare `T` on purpose: the §9 error envelope is
 * read from the body of a non-2xx, and the failure code — `code_expired`,
 * `number_mismatch`, `callback_receiver_down` — is what each screen branches
 * on to say something specific rather than "xatolik".
 */
interface DeviceEnrolmentApi {

    /** E1. The single-use code is the credential; there is no token yet. */
    @POST("enrolment/redeem")
    suspend fun redeem(@Body body: DeviceRedeemIn): Response<DeviceRedeemOut>

    /** §9.1, route 1. `line1_number` may be null and the SERVER decides — the
     *  app never treats "I don't know" as a match. */
    @POST("enrolment/verify/msisdn")
    suspend fun verifyMsisdn(
        @Body body: DeviceMsisdnVerifyIn,
    ): Response<DeviceVerificationStatusOut>

    /** §9.2, route 2. 503 `callback_receiver_down` means "tell the agent to
     *  call the admin", never "dial into nothing". */
    @POST("enrolment/verify/callback/start")
    suspend fun startCallback(): Response<DeviceCallbackStartOut>

    @GET("enrolment/verify/callback/status")
    suspend fun callbackStatus(
        @Query("verification_id") verificationId: String,
    ): Response<DeviceVerificationStatusOut>

    /** E2. Posted immediately after every check so the panel shows where the
     *  agent is stuck within 2 minutes (UC-03 AC). */
    @POST("capabilities")
    suspend fun reportCapabilities(
        @Body body: DeviceCapabilityBatchIn,
    ): Response<DeviceCapabilityBatchOut>

    /** Step timings and the "stuck" signal. N40 is measured by the product on
     *  every future enrolment, not only by a stopwatch on test day. */
    @POST("events")
    suspend fun reportEvents(@Body body: DeviceEventBatchIn): Response<DeviceEventBatchOut>
}
