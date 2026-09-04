package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * Never-false-ready (UC-03 AC, SPEC §7.8).
 *
 * `capturing` requires **every required capability working AND a verified
 * installation**, and the home screen and the server-facing state are computed
 * from this one function. A phone that says "Tayyor" and captures nothing is
 * the most expensive failure in the product, because the rollout looks finished
 * and nobody goes looking.
 *
 * SPEC asks for a test that denies each permission in turn and asserts both.
 * That is `every required capability blocks capturing on its own`.
 */
class CaptureReadinessTest {

    private fun allWorking(): MutableMap<Capability, CapabilityState> =
        CaptureReadiness.REQUIRED.associateWith { CapabilityState.GRANTED_WORKING }.toMutableMap()

    @Test
    fun `everything working and verified is capturing`() {
        val readiness = CaptureReadiness.evaluate(allWorking(), true, true)

        assertThat(readiness.state).isEqualTo(CaptureReadiness.CaptureState.CAPTURING)
        assertThat(readiness.blocking).isEmpty()
        assertThat(readiness.isCapturing).isTrue()
    }

    @Test
    fun `every required capability blocks capturing on its own`() {
        for (capability in CaptureReadiness.REQUIRED) {
            for (state in listOf(
                CapabilityState.DENIED,
                CapabilityState.DENIED_PERMANENTLY,
                CapabilityState.UNKNOWN,
                // The one that matters most: the OEM says granted and blocks it.
                CapabilityState.GRANTED_NOT_WORKING,
            )) {
                val states = allWorking().apply { put(capability, state) }
                val readiness = CaptureReadiness.evaluate(states, true, true)

                assertThat(readiness.isCapturing).isFalse()
                assertThat(readiness.blocking).contains(capability)
            }
        }
    }

    @Test
    fun `a missing capability counts as blocking - absent is not granted`() {
        val states = allWorking().apply { remove(Capability.MICROPHONE) }

        assertThat(CaptureReadiness.evaluate(states, true, true).blocking)
            .contains(Capability.MICROPHONE)
    }

    @Test
    fun `an unverified number is never capturing, however good the permissions`() {
        // The provisional token gets a phone through verification and nothing
        // else: the server accepts no calls until the number is proven.
        val readiness = CaptureReadiness.evaluate(allWorking(), true, numberVerified = false)

        assertThat(readiness.state).isEqualTo(CaptureReadiness.CaptureState.NOT_VERIFIED)
        assertThat(readiness.isCapturing).isFalse()
    }

    @Test
    fun `an unbound installation is never capturing`() {
        val readiness = CaptureReadiness.evaluate(allWorking(), false, true)

        assertThat(readiness.state).isEqualTo(CaptureReadiness.CaptureState.NOT_ENROLLED)
    }

    @Test
    fun `optional capabilities never block`() {
        // `contacts` degrades contact_name only and the app never reads the
        // contact book anyway (N28); an unverifiable OEM autostart must not be
        // able to stop a working phone.
        val states = allWorking().apply {
            put(Capability.CONTACTS, CapabilityState.DENIED)
            put(Capability.OEM_AUTOSTART, CapabilityState.UNKNOWN)
            put(Capability.CALL_PHONE, CapabilityState.DENIED)
        }

        assertThat(CaptureReadiness.evaluate(states, true, true).isCapturing).isTrue()
    }

    @Test
    fun `the blocker list is ordered the way E2 asks for them`() {
        // SPEC §5.2 wants the panel to name "the blocking capability"; naming a
        // different one from the phone would send an admin to the wrong step.
        val states = allWorking().apply {
            put(Capability.MICROPHONE, CapabilityState.DENIED)
            put(Capability.PHONE_STATE, CapabilityState.DENIED)
        }

        assertThat(CaptureReadiness.evaluate(states, true, true).blocking)
            .containsExactly(Capability.PHONE_STATE, Capability.MICROPHONE)
            .inOrder()
    }

    @Test
    fun `E2 puts the alarming permissions after two easy successes`() {
        // Not decoration: N40 gives 15 unaided minutes on somebody's own phone,
        // and the step where people stop is the first one that looks
        // frightening.
        val order = CaptureReadiness.E2_ORDER
        assertThat(order.take(2))
            .containsExactly(Capability.PHONE_STATE, Capability.CALL_LOG).inOrder()
        assertThat(order.indexOf(Capability.BATTERY_EXEMPTION))
            .isGreaterThan(order.indexOf(Capability.MICROPHONE))
        assertThat(order.indexOf(Capability.STORAGE_ACCESS))
            .isGreaterThan(order.indexOf(Capability.BATTERY_EXEMPTION))
    }

    @Test
    fun `contacts is never a required capability`() {
        // The install landing page promises in writing that the contact book is
        // never uploaded. Requiring it would contradict the promise.
        assertThat(CaptureReadiness.REQUIRED).doesNotContain(Capability.CONTACTS)
        assertThat(CaptureReadiness.OPTIONAL).contains(Capability.CONTACTS)
    }
}
