package uz.bonvi.call.data.repository

import com.squareup.moshi.Moshi
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.data.remote.api.DeviceCallReadApi
import uz.bonvi.call.data.remote.dto.DeviceCallOut
import uz.bonvi.call.data.remote.toFailure
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.di.NetworkModule
import uz.bonvi.call.domain.AudioState
import uz.bonvi.call.domain.CallDirection
import uz.bonvi.call.domain.CallDisposition
import uz.bonvi.call.domain.CaptureRoute
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.MyCall
import uz.bonvi.call.domain.MyCallsGateway
import uz.bonvi.call.domain.MyCallsPage
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The employee's own calls, read from the server.
 *
 * Mapping only. The two rules it must not break:
 *
 * 1. **`audioState` is copied, never derived.** It needs
 *    `call_audio.deleted_at`, which the call row does not carry — computing it
 *    here from `has_audio` would offer a play button for a recording retention
 *    has removed, and the employee would learn the app is broken when it is
 *    working exactly as designed.
 * 2. **No filtering.** The narrowing to this agent is the server's, by
 *    `agent_id`. A client-side filter over a wider response is not a boundary,
 *    it is a decoration on one.
 */
@Singleton
class RetrofitMyCallsGateway @Inject constructor(
    private val api: DeviceCallReadApi,
    private val session: SessionStore,
    private val moshi: Moshi,
    @IoDispatcher private val io: CoroutineDispatcher,
) : MyCallsGateway {

    override suspend fun page(cursor: String?, limit: Int): MyCallsGateway.Result =
        withContext(io) {
            @Suppress("TooGenericExceptionCaught")
            val response = try {
                api.myCalls(limit = limit, cursor = cursor)
            } catch (error: Exception) {
                // Broad, and the specific failure is no network — the normal
                // case for a phone in the field. Distinct from Failed because
                // the screen says something different and true for each.
                Timber.i("Own-calls list could not reach the server")
                return@withContext MyCallsGateway.Result.Offline
            }

            val body = response.body()
            if (!response.isSuccessful || body == null) {
                return@withContext MyCallsGateway.Result.Failed(response.toFailure(moshi).code)
            }

            MyCallsGateway.Result.Page(
                MyCallsPage(
                    items = body.items.map { it.toDomain() },
                    nextCursor = body.nextCursor,
                    hasMore = body.hasMore,
                ),
            )
        }

    /**
     * The absolute stream URL.
     *
     * Built rather than fetched: the player streams it through OkHttp itself so
     * ExoPlayer issues real `Range` requests and gets 206 responses, which is
     * what makes seek on a 20-minute recording work without downloading the
     * whole file over cellular (N43).
     */
    override suspend fun audioUrl(callId: String): String? {
        val base = session.snapshot.baseUrl.trimEnd('/')
        return "$base${NetworkModule.DEVICE_API_PREFIX}calls/$callId/audio"
    }

    private fun DeviceCallOut.toDomain() = MyCall(
        id = id.toString(),
        clientCallId = clientCallId.toString(),
        direction = CallDirection.entries.first { it.wire == direction.value },
        disposition = CallDisposition.entries.first { it.wire == disposition.value },
        remoteNumber = remoteNumber,
        contactName = contactName,
        startedAtEpochMillis = startedAt.toInstant().toEpochMilli(),
        durationSec = durationSec,
        // Copied. Never derived — see the class docstring.
        audioState = AudioState.fromWire(audioState.value),
        audioMissingReason = audioMissingReason?.let { reason ->
            AudioMissingReason.entries.first { it.wire == reason.value }
        },
        captureRoute = captureRoute?.let { route ->
            CaptureRoute.entries.first { it.wire == route.value }
        },
    )
}
