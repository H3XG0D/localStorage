package com.focusvpn.app.ui.design

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.hypot

class MeshMotionTest {
    @Test
    fun alphaReachesFullBeforeTheEnd() {
        assertEquals(0f, meshAlpha(0f), 0.001f)
        assertEquals(0.328f, meshAlpha(0.1f), 0.001f)
        assertEquals(0.82f, meshAlpha(0.25f), 0.001f)
        assertEquals(0.82f, meshAlpha(1f), 0.001f)
    }

    @Test
    fun coverRadiusReachesTheFarCorner() {
        val radius = meshCoverRadius(100f, 200f, 400f, 800f)
        val far = hypot(400f - 100f, 800f - 200f) + 24f
        assertEquals(far, radius, 0.01f)
        assertTrue(radius * 1f >= hypot(300f, 600f))
    }
}
