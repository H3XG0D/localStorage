package com.focusvpn.app.vpn

import android.net.TrafficStats
import java.io.File

private val tunNames = listOf("tun0", "tun1", "xray0")

/** Reads the VPN interface counters. Missing files mean the tunnel is down. */
fun readTunCounters(): IfaceCounters? {
    hiddenIfaceCounters()?.let { return it }
    val sys = LinkedHashMap<String, IfaceCounters>()
    val dir = File("/sys/class/net")
    dir.list()?.forEach { name ->
        val rx = File(dir, "$name/statistics/rx_bytes").readLongOrNull() ?: return@forEach
        val tx = File(dir, "$name/statistics/tx_bytes").readLongOrNull() ?: return@forEach
        sys[name] = IfaceCounters(rx, tx)
    }
    val proc = File("/proc/net/dev").readTextOrNull()
    return resolveTunCounters(sys, proc)
}

/**
 * Framework method is hidden from the SDK, but the VPN app can still ask for
 * its own tun counters when /sys and /proc/net are blocked.
 */
private fun hiddenIfaceCounters(): IfaceCounters? {
    val rxMethod = runCatching {
        TrafficStats::class.java.getMethod("getRxBytes", String::class.java)
    }.getOrNull() ?: return null
    val txMethod = runCatching {
        TrafficStats::class.java.getMethod("getTxBytes", String::class.java)
    }.getOrNull() ?: return null
    var rx = 0L
    var tx = 0L
    var found = false
    for (name in tunNames) {
        val down = runCatching { rxMethod.invoke(null, name) as Long }.getOrNull() ?: continue
        val up = runCatching { txMethod.invoke(null, name) as Long }.getOrNull() ?: continue
        if (down < 0 || up < 0) continue
        val present = down > 0 || up > 0 || File("/sys/class/net/$name").isDirectory
        if (!present) continue
        rx += down
        tx += up
        found = true
    }
    return if (found) IfaceCounters(rx, tx) else null
}

private fun File.readTextOrNull(): String? = try {
    if (isFile && canRead()) readText() else null
} catch (_: Exception) {
    null
}

private fun File.readLongOrNull(): Long? = readTextOrNull()?.trim()?.toLongOrNull()
