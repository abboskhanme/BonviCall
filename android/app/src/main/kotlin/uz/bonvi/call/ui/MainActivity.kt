package uz.bonvi.call.ui

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import dagger.hilt.android.AndroidEntryPoint
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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            BonviCallTheme {
                BonviCallNavHost(
                    deepLinkCode = codeFrom(intent),
                    simFacts = simFacts(),
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // A second scan of the same link while the flow is open must not
        // restart it; the code field simply refills.
        setIntent(intent)
    }

    private fun codeFrom(intent: Intent?): String? =
        intent?.data?.takeIf { it.scheme == DEEP_LINK_SCHEME }?.getQueryParameter("code")

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
