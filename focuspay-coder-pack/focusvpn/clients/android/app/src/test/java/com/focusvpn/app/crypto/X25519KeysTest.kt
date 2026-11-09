package com.focusvpn.app.crypto

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class X25519KeysTest {
    @Test
    fun publicIsDerivedFromPrivate() {
        val (priv, pub) = X25519Keys.generate()
        assertEquals(pub, X25519Keys.publicFromPrivate(priv))
        assertNotEquals(priv, pub)
    }

    @Test
    fun generateProducesDistinctPairs() {
        val a = X25519Keys.generate()
        val b = X25519Keys.generate()
        assertNotEquals(a.first, b.first)
    }
}
