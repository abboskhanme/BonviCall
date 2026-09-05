package uz.bonvi.call.arch

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.TestPaths

/**
 * Things that must not be possible in a release build.
 *
 * A field that lets anyone repoint a salesperson's phone at another server is
 * not something that ships: everything the app captures would go there and the
 * handset would look completely normal. The guard is enforced in the STORE, not
 * only in the screen that offers it — **hiding a control is not access
 * control**, the same mistake as a nav menu without a route gate.
 */
class ReleaseHardeningTest {

    private fun source(name: String): String =
        TestPaths.kotlinSources().single { it.name == name }.readText()

    @Test
    fun `a manual server address is refused unless the build is debug`() {
        val store = source("SessionStore.kt")
        assertThat(store).contains("ServerAddress.Source.MANUAL && !BuildConfig.DEBUG")
        assertThat(store).contains("serverAddressEditable")
    }

    @Test
    fun `the address is validated before it is written`() {
        // A saved unreachable address leaves the phone pointed at nothing, and
        // every failure after that reads as "no internet".
        assertThat(source("SessionStore.kt")).contains("ServerAddress.validate")
    }

    @Test
    fun `the screen only offers it when the store would accept it`() {
        // Two guards agreeing is fine; a screen that offers what the store
        // refuses is a bug report from a confused developer.
        assertThat(source("DiagnosticsScreen.kt")).contains("if (state.serverEditable)")
    }

    @Test
    fun `saving is gated on a successful check`() {
        assertThat(source("DiagnosticsScreen.kt")).contains("enabled = viewModel.canSave()")
        assertThat(source("DiagnosticsViewModel.kt")).contains("CheckResult.Reachable")
    }

    @Test
    fun `the reachability check bypasses the base-URL rewrite`() {
        // Testing an address has to reach exactly the address typed. The shared
        // client would rewrite it to the one being replaced, and the check
        // would pass against the wrong server.
        val network = source("NetworkModule.kt")
        assertThat(network).contains("OkHttpClient.Builder().build()")
        assertThat(source("ServerReachabilityApi.kt")).contains("@Url")
    }
}
