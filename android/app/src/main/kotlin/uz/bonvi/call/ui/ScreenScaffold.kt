package uz.bonvi.call.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import uz.bonvi.call.R

/**
 * A placeholder screen body.
 *
 * T22 declares every navigation destination up front so the Phase 4 tasks fill
 * screen bodies in parallel and nobody edits the graph. A screen still holding
 * this is a destination whose owner has not started, and it says so.
 *
 * The title comes from `strings.xml` — the one file on Android where Uzbek text
 * is legal (CONVENTIONS.md §14). The task id below it is English on purpose:
 * it is a build artefact for the team, not a sentence a user is meant to read,
 * and it disappears with the placeholder.
 */
@Composable
fun StubScreen(titleRes: Int, task: String) {
    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier.fillMaxSize().padding(24.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(text = stringResource(titleRes), style = MaterialTheme.typography.headlineSmall)
            Text(
                text = stringResource(R.string.common_not_ready),
                style = MaterialTheme.typography.bodyMedium,
            )
            Text(text = task, style = MaterialTheme.typography.labelSmall)
        }
    }
}
