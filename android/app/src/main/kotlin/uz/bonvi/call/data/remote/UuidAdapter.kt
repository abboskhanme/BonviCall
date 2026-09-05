package uz.bonvi.call.data.remote

import com.squareup.moshi.FromJson
import com.squareup.moshi.ToJson
import java.util.UUID

/**
 * `java.util.UUID` on the wire, as the string the server sends.
 *
 * Moshi refuses platform classes without an explicit adapter — `java.util.*`
 * has no reliable reflective shape — and the generated DTOs are full of UUID
 * ids. Without this, **every** device API call fails before it leaves the
 * phone, with `Unable to create converter for class …`.
 *
 * That is exactly what happened on the first handset this app ran on: the
 * failure was caught as a generic exception and reported to the user as "no
 * internet", on a phone with working mobile data, against a server the
 * browser could reach in the same second. The unit suite never saw it because
 * tests construct DTOs directly; only a real request through Retrofit builds
 * the converter, and only then does Moshi look at the types.
 *
 * The lesson is not about UUIDs. It is that a client whose serialisation layer
 * has never made one real call has not been tested.
 */
object UuidAdapter {
    @ToJson
    fun toJson(value: UUID): String = value.toString()

    @FromJson
    fun fromJson(value: String): UUID = UUID.fromString(value)
}

/**
 * `java.time.LocalDate` as the ISO date the server sends — `hired_at` and the
 * other date-only fields.
 *
 * Same reason as [UuidAdapter], and found the same way: the eager-converter
 * test caught it one run after the UUID fix. Two fatal serialisation gaps in
 * the same layer is the signal — the layer had never made a real call, so
 * nothing had ever asked Moshi to look at these types.
 *
 * Date, not date-time, deliberately. A `LocalDate` carries no zone and must
 * not acquire one on the way through: `hired_at` is a calendar day, and the
 * day somebody was employed does not shift because a phone is in a different
 * timezone.
 */
object LocalDateAdapter {
    @ToJson
    fun toJson(value: java.time.LocalDate): String = value.toString()

    @FromJson
    fun fromJson(value: String): java.time.LocalDate = java.time.LocalDate.parse(value)
}
