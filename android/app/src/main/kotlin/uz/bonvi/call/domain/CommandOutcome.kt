package uz.bonvi.call.domain

/**
 * How a dial's refusal becomes a reason the panel can group by.
 *
 * The dialler reports what went wrong in its own words — a freshness verdict, a
 * number it could not parse, the name of the exception the OS threw — and the
 * server's vocabulary is a closed enum. Doing that translation in one pure
 * function keeps it testable and keeps `os_refused` from becoming the bucket
 * everything falls into, which is how a fleet-wide permission problem hides.
 */
object CommandOutcome {

    /** @param reason `DialCommand.Result.Discarded.reason`. */
    fun forDialDiscard(reason: String): CommandFailure = when {
        // "discarded_stale_612s" — the age is part of the string on purpose,
        // and the bucket is the same whatever the age.
        reason.startsWith("discarded_stale") -> CommandFailure.DISCARDED_STALE

        // Thrown when CALL_PHONE was granted at enrolment and revoked later,
        // which is the failure UC-16 is most likely to meet in the field.
        reason == "SecurityException" -> CommandFailure.NO_PERMISSION

        // The panel sent something that is not a number. Not the phone's fault
        // and not something a retry fixes.
        reason == "unparseable_number" -> CommandFailure.UNSUPPORTED

        // ActivityNotFoundException and anything else the handset did.
        else -> CommandFailure.OS_REFUSED
    }
}
