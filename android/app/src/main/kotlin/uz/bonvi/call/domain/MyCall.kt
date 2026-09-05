package uz.bonvi.call.domain

/**
 * One of the employee's own calls, **as the server holds it** (client request,
 * N41).
 *
 * ═══ Why this is not the local queue ═══════════════════════════════════════
 * The point of the screen is the employee seeing their own record **as the
 * company sees it**. A list built from the local queue would show calls that
 * never uploaded — which the company does not have — and hide calls the
 * recovery sweep found in the OS call log, which it does. Those two errors
 * point in opposite directions and both destroy the value of the screen.
 *
 * So this type mirrors a server response and is filled from
 * `GET /api/device/v1/calls`. The narrowing to this agent's calls is done
 * server-side; there is no client-side filter over a wider response, because
 * the client is the thing that cannot be trusted to do it.
 */
data class MyCall(
    /** Server id. Used for the audio route, not for identity. */
    val id: String,
    /** The device's own key, so a row can be matched to a local record. */
    val clientCallId: String,
    val direction: CallDirection,
    val disposition: CallDisposition,
    val remoteNumber: String?,
    /** Resolved on the device at capture time, one number to one name (T139). */
    val contactName: String?,
    val startedAtEpochMillis: Long,
    val durationSec: Int,
    /** What the SERVER holds, not what the device believes it sent. */
    val hasAudio: Boolean,
    /** Always present, even with audio (N5). This screen is where an employee
     *  learns that *qayd etish* and *yozib olish* are different things. */
    val audioMissingReason: AudioMissingReason,
    val captureRoute: CaptureRoute,
) {
    /** What to show where a play button would be. Never a dead control. */
    val playable: Boolean get() = hasAudio
}

/** A page of them. Keyset, because the panel's rule applies here too. */
data class MyCallsPage(
    val items: List<MyCall>,
    val nextCursor: String?,
    val hasMore: Boolean,
)

/**
 * Reads the employee's own calls from the server.
 *
 * An interface because the endpoint does not exist yet
 * (`docs/DEVICE-READ-API.md` is the spec handed to `build-backend`). Everything
 * above it — the screen, the state, the Uzbek reason rendering — is built and
 * tested against this, so landing the endpoint is one Retrofit interface and a
 * binding, not a redesign.
 */
interface MyCallsGateway {

    sealed interface Result {
        data class Page(val page: MyCallsPage) : Result

        /** The endpoint is not deployed yet. Distinct from an error, because
         *  the screen says something different and truthful for each. */
        data object NotAvailable : Result

        data class Failed(val code: String?) : Result
        data object Offline : Result
    }

    suspend fun page(cursor: String?, limit: Int = DEFAULT_LIMIT): Result

    /** An absolute, authenticated URL the player can stream with `Range`.
     *  Null when this call has no audio the server holds. */
    suspend fun audioUrl(callId: String): String?

    companion object {
        /** A phone screen. 1 000-row pages are the panel's problem. */
        const val DEFAULT_LIMIT = 50
    }
}
