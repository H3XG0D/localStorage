package com.focusvpn.app.data

import okhttp3.OkHttpClient
import okhttp3.Protocol
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * Access JWTs die after 15 minutes. The client must rotate the refresh token
 * once, including when two calls see 401 together — a second refresh of the
 * same token revokes the whole family.
 */
class AccessSessionTest {
    @Test
    fun expiredAccessRefreshesOnceThenRetries() {
        val refreshHits = AtomicInteger()
        val gets = mutableListOf<String>()
        FakeCp { method, path, bearer ->
            when {
                method == "GET" && path == "/v1/servers" && bearer == "old-access" ->
                    reply(401, expiredBody)
                method == "POST" && path == "/v1/auth/refresh" && bearer == "old-refresh" -> {
                    refreshHits.incrementAndGet()
                    reply(200, newTokens)
                }
                method == "GET" && path == "/v1/servers" && bearer == "new-access" -> {
                    synchronized(gets) { gets.add(bearer) }
                    reply(200, """{"endpoints":[]}""")
                }
                else -> reply(401, invalidBody)
            }
        }.use { cp ->
            val gate = gate(cp, expiresAt = null)
            val servers = gate.call { cp.api.listServers(it.accessToken) }
            assertEquals(0, servers.endpoints.size)
            assertEquals(1, refreshHits.get())
            assertEquals(listOf("new-access"), gets)
            assertEquals("new-access", gate.current().accessToken)
            assertEquals("new-refresh", gate.current().refreshToken)
            assertTrue(gate.current().accessExpiresAtMs!! > System.currentTimeMillis())
        }
    }

    @Test
    fun parallel401sRefreshOnce() {
        val refreshHits = AtomicInteger()
        val oldGets = AtomicInteger()
        val arrived = AtomicInteger()
        val both = CountDownLatch(1)
        FakeCp { method, path, bearer ->
            when {
                method == "GET" && path == "/v1/servers" && bearer == "old-access" -> {
                    oldGets.incrementAndGet()
                    if (arrived.incrementAndGet() == 2) both.countDown() else both.await(3, TimeUnit.SECONDS)
                    reply(401, expiredBody)
                }
                method == "POST" && path == "/v1/auth/refresh" && bearer == "old-refresh" -> {
                    refreshHits.incrementAndGet()
                    reply(200, newTokens)
                }
                method == "GET" && path == "/v1/servers" && bearer == "new-access" ->
                    reply(200, """{"endpoints":[]}""")
                else -> reply(401, invalidBody)
            }
        }.use { cp ->
            val gate = gate(cp, expiresAt = null)
            val pool = Executors.newFixedThreadPool(2)
            val errors = java.util.concurrent.ConcurrentLinkedQueue<Throwable>()
            val start = CountDownLatch(1)
            repeat(2) {
                pool.submit {
                    start.await()
                    try {
                        gate.call { cp.api.listServers(it.accessToken) }
                    } catch (t: Throwable) {
                        errors.add(t)
                    }
                }
            }
            start.countDown()
            pool.shutdown()
            assertTrue(pool.awaitTermination(5, TimeUnit.SECONDS))
            assertEquals(emptyList<Throwable>(), errors.toList())
            assertEquals(2, oldGets.get())
            assertEquals(1, refreshHits.get())
            assertEquals("new-refresh", gate.current().refreshToken)
        }
    }

    @Test
    fun deadRefreshDoesNotRetry() {
        val refreshHits = AtomicInteger()
        val gets = AtomicInteger()
        FakeCp { method, path, bearer ->
            when {
                method == "GET" && path == "/v1/servers" -> {
                    gets.incrementAndGet()
                    reply(401, expiredBody)
                }
                method == "POST" && path == "/v1/auth/refresh" && bearer == "old-refresh" -> {
                    refreshHits.incrementAndGet()
                    reply(401, invalidBody)
                }
                else -> reply(500, """{"error":{"code":"internal","message":"no"}}""")
            }
        }.use { cp ->
            val gate = gate(cp, expiresAt = null)
            val error = runCatching { gate.call { cp.api.listServers(it.accessToken) } }.exceptionOrNull()
            assertTrue(error is SessionRevokedException)
            assertEquals(1, gets.get())
            assertEquals(1, refreshHits.get())
            assertEquals("old-refresh", gate.current().refreshToken)
        }
    }

