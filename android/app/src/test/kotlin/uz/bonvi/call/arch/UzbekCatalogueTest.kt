package uz.bonvi.call.arch

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.TestPaths
import java.io.File

/**
 * The Uzbek catalogue, read as one document (T105, N39).
 *
 * ═══ Why a pass rather than per-screen review ══════════════════════════════
 * The enrolment screens are read once, by a person who is uneasy, on a phone
 * they paid for. Strings written one screen at a time drift: the same idea gets
 * two words, and a promise made on one screen is contradicted by behaviour
 * explained on another. This test pins the parts of that which a machine can
 * see; the rest is the read itself.
 *
 * **The vocabulary distinction that runs through everything:**
 * *qayd etish* = logging the call (who, when, how long) · *yozib olish* =
 * recording the audio. They are different promises — a call with no microphone
 * permission is still *qayd etilgan* and not *yozib olingan* — and the app and
 * `docs/QOLLANMA.md` have to use them the same way or the manual is not
 * describing the app.
 */
class UzbekCatalogueTest {

    private val strings: Map<String, String> by lazy {
        val text = File(TestPaths.appDir, "src/main/res/values/strings.xml").readText()
        Regex("""<string name="([^"]+)">(.*?)</string>""", RegexOption.DOT_MATCHES_ALL)
            .findAll(text)
            .associate { it.groupValues[1] to it.groupValues[2] }
    }

    /**
     * The manual with runs of whitespace collapsed.
     *
     * A markdown document wraps, so a phrase can be split across a line break.
     * The first version of this test matched raw text and failed on where the
     * wrap happened to fall — which would have made every future edit to the
     * manual a coin toss. What is being checked is the vocabulary, not the
     * typography.
     */
    private val manual: String by lazy {
        File(TestPaths.repoRoot, "docs/QOLLANMA.md").readText()
            .replace(Regex("""\s+"""), " ")
    }

    @Test
    fun `every string is used somewhere`() {
        // A string nobody renders is a sentence nobody reviewed, and it will be
        // the one somebody copies next time.
        val code = TestPaths.kotlinSources().joinToString("\n") { it.readText() }
        val xml = File(TestPaths.appDir, "src/main").walkTopDown()
            .filter { it.isFile && it.extension == "xml" }
            .joinToString("\n") { it.readText() }

        val unused = strings.keys.filterNot { key ->
            code.contains("R.string.$key") || xml.contains("@string/$key")
        }
        assertThat(unused).isEmpty()
    }

    @Test
    fun `nothing claims the contact book is never touched`() {
        // ⚠️ The check that caught a real contradiction. T139 resolves ONE name
        // for a captured call and uploads it (N28 allows exactly that). A
        // string saying "Kontaktlar ... yuborilmaydi" was true before T139 and
        // false after it — and a promise the app then breaks costs more trust
        // than never having made it.
        val resolverExists = TestPaths.kotlinSources().any { it.name == "ContactNameResolver.kt" }
        if (!resolverExists) return

        for ((key, value) in strings) {
            val claimsNoContacts = value.contains("Kontaktlar") &&
                value.contains("yuborilmaydi") &&
                !value.contains("ismi")
            assertThat(claimsNoContacts)
                .isEqualTo(false)
        }
    }

    @Test
    fun `the app and the manual use the same words for the same things`() {
        // The manual is the app stated in the other direction. Where they name
        // the same thing differently, the reader concludes one of them is out
        // of date — and they are right to.
        val sharedVocabulary = listOf(
            "Yordam kerak",      // the stuck button, on every enrolment screen
            "ish raqam",         // the registered number
            "qayd etil",         // the call is logged
            "Ilova holati",      // the diagnostics screen
        )
        for (word in sharedVocabulary) {
            assertThat(manual.contains(word)).isTrue()
        }
    }

    @Test
    fun `N41's sentence is in both, and names the number`() {
        // The one sentence that earns or loses trust. It has to be identical in
        // spirit on the landing page, in the app, and in the manual.
        assertThat(strings["n41_recording_number"]).contains("Yozib olinadi")
        assertThat(strings["n41_only_this_number"]).contains("Ikkinchi SIM")
        assertThat(manual).contains("Yozib olinadi")
        assertThat(manual).contains("Ikkinchi SIM kartangizga hech qachon tegilmaydi")
    }

    @Test
    fun `every permission explains a CONSEQUENCE, not a permission name`() {
        // "Mikrofon ruxsati kerak" tells a non-technical reader nothing.
        // "Mikrofon bo'lmasa suhbat yozilmaydi" tells them what they lose.
        val why = strings.filterKeys { it.startsWith("perm_") && it.endsWith("_why") }
        assertThat(why).isNotEmpty()
        for ((key, value) in why) {
            assertThat(value.length).isAtLeast(40)
            // No raw Android permission names in front of a salesperson.
            for (leak in listOf("READ_", "RECORD_AUDIO", "android.permission")) {
                assertThat(value).doesNotContain(leak)
            }
        }
    }

    @Test
    fun `no English leaks into a user-facing string`() {
        // §14: the app's UI is Uzbek. A stray English word is usually a
        // placeholder somebody meant to come back to.
        val allowed = setOf("BonviCall", "SIM", "SMS", "Wi", "Fi", "MB", "GPS", "Android")
        val english = Regex("""\b(the|and|your|call|number|please|error|failed|retry)\b""",
            RegexOption.IGNORE_CASE)
        for ((key, value) in strings) {
            if (value in allowed) continue
            assertThat(english.containsMatchIn(value)).isEqualTo(false)
        }
    }

    @Test
    fun `the manual states what happens when capture stops`() {
        // Not softened, on instruction and on principle: an admin sees it and
        // will ask. Telling someone up front is more respectful than letting
        // them find out.
        assertThat(manual).contains("administrator")
        assertThat(manual.lowercase()).contains("o'chirsangiz")
    }
}
