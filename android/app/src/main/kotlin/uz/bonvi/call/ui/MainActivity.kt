package uz.bonvi.call.ui

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.launch
import androidx.lifecycle.lifecycleScope
import timber.log.Timber
import uz.bonvi.call.data.repository.ServerAddressRepository
import uz.bonvi.call.service.CaptureService
import uz.bonvi.call.domain.SimDirectory
import uz.bonvi.call.ui.theme.BonviCallTheme
import javax.inject.Inject

/**
 * The only Activity. Everything else is a Compose destination in
 * [BonviCallNavHost].
 *
 * Two jobs beyond hosting Compose, both of which exist so `ui/` never has to
 * touch telephony itself (SPEC §7.1's layering rule):
 *
 *  1. **The deep link.** `bonvicall://enrol?code=XXXXXXXX` comes from the
 *     install landing page, so on the happy path the agent never types a code.
 *     `singleTask` in the manifest means it reuses the running instance instead
 *     of stacking a second copy of the enrolment flow on the first.
 *  2. **The SIM facts E5 needs**, read once here and passed down. They are a
 *     hint for a human, never evidence — `getLine1Number()` is empty on many
 *     Uzbek SIMs (SPEC §9.1).
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    @Inject lateinit var sims: SimDirectory

    @Inject lateinit var serverAddress: ServerAddressRepository

    @Inject lateinit var session: uz.bonvi.call.data.session.SessionStore

    @Inject lateinit var capabilities: uz.bonvi.call.service.CapabilityRefresh

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        applyDeepLinkServer(intent)
        setContent {
            BonviCallTheme {
                BonviCallNavHost(
                    deepLinkCode = codeFrom(intent),
                    simFacts = simFacts(),
                    startDestination = startDestination(),
                )
            }
        }
    }

    /**
     * Opening the app restores capture.
     *
     * The strongest recovery signal this product has, and until now nothing
     * used it. A MIUI handset froze the app at 19:07 on the first real install:
     * the socket died, the fifteen-minute heartbeat never ran, and the phone
     * went silent — from the server that is indistinguishable from a phone with
     * no data. Every other mechanism (START_STICKY, the boot receiver, the
     * watchdog) is deferred while the OS is holding the app down; a person
     * opening it is not, and a foreground service started from a visible
     * Activity is always allowed, including on API 31+.
     *
     * Guarded and silent: an enrolled phone that cannot start its service has
     * a bigger problem than this line can fix, and it reports
     * `service_not_running` on its next contact either way.
     */
    override fun onStart() {
        super.onStart()
        if (session.snapshot.installationId == null) return

        // The other thing opening the app proves: what the permissions are NOW.
        // An agent who skipped "all files access" at enrolment and granted it
        // afterwards from the system settings comes back through this exact
        // callback, and until it ran the panel went on showing the phone as
        // blocked — for as long as nobody pressed "recheck". Nothing is sent
        // while the answers are unchanged.
        lifecycleScope.launch { capabilities.ifChanged("app opened") }

        if (CaptureService.isRunning) return
        @Suppress("TooGenericExceptionCaught")
        try {
            CaptureService.start(this)
        } catch (error: Exception) {
            Timber.w(error, "Could not start capture from the app")
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        applyDeepLinkServer(intent)
        // A second scan of the same link while the flow is open must not
        // restart it; the code field simply refills.
        setIntent(intent)
    }

    /**
     * `bonvicall://enrol?code=…&server=https://…`
     *
     * **The deep link wins.** A code opened from the install link carries the
     * server it belongs to, and that is the normal path; the field on the
     * diagnostics screen is for when there is no link — a code read out over
     * the phone, or a tunnel that moved after enrolment.
     */
    private fun applyDeepLinkServer(intent: Intent?) {
        val server = intent?.data
            ?.takeIf { it.scheme == DEEP_LINK_SCHEME }
            ?.getQueryParameter("server")
            ?: return
        lifecycleScope.launch { serverAddress.saveFromDeepLink(server) }
    }

    private fun codeFrom(intent: Intent?): String? =
        intent?.data?.takeIf { it.scheme == DEEP_LINK_SCHEME }?.getQueryParameter("code")

    /**
     * Where the app opens (T61).
     *
     * The home screen once the installation is bound **and the number is
     * proven**, and E1 until then. The refresh token is the proof: the server
     * issues the real pair only after verification — the provisional token from
     * E1 gets the phone through E5 and no further — so its presence is the one
     * fact that cannot be true on a half-finished install.
     *
     * A synchronous read, deliberately. It decides the first frame, and a flow
     * collected after composition would show E1 to an enrolled agent for a
     * moment on every launch. The snapshot is the same value the OkHttp
     * interceptors read.
     *
     * ⚠️ Every launch used to land on E1, which then bounced forward through
     * the whole flow — including E5, which would have started a fresh callback
     * challenge on a phone that was verified weeks ago.
     */
    private fun startDestination(): String = when {
        // A code in the link is an instruction to enrol THIS phone, even one
        // that believes it is already enrolled — UC-07's "the agent has a new
        // phone" and a re-enrolment after revocation both arrive this way.
        codeFrom(intent) != null -> Routes.ENROL_CODE

        session.snapshot.installationId != null && session.snapshot.refreshToken != null ->
            Routes.HOME

        else -> Routes.ENROL_CODE
    }

    /**
     * The chosen SIM's facts, or the only SIM's on a single-SIM handset.
     *
     * Reading them needs READ_PHONE_STATE, which E2 has already asked for by
     * the time E5 runs. Before that the list is empty, which is correct: an
     * empty list is what "we do not know" looks like, and nothing downstream
     * treats it as a match.
     */
    private fun simFacts(): SimFacts? =
        sims.available()
            .firstOrNull()
            ?.let { SimFacts(it.msisdn, it.carrierName, it.slotIndex) }

    private companion object {
        const val DEEP_LINK_SCHEME = "bonvicall"
    }
}
