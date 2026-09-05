package uz.bonvi.call.data.remote.api

import okhttp3.RequestBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query
import uz.bonvi.call.data.remote.dto.ChunkAcceptedOut
import uz.bonvi.call.data.remote.dto.CommitOut
import uz.bonvi.call.data.remote.dto.OpenUploadIn
import uz.bonvi.call.data.remote.dto.OpenUploadOut
import uz.bonvi.call.data.remote.dto.UploadStatusOut

/**
 * The resumable audio upload (SPEC §4.5, T74).
 *
 * Three steps, and the shape exists because the network this runs on drops:
 *
 * 1. `POST /calls/{client_call_id}/audio/session` — declare size, SHA-256,
 *    codec, container and capture route; get an `upload_id` and a `chunk_size`.
 * 2. `PUT /audio/{upload_id}/chunk?offset=…` — one chunk, with its own
 *    checksum. The server checks the offset, so a resume cannot silently
 *    interleave.
 * 3. `POST /audio/{upload_id}/commit` — the server verifies the whole-file
 *    SHA-256 and only then is the recording stored.
 *
 * `GET /audio/{upload_id}` is the resume point: it says how many bytes the
 * server already has, so a phone that died mid-upload continues rather than
 * restarting. On a 20-minute recording over a weak cell connection, restarting
 * is the difference between arriving and not.
 */
interface DeviceAudioApi {

    @POST("calls/{client_call_id}/audio/session")
    suspend fun openSession(
        @Path("client_call_id") clientCallId: String,
        @Body body: OpenUploadIn,
    ): Response<OpenUploadOut>

    /** How much the server already holds. The first call after a restart. */
    @GET("audio/{upload_id}")
    suspend fun status(@Path("upload_id") uploadId: String): Response<UploadStatusOut>

    /**
     * One chunk at [offset].
     *
     * `Content-Type` is `application/octet-stream` and is set by the
     * `RequestBody`, not by hand. The per-chunk checksum lets the server reject
     * a corrupted chunk without waiting for the whole-file commit to fail.
     */
    @PUT("audio/{upload_id}/chunk")
    suspend fun putChunk(
        @Path("upload_id") uploadId: String,
        @Query("offset") offset: Long,
        @Header("x-chunk-sha256") chunkSha256: String,
        @Body body: RequestBody,
    ): Response<ChunkAcceptedOut>

    /** Verifies the whole-file SHA-256 server-side. Local audio is deleted
     *  only after this succeeds (N11). */
    @POST("audio/{upload_id}/commit")
    suspend fun commit(@Path("upload_id") uploadId: String): Response<CommitOut>
}
