package com.focusvpn.app.vpn

import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ServerSocket

class TcpPingTest {
    @Test
    fun handshakeToAnOpenPortReturnsMilliseconds() {
        ServerSocket(0).use { server ->
            Thread { server.accept().close() }.apply { isDaemon = true }.start()
            val ms = TcpPing.millis("127.0.0.1", server.localPort, 1_000)
            assertTrue(ms != null && ms in 1..1_000)
        }
    }

    @Test
    fun closedPortIsUnknown() {
        assertNull(TcpPing.millis("127.0.0.1", 1, 200))
        assertNull(TcpPing.millis("", 443, 200))
    }
}
