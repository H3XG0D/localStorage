package com.focusvpn.app.ui.design

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.RoundRect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

private fun stroke(px: Float) = Stroke(width = px, cap = StrokeCap.Round, join = StrokeJoin.Round)

@Composable
private fun IconBox(modifier: Modifier, draw: androidx.compose.ui.graphics.drawscope.DrawScope.() -> Unit) {
    Canvas(modifier, onDraw = draw)
}

@Composable
fun IconPower(color: Color, modifier: Modifier, strokeWidth: Dp = 1.6.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        val cx = size.width / 2f
        drawLine(color, Offset(cx, size.height * 0.08f), Offset(cx, size.height * 0.48f), sw, StrokeCap.Round)
        drawArc(
            color = color,
            startAngle = 130f,
            sweepAngle = 280f,
            useCenter = false,
            topLeft = Offset(size.width * 0.16f, size.height * 0.22f),
            size = Size(size.width * 0.68f, size.height * 0.68f),
            style = stroke(sw),
        )
    }
}

@Composable
fun IconShield(color: Color, modifier: Modifier, strokeWidth: Dp = 1.7.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        val path = Path().apply {
            moveTo(size.width * 0.5f, size.height * 0.08f)
            lineTo(size.width * 0.86f, size.height * 0.22f)
            lineTo(size.width * 0.86f, size.height * 0.48f)
            quadraticTo(size.width * 0.86f, size.height * 0.78f, size.width * 0.5f, size.height * 0.92f)
            quadraticTo(size.width * 0.14f, size.height * 0.78f, size.width * 0.14f, size.height * 0.48f)
            lineTo(size.width * 0.14f, size.height * 0.22f)
            close()
        }
        drawPath(path, color, style = stroke(sw))
    }
}

@Composable
fun IconGlobe(color: Color, modifier: Modifier, strokeWidth: Dp = 1.6.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        val inset = size.minDimension * 0.08f
        drawOval(
            color = color,
            topLeft = Offset(inset, inset),
            size = Size(size.width - inset * 2, size.height - inset * 2),
            style = stroke(sw),
        )
        drawOval(
            color = color,
            topLeft = Offset(size.width * 0.32f, inset),
            size = Size(size.width * 0.36f, size.height - inset * 2),
            style = stroke(sw),
        )
        drawLine(color, Offset(inset, size.height / 2f), Offset(size.width - inset, size.height / 2f), sw, StrokeCap.Round)
    }
}

@Composable
fun IconUser(color: Color, modifier: Modifier, strokeWidth: Dp = 1.6.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        drawCircle(color, radius = size.minDimension * 0.16f, center = Offset(size.width / 2f, size.height * 0.32f), style = stroke(sw))
        drawArc(
            color = color,
            startAngle = 200f,
            sweepAngle = 140f,
            useCenter = false,
            topLeft = Offset(size.width * 0.16f, size.height * 0.48f),
            size = Size(size.width * 0.68f, size.height * 0.5f),
            style = stroke(sw),
        )
    }
}

@Composable
fun IconSearch(color: Color, modifier: Modifier, strokeWidth: Dp = 1.8.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        drawCircle(color, radius = size.minDimension * 0.28f, center = Offset(size.width * 0.42f, size.height * 0.42f), style = stroke(sw))
        drawLine(color, Offset(size.width * 0.64f, size.height * 0.64f), Offset(size.width * 0.88f, size.height * 0.88f), sw, StrokeCap.Round)
    }
}

@Composable
fun IconClose(color: Color, modifier: Modifier, strokeWidth: Dp = 1.8.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        val a = size.minDimension * 0.22f
        val b = size.minDimension * 0.78f
        drawLine(color, Offset(a, a), Offset(b, b), sw, StrokeCap.Round)
        drawLine(color, Offset(b, a), Offset(a, b), sw, StrokeCap.Round)
    }
}

@Composable
fun IconChevron(color: Color, modifier: Modifier, strokeWidth: Dp = 1.8.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        val path = Path().apply {
            moveTo(size.width * 0.36f, size.height * 0.2f)
            lineTo(size.width * 0.66f, size.height * 0.5f)
            lineTo(size.width * 0.36f, size.height * 0.8f)
        }
        drawPath(path, color, style = stroke(sw))
    }
}

@Composable
fun IconCheck(color: Color, modifier: Modifier, strokeWidth: Dp = 2.2.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        val path = Path().apply {
            moveTo(size.width * 0.18f, size.height * 0.52f)
            lineTo(size.width * 0.4f, size.height * 0.74f)
            lineTo(size.width * 0.82f, size.height * 0.28f)
        }
        drawPath(path, color, style = stroke(sw))
    }
}

