package uz.bonvi.call.core

/**
 * Phone numbers — one function, one constant (CONVENTIONS.md §7, N37).
 *
 * This is the **same rule as the server's `core/phone.py`**, and the two are
 * kept honest by the same file: `contract/phone-vectors.json` is read by
 * `server/tests/test_phone.py` and by `PhoneTest` here. Adding a format means
 * adding a vector, once. If the two implementations ever disagree, the release-2
 * join between BonviCall and BonviZvonki silently returns nothing, which is the
 * worst failure mode there is: no error, no data.
 *
 * **Fewer than 9 digits is never a key.** BonviZvonki learned this the
 * expensive way — `1234567` matches the tail of any number and marked strangers
 * as colleagues.
 *
 * `grep -rn "\[-9:\]\|takeLast(9)" android/` outside this file is a violation.
 */
object Phone {

    /** The ONLY place this number appears on the Android side. */
    const val PHONE_KEY_DIGITS: Int = 9

    /** Below this, a number is a PBX extension, not a subscriber number. */
    private const val EXTENSION_MAX_DIGITS: Int = 6

    private const val UZ_COUNTRY_CODE = "998"
    private const val UZ_NATIONAL_DIGITS = 9

    private fun digitsOf(raw: String?): String =
        raw?.filter { it.isDigit() }.orEmpty()

    /**
     * The last nine digits, or null when there are fewer than nine.
     *
     * Null is a legitimate answer and is stored as such: losing a call because
     * its number was odd is worse than an unkeyed row (SPEC §4.0).
     */
    fun phoneKey(raw: String?): String? {
        val digits = digitsOf(raw)
        if (digits.length < PHONE_KEY_DIGITS) return null
        return digits.substring(digits.length - PHONE_KEY_DIGITS)
    }

    /** E.164 for a number we can recognise; null when we cannot. */
    fun toE164(raw: String?): String? {
        val digits = digitsOf(raw)
        if (digits.length < PHONE_KEY_DIGITS) return null
        val national = digits.substring(digits.length - UZ_NATIONAL_DIGITS)
        return "+$UZ_COUNTRY_CODE$national"
    }

    /** A short internal number behind a PBX, never a subscriber (UC-25). */
    fun isExtension(raw: String?): Boolean {
        val digits = digitsOf(raw)
        return digits.isNotEmpty() && digits.length < EXTENSION_MAX_DIGITS
    }
}
