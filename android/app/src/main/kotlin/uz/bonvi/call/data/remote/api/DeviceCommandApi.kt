package uz.bonvi.call.data.remote.api

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import uz.bonvi.call.data.remote.dto.DeviceAckIn
import uz.bonvi.call.data.remote.dto.DeviceCommandListOut
import java.util.UUID

/**
 * Click-to-call and the other device commands (SPEC §4.6, UC-16, T80).
 *
 * The REST half of a two-transport channel: the socket carries a command in
 * about a second, and this is how a phone that was asleep, offline, or woken by
 * a push collects whatever is waiting. **Both paths reach the same lifecycle**
 * — the ack is the same shape either way — so a command delivered over one is
 * indistinguishable from the other in the panel.
 *
 * Acking returns whatever else is pending, so a phone that just dialled does
 * not need a second round trip to find the next command.
 */
interface DeviceCommandApi {

    /** Anything the phone should act on now. Expired commands are not
     *  returned, so an empty list is a complete answer. */
    @GET("commands")
    suspend fun pending(): Response<DeviceCommandListOut>

    /**
     * The outcome, and implicitly the latency (UC-16 measures a 5-second bar).
     *
     * **Every command is acked, including a refused one.** A command with no
     * outcome is indistinguishable from one that never arrived, and those need
     * different fixes.
     */
    @POST("commands/{command_id}/ack")
    suspend fun acknowledge(
        @Path("command_id") commandId: UUID,
        @Body body: DeviceAckIn,
    ): Response<DeviceCommandListOut>
}
