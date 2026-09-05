package uz.bonvi.call.enrolment

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.domain.Capability
import uz.bonvi.call.domain.CapabilityResult
import uz.bonvi.call.domain.CapabilityState
import uz.bonvi.call.domain.CaptureReadiness
import uz.bonvi.call.domain.NumberVerification
import javax.inject.Inject

/**
 * The enrolment flow's single ViewModel.
 *
 * One rather than six because the six screens are one transaction: E2's
 * capability results decide whether E6 may be reached, E4's SIM choice is what
 * E5 verifies, and the number from E1 is on every screen from then on (N41).
 * Splitting it would mean passing that state between destinations, which is how
 * a half-finished enrolment ends up looking finished.
 *
 * ⚠️ **`installed` is not `done`.** Redeeming a code returns only a
 * *provisional* token; the real pair is issued after the handset proves it is
 * on the registered number, and until then the server accepts no calls at all.
 * [UiState.isFullyEnrolled] is the only thing E6 may key off.
 */
@HiltViewModel
class EnrolmentViewModel @Inject constructor(
    private val repository: EnrolmentRepository,
    private val checks: CapabilityChecks,
    private val session: SessionStore,
    private val timer: StepTimer,
) : ViewModel() {

    data class UiState(
        val step: EnrolmentStep = EnrolmentStep.CODE,
        val busy: Boolean = false,

        /** N41. Non-null from the moment the code is redeemed, and shown on
         *  every screen after that — including before the install completes. */
        val registeredNumber: String? = null,
        val agentName: String? = null,

        /** The exception behind an "offline" message, for a debug build only.
         *  Every failure before a response is reported to the user as "no
         *  internet", which on the first real handset was wrong and cost
         *  hours: the phone had 4G, the browser reached the server, and the
         *  real cause was invisible because it was swallowed into one
         *  reassuring sentence. A user-facing message must stay simple; a
         *  tester needs the truth. */
        val debugDetail: String? = null,

        val capabilities: Map<Capability, CapabilityResult> = emptyMap(),
        val currentPermissionIndex: Int = 0,
        /** A check is running. The microphone probe is a real one-second
         *  capture, and a button that looks dead for a second on the step
         *  people already find alarming is where they stop. */
        val checking: Capability? = null,

        val simOptions: List<SimChoice> = emptyList(),
        val chosenSubscriptionId: Int? = null,

        val callback: EnrolmentRepository.CallbackChallenge? = null,
        val secondsLeft: Int = 0,
        val verificationState: String? = null,
        val verificationMethod: NumberVerification.Method? = null,
        val callbackFailure: NumberVerification.CallbackOutcome? = null,

        /** An Uzbek sentence, already resolved from an error code. Never a raw
         *  code and never an English string (T100's rule, applied here). */
        val message: UiMessage? = null,
    ) {
        /** Every required capability working AND the number proven or attested.
         *  The same function the server-facing state uses — there is no second
         *  code path that could disagree (UC-03's never-false-ready). */
        val readiness: CaptureReadiness.Readiness
            get() = CaptureReadiness.evaluate(
                states = capabilities.mapValues { it.value.state },
                installationActive = verificationState == "matched" || verificationState == "attested",
                numberVerified = verificationState == "matched" || verificationState == "attested",
            )

        val isFullyEnrolled: Boolean get() = readiness.isCapturing

        /** SPEC §9.3: attested is weaker evidence than proven and is rendered
         *  differently everywhere, so the identity anchor cannot silently
         *  degrade. */
        val isAttestedRatherThanProven: Boolean
            get() = verificationMethod == NumberVerification.Method.ADMIN_ATTESTED
    }

    data class SimChoice(
        val subscriptionId: Int,
        val slotIndex: Int,
        val carrierName: String,
        /** A hint only. It is empty on many Uzbek SIMs and never decides
         *  anything (SPEC §9.1). */
        val msisdn: String?,
    )

    /** What to tell the person, and what they can do about it. */
    data class UiMessage(
        val textRes: Int,
        val actionRes: Int? = null,
        val action: Action? = null,
    ) {
        enum class Action { RETRY, REQUEST_NEW_CODE, MOVE_TO_THIS_PHONE, CONTACT_ADMIN, OPEN_SETTINGS }
    }

    /** Debug builds only: the exception class and message, plus its cause.
     *  `UnknownHostException` and `SSLHandshakeException` and
     *  `SecurityException` send somebody to three different places, and
     *  "check your connection" sends them nowhere. */
    private fun debugDetailOf(error: Throwable?): String? {
        if (!uz.bonvi.call.BuildConfig.DEBUG || error == null) return null
        val cause = error.cause?.let { " ← ${it.javaClass.simpleName}: ${it.message}" }.orEmpty()
        return "${error.javaClass.simpleName}: ${error.message}$cause"
    }

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    init {
        timer.start(EnrolmentStep.CODE)
        viewModelScope.launch {
            // N41 survives a restart mid-enrolment: the number is read back
            // before the first frame rather than only after a successful redeem.
            val display = session.registeredNumberDisplay.first()
            val agent = session.agentName.first()
            if (display != null) _state.value = _state.value.copy(
                registeredNumber = display,
                agentName = agent,
            )

            // Resume where enrolment actually is, not at the beginning.
            //
            // An enrolment code is single-use. Restoring the number but not the
            // step sent a half-enrolled phone back to E1 to re-enter a code the
            // server had already consumed — an unrecoverable loop, and the
            // first real handset sat in it. The installation id is the fact
            // that matters: if one exists, redeem succeeded and this phone is
            // past E1 whatever happened to the process.
            //
            // PERMISSIONS is the safe resume point rather than a remembered
            // step: E2's checks are live and idempotent, so re-running them
            // costs a second and re-reads the truth, and E5 reads verification
            // state from the server rather than from anything held here.
            if (session.installationId.first() != null &&
                _state.value.step == EnrolmentStep.CODE
            ) {
                timer.finish(EnrolmentStep.CODE)
                timer.start(EnrolmentStep.PERMISSIONS)
                _state.value = _state.value.copy(step = EnrolmentStep.PERMISSIONS)
            }
        }
    }

    /** E2 order, with the alarming permissions after two easy successes. */
    val permissionOrder: List<Capability> = CaptureReadiness.E2_ORDER

    fun onCodeEntered(code: String) {
        viewModelScope.launch {
            _state.value = _state.value.copy(busy = true, message = null)
            when (val result = repository.redeem(code, chosenSubscription(), chosenSlot())) {
                is EnrolmentRepository.Result.Ok -> {
                    timer.finish(EnrolmentStep.CODE)?.let {
                        repository.reportStepTiming(EnrolmentStep.CODE.wire, it)
                    }
                    timer.start(EnrolmentStep.PERMISSIONS)
                    _state.value = _state.value.copy(
                        busy = false,
                        step = EnrolmentStep.PERMISSIONS,
                        registeredNumber = result.value.numberDisplay,
                        agentName = result.value.agentName,
                    )
                }

                is EnrolmentRepository.Result.Failed ->
                    _state.value = _state.value.copy(busy = false, message = redeemMessage(result.failure.code))

                is EnrolmentRepository.Result.Offline ->
                    _state.value = _state.value.copy(
                        busy = false,
                        message = UiMessage(R_OFFLINE, R_RETRY, UiMessage.Action.RETRY),
                        debugDetail = debugDetailOf(result.cause),
                    )
            }
        }
    }

    /**
     * Run one capability check and report it immediately.
     *
     * The row turns green **only when the check passes** — not when the dialog
     * was dismissed. That is the difference between a rollout that looks fine
     * and one that captures calls.
     */
    fun onPermissionStepFinished(capability: Capability) {
        viewModelScope.launch {
            _state.value = _state.value.copy(checking = capability)
            val result = checks.check(capability)
            _state.value = _state.value.copy(
                checking = null,
                capabilities = _state.value.capabilities + (capability to result),
            )
            // Immediately, so the panel shows where the agent is stuck within
            // two minutes (UC-03 AC).
            repository.reportCapabilities(listOf(result))
            if (result.isWorking || capability in CaptureReadiness.OPTIONAL) advancePermission()
        }
    }

    fun skipOptional(capability: Capability) {
        viewModelScope.launch {
            val skipped = CapabilityResult(capability, CapabilityState.NOT_APPLICABLE, "skipped by the agent")
            _state.value = _state.value.copy(
                capabilities = _state.value.capabilities + (capability to skipped),
            )
            repository.reportCapabilities(listOf(skipped))
            advancePermission()
        }
    }

    private fun advancePermission() {
        val next = _state.value.currentPermissionIndex + 1
        if (next < permissionOrder.size) {
            _state.value = _state.value.copy(currentPermissionIndex = next)
            return
        }
        viewModelScope.launch {
            timer.finish(EnrolmentStep.PERMISSIONS)?.let {
                repository.reportStepTiming(EnrolmentStep.PERMISSIONS.wire, it)
            }
        }
        _state.value = _state.value.copy(step = EnrolmentStep.SIM)
        timer.start(EnrolmentStep.SIM)
    }

    fun onSimOptions(options: List<SimChoice>) {
        // A single-SIM phone skips E4 silently (SPEC §8.2).
        if (options.size <= 1) {
            _state.value = _state.value.copy(
                simOptions = options,
                chosenSubscriptionId = options.firstOrNull()?.subscriptionId,
                step = EnrolmentStep.VERIFY,
            )
            timer.start(EnrolmentStep.VERIFY)
        } else {
            _state.value = _state.value.copy(simOptions = options)
        }
    }

    fun onSimChosen(subscriptionId: Int) {
        viewModelScope.launch {
            session.saveSubscription(subscriptionId)
            timer.finish(EnrolmentStep.SIM)?.let {
                repository.reportStepTiming(EnrolmentStep.SIM.wire, it)
            }
            timer.start(EnrolmentStep.VERIFY)
            _state.value = _state.value.copy(
                chosenSubscriptionId = subscriptionId,
                step = EnrolmentStep.VERIFY,
            )
        }
    }

    /**
     * E5. Route 1 runs **automatically and invisibly**; the agent is never told
     * the app "checked the SIM and failed". They are told what to do next.
     */
    fun onVerifyStarted(line1Number: String?, carrierName: String?, slot: Int?) {
        viewModelScope.launch {
            _state.value = _state.value.copy(busy = true, message = null)
            val registered = session.registeredNumberE164.first().orEmpty()

            // Skip the round trip when the SIM said nothing — the common case
            // on Uzbek SIMs. This never CLAIMS a match; it only avoids asking a
            // question whose answer is already known to be "no".
            val local = NumberVerification.checkMsisdn(line1Number, registered)
            if (local == NumberVerification.MsisdnOutcome.MATCHED) {
                val result = repository.verifyMsisdn(
                    line1Number, _state.value.chosenSubscriptionId, slot, carrierName,
                )
                if (result is EnrolmentRepository.Result.Ok && result.value.isMatched) {
                    finishVerification(result.value)
                    return@launch
                }
            }
            startCallbackRoute()
        }
    }

    private suspend fun startCallbackRoute() {
        when (val started = repository.startCallback()) {
            is EnrolmentRepository.Result.Ok ->
                _state.value = _state.value.copy(
                    busy = false,
                    callback = started.value,
                    secondsLeft = CALLBACK_WINDOW_SECONDS,
                )

            is EnrolmentRepository.Result.Failed -> {
                val receiverDown = started.failure.code == "callback_receiver_down"
                _state.value = _state.value.copy(
                    busy = false,
                    callbackFailure = if (receiverDown) {
                        NumberVerification.CallbackOutcome.RECEIVER_DOWN
                    } else {
                        null
                    },
                    // Never "dial into nothing": if every receiver is down the
                    // agent is told to contact the admin instead.
                    message = if (receiverDown) {
                        UiMessage(R_RECEIVER_DOWN, R_CONTACT_ADMIN, UiMessage.Action.CONTACT_ADMIN)
                    } else {
                        UiMessage(R_GENERIC, R_RETRY, UiMessage.Action.RETRY)
                    },
                )
            }

            is EnrolmentRepository.Result.Offline ->
                _state.value = _state.value.copy(
                    busy = false,
                    message = UiMessage(R_OFFLINE, R_RETRY, UiMessage.Action.RETRY),
                )
        }
    }

    fun onCallbackTick(secondsLeft: Int) {
        _state.value = _state.value.copy(secondsLeft = secondsLeft)
    }

    fun onPollCallback() {
        val challenge = _state.value.callback ?: return
        viewModelScope.launch {
            when (val status = repository.callbackStatus(challenge.verificationId)) {
                is EnrolmentRepository.Result.Ok ->
                    if (status.value.isMatched) {
                        finishVerification(status.value)
                    } else {
                        _state.value = _state.value.copy(
                            verificationState = status.value.state,
                            callbackFailure = status.value.failure,
                            message = status.value.failure?.let(::callbackMessage),
                        )
                    }

                is EnrolmentRepository.Result.Failed, is EnrolmentRepository.Result.Offline -> Unit
            }
        }
    }

    private suspend fun finishVerification(status: EnrolmentRepository.VerificationStatus) {
        timer.finish(EnrolmentStep.VERIFY)?.let {
            repository.reportStepTiming(EnrolmentStep.VERIFY.wire, it)
        }
        // Re-check the capabilities that only become true once the device is
        // bound, so E6 cannot be reached on a stale green (UC-03).
        val resolution = checks.check(Capability.SUBSCRIPTION_RESOLUTION)
        val service = checks.check(Capability.FOREGROUND_SERVICE)
        _state.value = _state.value.copy(
            busy = false,
            step = EnrolmentStep.DONE,
            verificationState = status.state,
            verificationMethod = status.method,
            capabilities = _state.value.capabilities +
                (Capability.SUBSCRIPTION_RESOLUTION to resolution) +
                (Capability.FOREGROUND_SERVICE to service),
        )
        repository.reportCapabilities(listOf(resolution, service))
    }

    /** SPEC §8.1's "Yordam kerak". A stalled enrolment must be an event, not
     *  silence — a silently stalled rollout looks exactly like a working one. */
    fun onStuck() {
        viewModelScope.launch { repository.reportStuck(_state.value.step.wire) }
    }

    private fun chosenSubscription(): Int? = _state.value.chosenSubscriptionId

    private fun chosenSlot(): Int? =
        _state.value.simOptions.firstOrNull { it.subscriptionId == chosenSubscription() }?.slotIndex

    /**
     * E1's failures, each with its own sentence and its own next action — never
     * a generic error. On a 15-minute unaided install this is most of the
     * difference between finishing and giving up.
     */
    private fun redeemMessage(code: String): UiMessage = when (code) {
        "enrolment_code_not_found" -> UiMessage(R_CODE_NOT_FOUND, R_RETRY, UiMessage.Action.RETRY)
        "enrolment_code_used" -> UiMessage(R_CODE_USED, R_NEW_CODE, UiMessage.Action.REQUEST_NEW_CODE)
        "enrolment_code_expired" -> UiMessage(R_CODE_EXPIRED, R_NEW_CODE, UiMessage.Action.REQUEST_NEW_CODE)
        "enrolment_code_revoked" -> UiMessage(R_CODE_REVOKED, R_NEW_CODE, UiMessage.Action.REQUEST_NEW_CODE)
        // UC-07's rebinding path: the agent has a new phone.
        "installation_already_active" ->
            UiMessage(R_ALREADY_ACTIVE, R_MOVE_HERE, UiMessage.Action.MOVE_TO_THIS_PHONE)
        else -> UiMessage(R_GENERIC, R_RETRY, UiMessage.Action.RETRY)
    }

    private fun callbackMessage(outcome: NumberVerification.CallbackOutcome): UiMessage =
        when (outcome) {
            // R19 happening. Retrying will never work on this operator, so the
            // app says so and offers the assisted path rather than a spinner.
            NumberVerification.CallbackOutcome.NO_CALLER_ID ->
                UiMessage(R_NO_CALLER_ID, R_CONTACT_ADMIN, UiMessage.Action.CONTACT_ADMIN)
            NumberVerification.CallbackOutcome.MISMATCH ->
                UiMessage(R_WRONG_SIM, R_RETRY, UiMessage.Action.RETRY)
            NumberVerification.CallbackOutcome.TIMEOUT ->
                UiMessage(R_TIMEOUT, R_RETRY, UiMessage.Action.RETRY)
            NumberVerification.CallbackOutcome.RECEIVER_DOWN ->
                UiMessage(R_RECEIVER_DOWN, R_CONTACT_ADMIN, UiMessage.Action.CONTACT_ADMIN)
            NumberVerification.CallbackOutcome.MATCHED -> UiMessage(R_GENERIC)
        }

    private companion object {
        const val CALLBACK_WINDOW_SECONDS = 300

        val R_OFFLINE = uz.bonvi.call.R.string.enrol_error_offline
        val R_GENERIC = uz.bonvi.call.R.string.enrol_error_generic
        val R_RETRY = uz.bonvi.call.R.string.common_retry
        val R_NEW_CODE = uz.bonvi.call.R.string.enrol_action_new_code
        val R_MOVE_HERE = uz.bonvi.call.R.string.enrol_action_move_here
        val R_CONTACT_ADMIN = uz.bonvi.call.R.string.enrol_action_contact_admin
        val R_CODE_NOT_FOUND = uz.bonvi.call.R.string.enrol_error_code_not_found
        val R_CODE_USED = uz.bonvi.call.R.string.enrol_error_code_used
        val R_CODE_EXPIRED = uz.bonvi.call.R.string.enrol_error_code_expired
        val R_CODE_REVOKED = uz.bonvi.call.R.string.enrol_error_code_revoked
        val R_ALREADY_ACTIVE = uz.bonvi.call.R.string.enrol_error_already_active
        val R_NO_CALLER_ID = uz.bonvi.call.R.string.enrol_error_no_caller_id
        val R_WRONG_SIM = uz.bonvi.call.R.string.enrol_error_wrong_sim
        val R_TIMEOUT = uz.bonvi.call.R.string.enrol_error_timeout
        val R_RECEIVER_DOWN = uz.bonvi.call.R.string.enrol_error_receiver_down
    }
}
