package uz.bonvi.call.enrolment

import com.squareup.moshi.Moshi
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.BuildConfig
import uz.bonvi.call.core.ApiFailure
import uz.bonvi.call.core.Capabilities
import uz.bonvi.call.core.Clock
import uz.bonvi.call.data.remote.api.DeviceEnrolmentApi
import uz.bonvi.call.data.remote.dto.AppInfoIn
import uz.bonvi.call.data.remote.dto.AppVariant
import uz.bonvi.call.data.remote.dto.DeviceCapabilityBatchIn
import uz.bonvi.call.data.remote.dto.DeviceCapabilityIn
import uz.bonvi.call.data.remote.dto.DeviceEventBatchIn
import uz.bonvi.call.data.remote.dto.DeviceEventDetailIn
import uz.bonvi.call.data.remote.dto.DeviceEventIn
import uz.bonvi.call.data.remote.dto.DeviceInfoIn
import uz.bonvi.call.data.remote.dto.DeviceMsisdnVerifyIn
import uz.bonvi.call.data.remote.dto.DeviceRedeemIn
import uz.bonvi.call.data.remote.toFailure
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.CapabilityResult
import uz.bonvi.call.domain.NumberVerification
import java.time.OffsetDateTime
import javax.inject.Inject
import javax.inject.Singleton
import uz.bonvi.call.data.remote.dto.Capability as CapabilityDto
import uz.bonvi.call.data.remote.dto.CapabilityState as CapabilityStateDto

/**
 * Everything E1–E6 asks of the server (SPEC §4.2, §8, §9).
 *
 * ═══ The provisional token, and why E1 is not "done" ═══════════════════════
 * `POST /enrolment/redeem` returns a **provisional** token, not the real pair.
 * The access/refresh pair is issued only once the handset has proved it is on
 * the registered number, and until then the server accepts nothing: an
 * unverified installation cannot upload a single call.
 *
 * So the UI must never present "installed" as "done". [EnrolmentState] carries
 * that distinction explicitly rather than leaving it to a screen to remember,
 * because a phone that says it is finished and uploads nothing is the failure
 * mode this whole flow exists to avoid — and it is invisible from the handset.
 */
