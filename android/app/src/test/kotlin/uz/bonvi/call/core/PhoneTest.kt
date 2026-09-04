package uz.bonvi.call.core

import com.google.common.truth.Truth.assertThat
import org.json.JSONObject
import org.junit.Test
import uz.bonvi.call.TestPaths

/**
 * The phone key, checked against `contract/phone-vectors.json` — **the same
 * file `server/tests/test_phone.py` reads** (CONVENTIONS.md §7,
 * CONVENTIONS-CLIENT.md §10).
 *
 * That shared file is the whole anti-drift mechanism. If Kotlin and Python ever
 * disagree about what the key of a number is, release 2's join between
 * BonviCall and BonviZvonki silently returns nothing: no error, no exception,
 * no data. Adding a number format means adding a vector, once, and both suites
 * pick it up.
 *
 * This test may not be deleted, skipped or weakened (CONVENTIONS.md §13).
 */
class PhoneTest {

    private val contract: JSONObject by lazy {
        val file = TestPaths.contractDir.resolve("phone-vectors.json")
        assertThat(file.isFile).isTrue()
        JSONObject(file.readText())
    }

    private fun nullableString(source: JSONObject, key: String): String? =
        if (source.isNull(key)) null else source.getString(key)

    @Test
    fun `the digit count is the one the contract declares`() {
        // The constant lives in exactly one place per implementation, and the
        // contract file is where the two agree on its value.
        assertThat(Phone.PHONE_KEY_DIGITS).isEqualTo(contract.getInt("phone_key_digits"))
    }

    @Test
    fun `every phone_key vector in the shared contract file matches`() {
        val vectors = contract.getJSONArray("vectors")
        assertThat(vectors.length()).isGreaterThan(0)

        for (index in 0 until vectors.length()) {
            val vector = vectors.getJSONObject(index)
            val raw = nullableString(vector, "raw")
            val expected = nullableString(vector, "key")

            assertThat(Phone.phoneKey(raw))
                .isEqualTo(expected)
        }
    }

    @Test
    fun `every e164 vector in the shared contract file matches`() {
        val vectors = contract.getJSONArray("vectors")
        for (index in 0 until vectors.length()) {
            val vector = vectors.getJSONObject(index)
            val raw = nullableString(vector, "raw")
            val expected = nullableString(vector, "e164")

            assertThat(Phone.toE164(raw))
                .isEqualTo(expected)
        }
    }

    @Test
    fun `the contract's extension vectors are extensions and the others are not`() {
        val extensions = contract.getJSONArray("extensions")
        for (index in 0 until extensions.length()) {
            assertThat(Phone.isExtension(extensions.getString(index))).isTrue()
        }

        val notExtensions = contract.getJSONArray("not_extensions")
        for (index in 0 until notExtensions.length()) {
            assertThat(Phone.isExtension(notExtensions.getString(index))).isFalse()
        }
    }

    @Test
    fun `fewer than nine digits is never a key`() {
        // BonviZvonki's own comment records why: 1234567 matches the tail of
        // any number and marked strangers as colleagues.
        assertThat(Phone.phoneKey("1234567")).isNull()
        assertThat(Phone.phoneKey("")).isNull()
        assertThat(Phone.phoneKey(null)).isNull()
    }
}
