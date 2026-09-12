package uz.bonvi.call.core

import com.google.common.truth.Truth.assertThat
import org.junit.After
import org.junit.Test
import timber.log.Timber
import java.io.File

/**
 * The debug file log, end to end from `Timber.i` to the bytes on disk.
 *
 * Exists because a planted tree that writes nothing is indistinguishable from
 * a phone that logs nothing at all — and that was this project's state for
 * its whole life: the old wrapper-shaped `RedactingTree` dropped every line
 * (see its KDoc). The first version of this test, written against the
 * wrapper, is what exposed it.
 */
class FileLogTreeTest {

    private val file = File.createTempFile("bonvicall", ".log").apply { delete() }

    @After
    fun uproot() {
        Timber.uprootAll()
        file.delete()
        File(file.parentFile, "${file.name}.1").delete()
    }

    @Test
    fun `a line logged through Timber lands in the file, redacted`() {
        Timber.plant(FileLogTree(file))

        Timber.i("Upload pass: sent=%d access_token=%s", 3, "secret-token-value")

        val text = file.readText()
        assertThat(text).contains("Upload pass: sent=3")
        assertThat(text).doesNotContain("secret-token-value")
        assertThat(text).contains("I/")
    }

    @Test
    fun `the file rotates at its limit and keeps one previous generation`() {
        Timber.plant(FileLogTree(file, maxBytes = 200))

        repeat(20) { Timber.w("line %02d %s", it, "x".repeat(40)) }

        val previous = File(file.parentFile, "${file.name}.1")
        assertThat(previous.exists()).isTrue()
        assertThat(file.length()).isLessThan(400L)
    }
}
