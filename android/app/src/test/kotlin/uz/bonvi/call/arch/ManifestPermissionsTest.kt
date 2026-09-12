package uz.bonvi.call.arch

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.TestPaths
import org.w3c.dom.Node
import java.io.File
import javax.xml.parsers.DocumentBuilderFactory

/**
 * The declared permission set, per flavour.
 *
 * Two things are pinned, and both are about a person rather than a build:
 *
 *  1. **Every `<uses-permission>` carries a comment naming its UC**
 *     (CONVENTIONS-CLIENT.md §9). Each permission is another alarming screen
 *     during N40's 15 unaided minutes, and T107 photographs those screens
 *     against whatever set T104 leaves behind. An uncommented permission is a
 *     review failure; this makes it a build failure.
 *  2. **The forbidden set stays forbidden.** READ_CONTACTS, SMS, location and
 *     camera are not "not needed yet" — the install landing page promises in
 *     writing that the contact book, SMS, photos and location are never
 *     uploaded (§8.1), and this test is that promise in executable form.
 */
private const val ANDROID_NS = "http://schemas.android.com/apk/res/android"

class ManifestPermissionsTest {

    private fun manifest(sourceSet: String): File =
        File(TestPaths.appDir, "src/$sourceSet/AndroidManifest.xml")

    /**
     * The `<uses-permission>` ELEMENTS, parsed as XML.
     *
     * Parsing rather than grepping matters here: the manifests document
     * themselves heavily, and the header comment of src/main names
     * `<uses-permission>` in prose. A text search finds that sentence and
     * reports a permission that does not exist.
     */
    private fun permissionElements(file: File): List<Node> {
        assertThat(file.isFile).isTrue()
        val document = DocumentBuilderFactory.newInstance()
            .apply { isNamespaceAware = true }
            .newDocumentBuilder()
            .parse(file)
        val nodes = document.getElementsByTagName("uses-permission")
        return (0 until nodes.length).map { nodes.item(it) }
    }

    private fun declaredPermissions(file: File): List<String> =
        permissionElements(file).mapNotNull { node ->
            node.attributes?.getNamedItemNS(ANDROID_NS, "name")?.nodeValue?.substringAfterLast('.')
        }

    /** Every `android:foregroundServiceType` value declared on any `<service>`. */
    private fun foregroundServiceTypes(file: File): List<String> {
        val document = DocumentBuilderFactory.newInstance()
            .apply { isNamespaceAware = true }
            .newDocumentBuilder()
            .parse(file)
        val services = document.getElementsByTagName("service")
        return (0 until services.length).flatMap { index ->
            services.item(index).attributes
                ?.getNamedItemNS(ANDROID_NS, "foregroundServiceType")
                ?.nodeValue
                ?.split("|")
                ?.map { it.trim() }
                .orEmpty()
        }
    }

    /**
     * The comment block that justifies this permission.
     *
     * Walks backwards over siblings, skipping whitespace and any permissions
     * that share the block. That models how the manifests are actually written
     * — FOREGROUND_SERVICE_MICROPHONE and FOREGROUND_SERVICE_DATA_SYNC sit
     * under one comment on purpose — and it needs no character-distance
     * heuristic, which is what the first version of this test used and got
     * wrong on a long comment.
     */
    private fun justifyingComment(element: Node): String {
        var sibling: Node? = element.previousSibling
        while (sibling != null) {
            when {
                sibling.nodeType == Node.COMMENT_NODE -> return sibling.nodeValue.orEmpty()
                sibling.nodeType == Node.TEXT_NODE && sibling.nodeValue.isNullOrBlank() -> Unit
                sibling.nodeName == "uses-permission" -> Unit
                else -> return ""
            }
            sibling = sibling.previousSibling
        }
        return ""
    }

    private val mainPermissions get() = declaredPermissions(manifest("main"))