    @Test
    fun refreshesBeforeTheCallWhenAccessIsInsideTheLeadWindow() {
        val bearers = mutableListOf<String>()
        val refreshHits = AtomicInteger()
        FakeCp { method, path, bearer ->
            when {
                method == "POST" && path == "/v1/auth/refresh" -> {
                    refreshHits.incrementAndGet()
                    reply(200, newTokens)
                }
                method == "GET" && path == "/v1/servers" -> {
                    synchronized(bearers) { bearers.add(bearer) }
                    reply(200, """{"endpoints":[]}""")
                }
                else -> reply(401, invalidBody)
            }
        }.use { cp ->
            val gate = gate(cp, expiresAt = System.currentTimeMillis() + 30_000)
            gate.call { cp.api.listServers(it.accessToken) }
            assertEquals(1, refreshHits.get())
            assertEquals(listOf("new-access"), bearers)
        }
    }

    private fun gate(cp: FakeCp, expiresAt: Long?) = AccessSession(
        initial = Session(
            apiBase = cp.base,
            email = "a@b.c",
            accessToken = "old-access",
            refreshToken = "old-refresh",
            accessExpiresAtMs = expiresAt,
        ),
        refresh = { cp.api.refresh(it) },
    )

    private class FakeCp(
        private val handle: (method: String, path: String, bearer: String) -> Reply,
    ) : AutoCloseable {
        private val server = ServerSocket(0)
        val base = "http://127.0.0.1:${server.localPort}"
        val api = ControlPlaneClient(
            base,
            OkHttpClient.Builder()
                .protocols(listOf(Protocol.HTTP_1_1))
                .connectTimeout(2, TimeUnit.SECONDS)
                .readTimeout(4, TimeUnit.SECONDS)
                .retryOnConnectionFailure(false)
                .build(),
        )
        private val accept = Thread {
            while (!server.isClosed) {
                try {
                    val sock = server.accept()
                    Thread {
                        try {
                            serve(sock)
                        } catch (_: IOException) {
                            sock.close()
                        }
                    }.apply { isDaemon = true }.start()
                } catch (_: IOException) {
                    break
                }
            }
        }.apply { isDaemon = true; start() }

        private fun serve(sock: Socket) {
            sock.soTimeout = 4_000
            val (method, path, bearer) = readRequest(sock)
            val reply = handle(method, path, bearer)
            val bytes = reply.body.toByteArray(Charsets.UTF_8)
            val status = if (reply.code == 200) "OK" else "Error"
            val head = "HTTP/1.1 ${reply.code} $status\r\n" +
                "Content-Type: application/json\r\n" +
                "Content-Length: ${bytes.size}\r\n" +
                "Connection: close\r\n\r\n"
            val out = sock.getOutputStream()
            out.write(head.toByteArray(Charsets.US_ASCII))
            out.write(bytes)
            out.flush()
            sock.close()
        }

        override fun close() {
            server.close()
            accept.join(1_000)
        }
    }

    private data class Reply(val code: Int, val body: String)

    companion object {
        private val expiredBody =
            """{"error":{"code":"expired_token","message":"access token expired"}}"""
        private val invalidBody =
            """{"error":{"code":"invalid_token","message":"invalid token"}}"""
        private val newTokens =
            """{"access_token":"new-access","refresh_token":"new-refresh","expires_in":900}"""

        private fun reply(code: Int, body: String) = Reply(code, body)

        private fun readRequest(sock: Socket): Triple<String, String, String> {
            val input = sock.getInputStream()
            val header = StringBuilder()
            val buf = ByteArray(2048)
            while (!header.contains("\r\n\r\n")) {
                val n = input.read(buf)
                if (n < 0) break
                header.append(String(buf, 0, n, Charsets.ISO_8859_1))
            }
            val raw = header.toString()
            val splitAt = raw.indexOf("\r\n\r\n")
            val head = if (splitAt >= 0) raw.substring(0, splitAt) else raw
            val lines = head.split("\r\n")
            val parts = lines.firstOrNull().orEmpty().split(" ")
            val bearer = lines.firstOrNull { it.startsWith("Authorization:", ignoreCase = true) }
                ?.substringAfter(":")
                ?.trim()
                ?.removePrefix("Bearer ")
                .orEmpty()
            val path = parts.getOrElse(1) { "" }
            val query = path.indexOf('?')
            return Triple(parts.getOrElse(0) { "" }, if (query >= 0) path.substring(0, query) else path, bearer)
        }
    }
}
