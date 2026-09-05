package uz.bonvi.call.data.remote.api

import retrofit2.Response
import retrofit2.http.GET
import retrofit2.http.Query
import uz.bonvi.call.data.remote.dto.DeviceCallListOut

/**
 * The employee's own calls (client request, N41).
 *
 * Scoped **server-side by `agent_id`**. There is no parameter here that could
 * widen it and no filter applied afterwards — the narrowing is the server's
 * job, because the client is the thing that cannot be trusted to do it.
 *
 * The audio route is not declared here: it is streamed by the player through
 * OkHttp directly, so ExoPlayer issues its own `Range` requests and gets real
 * 206 responses rather than a buffered body Retrofit has already consumed.
 */
interface DeviceCallReadApi {

    @GET("calls")
    suspend fun myCalls(
        @Query("limit") limit: Int,
        @Query("cursor") cursor: String?,
        @Query("since") since: String? = null,
    ): Response<DeviceCallListOut>
}
