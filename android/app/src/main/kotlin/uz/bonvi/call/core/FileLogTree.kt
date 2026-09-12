package uz.bonvi.call.core

import android.util.Log
import timber.log.Timber
import java.io.File
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * A Timber tree that appends to a file under the app's private storage.
 *
 * ═══ Why it exists ═════════════════════════════════════════════════════════
 * On the MIUI handsets this fleet runs, `adb logcat` shows the platform's own
 * lines and almost none of ours: the buffer is flooded by the media stack and
 * the app's `Log` output is dropped long before anybody reads it. A whole day
 * was spent (2026-09-12) inferring which audio source had been chosen from
 * `dumpsys audio` because the line that said so never surfaced. This tree
 * puts the same lines where `run-as` can read them:
 *
 *     adb shell run-as uz.bonvi.call cat files/logs/bonvicall.log
 *
 * ═══ Privacy ═══════════════════════════════════════════════════════════════
 * Planted ONLY in debug builds, and every line goes through
 * [RedactingTree.redact] before it is written (a wrapper tree cannot deliver
 * to another tree's protected hook — see [RedactingTree]). A release
 * build on an employee's phone writes no log file: the log lines name call
 * ids and counts, never numbers or names (N26), but a file that nobody needs
 * is a file that should not exist. It is rotated at [maxBytes] with one
 * previous generation kept, so it can never grow past twice that.
 */
class FileLogTree(
    private val file: File,
    private val maxBytes: Long = DEFAULT_MAX_BYTES,
) : Timber.DebugTree() {
    // A DebugTree subclass ONLY for its tag inference (the calling class's
    // name); `log` below never calls `super`, so nothing here reaches logcat.

    private val lock = Any()
    private val stamp = SimpleDateFormat("MM-dd HH:mm:ss.SSS", Locale.US)

    override fun log(priority: Int, tag: String?, message: String, t: Throwable?) {
        val line = buildString {
            append(stamp.format(Date()))
            append(' ')
            append(priorityLetter(priority))
            append('/')
            append(tag ?: "-")
            append(": ")
            append(RedactingTree.redact(message))
            append('\n')
            if (t != null) {
                append(Log.getStackTraceString(t))
                append('\n')
            }
        }
        synchronized(lock) {
            @Suppress("SwallowedException")
            try {
                file.parentFile?.mkdirs()
                if (file.length() > maxBytes) rotate()
                file.appendText(line)
            } catch (error: IOException) {
                // A log that cannot be written must not become a crash, and
                // logging the failure would recurse. Dropped, on purpose.
            }
        }
    }

    private fun rotate() {
        val previous = File(file.parentFile, "${file.name}.1")
        previous.delete()
        file.renameTo(previous)
    }

    private fun priorityLetter(priority: Int): Char = when (priority) {
        Log.VERBOSE -> 'V'
        Log.DEBUG -> 'D'
        Log.INFO -> 'I'
        Log.WARN -> 'W'
        Log.ERROR -> 'E'
        Log.ASSERT -> 'A'
        else -> '?'
    }

    companion object {
        const val DEFAULT_MAX_BYTES: Long = 1L shl 20
        const val RELATIVE_PATH: String = "logs/bonvicall.log"
    }
}
