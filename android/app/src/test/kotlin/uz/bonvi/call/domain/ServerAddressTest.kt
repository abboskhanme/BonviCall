package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * The server address, typed by a person under time pressure.
 *
 * ═══ What this is protecting against ═══════════════════════════════════════
 * On real hardware, a converter error surfaced as "no internet" on a phone with
 * working 4G and cost an afternoon. The lesson is that **a typo must show up as
 * a typo, at the point it is typed**, not as a network failure three screens
 * later. Everything below is that lesson.
 */
class ServerAddressTest {

    private fun valid(raw: String) = ServerAddress.validate(raw) as ServerAddress.Validation.Valid

    private fun reason(raw: String) =
        (ServerAddress.validate(raw) as ServerAddress.Validation.Invalid).reason

    @Test
    fun `a plain https address is accepted`() {
        assertThat(valid("https://bonvicall.uz").normalised).isEqualTo("https://bonvicall.uz")
    }

    @Test
    fun `a tunnel hostname with a port is accepted`() {
        // The case this feature exists for: a free tunnel that changes name on
        // every restart, or a laptop on the LAN.
        assertThat(valid("http://192.168.1.23:8020").normalised)
            .isEqualTo("http://192.168.1.23:8020")
        assertThat(valid("https://odd-name-1234.trycloudflare.com").normalised)
            .isEqualTo("https://odd-name-1234.trycloudflare.com")
    }

    @Test
    fun `a trailing slash and a path are dropped`() {
        // The client appends /api/device/v1. Without this, one gets
        // `https://host//api/device/v1` and the failure is a 404 that reads
        // like the server is down.
        assertThat(valid("https://bonvicall.uz/").normalised).isEqualTo("https://bonvicall.uz")
        assertThat(valid("https://bonvicall.uz/api/device/v1").normalised)
            .isEqualTo("https://bonvicall.uz")
    }

    @Test
    fun `surrounding whitespace is forgiven`() {
        // A pasted address usually carries some.
        assertThat(valid("  https://bonvicall.uz \n").normalised)
            .isEqualTo("https://bonvicall.uz")
    }

    @Test
    fun `a bare hostname is refused rather than guessed at`() {
        // Deliberately NOT helpful: `bonvicall.uz` could be http or https, and
        // guessing wrong produces a cleartext attempt that the network config
        // then refuses with a message about security rather than the address.
        assertThat(reason("bonvicall.uz")).isEqualTo(ServerAddress.Validation.Reason.BAD_SCHEME)
        assertThat(reason("192.168.1.23:8020"))
            .isEqualTo(ServerAddress.Validation.Reason.BAD_SCHEME)
    }

    @Test
    fun `a non-http scheme is refused`() {
        assertThat(reason("ftp://bonvicall.uz")).isEqualTo(ServerAddress.Validation.Reason.BAD_SCHEME)
        assertThat(reason("bonvicall://enrol"))
            .isEqualTo(ServerAddress.Validation.Reason.BAD_SCHEME)
    }

    @Test
    fun `a scheme with no host is refused`() {
        assertThat(reason("https://")).isEqualTo(ServerAddress.Validation.Reason.NO_HOST)
        assertThat(reason("https://:8020")).isEqualTo(ServerAddress.Validation.Reason.NO_HOST)
    }

    @Test
    fun `empty is not a URL`() {
        assertThat(reason("")).isEqualTo(ServerAddress.Validation.Reason.NOT_A_URL)
        assertThat(reason("   ")).isEqualTo(ServerAddress.Validation.Reason.NOT_A_URL)
    }

    @Test
    fun `production is the compiled-in default`() {
        assertThat(ServerAddress.PRODUCTION).startsWith("https://")
        assertThat(ServerAddress.validate(ServerAddress.PRODUCTION))
            .isInstanceOf(ServerAddress.Validation.Valid::class.java)
    }

    @Test
    fun `the deep link outranks a typed address`() {
        // A code opened from the install link carries the server it belongs to
        // and that is the normal path; the typed field is the manual fallback.
        assertThat(ServerAddress.Source.entries).containsExactly(
            ServerAddress.Source.DEEP_LINK,
            ServerAddress.Source.MANUAL,
            ServerAddress.Source.PRODUCTION_DEFAULT,
        ).inOrder()
    }
}