@Composable
fun IconSparkles(color: Color, modifier: Modifier, strokeWidth: Dp = 1.6.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        fun star(cx: Float, cy: Float, r: Float) {
            drawLine(color, Offset(cx, cy - r), Offset(cx, cy + r), sw, StrokeCap.Round)
            drawLine(color, Offset(cx - r, cy), Offset(cx + r, cy), sw, StrokeCap.Round)
        }
        star(size.width * 0.42f, size.height * 0.42f, size.minDimension * 0.22f)
        star(size.width * 0.74f, size.height * 0.28f, size.minDimension * 0.1f)
        star(size.width * 0.7f, size.height * 0.72f, size.minDimension * 0.08f)
    }
}

@Composable
fun IconZap(color: Color, modifier: Modifier, strokeWidth: Dp = 1.6.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        val path = Path().apply {
            moveTo(size.width * 0.56f, size.height * 0.06f)
            lineTo(size.width * 0.18f, size.height * 0.54f)
            lineTo(size.width * 0.48f, size.height * 0.54f)
            lineTo(size.width * 0.40f, size.height * 0.94f)
            lineTo(size.width * 0.84f, size.height * 0.40f)
            lineTo(size.width * 0.52f, size.height * 0.40f)
            close()
        }
        drawPath(path, color, style = stroke(sw))
    }
}

@Composable
fun IconArrowDownLeft(color: Color, modifier: Modifier, strokeWidth: Dp = 2.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        drawLine(
            color,
            Offset(size.width * 0.72f, size.height * 0.28f),
            Offset(size.width * 0.28f, size.height * 0.72f),
            sw,
            StrokeCap.Round,
        )
        drawLine(
            color,
            Offset(size.width * 0.28f, size.height * 0.42f),
            Offset(size.width * 0.28f, size.height * 0.72f),
            sw,
            StrokeCap.Round,
        )
        drawLine(
            color,
            Offset(size.width * 0.28f, size.height * 0.72f),
            Offset(size.width * 0.58f, size.height * 0.72f),
            sw,
            StrokeCap.Round,
        )
    }
}

@Composable
fun IconArrowUpRight(color: Color, modifier: Modifier, strokeWidth: Dp = 1.8.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        val path = Path().apply {
            moveTo(size.width * 0.28f, size.height * 0.72f)
            lineTo(size.width * 0.72f, size.height * 0.28f)
        }
        drawPath(path, color, style = stroke(sw))
        drawLine(color, Offset(size.width * 0.42f, size.height * 0.28f), Offset(size.width * 0.72f, size.height * 0.28f), sw, StrokeCap.Round)
        drawLine(color, Offset(size.width * 0.72f, size.height * 0.28f), Offset(size.width * 0.72f, size.height * 0.58f), sw, StrokeCap.Round)
    }
}

@Composable
fun IconArrowRight(color: Color, modifier: Modifier, strokeWidth: Dp = 2.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        drawLine(color, Offset(size.width * 0.16f, size.height * 0.5f), Offset(size.width * 0.78f, size.height * 0.5f), sw, StrokeCap.Round)
        val path = Path().apply {
            moveTo(size.width * 0.52f, size.height * 0.28f)
            lineTo(size.width * 0.8f, size.height * 0.5f)
            lineTo(size.width * 0.52f, size.height * 0.72f)
        }
        drawPath(path, color, style = stroke(sw))
    }
}

@Composable
fun IconSend(color: Color, modifier: Modifier, strokeWidth: Dp = 1.7.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        val path = Path().apply {
            moveTo(size.width * 0.16f, size.height * 0.28f)
            lineTo(size.width * 0.86f, size.height * 0.5f)
            lineTo(size.width * 0.16f, size.height * 0.72f)
            lineTo(size.width * 0.34f, size.height * 0.5f)
            close()
        }
        drawPath(path, color, style = stroke(sw))
    }
}

@Composable
fun IconKey(color: Color, modifier: Modifier, strokeWidth: Dp = 1.7.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        drawCircle(color, radius = size.minDimension * 0.16f, center = Offset(size.width * 0.32f, size.height * 0.62f), style = stroke(sw))
        drawLine(color, Offset(size.width * 0.44f, size.height * 0.5f), Offset(size.width * 0.84f, size.height * 0.22f), sw, StrokeCap.Round)
        drawLine(color, Offset(size.width * 0.66f, size.height * 0.36f), Offset(size.width * 0.78f, size.height * 0.48f), sw, StrokeCap.Round)
    }
}

@Composable
fun IconLogout(color: Color, modifier: Modifier, strokeWidth: Dp = 1.6.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        val path = Path().apply {
            moveTo(size.width * 0.42f, size.height * 0.16f)
            lineTo(size.width * 0.22f, size.height * 0.16f)
            lineTo(size.width * 0.22f, size.height * 0.84f)
            lineTo(size.width * 0.42f, size.height * 0.84f)
        }
        drawPath(path, color, style = stroke(sw))
        drawLine(color, Offset(size.width * 0.42f, size.height * 0.5f), Offset(size.width * 0.84f, size.height * 0.5f), sw, StrokeCap.Round)
        val head = Path().apply {
            moveTo(size.width * 0.66f, size.height * 0.32f)
            lineTo(size.width * 0.86f, size.height * 0.5f)
            lineTo(size.width * 0.66f, size.height * 0.68f)
        }
        drawPath(head, color, style = stroke(sw))
    }
}

