package uz.bonvi.call.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import dagger.hilt.android.AndroidEntryPoint
import timber.log.Timber

/**
 * Restarts the capture service after the events that stop it (UC-05).
 *
 * A reboot is the most common way a phone quietly stops reporting, and the
 * second most common is an app update. Both are here, plus
 * `LOCKED_BOOT_COMPLETED` so the service is running before the user unlocks —
 * the manifest entry is `directBootAware`, so this arrives first on devices
 * that support it.
 */
@AndroidEntryPoint
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_LOCKED_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
            -> {
                Timber.i("Restarting capture service after %s", intent.action)
                // TODO(T26): only start when an installation is bound and
                // active. Starting unconditionally would put a notification on
                // the phone of somebody who has not finished enrolling.
                CaptureService.start(context)
            }

            else -> Timber.w("BootReceiver ignored action %s", intent.action)
        }
    }
}
