package uz.bonvi.call.capture

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.TestPaths

/**
 * One number → one name, for one captured call (T139, N28).
 *
 * The behaviour that matters is structural rather than functional, so this
 * pins the structure: the signature that makes a personal-call lookup
 * unwriteable, the single-row query, and the absence of a cache. A functional
 * test would need a `ContactsProvider`, and what it would prove — that a query
 * returns a row — is not the risk here.
 */
class ContactNameResolverTest {

    private val raw: String by lazy {
        TestPaths.kotlinSources().single { it.name == "ContactNameResolver.kt" }.readText()
    }

    /**
     * The file with comments removed.
     *
     * The same lesson as `ArchitectureRulesTest`: the docstring that explains
     * why the book is never swept has to be allowed to NAME the thing it
     * forbids, or the documentation becomes unwritable and the check gets
     * deleted instead.
     */
    private val source: String by lazy {
        raw.replace(Regex("""/\*.*?\*/""", RegexOption.DOT_MATCHES_ALL), " ")
            .replace(Regex("""//.*$""", RegexOption.MULTILINE), " ")
    }

    @Test
    fun `a name can only be resolved for a call that passed the privacy boundary`() {
        // The signature IS the enforcement, exactly as it is for
        // OemHarvestStrategy.locate: a caller who has not passed
        // PrivacyBoundary.evaluate() cannot construct a Decision.Capture, so a
        // name cannot be looked up for a call on the employee's own SIM.
        assertThat(source).contains("suspend fun resolve(capture: Decision.Capture")
    }

    @Test
    fun `the lookup is by number, through PhoneLookup`() {
        // The provider's own "which contact has this number" index. It cannot
        // be pointed at the whole book.
        assertThat(source).contains("ContactsContract.PhoneLookup.CONTENT_FILTER_URI")
    }

    @Test
    fun `nothing sweeps the book`() {
        for (sweep in listOf(
            "Contacts.CONTENT_URI",
            "CommonDataKinds.Phone.CONTENT_URI",
            "Data.CONTENT_URI",
        )) {
            assertThat(source).doesNotContain(sweep)
        }
    }

    @Test
    fun `no name is cached`() {
        // A local table of resolved names would be a copy of the parts of the
        // address book we found interesting — N28 arrived at by another route.
        for (persistence in listOf("@Entity", "Dao", "DataStore", "SharedPreferences")) {
            assertThat(source).doesNotContain(persistence)
        }
    }

    @Test
    fun `a missing permission is a null name, never a failure`() {
        // E2 marks the step *ixtiyoriy*. The call ships without a name, and
        // that must not become an audio_missing_reason or an alert.
        assertThat(source).contains("if (!hasPermission())")
        assertThat(source).doesNotContain("AudioMissingReason")
        assertThat(source).doesNotContain("throw ")
    }

    @Test
    fun `only the display name column is read`() {
        // Not the contact id, not the photo, not the other numbers on the same
        // contact. One field, because one field is what N28 permits.
        assertThat(source).contains("ContactsContract.PhoneLookup.DISPLAY_NAME")
        assertThat(source).doesNotContain("PHOTO_URI")
        assertThat(source).doesNotContain("LOOKUP_KEY")
    }
}
