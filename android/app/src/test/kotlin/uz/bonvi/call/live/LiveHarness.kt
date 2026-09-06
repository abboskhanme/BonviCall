package uz.bonvi.call.live

import com.squareup.moshi.Moshi
import kotlinx.coroutines.Dispatchers
import okhttp3.OkHttpClient
import org.junit.Assume
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import uz.bonvi.call.data.remote.BaseUrlInterceptor
import uz.bonvi.call.data.remote.BearerAuthInterceptor
import uz.bonvi.call.data.remote.DeviceHeadersInterceptor
import uz.bonvi.call.data.remote.api.DeviceAudioApi
import uz.bonvi.call.data.remote.api.DeviceAuthApi
import uz.bonvi.call.data.remote.api.DeviceCallReadApi
import uz.bonvi.call.data.remote.api.DeviceCallsApi
import uz.bonvi.call.data.remote.api.DeviceEnrolmentApi
import uz.bonvi.call.data.remote.api.ServerReachabilityApi
import uz.bonvi.call.di.NetworkModule
import java.util.concurrent.TimeUnit

/**
 * Drives the app's **real** wire layer against a **live** server.
 *
 * ═══ Why this exists ═══════════════════════════════════════════════════════
 * Six contract defects and two live walls have now been found on this project.
 * Every one lived in the gap between layers that were each individually
 * tested — correct Python on one side, valid OpenAPI in the middle, a
 * compiling Kotlin client on the other, and a defect only where they meet.
 * **Not one was caught by a test on either side.**
 *
 * So this builds the same Moshi, the same interceptors, the same generated
 * DTOs and the same Retrofit interfaces the app builds, and points them at a
 * running server. It is the one thing the project has never had.
 *
 * It **skips** rather than fails when no server is reachable, because a
 * developer without one running must still be able to run the suite. The
 * address comes from `-Dbonvicall.liveServer=…`, defaulting to the compose
 * stack on localhost.
 */
object LiveHarness {

    val baseUrl: String =
        System.getProperty("bonvicall.liveServer") ?: "http://localhost:8020"

    /** Skip the whole class when nothing is listening. */
    fun requireServer() {
        val reachable = runCatching {
            val connection = java.net.URL("$baseUrl/healthz").openConnection()
                as java.net.HttpURLConnection
            connection.connectTimeout = 3_000
            connection.readTimeout = 3_000
            connection.responseCode == 200
        }.getOrDefault(false)
        Assume.assumeTrue("No live server at $baseUrl — skipping", reachable)
    }

    /**
     * **The app's own Moshi**, called rather than rebuilt.
     *
     * The first version of this harness reconstructed it — and immediately
     * drifted, missing the `UuidAdapter` the app already had. Every test failed
     * with "Unable to create converter for DeviceRedeemOut", which is the exact
     * symptom of the real bug this file exists to catch.
     *
     * A harness that reimplements the thing it is testing tests the
     * reimplementation. `NetworkModule` is an `object`, so there is no reason
     * to copy it.
     */
    fun moshi(): Moshi = NetworkModule.moshi()

    fun client(session: FakeSession): OkHttpClient = OkHttpClient.Builder()
        .addInterceptor(BaseUrlInterceptor { session.baseUrl })
        .addInterceptor(DeviceHeadersInterceptor { session.installationId })
        .addInterceptor(BearerAuthInterceptor { session.accessToken })
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    fun retrofit(session: FakeSession): Retrofit = Retrofit.Builder()
        .baseUrl(session.baseUrl.trimEnd('/') + "/api/device/v1/")
        .client(client(session))
        .addConverterFactory(MoshiConverterFactory.create(moshi()))
        .build()

    fun enrolment(session: FakeSession): DeviceEnrolmentApi =
        retrofit(session).create(DeviceEnrolmentApi::class.java)

    fun calls(session: FakeSession): DeviceCallsApi =
        retrofit(session).create(DeviceCallsApi::class.java)

    fun callRead(session: FakeSession): DeviceCallReadApi =
        retrofit(session).create(DeviceCallReadApi::class.java)

    fun audio(session: FakeSession): DeviceAudioApi =
        retrofit(session).create(DeviceAudioApi::class.java)

    fun auth(session: FakeSession): DeviceAuthApi =
        retrofit(session).create(DeviceAuthApi::class.java)

    fun reachability(): ServerReachabilityApi = Retrofit.Builder()
        .baseUrl(baseUrl)
        .client(OkHttpClient.Builder().build())
        .addConverterFactory(MoshiConverterFactory.create(moshi()))
        .build()
        .create(ServerReachabilityApi::class.java)

    val io = Dispatchers.Unconfined
}

/**
 * `SessionStore` without DataStore.
 *
 * The only Android piece the wire layer needs is somewhere to keep a token and
 * a base URL. Faking it is what lets the REAL repositories, interceptors and
 * DTOs run in a JVM — which is where the defects live.
 */
class FakeSession(override var baseUrl: String = LiveHarness.baseUrl) : LiveSession {
    override var installationId: String? = null
    override var accessToken: String? = null
    override var refreshToken: String? = null
    override var registeredNumberE164: String? = null
    override var registeredNumberDisplay: String? = null
    override var agentName: String? = null
    override var simSubscriptionId: Int? = null
    override var verificationMethod: String? = null
    override var authState: String = "active"
}

/** What the wire layer actually needs from a session. */
interface LiveSession {
    var baseUrl: String
    var installationId: String?
    var accessToken: String?
    var refreshToken: String?
    var registeredNumberE164: String?
    var registeredNumberDisplay: String?
    var agentName: String?
    var simSubscriptionId: Int?
    var verificationMethod: String?
    var authState: String
}
