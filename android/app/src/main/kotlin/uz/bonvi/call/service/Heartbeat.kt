package uz.bonvi.call.service

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.PowerManager
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.BuildConfig
import uz.bonvi.call.core.Capabilities
import uz.bonvi.call.core.Clock
import uz.bonvi.call.data.remote.api.DeviceCallsApi
import uz.bonvi.call.data.remote.dto.AppVariant
import uz.bonvi.call.data.remote.dto.DeviceHeartbeatIn
import uz.bonvi.call.data.remote.dto.NetworkType
import uz.bonvi.call.data.repository.CallQueueRepository
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.di.IoDispatcher
import javax.inject.Inject
import javax.inject.Singleton

/**
 * What the phone tells the server about itself (SPEC §4.4, UC-17).
 *
 * ═══ `app_version_code` is the whole point of this being a named field ═════
 * The minimum-version gate (N34) decides which handsets keep reporting. It
 * needs the version **code**, not the version string — and the code used to be
 * sent only at enrolment, so a phone that updated afterwards reported a new
 * string against an old code and the gate protected nothing. The live fleet
 * showed `unknown_version_count` at 5 of 5.
 *
 * The fix is not another header. `X-App-Version` and `X-App-Variant` already
 * ride on the interceptor, and adding a fourth is another thing to remember on
 * the next endpoint; `app_version_code` is a named contract field, so a
 * renamed or dropped value is a compile error rather than a silently absent
 * one. It is populated from the same `BuildConfig.VERSION_CODE` that
 * `EnrolmentRepository.appInfo()` sends at redeem, so the two can never
 * disagree.
 *
 * Everything else here is UC-17's device page: queue depth in records AND
 * bytes, battery and its optimisation exemption, storage, clock skew evidence,
 * and whether the capture service is actually running. All of it is a number
 * an admin acts on, which is why none of it is optional in practice even
 * though the schema allows null.
 */
@Singleton
class Heartbeat @Inject constructor(
    @ApplicationContext private val context: Context,
    private val api: DeviceCallsApi,
    private val queue: CallQueueRepository,
    private val session: SessionStore,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    /** What the server said back. `update` is what T82 acts on. */
    data class Result(
        val clockSkewSec: Int,
        val pendingCommands: Int,
        val updateRequired: Boolean,
        val minVersionCode: Int,
        val latestVersionCode: Int?,
        val apkUrl: String?,
        val messageUz: String?,
    )

    suspend fun send(): Result? = withContext(io) {
        if (session.snapshot.installationId == null) return@withContext null

        val depth = queue.depth()
        val body = DeviceHeartbeatIn(
            deviceEpochMs = Clock.epochMillis(),
            deviceTimezone = Clock.timezoneId(),

            appVersion = BuildConfig.VERSION_NAME,
            // ⚠️ The field the version gate reads. Same source as the value
            // sent at redeem, so enrolment and heartbeat cannot disagree.
            appVersionCode = BuildConfig.VERSION_CODE,
            appVariant = AppVariant.entries.first { it.value == BuildConfig.APP_VARIANT },
            apiLevel = Capabilities.sdkInt,

            serviceRunning = CaptureService.isRunning,
            captureEnabled = session.authStateSnapshot().canCapture,

            queueRecords = depth.pending,
            parkedRecords = depth.parked,
            queueBytes = depth.bytes,

            batteryLevel = batteryLevel(),
            batteryCharging = isCharging(),
            batteryOptimisationExempt = isExemptFromBatteryOptimisation(),
            powerSaveMode = isPowerSaveMode(),

            freeStorageBytes = context.filesDir.usableSpace,
            networkType = networkType(),
        )

        @Suppress("TooGenericExceptionCaught")
        val response = try {
            api.heartbeat(body)
        } catch (error: Exception) {
            // No network. A missed heartbeat is how the panel learns a phone is
            // offline (`device_offline_minutes`), so failing quietly here is
            // the correct behaviour, not a swallowed error.
            Timber.i("Heartbeat could not reach the server")
            return@withContext null
        }

        val out = response.body()
        if (!response.isSuccessful || out == null) return@withContext null

        Result(
            clockSkewSec = out.clockSkewSec,
            pendingCommands = out.pendingCommandCount ?: 0,
            updateRequired = out.update.required,
            minVersionCode = out.update.minVersionCode,
            latestVersionCode = out.update.latestVersionCode,
            apkUrl = out.update.apkUrl,
            messageUz = out.update.messageUz,
        )
    }

    private fun batteryLevel(): Int? =
        context.getSystemService(BatteryManager::class.java)
            ?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
            ?.takeIf { it in 0..100 }

    private fun isCharging(): Boolean? =
        context.getSystemService(BatteryManager::class.java)?.isCharging

    /** UC-03's `battery_exemption`, reported on every heartbeat rather than
     *  only at enrolment: an OEM update can revoke it silently, and the first
     *  symptom is a phone that stops reporting overnight. */
    private fun isExemptFromBatteryOptimisation(): Boolean? =
        context.getSystemService(PowerManager::class.java)
            ?.isIgnoringBatteryOptimizations(context.packageName)

    private fun isPowerSaveMode(): Boolean? =
        context.getSystemService(PowerManager::class.java)?.isPowerSaveMode

    /** Which connection the phone is on, for N14/N15's data accounting and for
     *  the upload policy's Wi-Fi-first rule. */
    fun networkType(): NetworkType? {
        val manager = context.getSystemService(ConnectivityManager::class.java) ?: return null
        val capabilities = manager.getNetworkCapabilities(manager.activeNetwork)
            ?: return NetworkType.NONE
        return when {
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> NetworkType.WIFI
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> NetworkType.CELLULAR
            else -> NetworkType.NONE
        }
    }

    fun onWifi(): Boolean = networkType() == NetworkType.WIFI

    fun onCellular(): Boolean = networkType() == NetworkType.CELLULAR
}