@Singleton
class EnrolmentRepository @Inject constructor(
    private val api: DeviceEnrolmentApi,
    private val session: SessionStore,
    private val moshi: Moshi,
    private val deviceFacts: DeviceFacts,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    /** Success or a typed failure. Never an exception across this boundary:
     *  every screen has to say something specific about every failure. */
    sealed interface Result<out T> {
        data class Ok<T>(val value: T) : Result<T>
        data class Failed(val failure: ApiFailure) : Result<Nothing>
        data class Offline(val cause: Throwable) : Result<Nothing>
    }

    /** What E1 learned, and what the rest of the flow needs. */
    data class Redeemed(
        val installationId: String,
        val agentName: String,
        /** N41: shown from this moment on, on every screen. */
        val numberDisplay: String,
        val numberE164: String,
        /** True when the number still has to be proven. Almost always true. */
        val verificationRequired: Boolean,
        val callbackMsisdn: String?,
        val receiverStatus: String?,
        val windowSeconds: Int,
    )

    /** E1. The single-use code is the only credential; there is no token yet. */
    suspend fun redeem(code: String, simSubscriptionId: Int?, simSlot: Int?): Result<Redeemed> =
        call {
            val response = api.redeem(
                DeviceRedeemIn(
                    code = code.trim().uppercase(),
                    device = deviceFacts.deviceInfo(),
                    app = deviceFacts.appInfo(),
                    deviceFingerprint = deviceFacts.fingerprint(),
                    deviceEpochMs = Clock.epochMillis(),
                    deviceTimezone = Clock.timezoneId(),
                    simSubscriptionId = simSubscriptionId,
                    simSlot = simSlot,
                ),
            )
            val body = response.body()
            if (!response.isSuccessful || body == null) {
                return@call Result.Failed(response.toFailure(moshi))
            }

            // Saved before anything else: N41's sentence must be true from now
            // on, including if the app is killed on the next screen.
            session.saveEnrolment(
                installationId = body.installationId.toString(),
                agentName = body.agent.fullName,
                numberDisplay = body.number.display,
                numberE164 = body.number.e164,
            )
            // PROVISIONAL. It gets the phone through verification and nothing
            // else — no call upload is accepted until the number is proven.
            session.saveProvisionalToken(body.provisionalToken)

            Result.Ok(
                Redeemed(
                    installationId = body.installationId.toString(),
                    agentName = body.agent.fullName,
                    numberDisplay = body.number.display,
                    numberE164 = body.number.e164,
                    verificationRequired = body.verification.required,
                    callbackMsisdn = body.verification.callbackMsisdn,
                    receiverStatus = body.verification.receiverStatus?.value,
                    windowSeconds = body.verification.windowSeconds,
                ),
            )
        }

    /**
     * §9.1, route 1.
     *
     * The MSISDN is sent as the SIM reported it — including null — and the
     * SERVER decides. The client-side rule in [NumberVerification.checkMsisdn]
     * exists so the UI can skip a pointless round trip when the SIM said
     * nothing, which is the common case on Uzbek SIMs; it never *claims* a
     * match on its own.
     */
    suspend fun verifyMsisdn(
        line1Number: String?,
        subscriptionId: Int?,
        simSlot: Int?,
        carrierName: String?,
    ): Result<VerificationStatus> = call {
        inferredProvenMethod = NumberVerification.Method.SIM_MSISDN
        val response = api.verifyMsisdn(
            DeviceMsisdnVerifyIn(
                line1Number = line1Number,
                subscriptionId = subscriptionId,
                simSlot = simSlot,
                carrierName = carrierName,
            ),
        )
        val body = response.body()
        if (!response.isSuccessful || body == null) {
            return@call Result.Failed(response.toFailure(moshi))
        }
        Result.Ok(persistTokensIfIssued(body))
    }

    data class CallbackChallenge(
        val verificationId: String,
        /** Shown in large type. The agent dials THIS. */
        val callbackMsisdn: String,
        val expiresAt: OffsetDateTime,
        val pollAfterMs: Int,
    )

    /** §9.2 step 1. A 503 `callback_receiver_down` means "tell the agent to
     *  contact the admin", never "dial into nothing". */
    suspend fun startCallback(): Result<CallbackChallenge> = call {
        inferredProvenMethod = NumberVerification.Method.CALLBACK
        val response = api.startCallback()
        val body = response.body()
        if (!response.isSuccessful || body == null) {
            return@call Result.Failed(response.toFailure(moshi))
        }
        Result.Ok(
            CallbackChallenge(
                verificationId = body.verificationId.toString(),
                callbackMsisdn = body.callbackMsisdn,
                expiresAt = body.expiresAt,
                pollAfterMs = body.pollAfterMs ?: DEFAULT_POLL_MS,
            ),
        )
    }

    data class VerificationStatus(
        val state: String,
        val failure: NumberVerification.CallbackOutcome?,
        val installationActive: Boolean,
        val method: NumberVerification.Method?,
    ) {
        val isMatched: Boolean get() = state == "matched" || state == "attested"
    }

    suspend fun callbackStatus(verificationId: String): Result<VerificationStatus> = call {
        val response = api.callbackStatus(verificationId)
        val body = response.body()
        if (!response.isSuccessful || body == null) {
            return@call Result.Failed(response.toFailure(moshi))
        }
        Result.Ok(persistTokensIfIssued(body))
    }

    /**
     * E2. Posted immediately after every check, so the panel shows where the
     * agent is stuck **within 2 minutes** (UC-03 AC) — during a live rollout
     * that is the difference between a phone call and a lost afternoon.
     */
    suspend fun reportCapabilities(results: List<CapabilityResult>): Result<Unit> = call {
        val now = Clock.toWire(Clock.epochMillis())
        val response = api.reportCapabilities(
            DeviceCapabilityBatchIn(
                capabilities = results.map { result ->
                    DeviceCapabilityIn(
                        capability = CapabilityDto.entries.first { it.value == result.capability.wire },
                        state = CapabilityStateDto.entries.first { it.value == result.state.wire },
                        checkedAt = OffsetDateTime.parse(now),
                        detail = result.detail,
                    )
                },
            ),
        )
        if (!response.isSuccessful) Result.Failed(response.toFailure(moshi)) else Result.Ok(Unit)
    }

    /**
     * N40, measured by the product rather than by a stopwatch on test day.
     *
     * Every step posts how long it took, so the 15-minute bar keeps being
     * measured as the fleet grows and phones get replaced — the trial is not a
     * one-off, it is the first sample.
     */
    suspend fun reportStepTiming(step: String, durationMs: Long, attempts: Int? = null) {
        // ⚠️ `detail` is null, not because we have nothing to say but because
        // every field on `DeviceEventDetailIn` currently generates as an empty
        // Kotlin class — see `GeneratedDtoShapeTest`. `kind` and `at` still
        // carry the measurement N40 needs; the attempt count is lost until the
        // contract stops minting a named type per field.
        postEvent("step_timing", detail = null, step = step, durationMs = durationMs)
    }

    /**
     * The "Yordam kerak" button (SPEC §8.1).
     *
     * **A stalled enrolment must be an event, not silence** — a silently
     * stalled rollout looks exactly like a working one until go-live.
     */
    suspend fun reportStuck(step: String) {
        // Same reason as above. `kind` is what moves the agent to
        // needs_assisted_install, so the signal itself is intact.
        postEvent("enrolment_stuck", detail = null, step = step, durationMs = null)
    }

    private suspend fun postEvent(
        kind: String,
        detail: DeviceEventDetailIn?,
        step: String,
        durationMs: Long?,
    ) {
        val result = call {
            val response = api.reportEvents(
                DeviceEventBatchIn(
                    events = listOf(
                        DeviceEventIn(
                            kind = kind,
                            at = OffsetDateTime.parse(Clock.toWire(Clock.epochMillis())),
                            detail = detail,
                        ),
                    ),
                ),
            )
            if (!response.isSuccessful) Result.Failed(response.toFailure(moshi)) else Result.Ok(Unit)
        }
        if (result !is Result.Ok) {
            // Telemetry must never block a person from finishing an install.
            Timber.w("Could not report %s for %s (%s ms)", kind, step, durationMs)
        }
    }

    /** The real token pair arrives only with a successful verification. */
    private suspend fun persistTokensIfIssued(
        body: uz.bonvi.call.data.remote.dto.DeviceVerificationStatusOut,
    ): VerificationStatus {
        val tokens = body.tokens
        // ⚠️ `IssuedTokensOut` carries NO `verification_method`, so the method
        // is inferred from the verification STATE: `attested` means an admin
        // vouched for the number rather than the handset proving it. SPEC §9.3
        // requires an attested binding to be rendered differently everywhere it
        // appears, and this is the only signal the phone gets. Raised for
        // build-backend — after a token refresh (`DeviceTokenPairOut`, which
        // DOES carry the field) the distinction currently survives only because
        // it was persisted here.
        val method = when (body.state.value) {
            "attested" -> NumberVerification.Method.ADMIN_ATTESTED
            "matched" -> inferredProvenMethod
            else -> null
        }
        if (tokens != null) {
            session.saveTokens(
                access = tokens.accessToken,
                refresh = tokens.refreshToken,
                verificationMethod = method?.wire,
            )
        }
        return VerificationStatus(
            state = body.state.value,
            failure = NumberVerification.CallbackOutcome.fromWire(body.failure?.value),
            installationActive = body.status?.value == "active",
            method = method,
        )
    }

    /** Which proven route we asked for last, so a `matched` state can be
     *  attributed to it. Set by [verifyMsisdn] and [startCallback]. */
    @Volatile
    private var inferredProvenMethod: NumberVerification.Method =
        NumberVerification.Method.CALLBACK

    private suspend fun <T> call(block: suspend () -> Result<T>): Result<T> = withContext(io) {
        @Suppress("TooGenericExceptionCaught")
        try {
            block()
        } catch (error: Exception) {
            // Broad, and the specific failures it catches are IOException (no
            // network, the normal case on a phone) and SSLException. Neither
            // may reach a Compose screen as a crash during an unaided install.
            Timber.w(error, "Enrolment call failed before a response")
            Result.Offline(error)
        }
    }

    private companion object {
        const val DEFAULT_POLL_MS = 2_000
    }
}