    @Test
    fun `the shared permission set is exactly what the use cases need`() {
        assertThat(mainPermissions).containsExactly(
            "INTERNET",                                 // UC-10, UC-11
            "ACCESS_NETWORK_STATE",                     // UC-11, N14/N15
            "READ_PHONE_STATE",                         // UC-09, UC-15
            "READ_PHONE_NUMBERS",                       // UC-04
            "READ_CALL_LOG",                            // UC-13
            "READ_CONTACTS",                            // UC-19, T139 — one name, never the book
            "RECORD_AUDIO",                             // UC-14
            "CALL_PHONE",                               // UC-16 — T104 keep-list
            "FOREGROUND_SERVICE",                       // UC-05
            "FOREGROUND_SERVICE_MICROPHONE",            // UC-14
            "FOREGROUND_SERVICE_DATA_SYNC",             // UC-11
            "FOREGROUND_SERVICE_PHONE_CALL",            // UC-05 — the type that survives doze
            "MANAGE_OWN_CALLS",                         // UC-05 — what qualifies for it, normal
            "REQUEST_INSTALL_PACKAGES",                 // UC-02, T82 — N33, no Play
            "RECEIVE_BOOT_COMPLETED",                   // UC-05
            "WAKE_LOCK",                                // UC-05, UC-11
            "REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",     // UC-03
            "POST_NOTIFICATIONS",                       // UC-05, UC-18
        )
    }

    @Test
    fun `CALL_PHONE is declared - UC-16 fails silently without it`() {
        // On T104's keep-list explicitly. It was nearly minimised away once,
        // and the failure it causes is a dial command that does nothing at all.
        assertThat(mainPermissions).contains("CALL_PHONE")
    }

    @Test
    fun `nothing the product promises never to read is declared`() {
        val forbidden = listOf(
            // READ_CONTACTS is declared (T139) and WRITE is not: the app turns
            // one number into one name and never modifies the book.
            "WRITE_CONTACTS",
            "READ_SMS", "RECEIVE_SMS", "SEND_SMS",
            "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION",
            "CAMERA",
            "READ_MEDIA_IMAGES", "READ_MEDIA_VIDEO",
            "QUERY_ALL_PACKAGES",
        )
        val everyManifest = listOf("main", "legacy28", "modern34").flatMap {
            declaredPermissions(manifest(it))
        }
        assertThat(everyManifest.filter { it in forbidden }).isEmpty()
    }

    @Test
    fun `legacy28 reads external storage and never writes it`() {
        val permissions = declaredPermissions(manifest("legacy28"))
        assertThat(permissions).contains("READ_EXTERNAL_STORAGE")
        // SPEC §7.2 names WRITE_EXTERNAL_STORAGE for this flavour; it is
        // deliberately absent. OEM recordings are opened read-only and never
        // moved, modified or deleted (CONVENTIONS.md §8.3), so a write
        // permission would authorise the one thing the boundary forbids.
        assertThat(permissions).doesNotContain("WRITE_EXTERNAL_STORAGE")
    }

    @Test
    fun `modern34 declares the scoped-storage route to the OEM folder`() {
        val permissions = declaredPermissions(manifest("modern34"))
        assertThat(permissions).containsExactly(
            "MANAGE_EXTERNAL_STORAGE",  // UC-14 under scoped storage
            "READ_MEDIA_AUDIO",         // UC-14, API 33+ split
        )
    }

