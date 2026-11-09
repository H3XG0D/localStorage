package com.focusvpn.app.data

/**
 * The refresh family is dead (reused, expired, or logged out). The caller must
 * drop the local session. Retrying would present the same revoked token again.
 */
class SessionRevokedException(cause: ApiException) : Exception(cause.message, cause)

/**
 * Single-flight access-token refresh.
 *
 * Access JWTs last 15 minutes. Two callers that both see 401 must not both
 * present the old refresh token: the second one is reuse detection and the
 * control plane revokes the whole family.
 *
 * [leadMs] refreshes a token that is about to expire before the request, so a
 * connect does not fail on the clock. Sessions saved before this field existed
 * have a null expiry and refresh only after a 401.
 */
class AccessSession(
    initial: Session,
    private val refresh: (refreshToken: String) -> Tokens,
    private val onSession: (Session) -> Unit = {},
    private val now: () -> Long = { System.currentTimeMillis() },
    private val leadMs: Long = LEAD_MS,
) {
    private val lock = Any()
    private var session: Session = initial
    private var closed = false

    fun current(): Session = synchronized(lock) { session }

    fun close() {
        synchronized(lock) { closed = true }
    }

    /** Replaces non-token fields (selected node, device) without rotating tokens. */
    fun update(transform: (Session) -> Session): Session {
        synchronized(lock) {
            checkOpen()
            val next = transform(session)
            publish(next)
            return next
        }
    }

    fun <T> call(block: (Session) -> T): T {
        val snapshot = ensureFresh()
        return try {
            block(snapshot)
        } catch (e: ApiException) {
            if (!e.isAccessRejected()) throw e
            val fresh = rotateIfStale(snapshot.accessToken)
            block(fresh)
        }
    }

    private fun ensureFresh(): Session {
        synchronized(lock) {
            checkOpen()
            val exp = session.accessExpiresAtMs
            if (exp != null && exp - now() <= leadMs) {
                rotateLocked()
            }
            return session
        }
    }

    /**
     * [usedAccess] is the token the failed call presented. Another thread may
     * already have rotated; presenting that refresh again would revoke the family.
     */
    private fun rotateIfStale(usedAccess: String): Session {
        synchronized(lock) {
            checkOpen()
            if (session.accessToken != usedAccess) return session
            rotateLocked()
            return session
        }
    }

    /** Caller holds [lock]. */
    private fun rotateLocked() {
        checkOpen()
        val tokens = try {
            refresh(session.refreshToken)
        } catch (e: ApiException) {
            if (e.isAccessRejected()) throw SessionRevokedException(e)
            throw e
        }
        checkOpen()
        publish(session.withTokens(tokens, now()))
    }

    /** Caller holds [lock]. */
    private fun publish(next: Session) {
        session = next
        if (!closed) onSession(next)
    }

    private fun checkOpen() {
        if (closed) {
            throw SessionRevokedException(
                ApiException(401, """{"error":{"code":"invalid_token","message":"invalid token"}}"""),
            )
        }
    }

    companion object {
        const val LEAD_MS = 60_000L
    }
}

fun ApiException.isAccessRejected(): Boolean =
    code == 401 && (errorCode == "expired_token" || errorCode == "invalid_token")
