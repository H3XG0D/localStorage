package com.focusvpn.app.data

import okhttp3.OkHttpClient
import okhttp3.Protocol
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ServerSocket
import java.net.SocketTimeoutException
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * A mobile NAT can drop an idle HTTP connection without telling the phone.
 * The next call then sits on that socket until the platform says "Read timed out",
 * and the control plane never sees the request. A fresh connection must be tried.
 */
class ControlPlaneClientTimeoutTest {
    @Test
    fun retriesWhenTheFirstSocketAcceptsAndNeverAnswers() {
        val hits = AtomicInteger(0)
        ServerSocket(0).use { server ->
            val worker = Thread {
                repeat(2) { turn ->
                    val sock = server.accept()
                    Thread {
                        hits.incrementAndGet()
                        sock.soTimeout = 2_000
                        readHeaders(sock)
                        if (turn == 0) {
                            Thread.sleep(3_000)
                            sock.close()
                        } else {
                            writeJson(sock, """{"endpoints":[]}""")
                        }
                    }.apply { isDaemon = true }.start()
                }
            }
            worker.isDaemon = true
            worker.start()

            val http = OkHttpClient.Builder()
                .protocols(listOf(Protocol.HTTP_1_1))
                .connectTimeout(2, TimeUnit.SECONDS)
                .readTimeout(400, TimeUnit.MILLISECONDS)
                .retryOnConnectionFailure(false)
                .build()
            val api = ControlPlaneClient("http://127.0.0.1:${server.localPort}", http)

            val servers = api.listServers("token")

            assertEquals(0, servers.endpoints.size)
            assertEquals(2, hits.get())
            worker.join(2_000)
        }
    }

    @Test
    fun givesUpInRussianWhenEveryAttemptStaysSilent() {
        ServerSocket(0).use { server ->
            val worker = Thread {
                repeat(2) {
                    val sock = server.accept()
                    Thread {
                        sock.soTimeout = 2_000
                        readHeaders(sock)
                        Thread.sleep(3_000)
                        sock.close()
                    }.apply { isDaemon = true }.start()
                }
            }
            worker.isDaemon = true
            worker.start()

            val http = OkHttpClient.Builder()
                .protocols(listOf(Protocol.HTTP_1_1))
                .connectTimeout(2, TimeUnit.SECONDS)
                .readTimeout(400, TimeUnit.MILLISECONDS)
                .retryOnConnectionFailure(false)
                .build()
            val api = ControlPlaneClient("http://127.0.0.1:${server.localPort}", http)

            val error = runCatching { api.listServers("token") }.exceptionOrNull()
            assertTrue(error is java.io.IOException)
            val message = error?.message.orEmpty()
            assertFalse(message.contains("Read timed out"))
            assertFalse(message.contains("timeout"))
            assertTrue(message.contains("не ответил"))
            worker.join(2_000)
        }
    }

    private fun readHeaders(sock: java.net.Socket) {
        val input = sock.getInputStream()
        val buf = ByteArray(1024)
        val text = StringBuilder()
        try {
            while (!text.contains("\r\n\r\n")) {
                val n = input.read(buf)
                if (n < 0) break
                text.append(String(buf, 0, n, Charsets.ISO_8859_1))
            }
        } catch (_: SocketTimeoutException) {
        }
    }

    private fun writeJson(sock: java.net.Socket, body: String) {
        val bytes = body.toByteArray(Charsets.UTF_8)
        val head = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n"
        val out = sock.getOutputStream()
        out.write(head.toByteArray(Charsets.US_ASCII))
        out.write(bytes)
        out.flush()
        sock.close()
    }
}
