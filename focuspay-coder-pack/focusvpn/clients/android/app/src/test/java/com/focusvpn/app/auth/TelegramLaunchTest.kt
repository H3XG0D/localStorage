package com.focusvpn.app.auth

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TelegramLaunchTest {
    private val link = "https://t.me/focusvpn1_bot?start=vpnauth_abc"

    @Test
    fun installedTelegramOpensThatAppWithTheSameLink() {
        val target = telegramTarget(link, setOf("org.telegram.messenger", "org.thunderdog.challegram"))
        assertEquals(link, target.uri)
        assertEquals("org.telegram.messenger", target.packageName)
    }

    @Test
    fun telegramXIsUsedWhenTheOfficialClientIsMissing() {
        val target = telegramTarget(link, setOf("org.thunderdog.challegram"))
        assertEquals("org.thunderdog.challegram", target.packageName)
    }

    @Test
    fun sideBySidePackageBeatsTelegramX() {
        val target = telegramTarget(
            link,
            setOf("org.telegram.messenger.web", "org.thunderdog.challegram"),
        )
        assertEquals("org.telegram.messenger.web", target.packageName)
    }

    @Test
    fun withoutTelegramTheLinkStaysImplicit() {
        val target = telegramTarget(link, emptySet())
        assertEquals(link, target.uri)
        assertNull(target.packageName)
    }

    @Test
    fun unrelatedUrlIsNotPinnedToTelegram() {
        val target = telegramTarget("https://focuspay.org/vpn.apk", setOf("org.telegram.messenger"))
        assertNull(target.packageName)
    }
}
