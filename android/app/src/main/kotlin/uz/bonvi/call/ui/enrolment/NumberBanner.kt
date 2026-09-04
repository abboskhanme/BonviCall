package uz.bonvi.call.ui.enrolment

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import uz.bonvi.call.R

/**
 * N41, on screen.
 *
 * "The app permanently shows which number it records." This is that sentence,
 * and it is shown on **every enrolment screen** from the moment the code is
 * redeemed — before the install finishes, not after — and on the home screen
 * afterwards. The install landing page has already said it once before anything
 * was installed; this is the app keeping the same promise.
 *
 * It is not a settings detail. The person holding the phone paid for it, and
 * the only thing that makes the privacy boundary real to them is being able to
 * see, at any moment, exactly which number is being recorded and that the other
 * SIM is not.
 */
@Composable
fun NumberBanner(number: String?, modifier: Modifier = Modifier) {
    if (number.isNullOrBlank()) return
    Column(
        modifier = modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.primaryContainer)
            .padding(horizontal = 16.dp, vertical = 12.dp),
    ) {
        Text(
            text = stringResource(R.string.n41_recording_number, number),
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onPrimaryContainer,
        )
        Text(
            text = stringResource(R.string.n41_only_this_number),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onPrimaryContainer,
        )
        Text(
            text = stringResource(R.string.n41_never_uploaded),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onPrimaryContainer,
        )
    }
}
