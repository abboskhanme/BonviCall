package uz.bonvi.call.ui.enrolment

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import timber.log.Timber
import uz.bonvi.call.core.Capabilities
import uz.bonvi.call.domain.Capability

/**
 * Deep links into the settings screens E2 sends people to.
 *
 * Every one of them falls back to the app's own settings page. An OEM that does
 * not implement an action would otherwise throw `ActivityNotFoundException` in
 * the middle of an unaided install, on the alarming step, which is exactly
 * where a person gives up.
 */
fun Context.openAppSettings() {
    startSafely(
        Intent(
            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
            Uri.fromParts("package", packageName, null),
        ),
    )
}

fun Context.openSettingsFor(capability: Capability) {
    val intent = when (capability) {
        // Asking for the exemption directly is one tap; the battery settings
        // list is four, and two of them are named differently on every OEM.
        Capability.BATTERY_EXEMPTION ->
            Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                .setData(Uri.parse("package:$packageName"))

        // The all-files screen exists only where scoped storage does. Below
        // that the legacy read permission is a normal runtime dialog, and this
        // branch is never reached — asked as a capability, never a version.
        Capability.STORAGE_ACCESS -> if (Capabilities.requiresAllFilesAccess()) {
            @Suppress("InlinedApi")
            Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                .setData(Uri.parse("package:$packageName"))
        } else {
            null
        }

        Capability.NOTIFICATIONS ->
            Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)

        // OEM autostart has no standard action. The app's own settings page is
        // the closest honest destination, and E3 carries the per-OEM path as
        // text and a photograph instead of pretending an intent exists.
        else -> null
    }
    if (intent == null) {
        openAppSettings()
        return
    }
    startSafely(intent)
}

private fun Context.startSafely(intent: Intent) {
    try {
        startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (error: ActivityNotFoundException) {
        // The specific failure: an OEM build with the action removed. Falling
        // back is always better than a crash on the step people already find
        // frightening.
        Timber.w(error, "Settings action unavailable; falling back to app details")
        if (intent.action != Settings.ACTION_APPLICATION_DETAILS_SETTINGS) openAppSettings()
    }
}