/**
 * What this handset is, for the enrolment payload.
 *
 * Separated so the repository can be tested without Android. Everything it
 * returns is in the contract's allow-list — there is no free-form map on a
 * device DTO (CONVENTIONS.md §8.5), so a field that is not named in the
 * contract cannot leave the phone.
 */
interface DeviceFacts {
    fun deviceInfo(): DeviceInfoIn
    fun appInfo(): AppInfoIn

    /** Stable across reinstalls on the same handset, so a re-enrolment can be
     *  recognised as the same phone rather than a new one. */
    fun fingerprint(): String
}

/** The real one. */
@Singleton
class AndroidDeviceFacts @Inject constructor(
    private val session: SessionStore,
) : DeviceFacts {

    override fun deviceInfo(): DeviceInfoIn = DeviceInfoIn(
        androidRelease = Capabilities.osRelease,
        apiLevel = Capabilities.sdkInt,
        // A HASH of Build.FINGERPRINT, never the string itself: the raw value
        // names the exact firmware build on somebody's personal handset and the
        // server has no use for that (N28).
        buildFingerprintHash = fingerprint(),
        manufacturer = Capabilities.manufacturer,
        model = Capabilities.model,
    )

    override fun appInfo(): AppInfoIn = AppInfoIn(
        version = BuildConfig.VERSION_NAME,
        versionCode = BuildConfig.VERSION_CODE,
        variant = AppVariant.entries.first { it.value == BuildConfig.APP_VARIANT },
    )

    override fun fingerprint(): String = Capabilities.buildFingerprintHash()
}
