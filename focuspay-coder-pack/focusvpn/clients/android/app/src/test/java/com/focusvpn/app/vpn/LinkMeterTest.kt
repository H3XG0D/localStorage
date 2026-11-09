package com.focusvpn.app.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LinkMeterTest {
    @Test
    fun listedHostsWinOverTheTunnelProfile() {
        val listed = listOf(Probe("DE1", "de.example", 443))
        val fallback = listOf(Probe("NL1", "nl.example", 443))
        assertEquals(listed, probes(listed, fallback))
        assertEquals(fallback, probes(listOf(Probe("DE1", "", 443)), fallback))
        assertEquals(listOf(Probe("DE1", "de.example", 443)), probes(listOf(Probe("DE1", "de.example", 0)), emptyList()))
    }

    @Test
    fun autoPlaceShowsTheFastestPing() {
        val pings = mapOf("DE1" to 90, "NL1" to 40)
        assertEquals(40, shownPing(pings, null))
        assertEquals(90, shownPing(pings, "DE1"))
        assertNull(shownPing(pings, "RO1"))
    }

    @Test
    fun barsAndLabelsStayEmptyUntilMeasured() {
        assertEquals(0, signalBars(null))
        assertEquals(3, signalBars(80))
        assertEquals(2, signalBars(81))
        assertEquals(1, signalBars(400))
        assertEquals("—", formatPing(null))
        assertEquals("80 мс", formatPing(80))
        assertEquals("—", formatMbps(null))
        assertEquals("0.0", formatMbps(0.0))
        assertEquals("12.4", formatMbps(12.44))
        assertEquals("100", formatMbps(100.2))
    }

    @Test
    fun throughputUsesTheByteDelta() {
        val before = IfaceCounters(rxBytes = 1_000_000, txBytes = 500_000)
        val after = IfaceCounters(rxBytes = 2_000_000, txBytes = 500_000)
        val speed = throughputMbps(before, after, 1_000)
        assertEquals(8.0, speed!!.down, 0.001)
        assertEquals(0.0, speed.up, 0.001)
        assertNull(throughputMbps(after, before, 1_000))
        assertNull(throughputMbps(before, after, 50))
    }

    @Test
    fun tunCountersIgnoreWifiAndPreferSysfs() {
        val proc = """
            Inter-|   Receive                                                |  Transmit
             face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
            wlan0: 9000 0 0 0 0 0 0 0 8000 0 0 0 0 0 0 0
             tun0: 1000 0 0 0 0 0 0 0 250 0 0 0 0 0 0 0
             tun1: 5 0 0 0 0 0 0 0 7 0 0 0 0 0 0 0
        """.trimIndent()
        assertEquals(IfaceCounters(1005, 257), resolveTunCounters(emptyMap(), proc))
        assertEquals(
            IfaceCounters(50, 60),
            resolveTunCounters(mapOf("tun0" to IfaceCounters(50, 60), "wlan0" to IfaceCounters(9, 9)), proc),
        )
        assertNull(resolveTunCounters(emptyMap(), "wlan0: 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0"))
    }
}
