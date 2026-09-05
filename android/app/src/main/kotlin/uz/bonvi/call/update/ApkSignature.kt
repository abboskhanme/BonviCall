package uz.bonvi.call.update

import android.content.Context
import android.content.pm.PackageManager
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import uz.bonvi.call.core.Capabilities
import java.io.File
import java.security.MessageDigest
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Does this APK carry the same signing key as the app already installed? (T82)
 *
 * ═══ Why this is checked before installing and not after ═══════════════════
 * Android will not install an update signed by a different key. It fails, and
 * the only way to get the new build onto the handset is **uninstall and
 * reinstall — which destroys the phone's unsent queue** (`docs/APK-SIGNING.md`).
 * An agent following the prompt would do exactly that, and lose every call the
 * phone had captured and not yet uploaded.
 *
 * So a mismatched APK is refused here, with the download deleted, and reported.
 * A wrong key is either a build mistake or something worse; neither is
 * something to hand to a salesperson as an install prompt.
 *
 * The comparison is against **the running app's own signer**, not a constant
 * compiled in. A hard-coded fingerprint would have to be updated in the same
 * release that rotates the key, which is precisely the release where getting it
 * wrong is unrecoverable.
 */
@Singleton
class ApkSignature @Inject constructor(
    @ApplicationContext private val context: Context,
) {

    sealed interface Verdict {
        data object Matches : Verdict
        data class Mismatch(val expected: String, val actual: String) : Verdict
        /** The APK could not be read, or the platform would not report a
         *  signer. Refused: unverifiable is not the same as verified. */
        data class Unverifiable(val why: String) : Verdict
    }

    fun verify(apk: File): Verdict {
        val installed = installedSignerSha256()
            ?: return Verdict.Unverifiable("cannot read this app's own signer")
        val candidate = apkSignerSha256(apk)
            ?: return Verdict.Unverifiable("cannot read the downloaded APK's signer")

        return if (installed.equals(candidate, ignoreCase = true)) {
            Verdict.Matches
        } else {
            Timber.e("Downloaded APK is signed by a different key; refusing to install it")
            Verdict.Mismatch(installed, candidate)
        }
    }

    private fun installedSignerSha256(): String? = signerOf(context.packageName, null)

    private fun apkSignerSha256(apk: File): String? = signerOf(null, apk.absolutePath)

    @Suppress("DEPRECATION")
    private fun signerOf(packageName: String?, archivePath: String?): String? = runCatching {
        val manager = context.packageManager
        val flags = if (Capabilities.supportsSigningInfo()) {
            PackageManager.GET_SIGNING_CERTIFICATES
        } else {
            PackageManager.GET_SIGNATURES
        }
        val info = when {
            packageName != null -> manager.getPackageInfo(packageName, flags)
            archivePath != null -> manager.getPackageArchiveInfo(archivePath, flags)
            else -> null
        } ?: return null

        val certificates = if (Capabilities.supportsSigningInfo()) {
            info.signingInfo?.let { signing ->
                if (signing.hasMultipleSigners()) {
                    signing.apkContentsSigners
                } else {
                    signing.signingCertificateHistory
                }
            }
        } else {
            info.signatures
        }

        certificates?.firstOrNull()?.toByteArray()?.let { bytes ->
            MessageDigest.getInstance("SHA-256").digest(bytes)
                .joinToString("") { "%02x".format(it) }
        }
    }.onFailure {
        // Broad, and the specific failure is a NameNotFoundException or an OEM
        // that refuses to parse a downloaded archive. Either way the answer is
        // "we cannot tell", which this class treats as a refusal.
        Timber.w(it, "Could not read a package signer")
    }.getOrNull()
}
