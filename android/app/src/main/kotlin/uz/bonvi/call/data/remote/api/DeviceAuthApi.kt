package uz.bonvi.call.data.remote.api

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.POST
import uz.bonvi.call.data.remote.dto.DeviceRefreshIn
import uz.bonvi.call.data.remote.dto.DeviceTokenPairOut

/** `POST /auth/refresh` (SPEC §4.3, T79). Also where N34's refusal arrives. */
interface DeviceAuthApi {
    @POST("auth/refresh")
    suspend fun refresh(@Body body: DeviceRefreshIn): Response<DeviceTokenPairOut>
}
