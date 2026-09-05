package uz.bonvi.call.data.repository

import timber.log.Timber
import uz.bonvi.call.domain.MyCallsGateway
import javax.inject.Inject
import javax.inject.Singleton

/**
 * ⚠️ **STUB. Waiting on `GET /api/device/v1/calls`.**
 *
 * The device surface currently has no read routes at all — it can post calls
 * and upload audio and cannot read anything back. `docs/DEVICE-READ-API.md` is
 * the spec handed to `build-backend`; this returns [MyCallsGateway.Result.NotAvailable]
 * until it lands.
 *
 * `NotAvailable` is deliberately a distinct outcome from `Failed` and
 * `Offline`. The screen says something different and TRUTHFUL for each: "not
 * yet available" is not "something went wrong", and telling an employee their
 * calls failed to load when the feature is simply not deployed is the kind of
 * small lie that makes the honest messages elsewhere less believable.
 *
 * TODO(device-read-api): replace with a Retrofit implementation. When the
 * contract lands, `make android-dto` generates the DTOs and this file becomes
 * one interface plus a mapper — nothing above it changes.
 */
@Singleton
class PendingMyCallsGateway @Inject constructor() : MyCallsGateway {

    override suspend fun page(cursor: String?, limit: Int): MyCallsGateway.Result {
        Timber.i("Own-calls endpoint is not deployed yet; showing the waiting state")
        return MyCallsGateway.Result.NotAvailable
    }

    override suspend fun audioUrl(callId: String): String? = null
}
