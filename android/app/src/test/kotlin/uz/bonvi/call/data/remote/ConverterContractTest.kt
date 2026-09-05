package uz.bonvi.call.data.remote

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import org.junit.Test
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import uz.bonvi.call.data.remote.api.AppUpdateApi
import uz.bonvi.call.data.remote.api.DeviceAudioApi
import uz.bonvi.call.data.remote.api.DeviceAuthApi
import uz.bonvi.call.data.remote.api.DeviceCallsApi
import uz.bonvi.call.data.remote.api.DeviceEnrolmentApi

/**
 * Every API method can actually build its converter.
 *
 * This exists because of a failure on the first handset the app ever ran on.
 * `DeviceRedeemOut` carries `java.util.UUID` ids, Moshi refuses platform
 * classes without an explicit adapter, and the converter therefore threw the
 * moment Retrofit tried to build it — **before a single byte left the phone**.
 * The repository caught it with the same broad `catch` that handles a genuine
 * network failure and told the user "no internet", on a phone with working
 * mobile data, against a server its own browser reached in the same second.
 *
 * Nothing in the existing suite could see it: the DTO tests construct objects
 * directly, and `retrofit.create()` builds converters **lazily**, per method,
 * on first call. `validateEagerly(true)` is what turns that into something a
 * test can assert — it builds every converter for every method up front, which
 * is precisely the work that was failing in production and passing in CI.
 *
 * So this is not a test about UUIDs. It is the test that asks whether the
 * serialisation layer can do its job at all, for every method, and it must be
 * extended whenever an API interface is added.
 */
class ConverterContractTest {

    private fun retrofit(): Retrofit = Retrofit.Builder()
        .baseUrl("https://example.invalid/api/device/v1/")
        // The same Moshi the app builds. If NetworkModule gains an adapter and
        // this does not, the test stops being about the real client — so any
        // change there belongs here in the same commit.
        .addConverterFactory(
            MoshiConverterFactory.create(
                Moshi.Builder()
                    .add(OffsetDateTimeAdapter())
                    .add(UuidAdapter)
                    .add(LocalDateAdapter)
                    .add(KotlinJsonAdapterFactory())
                    .build(),
            ),
        )
        // The whole point: build every converter now rather than on first call.
        .validateEagerly(true)
        .build()

    @Test
    fun `every device api builds its converters`() {
        val retrofit = retrofit()
        // A throw here fails the test with the same IllegalArgumentException a
        // handset would have reported as "check your connection".
        retrofit.create(DeviceEnrolmentApi::class.java)
        retrofit.create(DeviceAuthApi::class.java)
        retrofit.create(DeviceCallsApi::class.java)
        retrofit.create(DeviceAudioApi::class.java)
        retrofit.create(AppUpdateApi::class.java)
    }

    @Test
    fun `uuid survives a round trip as the string the server sends`() {
        val moshi = Moshi.Builder().add(UuidAdapter).build()
        val adapter = moshi.adapter(java.util.UUID::class.java)
        val id = java.util.UUID.fromString("af5885ae-43e2-43d9-9983-9d79f9f09704")

        // Quoted JSON string, not an object: the server sends a plain string
        // and anything else would parse on neither side.
        assert(adapter.toJson(id) == "\"af5885ae-43e2-43d9-9983-9d79f9f09704\"")
        assert(adapter.fromJson("\"af5885ae-43e2-43d9-9983-9d79f9f09704\"") == id)
    }
}
