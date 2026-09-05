package uz.bonvi.call.di

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import uz.bonvi.call.data.remote.BaseUrlInterceptor
import uz.bonvi.call.data.remote.BearerAuthInterceptor
import uz.bonvi.call.data.remote.DeviceHeadersInterceptor
import uz.bonvi.call.data.remote.OffsetDateTimeAdapter
import uz.bonvi.call.data.remote.TokenAuthenticator
import uz.bonvi.call.data.remote.api.DeviceAuthApi
import uz.bonvi.call.data.remote.api.DeviceCallsApi
import uz.bonvi.call.data.remote.api.DeviceEnrolmentApi
import uz.bonvi.call.data.session.SessionStore
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

/**
 * The HTTP stack.
 *
 * **HTTPS only, and certificate errors are fatal** (N22,
 * CONVENTIONS-CLIENT.md §9). There is no `hostnameVerifier`, no custom
 * `TrustManager` and no `sslSocketFactory` override in this file, and there
 * must never be: the thing a bypass would expose is the audio of every call the
 * fleet makes. Cleartext is refused by the network security config, which is
 * enforced by the platform rather than by this code.
 */
@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides
    @Singleton
    fun moshi(): Moshi = Moshi.Builder()
        .add(OffsetDateTimeAdapter())
        // Reflection LAST: the generated DTOs carry codegen adapters and are
        // matched first; the reflective factory only catches the handful of
        // hand-written wire types (the error envelope).
        .add(KotlinJsonAdapterFactory())
        .build()

    @Provides
    @Singleton
    fun okHttp(
        session: SessionStore,
        authenticator: TokenAuthenticator,
    ): OkHttpClient = OkHttpClient.Builder()
        // T79/N25: a 401 refreshes once and replays. A REFUSED refresh writes
        // auth_expired and holds the queue — it never discards.
        .authenticator(authenticator)
        .addInterceptor(BaseUrlInterceptor { session.snapshot.baseUrl })
        .addInterceptor(DeviceHeadersInterceptor { session.snapshot.installationId })
        .addInterceptor(BearerAuthInterceptor { session.snapshot.accessToken })
        // A phone on a weak cell connection is the normal case, not the edge
        // case. Long enough to finish, short enough that the upload worker
        // retries rather than parking a live socket.
        .connectTimeout(CONNECT_TIMEOUT_SEC, TimeUnit.SECONDS)
        .readTimeout(READ_TIMEOUT_SEC, TimeUnit.SECONDS)
        .writeTimeout(WRITE_TIMEOUT_SEC, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    @Provides
    @Singleton
    fun retrofit(client: OkHttpClient, moshi: Moshi): Retrofit =
        Retrofit.Builder()
            // A placeholder: BaseUrlInterceptor rewrites the host per request,
            // because the server this installation belongs to is not known
            // until a code is redeemed.
            .baseUrl(SessionStore.DEFAULT_BASE_URL + DEVICE_API_PREFIX)
            .client(client)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()

    @Provides
    @Singleton
    fun enrolmentApi(retrofit: Retrofit): DeviceEnrolmentApi =
        retrofit.create(DeviceEnrolmentApi::class.java)

    @Provides
    @Singleton
    fun callsApi(retrofit: Retrofit): DeviceCallsApi = retrofit.create(DeviceCallsApi::class.java)

    @Provides
    @Singleton
    fun authApi(retrofit: Retrofit): DeviceAuthApi = retrofit.create(DeviceAuthApi::class.java)

    /** Path versioning, never a header (CONVENTIONS.md §4.1). */
    const val DEVICE_API_PREFIX = "/api/device/v1/"

    private const val CONNECT_TIMEOUT_SEC = 15L
    private const val READ_TIMEOUT_SEC = 30L
    private const val WRITE_TIMEOUT_SEC = 60L
}
