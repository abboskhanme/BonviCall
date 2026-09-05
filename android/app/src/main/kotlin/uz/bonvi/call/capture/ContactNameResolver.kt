package uz.bonvi.call.capture

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.ContactsContract
import androidx.core.content.ContextCompat
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.Decision
import javax.inject.Inject
import javax.inject.Singleton

/**
 * One number → one name, for one captured call (T139, N28).
 *
 * ═══ This is a privacy task wearing a convenience task's clothes ═══════════
 * The address book is on a phone the employee bought, and it is theirs.
 * Holding `READ_CONTACTS` so that a call list can say "Aziz" instead of
 * "+998 90 111-22-33" does not make the rest of it ours. N28 allows exactly
 * three things off the handset — call metadata, audio, and **a contact name
 * where one resolves**. Not the book, not a subset of it, not a cache of the
 * ones we happened to look up.
 *
 * So the rules here are the same shape as Guard 1's, and for the same reason:
 *
 * 1. **A name is resolved only for a call that already passed the privacy
 *    boundary.** [resolve] takes a [Decision.Capture] — the proof that the call
 *    was on the registered number — exactly as `OemHarvestStrategy.locate`
 *    does. A caller who has not passed `PrivacyBoundary.evaluate()` cannot
 *    express the request, so a name cannot be looked up for a personal call.
 * 2. **One lookup, by number.** `PhoneLookup.CONTENT_FILTER_URI` asks the
 *    provider for the contact matching a single number. There is no query in
 *    this file that returns more than one row, no cursor over
 *    `Contacts.CONTENT_URI`, and no sweep. A sweep is what "reading the
 *    contact book" means, and it never happens.
 * 3. **Nothing is cached.** The result goes onto the one call being uploaded
 *    and is not stored. A local table of resolved names would be a copy of the
 *    parts of the address book we found interesting, which is the thing N28
 *    forbids arriving at by a different route.
 * 4. **No permission is not a failure.** The call ships without a name. It is
 *    not an `audio_missing_reason`, not an alert, not a blocked capability —
 *    E2 marks the step *ixtiyoriy* and an agent may skip it.
 *
 * ⚠️ **This is the only file in the app that may read `ContactsContract`.**
 * `grep -rn "ContactsContract" android/` returns this file, and
 * `ArchitectureRulesTest` fails the build otherwise — the same mechanism that
 * keeps `SubscriptionManager` to one reader. One reader is one place that can
 * decide to read more than one row.
 */
@Singleton
class ContactNameResolver @Inject constructor(
    @ApplicationContext private val context: Context,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    /**
     * The display name for [remoteNumber], or null.
     *
     * @param capture proof that this call is on the registered number. Unused
     *        by the query itself and **required by the signature**: it is what
     *        makes "resolve a name for any number" unwriteable.
     */
    suspend fun resolve(capture: Decision.Capture, remoteNumber: String?): String? =
        withContext(io) {
            @Suppress("UNUSED_EXPRESSION") capture
            val number = remoteNumber?.trim()?.takeIf { it.isNotEmpty() } ?: return@withContext null
            if (!hasPermission()) {
                // Expected, and not a failure: E2 marks this step optional and
                // an agent may skip it. The call ships without a name.
                return@withContext null
            }

            @Suppress("TooGenericExceptionCaught")
            try {
                lookup(number)
            } catch (error: Exception) {
                // Broad, and the specific failure is a SecurityException from
                // an OEM privacy manager that reports the permission as granted
                // and refuses the provider — the UC-03 trap. A missing name is
                // never worth losing a call over.
                Timber.w(error, "Contact lookup refused")
                null
            }
        }

    /**
     * A single-row lookup by number.
     *
     * `PhoneLookup` is the provider's own "which contact has this number"
     * index. It does the number normalisation the OS uses for the dialler, so
     * the answer matches what the employee sees on their own screen — and it
     * cannot be pointed at the whole book.
     */
    private fun lookup(number: String): String? {
        val uri: Uri = Uri.withAppendedPath(
            ContactsContract.PhoneLookup.CONTENT_FILTER_URI,
            Uri.encode(number),
        )
        return context.contentResolver.query(
            uri,
            arrayOf(ContactsContract.PhoneLookup.DISPLAY_NAME),
            null,
            null,
            // One row. Not a limit that could be raised — the provider is being
            // asked about one number.
            null,
        ).use { cursor ->
            if (cursor == null || !cursor.moveToFirst()) return null
            cursor.getString(0)?.trim()?.takeIf { it.isNotEmpty() }
        }
    }

    fun hasPermission(): Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.READ_CONTACTS) ==
            PackageManager.PERMISSION_GRANTED
}
