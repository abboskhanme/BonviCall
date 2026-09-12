package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * E3 appears on the handsets that need it and nowhere else (SPEC §8.2, R3).
 *
 * Both halves matter. A MIUI phone without these steps is killed overnight by
 * its own battery manager and the calls are simply absent; a handset that does
 * not need them and is shown them anyway loses a minute of a fifteen-minute
 * budget and learns that the instructions do not match its screens.
 */
class OemGuidanceTest {

    @Test
    fun `the manufacturers SPEC names get their own paths`() {
        for (oem in listOf("Xiaomi", "Redmi", "POCO", "HUAWEI", "honor", "OPPO", "vivo", "samsung")) {
            assertThat(OemGuidance.stepsFor(oem)).isNotEmpty()
            assertThat(OemGuidance.applies(oem)).isTrue()
        }
    }

    @Test
    fun `a handset with no battery manager of its own is not sent to E3`() {
        for (oem in listOf("Google", "Nokia", "Sony", "")) {
            assertThat(OemGuidance.stepsFor(oem)).isEmpty()
            assertThat(OemGuidance.applies(oem)).isFalse()
        }
    }

    @Test
    fun `the manufacturer string is whatever Build reports, in any case`() {
        // `Build.MANUFACTURER` is "Xiaomi" on one handset and "xiaomi" on
        // another. A case-sensitive match here would skip E3 on exactly the
        // phones it exists for.
        assertThat(OemGuidance.stepsFor("XIAOMI")).isEqualTo(OemGuidance.stepsFor("xiaomi"))
    }

    @Test
    fun `the screen and the flow cannot disagree about whether E3 exists`() {
        // `applies` is what the enrolment flow asks; `stepsFor` is what the
        // screen renders. When those two lived in different files the flow
        // could not ask, and E3 was skipped on every handset in the fleet.
        for (oem in listOf("Xiaomi", "Google", "samsung", "unknown-oem")) {
            assertThat(OemGuidance.applies(oem)).isEqualTo(OemGuidance.stepsFor(oem).isNotEmpty())
        }
    }
}
