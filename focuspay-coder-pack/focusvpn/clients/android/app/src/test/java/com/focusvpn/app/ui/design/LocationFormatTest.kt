package com.focusvpn.app.ui.design

import com.focusvpn.app.data.EndpointDTO
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class LocationFormatTest {
    @Test
    fun regionAliasesMatchMockChips() {
        assertEquals("europe", regionBucket("eu-central", "DE"))
        assertEquals("europe", regionBucket("EU", "DE"))
        assertEquals("america", regionBucket("us-east", "US"))
        assertEquals("asia", regionBucket("ap-southeast", "SG"))
        assertEquals("europe", regionBucket("", "NL"))
        assertEquals("", regionBucket("unknown", "ZZ"))
    }

    @Test
    fun searchUsesCountryNameAndNode() {
        val de = EndpointDTO(id = "1", node = "DE-01", country = "DE", region = "eu-central", protocol = "vless")
        val us = EndpointDTO(id = "2", node = "US-01", country = "US", region = "us-east", protocol = "vless")
        assertTrue(endpointMatches(de, "германия", "all"))
        assertTrue(endpointMatches(de, "de-01", "europe"))
        assertFalse(endpointMatches(de, "германия", "america"))
        assertFalse(endpointMatches(us, "германия", "all"))
        assertTrue(endpointMatches(us, "", "america"))
    }

    @Test
    fun subscriptionDateAndDays() {
        val today = LocalDate.of(2026, 10, 7)
        assertEquals("7 ноября 2026", formatSubscriptionDate("2026-11-07"))
        assertEquals(31L, daysUntil("2026-11-07", today))
        assertTrue(subscriptionActive("2026-11-07", today))
        assertFalse(subscriptionActive("2026-10-06", today))
        assertFalse(subscriptionActive(null, today))
        assertEquals("день", ruDays(31))
        assertEquals("дня", ruDays(2))
        assertEquals("дней", ruDays(11))
    }

    @Test
    fun subscriptionBarUsesKnownPlanLength() {
        val today = LocalDate.of(2026, 10, 7)
        assertEquals(7, planPeriodDays("week"))
        assertEquals(30, planPeriodDays("month"))
        assertEquals(90, planPeriodDays("quarter"))
        assertEquals(90, planPeriodDays("q3"))
        assertEquals(null, planPeriodDays("trial"))
        assertEquals(1f, subscriptionProgress("2026-11-07", "month", today))
        assertEquals(3f / 7f, subscriptionProgress("2026-10-10", "week", today))
        assertEquals(1f, subscriptionProgress("2026-10-10", "trial", today))
        assertEquals(0f, subscriptionProgress("2026-10-06", "week", today))
        assertEquals(0f, subscriptionProgress(null, "month", today))
    }

    @Test
    fun durationPadsHours() {
        assertEquals("00:01:05", formatDuration(65))
        assertEquals("01:00:00", formatDuration(3600))
    }
}
