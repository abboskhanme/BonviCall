package uz.bonvi.call.service

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.data.remote.api.DeviceCommandApi
import uz.bonvi.call.data.remote.dto.DeviceAckIn
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.CommandFailure
import uz.bonvi.call.domain.CommandKind
import uz.bonvi.call.domain.CommandOutcome
import uz.bonvi.call.core.Clock
import java.time.OffsetDateTime
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Carries out what the panel asked for, whichever transport brought it
 * (SPEC §4.6, UC-16, T80).
 *
 * ═══ One lifecycle, two transports ═════════════════════════════════════════
 * A command arrives on the socket in about a second, or is collected over REST
 * by a phone that was asleep. Both end here, so the panel cannot tell which one
 * delivered it — which is the point: UC-16's five-second bar is measured from
 * the acknowledgement, and two code paths would mean two different answers to
 * the same question.
 *
 * ═══ Every command is answered ═════════════════════════════════════════════
 * Including the ones this build refuses. A command with no outcome is
 * indistinguishable from one that never arrived, and those are different
 * faults: the first is a phone that will not do it, the second is a channel
 * that did not reach it.
 */
@Singleton
class CommandRunner @Inject constructor(
    private val api: DeviceCommandApi,
    private val dial: DialCommand,
    private val capabilities: CapabilityRefresh,
    private val revocation: Revocation,
    private val session: SessionStore,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    /** One command, in the shape both transports produce. */
    data class Incoming(
        val commandId: UUID,
        val kind: CommandKind?,
        val number: String?,
        val issuedAtEpochMillis: Long,
    )

    /** What to tell the server. `failure == null` means it was carried out. */
    data class Ack(val failure: CommandFailure?) {
        val status: String get() = if (failure == null) ACKNOWLEDGED else FAILED
    }

    /**
     * Do it. Never throws — a command that blows up in here would take the
     * socket's read loop or the heartbeat worker with it.
     */
    @Suppress("TooGenericExceptionCaught")
    suspend fun execute(command: Incoming): Ack = try {
        when (command.kind) {
            CommandKind.DIAL -> executeDial(command)

            // Reaching this line IS the answer. The panel asked whether the
            // phone is there; the acknowledgement says it is.
            CommandKind.PING -> Ack(null)

            CommandKind.RECHECK -> executeRecheck()

            CommandKind.LOGOUT -> {
                // UC-08. The audio goes first and the metadata queue is kept —
                // see Revocation, which is where that asymmetry is argued.
                revocation.revokeLocally()
                Ack(null)
            }

            // Named in the contract, issued by nothing today. Answering
            // `unsupported` tells an admin to stop expecting it; silence would
            // look like a phone that ignores its commands.
            CommandKind.CONFIG -> Ack(CommandFailure.UNSUPPORTED)

            // A kind this build has never heard of. Same reasoning.
            null -> Ack(CommandFailure.UNSUPPORTED)
        }
    } catch (error: Exception) {
        Timber.e(error, "Command %s failed", command.commandId)
        Ack(CommandFailure.OS_REFUSED)
    }

    private fun executeDial(command: Incoming): Ack {
        val number = command.number
            ?: return Ack(CommandFailure.UNSUPPORTED)
        return when (val result = dial.execute(number, command.issuedAtEpochMillis)) {
            is DialCommand.Result.Dialled -> Ack(null)
            is DialCommand.Result.Discarded -> Ack(CommandOutcome.forDialDiscard(result.reason))
        }
    }

    /**
     * Re-run E2's checks and report them.
     *
     * The panel's "recheck" button exists because a capability granted at
     * enrolment can be taken away later — by the owner, by an OEM cleaner, by
     * an OS update — and until this ran, the panel could only ever show what
     * the phone looked like on the day it was installed.
     */
    private suspend fun executeRecheck(): Ack =
        // Every check including the microphone, reported whether or not it
        // changed: an admin pressing this has asked a question and is owed an
        // answer. The unattended pass is `CapabilityRefresh.ifChanged`, which
        // runs on every heartbeat and skips both of those.
        if (capabilities.full().reported) {
            Ack(null)
        } else {
            // The checks ran; the report did not arrive. Saying `device_offline`
            // is the honest version — the next heartbeat carries the state
            // anyway, so nothing is lost.
            Ack(CommandFailure.DEVICE_OFFLINE)
        }

    /**
     * Collect everything waiting over REST, run it, and acknowledge it.
     *
     * The ack returns whatever else is pending, so a phone that just dialled
     * does not need a second round trip — the loop follows that chain rather
     * than polling again, and is bounded so a server that always answers with
     * one more command cannot spin here forever.
     *
     * @return how many commands were carried out or refused.
     */
    @Suppress("TooGenericExceptionCaught")
    suspend fun drain(): Int = withContext(io) {
        if (session.snapshot.installationId == null) return@withContext 0

        var handled = 0
        var pending = try {
            api.pending().body()?.commands.orEmpty()
        } catch (error: Exception) {
            // Offline. The socket or the next heartbeat will come back to it,
            // and a command too old to matter is discarded on arrival anyway.
            Timber.i("Could not collect commands")
            return@withContext 0
        }

        var round = 0
        while (pending.isNotEmpty() && round < MAX_ROUNDS) {
            round++
            var next = emptyList<uz.bonvi.call.data.remote.dto.DeviceCommandOut>()
            for (command in pending) {
                val ack = execute(
                    Incoming(
                        commandId = command.commandId,
                        kind = CommandKind.fromWire(command.kind.value),
                        number = command.number,
                        issuedAtEpochMillis = command.issuedAt.toInstant().toEpochMilli(),
                    ),
                )
                handled++
                next = acknowledge(command.commandId, ack) ?: next
            }
            pending = next
        }
        handled
    }

    /** @return the commands the server sent back with the ack, or null when it
     *  could not be delivered — the command still ran, and the server's
     *  `ack_timeout` sweep is what makes that visible. */
    @Suppress("TooGenericExceptionCaught")
    suspend fun acknowledge(
        commandId: UUID,
        ack: Ack,
    ): List<uz.bonvi.call.data.remote.dto.DeviceCommandOut>? = try {
        val response = api.acknowledge(
            commandId,
            DeviceAckIn(
                status = ack.status,
                at = OffsetDateTime.parse(Clock.toWire(Clock.epochMillis())),
                failureReason = ack.failure?.let(::toDto),
            ),
        )
        response.body()?.commands
    } catch (error: Exception) {
        Timber.w("Could not acknowledge command %s", commandId)
        null
    }

    private fun toDto(failure: CommandFailure) =
        uz.bonvi.call.data.remote.dto.CommandFailureReason.entries
            .first { it.value == failure.wire }

    private companion object {
        const val ACKNOWLEDGED = "acknowledged"
        const val FAILED = "failed"

        /** The ack may carry more work; three rounds is generous for a phone
         *  that has been asleep and still bounded. */
        const val MAX_ROUNDS = 3
    }
}
