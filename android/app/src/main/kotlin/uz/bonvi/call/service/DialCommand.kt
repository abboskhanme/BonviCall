package uz.bonvi.call.service

import android.content.Context
import android.content.Intent
import android.net.Uri
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import uz.bonvi.call.core.Clock
import uz.bonvi.call.core.Phone
import uz.bonvi.call.service.work.CommandFreshness
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Click-to-call (T80, UC-16).
 *
 * The panel issues a `dial` command; this places the call. Three rules, and the
 * first two are about not doing the wrong thing:
 *
 * 1. **Stale commands are discarded, not dialled.** See [CommandFreshness]: a
 *    number dialled ten minutes late is worse than one not dialled at all.
 * 2. **`ACTION_CALL`, not `ACTION_DIAL`.** UC-16 is one tap in the panel and a
 *    ringing phone, not a pre-filled dialler the salesperson still has to press.
 *    That is why `CALL_PHONE` is on T104's keep-list — without it this fails
 *    *silently*, which is the worst possible failure for a feature nobody
 *    exercises daily.
 * 3. **The result is always reported**, including refusal. A command with no
 *    outcome looks identical to one that never arrived.
 */
@Singleton
class DialCommand @Inject constructor(
    @ApplicationContext private val context: Context,
    private val freshness: CommandFreshness,
) {

    sealed interface Result {
        data class Dialled(val e164: String) : Result
        data class Discarded(val reason: String) : Result
    }

    fun execute(rawNumber: String, issuedAtEpochMillis: Long): Result {
        val now = Clock.epochMillis()
        if (!freshness.isFresh(issuedAtEpochMillis, now)) {
            val reason = freshness.stalenessReason(issuedAtEpochMillis, now)
            Timber.w("Dial command ignored: %s", reason)
            return Result.Discarded(reason)
        }

        // Same normalisation as everything else (N37). A number the server and
        // the phone disagree about is a call to the wrong person.
        val e164 = Phone.toE164(rawNumber)
            ?: return Result.Discarded("unparseable_number").also {
                Timber.w("Dial command carried a number that is not a number")
            }

        @Suppress("TooGenericExceptionCaught")
        return try {
            context.startActivity(
                Intent(Intent.ACTION_CALL, Uri.parse("tel:$e164"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
            Result.Dialled(e164)
        } catch (error: Exception) {
            // Broad, and the specific failures are SecurityException when
            // CALL_PHONE was revoked after enrolment, and
            // ActivityNotFoundException on a handset with no dialler. Both are
            // reported rather than thrown: the panel must be able to say the
            // command was refused and why.
            Timber.e(error, "Dial command could not be placed")
            Result.Discarded(error.javaClass.simpleName)
        }
    }
}
