package uz.bonvi.call.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import dagger.hilt.android.AndroidEntryPoint
import uz.bonvi.call.ui.theme.BonviCallTheme

/**
 * The only Activity. Everything else is a Compose destination in
 * [BonviCallNavHost].
 *
 * `singleTask` in the manifest, so the `bonvicall://enrol?code=…` deep link
 * from the install landing page (UC-02, §8.1) reuses the running instance
 * instead of stacking a second copy of the enrolment flow on top of the first.
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            BonviCallTheme {
                BonviCallNavHost()
            }
        }
    }
}
