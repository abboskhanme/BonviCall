package uz.bonvi.call

import java.io.File

/**
 * Where the repository is, from inside a unit test.
 *
 * `app/build.gradle.kts` passes the two roots as system properties, because
 * Gradle does not promise which directory it forks the test JVM in and a test
 * that resolves `../../contract` by luck fails on somebody else's machine.
 * The walk-up fallback exists for running a single test from an IDE.
 */
object TestPaths {

    val repoRoot: File by lazy {
        System.getProperty("bonvicall.repoRoot")?.let(::File)?.takeIf { it.isDirectory }
            ?: walkUpTo("contract")
    }

    val appDir: File by lazy {
        System.getProperty("bonvicall.appDir")?.let(::File)?.takeIf { it.isDirectory }
            ?: File("").absoluteFile
    }

    /** `contract/` — the shared wire contract, read by the server tests too. */
    val contractDir: File get() = File(repoRoot, "contract")

    /** Every Kotlin source file in the app, across all source sets. */
    fun kotlinSources(): List<File> =
        listOf("src/main", "src/legacy28", "src/modern34")
            .map { File(appDir, it) }
            .filter { it.isDirectory }
            .flatMap { root -> root.walkTopDown().filter { it.isFile && it.extension == "kt" } }

    private fun walkUpTo(marker: String): File {
        var candidate: File? = File("").absoluteFile
        while (candidate != null) {
            if (File(candidate, marker).isDirectory) return candidate
            candidate = candidate.parentFile
        }
        error("Could not find the repository root: no '$marker' directory above ${File("").absolutePath}")
    }
}
