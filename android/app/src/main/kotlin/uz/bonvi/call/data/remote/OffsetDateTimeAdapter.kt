package uz.bonvi.call.data.remote

import com.squareup.moshi.FromJson
import com.squareup.moshi.ToJson
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter

/**
 * Wire timestamps are ISO-8601 **with an explicit offset** (N36, SPEC §4.0):
 * `2026-09-04T14:03:11.412+05:00`.
 *
 * Moshi has no `java.time` adapter, and the alternative — letting the generated
 * DTOs carry a `String` — would put the parsing in whichever caller needed it
 * first and then in a second one, differently. `java.time` is available from
 * API 26, which is `minSdk`.
 */
class OffsetDateTimeAdapter {

    @ToJson
    fun toJson(value: OffsetDateTime): String = value.format(FORMATTER)

    @FromJson
    fun fromJson(value: String): OffsetDateTime = OffsetDateTime.parse(value, FORMATTER)

    private companion object {
        /** Lenient on input (accepts a `Z` offset and any fraction length),
         *  explicit on output. */
        val FORMATTER: DateTimeFormatter = DateTimeFormatter.ISO_OFFSET_DATE_TIME
    }
}
