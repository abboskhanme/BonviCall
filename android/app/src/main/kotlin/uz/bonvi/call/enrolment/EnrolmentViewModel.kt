package uz.bonvi.call.enrolment

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import uz.bonvi.call.core.Capabilities
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.domain.Capability
import uz.bonvi.call.domain.CapabilityResult
import uz.bonvi.call.domain.CapabilityState
import uz.bonvi.call.domain.CaptureReadiness
import uz.bonvi.call.domain.DeviceAuthState
import uz.bonvi.call.domain.NumberVerification
import uz.bonvi.call.domain.OemGuidance
import uz.bonvi.call.domain.runtimePermission
import uz.bonvi.call.domain.SimDirectory
import uz.bonvi.call.domain.SimOptionInfo
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
    private val sims: SimDirectory,
    private val capture: CaptureLauncher,
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
        /** A check is running. The microphone probe is a real one-second
         *  capture, and a button that looks dead for a second on the step
         *  people already find alarming is where they stop. */
        val checking: Capability? = null,
        /** The whole E2 sweep is running — every check at once, after the one
         *  permission dialog. Distinct from [checking], which is one row being
         *  re-tested after a trip to a settings screen. */
        val checkingAll: Boolean = false,

        val simOptions: List<SimChoice> = emptyList(),
        val chosenSubscriptionId: Int? = null,

        val callback: EnrolmentRepository.CallbackChallenge? = null,

        /** No route this handset can take is left, and an admin attesting from
         *  the panel is the only way forward. The screen polls while this is
         *  true, so the enrolment completes itself the moment they act. */
        val awaitingAttestation: Boolean = false,
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
                installationActive = NumberVerification.isBound(verificationState),
                numberVerified = NumberVerification.isBound(verificationState),
            )

        val isFullyEnrolled: Boolean get() = readiness.isCapturing

        /**
         * Can this handset record audio at all?
         *
         * A phone with no working microphone and no reachable OEM recorder is
         * `CAPTURING` — it logs every call with `recording_route_unavailable`,
         * which the gap report counts and the panel renders. Saying so at E6
         * stops somebody chasing a fault that is not there (UC-14).
         */
        val audioAvailable: Boolean
            get() = capabilities[Capability.MICROPHONE]?.isWorking == true ||
                capabilities[Capability.OEM_RECORDER]?.isWorking == true

        // `isAttestedRatherThanProven` lived here and is gone: it collapsed
        // two different unproven bindings into one boolean, and E6 has to tell
        // them apart — "an admin looked at this number" and "nobody has" are
        // not the same sentence. The screens branch on [verificationMethod]
        // and `Method.isProven` directly, which is one fact rather than a
        // derived second one that can disagree with it (SPEC §9.3).
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
            // ⚠️ A REVOKED installation is the exception. Its id is still on
            // the phone, so the resume rule would skip the agent straight past
            // the one screen they need — the code field — and there would be no
            // way back to it. UC-08 ends with a handset that can be enrolled
            // again, not one locked out by its own history.
            // ⚠️ The test is "does this phone hold a credential it can still
            // use", not "has it ever enrolled".
            //
            // An installation id survives everything, including the two states
            // in which the phone can do nothing at all: REVOKED, and
            // AUTH_EXPIRED — which is where a refused refresh lands it, and a
            // refused refresh is ordinary here (`refresh_reused` after a
            // response is lost mid-rotation kills both pairs server-side by
            // design). Keying the skip on the id alone sent such a handset
            // straight past the one screen it needs, and the code field was
            // then unreachable: a live Redmi sat on a home screen claiming to
            // capture, uploading nothing, with 39 calls held and no way for
            // the agent to enter the new code that would have freed them.
            //
            // The server's own recovery note says re-enrolling on the same
            // number keeps the queue. This is what makes that reachable.
            val authState = session.authStateSnapshot()
            val usable = authState.canCapture && session.refreshToken.first() != null
            if (usable &&
                session.installationId.first() != null &&
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

    /**
     * Every runtime permission E2 needs, asked for in **one** request.
     *
     * ═══ Why this replaced nine sequential steps ═══════════════════════════
     * E2 used to walk the nine capabilities one card at a time: tap, dialog,
     * check, next card, tap again. Six of them are ordinary runtime
     * permissions, and Android will show those six dialogs back to back from a
     * single `RequestMultiplePermissions` — same dialogs, same order, one tap
     * to start them instead of six.
     *
     * The three that are left are not dialogs at all (battery exemption,
     * all-files access, OEM autostart); they are settings screens, and those
     * still get their own button because that is what they are. So the
     * ordinary handset now goes: one tap, the system's own sequence, done.
     *
     * What is deliberately unchanged is the part that matters: **every
     * capability is still exercised** after the dialogs, and a row goes green
     * only when its check passes, never because a dialog was dismissed.
     */
    val runtimePermissions: List<String> =
        CaptureReadiness.E2_ORDER.mapNotNull { it.runtimePermission() }.distinct()

    /** The E2 rows that are a settings screen rather than a dialog, so the
     *  screen can render them apart and only when they are not already
     *  working. */
    val settingsCapabilities: List<Capability> =
        CaptureReadiness.E2_ORDER.filter { it.runtimePermission() == null }

    /**
     * Run every E2 check at once, report them in one batch, and move on when
     * nothing required is missing.
     *
     * One batch rather than nine posts: the panel wants to know where an agent
     * is stuck within two minutes (UC-03 AC), and nine round trips on the link
     * this app is installed over is how E2 came to feel slow.
     */
    fun onPermissionsChecked() {
        viewModelScope.launch {
            _state.value = _state.value.copy(checkingAll = true)
            val results = permissionOrder.map { checks.check(it) }
            _state.value = _state.value.copy(
                checkingAll = false,
                capabilities = _state.value.capabilities +
                    results.associateBy { it.capability },
            )
            repository.reportCapabilities(results)

            // Advance only when every REQUIRED capability works. A missing
            // optional one — contacts, autostart — never holds the flow, and a
            // missing required one leaves the agent on a screen that now shows
            // exactly which rows failed and what each costs.
            if (blockingRequired().isEmpty()) leavePermissions()
        }
    }

    /** Required capabilities still not working, in the order E2 asks for them. */
    fun blockingRequired(): List<Capability> =
        CaptureReadiness.REQUIRED
            .filter { it in permissionOrder }
            .filter { _state.value.capabilities[it]?.isWorking != true }
            .sortedBy { permissionOrder.indexOf(it) }

    /**
     * Leave E2 with whatever the checks found.
     *
     * Reachable with a required capability still failing, and that is the
     * decision UC-14 asks for rather than a hole: the screen has already named
     * what each missing capability costs, the state is reported either way, and
     * an enrolled handset reporting `BLOCKED` is visible to an admin while an
     * unenrolled one is not.
     */
    fun onPermissionsDone() {
        viewModelScope.launch {
            val unchecked = permissionOrder.filter { it !in _state.value.capabilities }
            if (unchecked.isNotEmpty()) {
                val skipped = unchecked.map {
                    CapabilityResult(it, CapabilityState.NOT_APPLICABLE, "skipped by the agent")
                }
                _state.value = _state.value.copy(
                    capabilities = _state.value.capabilities + skipped.associateBy { it.capability },
                )
                repository.reportCapabilities(skipped)
            }
            leavePermissions()
        }
    }

    fun onCodeEntered(code: String) {
        viewModelScope.launch {
            _state.value = _state.value.copy(busy = true, message = null)
            when (val result = repository.redeem(code, chosenSubscription(), chosenSlot())) {
                is EnrolmentRepository.Result.Ok -> {
                    val elapsed = timer.finish(EnrolmentStep.CODE)
                    timer.start(EnrolmentStep.PERMISSIONS)
                    _state.value = _state.value.copy(
                        busy = false,
                        step = EnrolmentStep.PERMISSIONS,
                        registeredNumber = result.value.numberDisplay,
                        agentName = result.value.agentName,
                    )
                    // Reported AFTER the step moves. `step_timing` is
                    // telemetry, and the repository's own rule is that
                    // telemetry never blocks a person from finishing an
                    // install — awaiting it here holds E1 on screen for a
                    // whole HTTP timeout on the slow link this app is
                    // installed over, which is indistinguishable from the
                    // button doing nothing.
                    elapsed?.let { repository.reportStepTiming(EnrolmentStep.CODE.wire, it) }
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
            // No navigation here any more. This is the single-row re-check —
            // the agent came back from a settings screen and the row should now
            // say what the OS actually reports. Leaving E2 is
            // [onPermissionsChecked]'s decision or the agent's
            // ([onPermissionsDone]), and a re-check that also navigated used to
            // take the screen away mid-list.
        }
    }

    /**
     * Continue past a capability that will not work.
     *
     * **Not a hidden escape hatch**: the screen has already named what it costs
     * (`CapabilityConsequence`), and the state is reported either way — so the
     * panel knows exactly which capability is missing on which phone. An
     * enrolled handset reporting `BLOCKED` is visible to an admin; an
     * unenrolled one is not, which is why this exists at all.
     *
     * The last CHECKED result is kept rather than overwritten: `denied` and
     * `granted_not_working` are different problems and the funnel needs to know
     * which. Only a capability never checked is recorded as skipped.
     */
    fun onContinueWithout(capability: Capability) {
        viewModelScope.launch {
            val existing = _state.value.capabilities[capability]
            if (existing == null) {
                val skipped = CapabilityResult(
                    capability,
                    CapabilityState.NOT_APPLICABLE,
                    "skipped by the agent",
                )
                _state.value = _state.value.copy(
                    capabilities = _state.value.capabilities + (capability to skipped),
                )
                repository.reportCapabilities(listOf(skipped))
            }
        }
    }

    private fun leavePermissions() {
        viewModelScope.launch {
            val elapsed = timer.finish(EnrolmentStep.PERMISSIONS)
            // E3 first, on the manufacturers that need it (R3). Asking
            // [OemGuidance] rather than a version check is T63's rule, and it
            // is the same object the screen renders from — so the flow can
            // never route a phone to an empty E3, and never skip a MIUI one.
            if (OemGuidance.applies(Capabilities.manufacturer)) {
                timer.start(EnrolmentStep.OEM_STEPS)
                _state.value = _state.value.copy(step = EnrolmentStep.OEM_STEPS)
            } else {
                openSimStep()
            }
            // After the step moves, for the reason E1 gives above.
            elapsed?.let { repository.reportStepTiming(EnrolmentStep.PERMISSIONS.wire, it) }
        }
    }

    /**
     * E3 is done — as far as anything on this handset can tell.
     *
     * The OEM screens expose no check, so this records nothing new: the
     * `oem_autostart` capability stays whatever E2's check made it (`unknown`
     * on most manufacturers), and the panel keeps seeing a phone whose autostart
     * is unproven rather than one that claims it is on.
     */
    fun onOemStepsFinished() {
        viewModelScope.launch {
            val elapsed = timer.finish(EnrolmentStep.OEM_STEPS)
            openSimStep()
            elapsed?.let { repository.reportStepTiming(EnrolmentStep.OEM_STEPS.wire, it) }
        }
    }

    /**
     * Read the SIM list and hand over to E4 or E5.
     *
     * The list is read HERE and nowhere earlier: it needs READ_PHONE_STATE,
     * which is the first row of E2, so asking before that returns an empty list
     * — and an empty E4 is a screen with an explanation and no buttons, which
     * is the same dead end as a step that never navigates.
     *
     * [onSimOptions] then decides whether E4 is shown at all: a single-SIM
     * phone skips it silently and lands on E5 (SPEC §8.2).
     */
    private fun openSimStep() {
        onSimOptions(sims.available().map(::choiceOf))
    }

    /** The domain's SIM row as E4 renders it. The MSISDN travels as-is,
     *  including null: it is a hint for the human and never evidence — it is
     *  empty on many Uzbek SIMs (SPEC §9.1). */
    private fun choiceOf(sim: SimOptionInfo): SimChoice = SimChoice(
        subscriptionId = sim.subscriptionId,
        slotIndex = sim.slotIndex,
        carrierName = sim.carrierName,
        msisdn = sim.msisdn,
    )

    fun onSimOptions(options: List<SimChoice>) {
        // A single-SIM phone skips E4 silently (SPEC §8.2). So does a phone
        // whose OS told us nothing: an empty list is "we do not know", and
        // stopping on a SIM screen with no rows would strand the enrolment on
        // a question nobody can answer — E5 proves the number anyway.
        if (options.size <= 1) {
            _state.value = _state.value.copy(
                simOptions = options,
                chosenSubscriptionId = options.firstOrNull()?.subscriptionId,
                step = EnrolmentStep.VERIFY,
            )
            timer.start(EnrolmentStep.VERIFY)
            options.firstOrNull()?.let {
                viewModelScope.launch { session.saveSubscription(it.subscriptionId) }
            }
        } else {
            _state.value = _state.value.copy(
                simOptions = options,
                step = EnrolmentStep.SIM,
            )
            timer.start(EnrolmentStep.SIM)
        }
    }

    fun onSimChosen(subscriptionId: Int) {
        viewModelScope.launch {
            // The local write stays first: Guard 1 judges every future call
            // against it, and it is a DataStore write rather than a round trip.
            session.saveSubscription(subscriptionId)
            val elapsed = timer.finish(EnrolmentStep.SIM)
            timer.start(EnrolmentStep.VERIFY)
            _state.value = _state.value.copy(
                chosenSubscriptionId = subscriptionId,
                step = EnrolmentStep.VERIFY,
            )
            elapsed?.let { repository.reportStepTiming(EnrolmentStep.SIM.wire, it) }
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

            // ⚠️ Route 2 unavailable is NOT the end of the flow any more.
            //
            // It used to be: "contact the admin", and the agent sat there. On
            // this fleet no callback receiver exists at all, so every single
            // enrolment reached this branch and stopped — which is the whole
            // reason handsets never captured anything. Route 3 finishes the
            // install on the strength of the code, visibly and weakly, and
            // that is strictly better than a phone that reports nothing.
            is EnrolmentRepository.Result.Failed -> selfDeclare()

            // Same reasoning, different cause: a phone that cannot reach the
            // server to start a challenge can still be enrolled the moment it
            // can, and route 3 is one request rather than a five-minute window.
            is EnrolmentRepository.Result.Offline ->
                _state.value = _state.value.copy(
                    busy = false,
                    message = UiMessage(R_OFFLINE, R_RETRY, UiMessage.Action.RETRY),
                )
        }
    }

    /**
     * E5's "Keyinroq tasdiqlash" — finish now, on the code alone.
     *
     * Offered even when the callback route IS available, because dialling a
     * number and waiting is a step, and a step on the last screen of an
     * unaided install is where people stop. It costs the strength of the
     * binding and the panel shows exactly that.
     */
    fun onSkipVerification() {
        viewModelScope.launch {
            _state.value = _state.value.copy(busy = true, message = null)
            selfDeclare()
        }
    }

    /**
     * Route 3 (SPEC §9.3): bind on the strength of the enrolment code.
     *
     * When an admin has turned it off, the only route left is attestation from
     * the panel — so the screen says so **and starts polling**, rather than
     * telling the agent to contact somebody and then never noticing that they
     * did.
     */
    private suspend fun selfDeclare() {
        when (val declared = repository.verifySelfDeclared()) {
            is EnrolmentRepository.Result.Ok -> finishVerification(declared.value)

            is EnrolmentRepository.Result.Failed ->
                _state.value = _state.value.copy(
                    busy = false,
                    awaitingAttestation = declared.failure.code == "self_declared_disabled",
                    callbackFailure = NumberVerification.CallbackOutcome.RECEIVER_DOWN,
                    message = UiMessage(
                        R_RECEIVER_DOWN,
                        R_CONTACT_ADMIN,
                        UiMessage.Action.CONTACT_ADMIN,
                    ),
                )

            is EnrolmentRepository.Result.Offline ->
                _state.value = _state.value.copy(
                    busy = false,
                    message = UiMessage(R_OFFLINE, R_RETRY, UiMessage.Action.RETRY),
                    debugDetail = debugDetailOf(declared.cause),
                )
        }
    }

    /**
     * Ask the server whether somebody else finished this enrolment.
     *
     * The somebody is an admin attesting from the panel. That activated the
     * installation server-side, and the handset had no way to hear about it —
     * the real token pair is minted at verification, so a phone told to contact
     * an admin stayed on that screen after the admin had acted. Polled while
     * [UiState.awaitingAttestation] is true.
     */
    fun onPollStatus() {
        viewModelScope.launch {
            val status = repository.enrolmentStatus()
            if (status is EnrolmentRepository.Result.Ok && status.value.isMatched) {
                finishVerification(status.value)
            }
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
        val elapsed = timer.finish(EnrolmentStep.VERIFY)
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

        // The number is proven, so the server now accepts this phone's calls —
        // and capture starts here rather than at the next reboot. Nothing used
        // to make this call: an enrolled handset sent its first heartbeat only
        // when something else happened to wake the service, and until then the
        // panel showed it as a device that had never reported.
        capture.onEnrolmentComplete()
        repository.reportCapabilities(listOf(resolution, service))
        elapsed?.let { repository.reportStepTiming(EnrolmentStep.VERIFY.wire, it) }
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
