package uz.bonvi.call.data.remote.api

import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.GET
import retrofit2.http.Path
import retrofit2.http.Streaming

/**
 * The APK download (T82, N33).
 *
 * `GET /api/v1/app/download/{version_code}` is **public and unauthenticated**:
 * it is the same URL the install landing page hands an agent who has no
 * credential yet, and an updater that needed a token could not fix a phone
 * whose token is the thing that is broken.
 *
 * Play is not an option (N33), so this path IS how a fix reaches the fleet.
 * That makes it worth two extra checks in `ApkInstaller` — the signature, and
 * the timing — rather than a straight download-and-open.
 *
 * `@Streaming` because the APK is ~12 MB: buffering it into memory on a phone
 * that is already low on storage is how the update fails on the handsets that
 * most need it.
 */
interface AppUpdateApi {

    @Streaming
    @GET("/api/v1/app/download/{version_code}")
    suspend fun download(@Path("version_code") versionCode: Int): Response<ResponseBody>
}