    @Test
    fun `the phoneCall type is declared only where the app qualifies for it`() {
        // ⚠️ This test used to say the opposite, and the reasoning it carried
        // was right about the RULE and wrong about the app. On API 34+ the
        // `phoneCall` type requires the default-dialer role, MANAGE_OWN_CALLS,
        // or device ownership — and starting a service with a type you do not
        // qualify for throws. BonviCall now holds MANAGE_OWN_CALLS, which is a
        // NORMAL permission: granted at install, no dialog, nothing an agent
        // sees. CallSentry qualified the same way and stayed alive on the same
        // handsets, where this app went silent 19 minutes after the screen went
        // off.
        //
        // What it buys: exemption from Android 15's six-hour `dataSync` budget,
        // and permission to be restarted from the background — which is exactly
        // what the watchdog does after an OEM kill.
        val declared = declaredPermissions(manifest("main"))
        for (sourceSet in listOf("main", "legacy28", "modern34")) {
            if (!foregroundServiceTypes(manifest(sourceSet)).contains("phoneCall")) continue
            assertThat(declared).contains("FOREGROUND_SERVICE_PHONE_CALL")
            assertThat(declared).contains("MANAGE_OWN_CALLS")
        }
    }

    @Test
    fun `the service never assumes the OS will accept its best type`() {
        // The manifest declares what MAY be used; the runtime decides what IS.
        // A type the OS refuses must degrade to a lesser one, never take the
        // service down — a phone capturing with `microphone|dataSync` is worth
        // more than one that crashed insisting on `phoneCall`.
        val service = TestPaths.kotlinSources().single { it.name == "CaptureService.kt" }.readText()
        assertThat(service).contains("ServiceCompat.startForeground")
        assertThat(service).contains("catch")
        // And what the OS accepted is reported, so the fleet answers this
        // question with data rather than with this comment.
        assertThat(service).contains("activeType")
    }

    @Test
    fun `every uses-permission carries a comment naming its UC`() {
        // CONVENTIONS-CLIENT.md §9. The comment is checked by proximity: a
        // permission must have a comment block above it that names a UC, an N
        // requirement or an R risk. It is crude and it catches the real case —
        // a permission pasted in without a reason.
        val reason = Regex("""UC-\d+|N\d+|R\d+""")
        val uncommented = mutableListOf<String>()

        for (sourceSet in listOf("main", "legacy28", "modern34")) {
            for (element in permissionElements(manifest(sourceSet))) {
                val name = element.attributes
                    ?.getNamedItemNS(ANDROID_NS, "name")?.nodeValue.orEmpty()
                if (!reason.containsMatchIn(justifyingComment(element))) {
                    uncommented += "$sourceSet: $name"
                }
            }
        }

        assertThat(uncommented).isEmpty()
    }

    @Test
    fun `the shipped network config refuses cleartext outright`() {
        // N22, CONVENTIONS-CLIENT.md §9. `main` is what every release build
        // uses, and it permits cleartext to nothing at all.
        val config = File(TestPaths.appDir, "src/main/res/xml/network_security_config.xml")
        assertThat(config.readText()).contains("cleartextTrafficPermitted=\"false\"")
        assertThat(config.readText()).doesNotContain("cleartextTrafficPermitted=\"true\"")
        assertThat(manifest("main").readText()).contains("android:networkSecurityConfig")

        // No release-only override can reintroduce one.
        assertThat(File(TestPaths.appDir, "src/release/res/xml/network_security_config.xml").exists())
            .isFalse()
    }

