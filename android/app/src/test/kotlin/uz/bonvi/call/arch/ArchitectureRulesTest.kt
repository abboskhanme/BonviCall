package uz.bonvi.call.arch

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.TestPaths
import java.io.File

/**
 * The three architecture rules of SPEC §7.1, **enforced by test rather than by
 * review**.
 *
 * There is one Gradle module, so nothing but this file stops `ui/` importing
 * an OkHttp client or `service/` opening `/sdcard` directly. SPEC chose a
 * single module deliberately — the boundary that matters is the privacy
 * boundary, and that one is a type signature — but it chose it on the condition
 * that these rules are mechanical. This is that mechanism.
 *
 * Each failure message names the rule and where it is written down, because the
 * person who trips it is usually not the person who read the document.
 */
class ArchitectureRulesTest {

    private data class Source(val file: File, val text: String) {
        // `invariantSeparatorsPath`, not `path`: every rule below matches a
        // path FRAGMENT written with `/`, and on Windows `path` comes back with
        // `\` — so `substringAfter("src/")` returned the whole absolute path and
        // the `filterNot` exclusions below never matched their own allowed file.
        // The rules then failed on the one file each of them exists to permit.
        val relativePath: String = file.invariantSeparatorsPath.substringAfter("src/")

        val pkg: String = Regex("""^package\s+([\w.]+)""", RegexOption.MULTILINE)
            .find(text)?.groupValues?.get(1).orEmpty()

        /**
         * The file with comments removed.
         *
         * Every rule below is checked against THIS, not the raw text. A rule
         * that fired on comments would make the documentation unwritable: the
         * files that explain why `MediaStore` is confined to `capture/` are
         * mostly outside `capture/`, and a check nobody can satisfy without
         * deleting the explanation is a check that gets deleted instead.
         */
        val code: String = text
            .replace(Regex("""/\*.*?\*/""", RegexOption.DOT_MATCHES_ALL), " ")
            .replace(Regex("""//.*$""", RegexOption.MULTILINE), " ")
    }

    private val sources: List<Source> by lazy {
        TestPaths.kotlinSources().map { Source(it, it.readText()) }
    }

    private fun sourcesOutside(vararg allowedPackages: String): List<Source> =
        sources.filterNot { source -> allowedPackages.any { source.pkg.startsWith(it) } }

    @Test
    fun `there is something to check`() {
        // A rule test that silently scans zero files passes forever.
        assertThat(sources).isNotEmpty()
        assertThat(sources.map { it.pkg }).contains("uz.bonvi.call.capture")
    }

    // ── Rule 1 ────────────────────────────────────────────────────────────
    @Test
    fun `media and external-storage APIs appear only under capture`() {
        // SPEC §7.1. CallSentry let the recording code reach into /sdcard from
        // anywhere; here that is confined to one package and, more importantly,
        // to one TYPE (OemHarvestStrategy.locate(Decision.Capture, …)).
        // The dotted forms, so the rule catches a CALL and not a class whose
        // name merely starts with the API's. `MediaStoreOemRecordingLocator`
        // is bound from `di/` on modern34 and naming it there is not a use of
        // MediaStore — matching on the bare word made this rule fail for a
        // reason that had nothing to do with what it guards.
        val forbidden = listOf(
            "MediaStore.",
            "MediaRecorder.",
            "AudioRecord(",
            "Environment.getExternalStorageDirectory",
            "getExternalStoragePublicDirectory",
        )
        val offenders = sourcesOutside("uz.bonvi.call.capture").flatMap { source ->
            forbidden.filter { source.code.contains(it) }.map { "${source.relativePath}: $it" }
        }
        assertThat(offenders).isEmpty()
    }

    // ── Rule 2 ────────────────────────────────────────────────────────────
    @Test
    fun `Build VERSION SDK_INT appears only in core Capabilities`() {
        // CONVENTIONS-CLIENT.md §7, SPEC §7.1. Everything else asks a
        // capability. Two flavours ship, and a version check scattered through
        // the capture path is how they silently diverge.
        val offenders = sources
            .filter { it.code.contains("SDK_INT") }
            .map { it.relativePath }
            .filterNot { it.endsWith("core/Capabilities.kt") }
        assertThat(offenders).isEmpty()
    }

    // ── Rule 3 ────────────────────────────────────────────────────────────
    @Test
    fun `ui never reaches data remote or capture directly`() {
        // SPEC §7.1 calls this "the one layering rule worth enforcing without a
        // module system, because it is the one that decides whether the
        // enrolment screens can be tested without a phone".
        val offenders = sources
            .filter { it.pkg.startsWith("uz.bonvi.call.ui") }
            .flatMap { source ->
                Regex("""^import\s+([\w.]+)""", RegexOption.MULTILINE)
                    .findAll(source.code)
                    .map { it.groupValues[1] }
                    .filter {
                        it.startsWith("uz.bonvi.call.data.remote") ||
                            it.startsWith("uz.bonvi.call.capture") ||
                            it.startsWith("okhttp3.") ||
                            it.startsWith("retrofit2.")
                    }
                    .map { "${source.relativePath} imports $it" }
                    .toList()
            }
        assertThat(offenders).isEmpty()
    }