@Composable
fun IconPhone(color: Color, modifier: Modifier, strokeWidth: Dp = 1.5.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        val radius = CornerRadius(size.minDimension * 0.08f, size.minDimension * 0.08f)
        val path = Path().apply {
            addRoundRect(
                RoundRect(
                    left = size.width * 0.28f,
                    top = size.height * 0.08f,
                    right = size.width * 0.72f,
                    bottom = size.height * 0.92f,
                    topLeftCornerRadius = radius,
                    topRightCornerRadius = radius,
                    bottomRightCornerRadius = radius,
                    bottomLeftCornerRadius = radius,
                ),
            )
        }
        drawPath(path, color, style = stroke(sw))
        drawLine(color, Offset(size.width * 0.42f, size.height * 0.8f), Offset(size.width * 0.58f, size.height * 0.8f), sw, StrokeCap.Round)
    }
}

@Composable
fun IconFingerprint(color: Color, modifier: Modifier, strokeWidth: Dp = 1.5.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        val cx = size.width / 2f
        val cy = size.height * 0.52f
        drawLine(
            color,
            Offset(cx, cy - size.minDimension * 0.08f),
            Offset(cx, cy + size.minDimension * 0.18f),
            sw,
            StrokeCap.Round,
        )
        listOf(0.18f, 0.30f, 0.42f).forEach { r ->
            drawArc(
                color = color,
                startAngle = 200f,
                sweepAngle = 230f,
                useCenter = false,
                topLeft = Offset(cx - size.minDimension * r, cy - size.minDimension * r),
                size = Size(size.minDimension * r * 2, size.minDimension * r * 2),
                style = stroke(sw),
            )
        }
    }
}

@Composable
fun IconHelp(color: Color, modifier: Modifier, strokeWidth: Dp = 1.6.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        drawCircle(color, radius = size.minDimension * 0.38f, center = Offset(size.width / 2f, size.height / 2f), style = stroke(sw))
        val path = Path().apply {
            moveTo(size.width * 0.38f, size.height * 0.4f)
            quadraticTo(size.width * 0.4f, size.height * 0.28f, size.width * 0.5f, size.height * 0.28f)
            quadraticTo(size.width * 0.64f, size.height * 0.28f, size.width * 0.64f, size.height * 0.42f)
            quadraticTo(size.width * 0.64f, size.height * 0.52f, size.width * 0.5f, size.height * 0.56f)
        }
        drawPath(path, color, style = stroke(sw))
        drawCircle(color, radius = sw * 0.7f, center = Offset(size.width / 2f, size.height * 0.72f))
    }
}

@Composable
fun IconSettings(color: Color, modifier: Modifier, strokeWidth: Dp = 1.5.dp) {
    IconBox(modifier) {
        val sw = strokeWidth.toPx()
        drawCircle(color, radius = size.minDimension * 0.16f, center = Offset(size.width / 2f, size.height / 2f), style = stroke(sw))
        val path = Path().apply {
            moveTo(size.width * 0.5f, size.height * 0.08f)
            lineTo(size.width * 0.58f, size.height * 0.18f)
            lineTo(size.width * 0.72f, size.height * 0.16f)
            lineTo(size.width * 0.78f, size.height * 0.3f)
            lineTo(size.width * 0.9f, size.height * 0.38f)
            lineTo(size.width * 0.84f, size.height * 0.52f)
            lineTo(size.width * 0.9f, size.height * 0.66f)
            lineTo(size.width * 0.76f, size.height * 0.72f)
            lineTo(size.width * 0.7f, size.height * 0.86f)
            lineTo(size.width * 0.56f, size.height * 0.82f)
            lineTo(size.width * 0.5f, size.height * 0.92f)
            lineTo(size.width * 0.44f, size.height * 0.82f)
            lineTo(size.width * 0.3f, size.height * 0.86f)
            lineTo(size.width * 0.24f, size.height * 0.72f)
            lineTo(size.width * 0.1f, size.height * 0.66f)
            lineTo(size.width * 0.16f, size.height * 0.52f)
            lineTo(size.width * 0.1f, size.height * 0.38f)
            lineTo(size.width * 0.22f, size.height * 0.3f)
            lineTo(size.width * 0.28f, size.height * 0.16f)
            lineTo(size.width * 0.42f, size.height * 0.18f)
            close()
        }
        drawPath(path, color, style = stroke(sw))
    }
}
