package uz.bonvi.call.data.remote.api

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.POST
import uz.bonvi.call.data.remote.dto.DeviceCallBatchIn
import uz.bonvi.call.data.remote.dto.DeviceCallBatchOut
import uz.bonvi.call.data.remote.dto.DeviceCallLogDeltaIn
import uz.bonvi.call.data.remote.dto.DeviceCallLogDeltaOut
import uz.bonvi.call.data.remote.dto.DeviceHeartbeatIn
import uz.bonvi.call.data.remote.dto.DeviceHeartbeatOut

/**
 * The ingest surface (SPEC §4.4, T68/T74).
 *
 * `POST /calls` is a **batch upsert keyed on `client_call_id`**, so delivery is
 * at-least-once and storage is exactly-once: the device may send the same call
 * as often as it likes and the server answers 200 with the same id. That is why
 * the upload worker can be simple — it never has to reason about whether a
 * previous attempt got through, and a reply lost on the way back costs one
 * retry rather than one duplicate (N2 requires a duplicate rate of 0).
 *
 * These three are also the **drain routes** of the minimum-version gate
 * (CONVENTIONS.md §4.4): an app below the minimum version keeps being allowed
 * to upload its backlog and is refused only afterwards. Refusing an old client
 * must never destroy data.
 */
interface DeviceCallsApi {

    /** Up to 50 calls or 256 KiB per batch (SPEC §4.0). */
    @POST("calls")
    suspend fun uploadCalls(@Body body: DeviceCallBatchIn): Response<DeviceCallBatchOut>

    /**
     * UC-13's evidence. What the device saw in its own call log versus what it
     * uploaded, per day — including the calls the privacy boundary discarded.
     * It is what turns "this phone captured nothing today" from a silence into
     * a number the gap report can explain.
     */
    @POST("call-log-delta")
    suspend fun reportCallLogDelta(
        @Body body: DeviceCallLogDeltaIn,
    ): Response<DeviceCallLogDeltaOut>

    /** Queue depth, battery, clock skew, capture health. Also how the server
     *  learns a `replaced` installation has finished draining (SPEC §9.3). */
    @POST("heartbeat")
    suspend fun heartbeat(@Body body: DeviceHeartbeatIn): Response<DeviceHeartbeatOut>
}
