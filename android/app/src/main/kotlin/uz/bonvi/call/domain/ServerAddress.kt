package uz.bonvi.call.domain

/**
 * The server this installation talks to, and who may change it.
 *
 * ═══ Why this is editable at all ═══════════════════════════════════════════
 * A free tunnel gets a new hostname every restart, and it has died twice
 * mid-test — each time costing a rebuild, a file transfer and a reinstall
 * before anyone could do anything. Baking the address in at build time made a
 * five-second problem into a twenty-minute one.
 *
 * ═══ Why it is editable only in a debug build ══════════════════════════════
 * A field that lets anyone repoint a salesperson's phone at another server is
 * not something that ships. Everything this app captures would go there, and
 * the handset would look completely normal. So the guard is not "hide the
 * screen" — hiding a control is not access control, the same mistake as a nav
 * menu without a route gate. [isEditable] is checked in the STORE, so a release
 * build refuses the write even if a screen somehow asks for it.
 */
object ServerAddress {

    /** Production. A release build uses this and cannot be moved off it. */
    const val PRODUCTION = "https://bonvicall.uz"

    sealed interface Validation {
        data class Valid(val normalised: String) : Validation
        data class Invalid(val reason: Reason) : Validation

        enum class Reason {
            /** Empty, or not a URL at all. */
            NOT_A_URL,

            /** Something other than http or https — `ftp://`, or a bare host
             *  the user pasted without a scheme. */
            BAD_SCHEME,

            /** No host. `https://` on its own. */
            NO_HOST,
        }
    }

    /**
     * Validate and normalise a typed address.
     *
     * The point is that **a typo shows up as a typo**, here, rather than as
     * "no internet" three screens later. That failure has already happened
     * once on real hardware and cost an afternoon: a converter error surfaced
     * as a network error on a phone with working 4G.
     *
     * Normalisation drops a trailing slash and any path, because the API prefix
     * is appended by the client — `https://host/` and `https://host` must not
     * produce `//api/device/v1`.
     */
    fun validate(raw: String): Validation {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) return Validation.Invalid(Validation.Reason.NOT_A_URL)

        // Deliberately strict about the scheme rather than helpfully adding
        // one: a pasted `bonvicall.uz` could be http or https, and guessing
        // wrong is a cleartext attempt the network config then refuses with a
        // message about security rather than about the address.
        val scheme = trimmed.substringBefore("://", missingDelimiterValue = "")
        if (scheme.isEmpty()) return Validation.Invalid(Validation.Reason.BAD_SCHEME)
        if (scheme != "http" && scheme != "https") {
            return Validation.Invalid(Validation.Reason.BAD_SCHEME)
        }

        val rest = trimmed.substringAfter("://")
        val host = rest.substringBefore('/').substringBefore('?')
        if (host.isEmpty() || host.startsWith(":")) {
            return Validation.Invalid(Validation.Reason.NO_HOST)
        }

        return Validation.Valid("$scheme://$host")
    }

    /**
     * Where an address may come from, in precedence order.
     *
     * The deep link wins: a code opened from the install link carries the
     * server it belongs to, and that is the normal path. The manual field is
     * for when there is no link — a code read out over the phone, or a tunnel
     * that moved after enrolment.
     */
    enum class Source { DEEP_LINK, MANUAL, PRODUCTION_DEFAULT }
}
