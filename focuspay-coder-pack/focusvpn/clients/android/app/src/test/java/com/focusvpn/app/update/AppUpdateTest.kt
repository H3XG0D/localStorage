package com.focusvpn.app.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AppUpdateTest {
    @Test
    fun newerCodeIsAnOffer() {
        assertTrue(isNewerVersion(3, 2))
        val offer = offerFromManifest(
            """{"versionCode":4,"versionName":"0.1.3","url":"https://focuspay.org/vpn.apk"}""",
            3,
        )
        assertEquals(4, offer?.versionCode)
        assertEquals("0.1.3", offer?.versionName)
    }

    @Test
    fun sameOrOlderOrBrokenIsQuiet() {
        assertNull(offerFromManifest("""{"versionCode":3,"versionName":"0.1.2","url":"https://focuspay.org/vpn.apk"}""", 3))
        assertNull(offerFromManifest("""{"versionCode":2,"versionName":"0.1.1","url":"https://focuspay.org/vpn.apk"}""", 3))
        assertNull(offerFromManifest("""{"versionCode":9,"versionName":"x","url":""}""", 3))
        assertNull(offerFromManifest("not-json", 3))
    }
}
