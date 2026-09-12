package uz.bonvi.call.live

import com.squareup.moshi.Moshi
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/**
 * Issues a real enrolment code, the way an admin does.
 *
 * The device tests need a fresh single-use code each time, and minting one
 * through the panel API is the only honest way to get it — a fixture code
 * would test a path nobody walks.
 */
object LiveAdmin {

    private const val EMAIL = "admin@bonvi.uz"
    private const val PASSWORD = "Bonvi2026!"

    private val client = OkHttpClient.Builder().build()
    private val json = "application/json".toMediaType()

    private var token: String? = null

    private fun login(): String? = token ?: runCatching {
        val response = client.newCall(
            Request.Builder()
                .url("${LiveHarness.baseUrl}/api/v1/auth/login")
                .post("""{"email":"$EMAIL","password":"$PASSWORD"}""".toRequestBody(json))
                .build(),
        ).execute()
        response.use {
            if (!it.isSuccessful) return null
            JSONObject(it.body!!.string()).getString("access_token")
        }
    }.getOrNull()?.also { token = it }

    private fun firstNumberId(bearer: String): String? = runCatching {
        client.newCall(
            Request.Builder()
                .url("${LiveHarness.baseUrl}/api/v1/numbers")
                .header("Authorization", "Bearer $bearer")
                .build(),
        ).execute().use { response ->
            if (!response.isSuccessful) return null
            JSONObject(response.body!!.string())
                .getJSONArray("items").getJSONObject(0).getString("id")
        }
    }.getOrNull()

    /** A fresh single-use code, or null when the admin path is unavailable —
     *  in which case the calling test returns rather than failing. */
    fun issueCode(): String? {
        val bearer = login() ?: return null
        val numberId = firstNumberId(bearer) ?: return null
        return runCatching {
            client.newCall(
                Request.Builder()
                    .url("${LiveHarness.baseUrl}/api/v1/numbers/$numberId/enrolment-code")
                    .header("Authorization", "Bearer $bearer")
                    .post("{}".toRequestBody(json))
                    .build(),
            ).execute().use { response ->
                if (!response.isSuccessful) return null
                JSONObject(response.body!!.string()).getString("code")
            }
        }.getOrNull()
    }

    /**
     * An enrolled installation with its number **verified**, so the capture
     * tests have something the server will accept calls from.
     *
     * Verification goes through the ADMIN attestation path (SPEC §9.3, T142)
     * rather than by faking a callback: it is a real route the product has, it
     * is the one an agent whose operator suppresses CLI actually uses, and it
     * is the only one reachable without a phone dialling a receiver.
     */
    /** [verifiedSession], but a fixture failure is a test failure rather than a
     *  silent skip. */
    fun requireVerifiedSession(): FakeSession = requireNotNull(verifiedSession()) {
        "Could not build a verified installation against ${LiveHarness.baseUrl}. " +
            "Every capture test would otherwise pass without running."
    }

    fun verifiedSession(): FakeSession? {
        val bearer = login() ?: return null
        val code = issueCode() ?: return null
        val session = FakeSession()

        val redeemed = kotlinx.coroutines.runBlocking {
            LiveHarness.enrolment(session).redeem(
                uz.bonvi.call.data.remote.dto.DeviceRedeemIn(
                    code = code,
                    device = uz.bonvi.call.data.remote.dto.DeviceInfoIn(
                        androidRelease = "9", apiLevel = 28,
                        buildFingerprintHash = "c".repeat(64),
                        manufacturer = "Samsung", model = "SM-A515F",
                    ),
                    app = uz.bonvi.call.data.remote.dto.AppInfoIn(
                        uz.bonvi.call.data.remote.dto.AppVariant.LEGACY28, "1.0.0", 1,
                    ),
                    deviceFingerprint = "c".repeat(64),
                    deviceEpochMs = System.currentTimeMillis(),
                    deviceTimezone = "Asia/Tashkent",
                    simSubscriptionId = 2, simSlot = 0,
                ),
            )
        }.body() ?: return null

        session.installationId = redeemed.installationId.toString()
        session.accessToken = redeemed.provisionalToken
        session.registeredNumberE164 = redeemed.number.e164

        val attested = attest(bearer, redeemed.installationId.toString())
        if (!attested) return null

        // Attestation issues the real pair; the app learns it by polling the
        // verification status, which is exactly what E5 does.
        val status = kotlinx.coroutines.runBlocking {
            LiveHarness.enrolment(session).callbackStatus(redeemed.installationId.toString())
        }
        status.body()?.tokens?.let {
            session.accessToken = it.accessToken
            session.refreshToken = it.refreshToken
        }
        return session
    }

    /**
     * Issue a command the way the panel does (T55, UC-16).
     *
     * `202 Accepted` means queued for delivery, not done — the device half is
     * what makes it done, which is exactly what the test using this checks.
     *
     * @return the command id, or null when the admin path is unavailable.
     */
    fun issueCommand(installationId: String, kind: String, number: String? = null): String? {
        val bearer = login() ?: return null
        val body = if (number == null) {
            """{"kind":"$kind"}"""
        } else {
            """{"kind":"$kind","number":"$number"}"""
        }
        return runCatching {
            client.newCall(
                Request.Builder()
                    .url("${LiveHarness.baseUrl}/api/v1/devices/$installationId/commands")
                    .header("Authorization", "Bearer $bearer")
                    .post(body.toRequestBody(json))
                    .build(),
            ).execute().use { response ->
                if (!response.isSuccessful) return null
                JSONObject(response.body!!.string()).getString("id")
            }
        }.getOrNull()
    }

    /** What the panel shows for one command: `sent`, `acknowledged`, `failed`. */
    fun commandStatus(commandId: String): String? {
        val bearer = login() ?: return null
        return runCatching {
            client.newCall(
                Request.Builder()
                    .url("${LiveHarness.baseUrl}/api/v1/commands/$commandId")
                    .header("Authorization", "Bearer $bearer")
                    .build(),
            ).execute().use { response ->
                if (!response.isSuccessful) return null
                JSONObject(response.body!!.string()).getString("status")
            }
        }.getOrNull()
    }

    /** UC-08, from the admin side, so the device half can be observed. */
    fun revoke(installationId: String): Boolean {
        val bearer = login() ?: return false
        return runCatching {
            client.newCall(
                Request.Builder()
                    .url("${LiveHarness.baseUrl}/api/v1/installations/$installationId/revoke")
                    .header("Authorization", "Bearer $bearer")
                    .post("""{"reason":"live integration harness"}""".toRequestBody(json))
                    .build(),
            ).execute().use { it.isSuccessful }
        }.getOrDefault(false)
    }

    private fun attest(bearer: String, installationId: String): Boolean = runCatching {
        client.newCall(
            Request.Builder()
                .url("${LiveHarness.baseUrl}/api/v1/installations/$installationId/attest")
                .header("Authorization", "Bearer $bearer")
                .post(
                    """{"reason":"live integration harness"}""".toRequestBody(json),
                )
                .build(),
        ).execute().use { it.isSuccessful }
    }.getOrDefault(false)

    @Suppress("unused")
    private val moshi: Moshi = LiveHarness.moshi()
}
