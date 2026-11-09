package com.focusvpn.app.ui.design

import kotlin.math.hypot
import kotlin.math.min

/** Opacity of the connection mesh. Full strength is 0.82, reached a quarter of the way in. */
fun meshAlpha(amount: Float): Float = min(amount.coerceAtLeast(0f) * 4f, 1f) * 0.82f

/** Radius that reaches every corner of the screen, plus a small margin. */
fun meshCoverRadius(x: Float, y: Float, width: Float, height: Float): Float =
    maxOf(
        hypot(x, y),
        hypot(width - x, y),
        hypot(x, height - y),
        hypot(width - x, height - y),
    ) + 24f
