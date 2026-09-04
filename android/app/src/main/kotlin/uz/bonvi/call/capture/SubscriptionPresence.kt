package uz.bonvi.call.capture

import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.enrolment.SubscriptionPresenceProbe
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The `subscription_resolution` capability (SPEC §7.8).
 *
 * A thin adapter over [SubscriptionPrivacyBoundary], which is the only file
 * allowed to read `SubscriptionManager`. It exists so `enrolment/` can ask the
 * question without becoming a second reader of the telephony API — one reader
 * is one place that can decide a private call is a work call.
 */
@Singleton
class EnrolledSubscriptionPresenceProbe @Inject constructor(
    private val boundary: SubscriptionPrivacyBoundary,
    private val session: SessionStore,
) : SubscriptionPresenceProbe {

    override fun enrolledSubscriptionPresent(): Boolean =
        boundary.enrolledSubscriptionPresent(session.snapshot.simSubscriptionId)
}
