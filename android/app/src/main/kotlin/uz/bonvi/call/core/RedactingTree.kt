package uz.bonvi.call.core

import timber.log.Timber

/**
 * Logging with N26 redaction.
 *
 * A token, a password, an enrolment code or a verification code in a log line
 * is a finding, not a style problem: these phones are the employees' own, log
 * buffers get shared in support chats, and an enrolment code is a credential
 * that binds a handset to a company number. Everything matched is replaced with
 * its last four characters, which is enough to correlate two log lines and not
 * enough to reuse.
 *
 * `RedactingTreeTest` asserts a token does not survive a round trip.
 */
class RedactingTree : Timber.DebugTree() {

    /**
     * ⚠️ A SUBCLASS of `DebugTree`, not a wrapper around one — and the reason
     * is the single most expensive line this project has had.
     *
     * The previous shape was `class RedactingTree(delegate: Timber.Tree)` whose
     * `log` called `delegate.log(priority, tag, redact(message), t)`. That
     * reads as the protected four-argument hook. It is not: Kotlin cannot
     * reach a protected member through a receiver of the base type, so the
     * call bound to the PUBLIC `log(priority, message, vararg args)` overload
     * with `tag` in the message slot — and `tag` is null at that point, so
     * Timber's `prepareLog` swallowed the line as "empty message, no
     * throwable". Every `Timber.i/w/e` on every handset went nowhere. It was
     * read as "MIUI suppresses third-party logs" and a day of field diagnosis
     * ran on `dumpsys` instead. A JVM test that plants a tree and reads back
     * the line (`FileLogTreeTest`) is what caught it, on 2026-09-12.
     *
     * `super.log` is the protected hook on THIS instance, which is exactly the
     * access Kotlin allows.
     */
    override fun log(priority: Int, tag: String?, message: String, t: Throwable?) {
        super.log(priority, tag, redact(message), t)
    }

    companion object {

        /** A pattern plus which capture group holds the secret. */
        private data class Rule(val regex: Regex, val secretGroup: Int)

        /** Keys whose VALUE is a secret, in JSON, a query string or a body. */
        private val SENSITIVE_KEYS = listOf(
            "password",
            "access_token",
            "refresh_token",
            "credential",
            "token_hash",
            "enrolment_code",
            "verification_code",
            "code",
        )

        private val RULES: List<Rule> = buildList {
            // Header form FIRST. `Authorization: Bearer <token>` must be caught
            // as a header, or the generic key rule masks the word "Bearer" and
            // leaves the token in plain sight — which is exactly the bug this
            // ordering exists to prevent, and it is why the test asserts on
            // this shape specifically.
            add(
                Rule(
                    Regex("""(?i)\b(?:authorization|cookie)\s*[:=]\s*"?(?:bearer\s+)?([^"\s,;}]+)"""),
                    secretGroup = 1,
                ),
            )
            // A bare bearer token, arriving without a key name.
            add(Rule(Regex("""(?i)\bbearer\s+([A-Za-z0-9._\-]+)"""), secretGroup = 1))
            // "key": "value" | key=value | key: value — one pass over all three.
            SENSITIVE_KEYS.forEach { key ->
                add(
                    Rule(
                        Regex("""(?i)"?\b${Regex.escape(key)}\b"?\s*[:=]\s*"?([^"\s,;}&]+)"""),
                        secretGroup = 1,
                    ),
                )
            }
        }

        fun redact(message: String): String =
            RULES.fold(message) { text, rule ->
                rule.regex.replace(text) { match ->
                    val group = match.groups[rule.secretGroup] ?: return@replace match.value
                    val prefixLength = group.range.first - match.range.first
                    match.value.substring(0, prefixLength) + mask(group.value)
                }
            }

        /** Four characters or fewer would be the whole secret, so nothing is
         *  shown. Above that, the last four are enough to correlate two log
         *  lines and not enough to reuse. */
        private fun mask(secret: String): String =
            if (secret.length <= 4) "\u2026" else "\u2026" + secret.takeLast(4)
    }
}