    // ── Rule 4 ────────────────────────────────────────────────────────────
    @Test
    fun `no content-provider query puts LIMIT in its sort order`() {
        // Android 11+ validates the sort-order argument and answers
        // `IllegalArgumentException` for a trailing `LIMIT`. Both of this app's
        // call-log queries did it, and on a live Android 15 handset the result
        // was `call_log: granted_not_working` — a working permission reported
        // as broken, with capture blocked behind it and the recovery sweep
        // silently finding nothing. CallSentry, on the same phone, sorted and
        // read the first row; that is the portable form.
        //
        // Room's own `@Query` is SQLite and is not affected — this looks only
        // at files that reach a ContentResolver.
        val offenders = sources
            .filter { it.code.contains("contentResolver.query(") }
            .filter { source ->
                // One line, one string literal, an SQL keyword — not the
                // identifier `limit`, which is a parameter name all over this
                // file and is not the bug.
                Regex(""""[^"\n]*\bLIMIT\b[^"\n]*"""")
                    .containsMatchIn(source.code)
            }
            .map { it.relativePath }
        assertThat(offenders).isEmpty()
    }

    // ── The privacy boundary (CONVENTIONS.md §8) ──────────────────────────
    @Test
    fun `SubscriptionManager and PHONE_ACCOUNT_ID are read in one place only`() {
        // Guard 1 is the sole producer of Decision.Capture. A second reader of
        // the subscription is a second place that can decide a private call is
        // a work call.
        val offenders = sources
            .filter { it.code.contains("SubscriptionManager") || it.code.contains("PHONE_ACCOUNT_ID") }
            .map { it.relativePath }
            .filterNot { it.contains("PrivacyBoundary") }
        assertThat(offenders).isEmpty()
    }

    @Test
    fun `the contact book is read in one place only`() {
        // T139, N28. The address book is on a phone the employee bought.
        // Holding READ_CONTACTS to turn one number into one name does not make
        // the rest of it ours, and one reader is one place that can decide to
        // read more than one row. Same mechanism as SubscriptionManager above.
        val offenders = sources
            .filter { it.code.contains("ContactsContract") }
            .map { it.relativePath }
            .filterNot { it.endsWith("capture/ContactNameResolver.kt") }
        assertThat(offenders).isEmpty()
    }

    @Test
    fun `nothing sweeps the contact book`() {
        // A single-number lookup through PhoneLookup is allowed; a cursor over
        // the contacts table is what "reading the contact book" means, and it
        // must not exist anywhere.
        val sweeps = sources.flatMap { source ->
            listOf("Contacts.CONTENT_URI", "CommonDataKinds.Phone.CONTENT_URI", "Data.CONTENT_URI")
                .filter { source.code.contains(it) }
                .map { "${source.relativePath}: $it" }
        }
        assertThat(sweeps).isEmpty()
    }

    @Test
    fun `no device DTO carries a free-form map`() {
        // CONVENTIONS.md §8.5: the wire schema is the allow-list. A field the
        // contract does not name must not be able to LEAVE the phone.
        //
        // Scoped to the REQUEST DTOs (`...In`), and that is the rule's own
        // wording rather than a convenience: §8.5 is about data leaving the
        // handset. `ErrorBody.detail` is `Any?` and inbound — it is the
        // machine-readable part of the §9 envelope the server sends back
        // (SPEC §4.0), so nothing of the employee's can travel through it. The
        // same distinction `DeviceContractPrivacyTest` already makes one level
        // up, where it checks `...In` schemas only.
        //
        // The check is on PROPERTY DECLARATIONS, not on the whole file:
        // openapi-generator emits `encode(data: kotlin.Any?)` helpers on every
        // generated enum, and a rule that fires on generator plumbing is a rule
        // somebody turns off. `DeviceContractPrivacyTest` enforces the same
        // rule one level up, on the contract itself, where it can name the
        // offending server schema.
        val dtoSources = sources
            .filter { it.pkg.startsWith("uz.bonvi.call.data.remote.dto") }
            .filter { it.file.nameWithoutExtension.endsWith("In") }
        val property = Regex("""^\s*(?:val|var)\s+\w+\s*:\s*([^=,)]+)""", RegexOption.MULTILINE)
        val offenders = dtoSources.flatMap { source ->
            property.findAll(source.code)
                .map { it.groupValues[1].trim() }
                .filter { type ->
                    type.contains("Map<") ||
                        type.contains("JsonObject") ||
                        type.contains("JsonElement") ||
                        Regex("""\bAny\b""").containsMatchIn(type)
                }
                .map { "${source.relativePath}: $it" }
                .toList()
        }
        assertThat(offenders).isEmpty()
    }

    @Test
    fun `the phone key rule is not reimplemented anywhere`() {
        // CONVENTIONS.md §7: one name for one rule. Three names is how the rule
        // eventually differs — BonviZvonki had exactly three.
        val offenders = sources
            .filter { it.code.contains("takeLast(9)") || it.code.contains("substring(digits.length - 9)") }
            .map { it.relativePath }
            .filterNot { it.endsWith("core/Phone.kt") }
        assertThat(offenders).isEmpty()
    }

    @Test
    fun `forbidden concurrency primitives are absent`() {
        // CONVENTIONS-CLIENT.md §8. Nothing touches disk or network on the main
        // thread, and nothing outside a test uses a scope that outlives the
        // component that started it.
        val forbidden = listOf("GlobalScope", "runBlocking(", "AsyncTask", "Thread {")
        val offenders = sources.flatMap { source ->
            forbidden.filter { source.code.contains(it) }.map { "${source.relativePath}: $it" }
        }
        assertThat(offenders).isEmpty()
    }

    @Test
    fun `wall-clock time is read in one place`() {
        // CONVENTIONS.md §6: currentTimeMillis appears only where a WIRE
        // timestamp is built. Durations use the monotonic clock, because
        // subtracting two wall-clock readings across a clock change produces a
        // negative call length.
        val offenders = sources
            .filter { it.code.contains("currentTimeMillis") }
            .map { it.relativePath }
            .filterNot { it.endsWith("core/Clock.kt") }
        assertThat(offenders).isEmpty()
    }
}
