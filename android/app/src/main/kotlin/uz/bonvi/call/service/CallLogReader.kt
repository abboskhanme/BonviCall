package uz.bonvi.call.service

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.provider.CallLog
import androidx.core.content.ContextCompat
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.capture.SubscriptionPrivacyBoundary
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.CallDirection
import uz.bonvi.call.domain.CallDisposition
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Reads the OS call log (T67, UC-13).
 *
 * The call log is the **source of truth for reconciliation**: the live capture
 * knows when it saw the edges, the log knows what the phone actually did. It is
 * also the only place `client_call_id`'s `started_at` can come from — the log's
 * `DATE` value is the only timestamp two independent installs will agree on
 * (§3.10 rule 1).
 *
 * A missing permission is not an exception here. It is an empty list plus a
 * capability that will report `denied`, so the panel names the blocker instead
 * of the app crashing on a phone somebody is mid-install on.
 */
@Singleton
class CallLogReader @Inject constructor(
    @ApplicationContext private val context: Context,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    /** One call-log row, reduced to what reconciliation needs. */
    data class Entry(
        val startedAtEpochMillis: Long,
        val durationSec: Int,
        val direction: CallDirection,
        val disposition: CallDisposition,
        val remoteNumber: String?,
        /** The call log's own SIM attribution, when the OEM populates it.
         *  Guard 1 uses it when the live broadcast carried nothing. */
        val phoneAccountId: String?,
    ) {
        val endedAtEpochMillis: Long get() = startedAtEpochMillis + durationSec * 1000L
    }

    suspend fun since(fromEpochMillis: Long, limit: Int = MAX_ROWS): List<Entry> =
        withContext(io) {
            if (!hasPermission()) {
                Timber.w("Call log not readable; reconciliation will report a gap")
                return@withContext emptyList()
            }
            @Suppress("TooGenericExceptionCaught")
            try {
                query(fromEpochMillis, limit)
            } catch (error: Exception) {
                // Broad, and the specific failure is a SecurityException from an
                // OEM privacy manager that reports READ_CALL_LOG as granted and
                // refuses the provider — the UC-03 trap. The sweep REPORTS the
                // gap rather than inventing rows (SPEC §7.5).
                Timber.w(error, "Call-log query refused")
                emptyList()
            }
        }

    private fun query(fromEpochMillis: Long, limit: Int): List<Entry> {
        val projection = arrayOf(
            CallLog.Calls.DATE,
            CallLog.Calls.DURATION,
            CallLog.Calls.TYPE,
            CallLog.Calls.NUMBER,
            // By reference: only capture/PrivacyBoundary.kt may name the SIM
            // attribution column (CONVENTIONS.md §8.1). This reader carries the
            // value as opaque text and never interprets it.
            SubscriptionPrivacyBoundary.SIM_ATTRIBUTION_COLUMN,
        )
        return context.contentResolver.query(
            CallLog.Calls.CONTENT_URI,
            projection,
            "${CallLog.Calls.DATE} >= ?",
            arrayOf(fromEpochMillis.toString()),
            // ⚠️ **No `LIMIT` here either.** Android 11+ rejects it in the sort
            // order with `IllegalArgumentException`, which this class catches
            // and reports as a gap — so on a modern handset the recovery sweep
            // would quietly find nothing, for ever. The bound is applied while
            // reading instead: a cursor is fetched in windows, so stopping
            // early costs nothing.
            "${CallLog.Calls.DATE} ASC",
        ).use { cursor ->
            if (cursor == null) return emptyList()
            val entries = ArrayList<Entry>(minOf(cursor.count, limit))
            val date = cursor.getColumnIndex(CallLog.Calls.DATE)
            val duration = cursor.getColumnIndex(CallLog.Calls.DURATION)
            val type = cursor.getColumnIndex(CallLog.Calls.TYPE)
            val number = cursor.getColumnIndex(CallLog.Calls.NUMBER)
            val account =
                cursor.getColumnIndex(SubscriptionPrivacyBoundary.SIM_ATTRIBUTION_COLUMN)
            while (entries.size < limit && cursor.moveToNext()) {
                val callType = cursor.getInt(type)
                entries += Entry(
                    startedAtEpochMillis = cursor.getLong(date),
                    durationSec = cursor.getInt(duration),
                    direction = callType.toDirection(),
                    disposition = callType.toDisposition(cursor.getInt(duration)),
                    remoteNumber = cursor.getString(number),
                    phoneAccountId = if (account >= 0) cursor.getString(account) else null,
                )
            }
            entries
        }
    }

    private fun hasPermission(): Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.READ_CALL_LOG) ==
            PackageManager.PERMISSION_GRANTED

    private fun Int.toDirection(): CallDirection = when (this) {
        CallLog.Calls.OUTGOING_TYPE -> CallDirection.OUTGOING
        else -> CallDirection.INCOMING
    }

    /**
     * UC-09's rule in one place: an outgoing call with zero duration was not
     * answered, and is never reported as a conversation.
     */
    private fun Int.toDisposition(durationSec: Int): CallDisposition = when {
        this == CallLog.Calls.MISSED_TYPE -> CallDisposition.MISSED
        this == CallLog.Calls.REJECTED_TYPE -> CallDisposition.REJECTED
        durationSec > 0 -> CallDisposition.ANSWERED
        this == CallLog.Calls.OUTGOING_TYPE -> CallDisposition.NO_ANSWER
        else -> CallDisposition.MISSED
    }

    private companion object {
        /** A sweep after a long offline period must not read the whole log. */
        const val MAX_ROWS = 500
    }
}
