package com.focusvpn.app.notify

import com.focusvpn.app.data.EndpointDTO
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class NoticesTest {
    private val today = LocalDate.of(2026, 10, 8)

    @Test
    fun asksOnlyOnceOnAndroid13WhenMissing() {
        assertTrue(shouldAskNotificationAccess(33, granted = false, alreadyAsked = false))
        assertFalse(shouldAskNotificationAccess(33, granted = true, alreadyAsked = false))
        assertFalse(shouldAskNotificationAccess(33, granted = false, alreadyAsked = true))
        assertFalse(shouldAskNotificationAccess(32, granted = false, alreadyAsked = false))
    }

    @Test
    fun updateNoticeIsKeyedByVersionCode() {
        val notice = updateNotice(6, "0.1.5")
        assertEquals("update:6", notice.key)
        assertEquals("Доступно обновление", notice.title)
        assertEquals("0.1.5", notice.text)
        assertEquals("6", updateNotice(6, "  ").text)
    }

    @Test
    fun subscriptionWindowIsOneDayAheadOrAlreadyOver() {
        val ending = subscriptionNotice("2026-10-09", today)
        assertEquals("sub:2026-10-09:ending", ending?.key)
        assertEquals("Подписка заканчивается", ending?.title)
        assertEquals("9 октября 2026", ending?.text)

        assertEquals("sub:2026-10-08:ending", subscriptionNotice("2026-10-08", today)?.key)
        assertEquals("sub:2026-10-07:ended", subscriptionNotice("2026-10-07", today)?.key)
        assertEquals("Подписка закончилась", subscriptionNotice("2026-10-07", today)?.title)
        assertNull(subscriptionNotice("2026-10-10", today))
        assertNull(subscriptionNotice(null, today))
        assertNull(subscriptionNotice("  ", today))
    }

    @Test
    fun seenKeyIsNotPostedAgain() {
        val notice = subscriptionNotice("2026-10-09", today)
        assertEquals(notice, pendingNotice(notice, emptySet()))
        assertNull(pendingNotice(notice, setOf("sub:2026-10-09:ending")))
        assertNull(pendingNotice(null, emptySet()))
    }

    @Test
    fun connectedLineUsesCountryOrAuto() {
        val labels = placeLabels(listOf(EndpointDTO(id = "1", node = "DE1", country = "DE")))
        assertEquals("Германия · DE1", labels["DE1"])
        assertEquals("Подключено · Германия · DE1", connectedStatusText("DE1", labels, auto = true))
        assertEquals(
            "Подключено · Авто — самый быстрый",
            connectedStatusText("DE1", emptyMap(), auto = true),
        )
        assertEquals("Подключено · DE1", connectedStatusText("DE1", emptyMap(), auto = false))
        assertEquals("DE1", nodePlaceLabel("DE1", ""))
    }
}
