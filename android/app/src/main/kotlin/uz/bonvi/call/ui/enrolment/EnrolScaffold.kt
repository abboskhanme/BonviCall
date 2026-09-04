package uz.bonvi.call.ui.enrolment

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import uz.bonvi.call.R

/**
 * Every enrolment screen has the same three parts: the N41 banner, the step's
 * own body, and a permanent "Yordam kerak".
 *
 * That last one is SPEC §8.1's rule applied inside the app: **a stalled
 * enrolment must be an event, not silence.** A silently stalled rollout looks
 * exactly like a working one until go-live, so the button posts
 * `enrolment_stuck` with the step the agent was on and moves them to
 * `needs_assisted_install` in the panel.
 */
@Composable
fun EnrolScaffold(
    number: String?,
    title: String,
    onStuck: () -> Unit,
    content: @Composable () -> Unit,
) {
    Surface(modifier = Modifier.fillMaxSize()) {
        Column(modifier = Modifier.fillMaxSize()) {
            NumberBanner(number)
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(text = title, style = MaterialTheme.typography.headlineSmall)
                content()
                TextButton(onClick = onStuck) {
                    Text(stringResource(R.string.common_help))
                }
            }
        }
    }
}
