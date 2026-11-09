package com.focusvpn.app.vpn

import java.util.Locale

/** Bytes seen on a network interface. rx is download into the phone, tx is upload. */
data class IfaceCounters(val rxBytes: Long, val txBytes: Long)

data class Mbps(val down: Double, val up: Double)

/** A server the home screen can time with a TCP handshake. */
data class Probe(val node: String, val host: String, val port: Int)

/**
 * Prefer addresses from the server list. Fall back to the live tunnel profile
 * when the list has no host yet.
 */
fun probes(listed: List<Probe>, fallback: List<Probe>): List<Probe> {
    val ready = listed.mapNotNull { it.usable() }
    if (ready.isNotEmpty()) return ready
    return fallback.mapNotNull { it.usable() }
}

private fun Probe.usable(): Probe? {
    val host = host.trim()
    val node = node.trim()
    if (host.isEmpty() || node.isEmpty()) return null
    val port = if (port in 1..65535) port else 443
    return Probe(node, host, port)
}

/** Ping shown next to a location. Blank node means automatic: the fastest measured server. */
fun shownPing(byNode: Map<String, Int>, node: String?): Int? =
    if (node.isNullOrBlank()) byNode.values.minOrNull() else byNode[node]

/** 0 when unknown, otherwise 1..3 bars. A measured server always lights at least one. */
fun signalBars(ms: Int?): Int = when {
    ms == null || ms < 0 -> 0
    ms <= 80 -> 3
    ms <= 160 -> 2
    else -> 1
}

fun formatPing(ms: Int?): String =
    if (ms == null || ms < 0) "—" else "${ms.coerceAtMost(9999)} мс"

fun formatMbps(mbps: Double?): String {
    if (mbps == null || mbps.isNaN() || mbps < 0.0) return "—"
    val v = mbps.coerceAtMost(9999.0)
    return if (v >= 100.0) v.toInt().toString() else String.format(Locale.US, "%.1f", v)
}

/**
 * Megabits per second between two counter reads.
 * A backwards counter (tunnel recreated) yields null so the UI does not flash a spike.
 */
fun throughputMbps(before: IfaceCounters, after: IfaceCounters, elapsedMs: Long): Mbps? {
    if (elapsedMs < 200) return null
    if (after.rxBytes < before.rxBytes || after.txBytes < before.txBytes) return null
    val seconds = elapsedMs / 1000.0
    return Mbps(
        down = (after.rxBytes - before.rxBytes) * 8.0 / seconds / 1_000_000.0,
        up = (after.txBytes - before.txBytes) * 8.0 / seconds / 1_000_000.0,
    )
}

fun parseProcNetDev(text: String): Map<String, IfaceCounters> {
    val out = LinkedHashMap<String, IfaceCounters>()
    for (line in text.lineSequence()) {
        val colon = line.indexOf(':')
        if (colon <= 0) continue
        val name = line.substring(0, colon).trim()
        if (name.isEmpty()) continue
        val parts = line.substring(colon + 1).trim().split(Regex("\\s+"))
        if (parts.size < 9) continue
        val rx = parts[0].toLongOrNull() ?: continue
        val tx = parts[8].toLongOrNull() ?: continue
        out[name] = IfaceCounters(rx, tx)
    }
    return out
}

/** Sum tun/xray interfaces. Sysfs wins when it has any; otherwise /proc/net/dev. */
fun resolveTunCounters(sysfs: Map<String, IfaceCounters>, procText: String?): IfaceCounters? {
    val fromSys = sysfs.filterKeys { isTun(it) }
    if (fromSys.isNotEmpty()) {
        return IfaceCounters(
            fromSys.values.sumOf { it.rxBytes },
            fromSys.values.sumOf { it.txBytes },
        )
    }
    if (procText.isNullOrBlank()) return null
    val fromProc = parseProcNetDev(procText).filterKeys { isTun(it) }
    if (fromProc.isEmpty()) return null
    return IfaceCounters(
        fromProc.values.sumOf { it.rxBytes },
        fromProc.values.sumOf { it.txBytes },
    )
}

private fun isTun(name: String): Boolean = name.startsWith("tun") || name.startsWith("xray")
