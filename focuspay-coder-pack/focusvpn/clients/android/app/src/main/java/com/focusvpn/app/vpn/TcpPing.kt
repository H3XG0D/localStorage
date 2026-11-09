package com.focusvpn.app.vpn

import java.net.InetSocketAddress
import java.net.Socket

/** Milliseconds for a TCP handshake, or null when the server does not answer. */
object TcpPing {
    fun millis(host: String, port: Int, timeoutMs: Int): Int? {
        if (host.isBlank() || port !in 1..65535 || timeoutMs <= 0) return null
        val started = System.nanoTime()
        return try {
            Socket().use { socket ->
                socket.connect(InetSocketAddress(host, port), timeoutMs)
            }
            ((System.nanoTime() - started) / 1_000_000L).toInt().coerceIn(1, 60_000)
        } catch (_: Exception) {
            null
        }
    }
}
