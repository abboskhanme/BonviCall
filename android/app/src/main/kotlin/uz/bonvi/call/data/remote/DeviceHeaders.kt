package uz.bonvi.call.data.remote

import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.Response
import uz.bonvi.call.BuildConfig
import uz.bonvi.call.core.Capabilities

/**
 * The two headers every device request must carry (CONVENTIONS.md §4.5).
 *
 * A missing one is a 400 `header_missing`, never a 500 — and the minimum-version
 * gate (N34) reads `X-App-Version` to decide whether this build is still
 * allowed anything other than draining its queue. Adding them in one
 * interceptor rather than per call is what stops a new endpoint being written
 * without them.
 */
class DeviceHeadersInterceptor(
    private val installationId: () -> String?,
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val builder = chain.request().newBuilder()
            .header(APP_VERSION, BuildConfig.VERSION_NAME)
            .header(APP_VARIANT, BuildConfig.APP_VARIANT)
            .header(OS_VERSION, Capabilities.osRelease)
        installationId()?.let { builder.header(INSTALLATION_ID, it) }
        return chain.proceed(builder.build())
    }

    companion object {
        const val APP_VERSION = "X-App-Version"
        const val INSTALLATION_ID = "X-Installation-Id"
        const val APP_VARIANT = "X-App-Variant"
        const val OS_VERSION = "X-OS-Version"
    }
}

/**
 * Bearer token for the calls that have one.
 *
 * E1's redeem is the exception and must stay one: the single-use code IS the
 * credential there, and there is no token until it succeeds.
 */
class BearerAuthInterceptor(private val token: () -> String?) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val bearer = token() ?: return chain.proceed(chain.request())
        return chain.proceed(
            chain.request().newBuilder().header("Authorization", "Bearer $bearer").build(),
        )
    }
}

/**
 * Points every request at the server this installation belongs to.
 *
 * Retrofit fixes its base URL at construction, but the server is not known
 * until a code is redeemed — the enrolment code carries the host it belongs to,
 * and hard-coding production would make a local server (T29, M1) unreachable.
 * Rewriting scheme/host/port per request is the standard answer and keeps the
 * relative paths in `DeviceEnrolmentApi` unchanged.
 *
 * It refuses to downgrade the scheme: a configured `http://` base cannot turn
 * an https request into a cleartext one. The network security config would
 * refuse it anyway; this makes the intent local and readable (N22).
 */
class BaseUrlInterceptor(private val baseUrl: () -> String) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val configured = baseUrl().toHttpUrlOrNull() ?: return chain.proceed(chain.request())
        val original = chain.request().url
        val rewritten = original.newBuilder()
            .scheme(configured.scheme)
            .host(configured.host)
            .port(configured.port)
            .build()
        return chain.proceed(chain.request().newBuilder().url(rewritten).build())
    }
}