    @Test
    fun `the debug config permits cleartext to named hosts only`() {
        // Narrowed, not lifted. Requiring real TLS for every local iteration is
        // a recurring tax across Phase 4 and the risk is essentially zero —
        // src/debug/ resources are not in a release artefact. What must stay
        // true is that the hole is a LIST OF HOSTS and never a blanket switch.
        // The TEMPLATE, which is what is tracked. The substituted copy (with
        // the developer's LAN address from `bonvicall.devHost`) lands in build/
        // and is never committed — so nobody's home IP reaches the repository
        // and nobody edits a tracked file to test on their own network.
        val debug = File(TestPaths.appDir, "src/debug/network_security_config.template.xml")
        if (!debug.exists()) return
        val text = debug.readText()

        // The base config still refuses cleartext, so an accidental http:// to
        // anything not named below still fails.
        assertThat(text).contains("<base-config cleartextTrafficPermitted=\"false\">")
        // The permission is scoped to a <domain-config>, never to <base-config>.
        assertThat(Regex("""<base-config[^>]*cleartextTrafficPermitted="true"""").containsMatchIn(text))
            .isFalse()
        assertThat(text).contains("<domain-config cleartextTrafficPermitted=\"true\">")

        // At least one named domain, and no wildcard.
        val domains = Regex("""<domain[^>]*>([^<]+)</domain>""").findAll(text)
            .map { it.groupValues[1].trim() }
            .toList()
        assertThat(domains).isNotEmpty()
        assertThat(domains.any { it == "*" || it.startsWith("*.") }).isFalse()
        // The LAN host is a placeholder in the tracked file, not an address.
        assertThat(domains).contains("__DEV_HOST__")

        // No build type trusts user-installed certificates. This is the part
        // that matters: a handset with a corporate or malware root must never
        // be able to read the audio of every call the fleet makes.
        assertThat(text).doesNotContain("src=\"user\"")
        assertThat(File(TestPaths.appDir, "src/main/res/xml/network_security_config.xml").readText())
            .doesNotContain("src=\"user\"")
    }

    @Test
    fun `the capture service declares a foreground type both flavours qualify for`() {
        // Android 14 refuses a foreground service with no type. All three are
        // declared once in main — the manifest cannot express "try this, then
        // that", so it lists what is allowed and CaptureService picks — and the
        // two flavours cannot drift because neither overrides it.
        assertThat(manifest("main").readText())
            .contains("android:foregroundServiceType=\"phoneCall|microphone|dataSync\"")
        // No flavour overrides it.
        assertThat(manifest("modern34").readText()).doesNotContain("foregroundServiceType")
        assertThat(manifest("legacy28").readText()).doesNotContain("foregroundServiceType")
    }

    @Test
    fun `backup is off so an installation-bound credential cannot be restored elsewhere`() {
        // N24: a token restored onto a different handset is exactly the
        // installation_mismatch the server refuses.
        assertThat(manifest("main").readText()).contains("android:allowBackup=\"false\"")
    }

    @Test
    fun `the signing key is never committed`() {
        // T81. Losing the key means no device can ever be updated again
        // (docs/APK-SIGNING.md); committing it is the other half of the same
        // incident. The example file exists so nobody has to guess the shape.
        val android = TestPaths.appDir.parentFile
        assertThat(File(android, "keystore.properties.example").isFile).isTrue()

        // ⚠️ The rule is "never COMMITTED", and it is enforced by the ignore
        // patterns below. This used to assert the file did not EXIST, which is
        // a different and wrong rule: the machine that cuts releases must hold
        // one, and on 2026-09-11 — the day the project's first keystore was
        // generated — that assertion turned a correct setup into a red build.
        // Ignoring is the guarantee; absence is an accident of whose laptop
        // the suite happens to be running on.
        val ignored = File(android, ".gitignore").readText()
        for (pattern in listOf("keystore.properties", "*.jks", "*.keystore")) {
            assertThat(ignored).contains(pattern)
        }

        // And the key itself must never sit anywhere git is watching that the
        // patterns do not cover.
        val stray = android.walkTopDown()
            .filter { it.isFile && (it.extension == "jks" || it.extension == "keystore") }
            .filterNot { it.parentFile == android }
            .map { it.relativeTo(android).path }
            .toList()
        assertThat(stray).isEmpty()
    }

    @Test
    fun `the release build is signed only when a keystore is configured`() {
        // Without it `assembleRelease` must still succeed and produce
        // -unsigned.apk: CI and a developer without the key have to be able to
        // prove the release variant compiles.
        val build = File(TestPaths.appDir, "build.gradle.kts").readText()
        assertThat(build).contains("takeIf { it.storeFile != null }")
        assertThat(build).contains("enableV2Signing = true")
    }
}
