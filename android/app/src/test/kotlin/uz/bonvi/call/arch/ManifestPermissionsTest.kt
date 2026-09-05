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
            "RECORD_AUDIO",                             // UC-14
            "CALL_PHONE",                               // UC-16 — T104 keep-list
            "FOREGROUND_SERVICE",                       // UC-05
            "FOREGROUND_SERVICE_MICROPHONE",            // UC-14
            "FOREGROUND_SERVICE_DATA_SYNC",             // UC-11
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
            "READ_CONTACTS", "WRITE_CONTACTS",
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
    fun `the phoneCall foreground-service type is declared nowhere`() {
        // SPEC §7.2 lists it; it is wrong, and this test is what stops it being
        // added back from the SPEC. On API 34 the phoneCall type requires the
        // app to be the default dialer, hold MANAGE_OWN_CALLS, or be a device
        // owner. BonviCall is none of the three and cannot become any of them:
        // it observes calls rather than managing them, and the handsets are the
        // employees' own (REQUIREMENTS.md §5.7). Starting a foreground service
        // of a type you do not qualify for throws SecurityException, so this
        // would be a crash on every API 34 device, not a measurement.
        for (sourceSet in listOf("main", "legacy28", "modern34")) {
            assertThat(declaredPermissions(manifest(sourceSet)))
                .doesNotContain("FOREGROUND_SERVICE_PHONE_CALL")
            // Parsed, not grepped: the modern34 manifest explains at length WHY
            // this type is absent, and a text search would find that
            // explanation and fail. The rule is about declarations.
            assertThat(foregroundServiceTypes(manifest(sourceSet))).doesNotContain("phoneCall")
        }
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
        // Android 14 refuses a foreground service with no type, and throws for
        // a type the app does not qualify for. `microphone|dataSync` is the set
        // BonviCall actually holds the permissions for, and it is declared once
        // in main so the two flavours cannot drift.
        assertThat(manifest("main").readText())
            .contains("android:foregroundServiceType=\"microphone|dataSync\"")
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
        assertThat(File(android, "keystore.properties").exists()).isFalse()

        val ignored = File(android, ".gitignore").readText()
        for (pattern in listOf("keystore.properties", "*.jks", "*.keystore")) {
            assertThat(ignored).contains(pattern)
        }
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
