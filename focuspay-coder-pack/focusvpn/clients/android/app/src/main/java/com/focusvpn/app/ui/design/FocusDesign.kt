package com.focusvpn.app.ui.design

import android.provider.Settings
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.focusvpn.app.R
import com.focusvpn.app.vpn.formatPing
import com.focusvpn.app.vpn.signalBars
import com.focusvpn.app.ui.theme.BgBase
import com.focusvpn.app.ui.theme.Dim
import com.focusvpn.app.ui.theme.Ink
import com.focusvpn.app.ui.theme.Onest
import com.focusvpn.app.ui.theme.TextMuted
import com.focusvpn.app.ui.theme.White
enum class MeshKind { Login, Profile, Connection }

@Composable
fun FocusMesh(kind: MeshKind, modifier: Modifier = Modifier) {
    androidx.compose.foundation.Canvas(modifier) {
        drawRect(Color(0xFF17132E))
        fun blob(cx: Float, cy: Float, rx: Float, ry: Float, color: Color) {
            val radius = maxOf(rx * size.width, ry * size.height)
            drawRect(
                brush = Brush.radialGradient(
                    colors = listOf(color, color.copy(alpha = 0f)),
                    center = Offset(cx * size.width, cy * size.height),
                    radius = radius,
                ),
            )
        }
        when (kind) {
            MeshKind.Login -> {
                blob(0.08f, 0.20f, 0.78f, 0.80f, Color(0xFF2C7BF2))
                blob(0.82f, 0.35f, 0.65f, 0.60f, Color(0xFF8B5CF6))
                blob(0.94f, 0.82f, 0.62f, 0.58f, Color(0xFF22D3EE))
                blob(0.28f, 0.92f, 0.65f, 0.60f, Color(0xFF1E1B4B))
            }
            MeshKind.Profile -> {
                blob(0.08f, 0.20f, 0.78f, 0.80f, Color(0xFF6D5BFF))
                blob(0.82f, 0.35f, 0.65f, 0.60f, Color(0xFFA98BFF))
                blob(0.94f, 0.82f, 0.62f, 0.58f, Color(0xFFFF7AC2))
                blob(0.28f, 0.92f, 0.65f, 0.60f, Color(0xFF3C2A86))
            }
            MeshKind.Connection -> {
                blob(0.35f, 0.20f, 0.78f, 0.80f, Color(0xFF2E7BFF))
                blob(0.65f, 0.35f, 0.65f, 0.60f, Color(0xFF7B3FF2))
                blob(0.63f, 0.82f, 0.62f, 0.58f, Color(0xFF17D6C6))
                blob(0.28f, 0.92f, 0.65f, 0.60f, Color(0xFF0E2A66))
                drawRect(Color(0x330C091F))
            }
        }
    }
}

@Composable
fun ConnectionMeshLayer(
    active: Boolean,
    origin: Offset,
    modifier: Modifier = Modifier,
) {
    val reduceMotion = rememberReduceMotion()
    val progress = remember { Animatable(if (active) 1f else 0f) }
    LaunchedEffect(active, reduceMotion) {
        val target = if (active) 1f else 0f
        if (reduceMotion) progress.snapTo(target)
        else {
            progress.animateTo(
                target,
                tween(
                    durationMillis = if (active) 1450 else 850,
                    easing = CubicBezierEasing(0.22f, 1f, 0.36f, 1f),
                ),
            )
        }
    }
    val amount = progress.value
    Box(
        modifier
            .alpha(meshAlpha(amount))
            .drawWithContent {
                if (amount <= 0.001f || size.width <= 0f || size.height <= 0f) return@drawWithContent
                val radius = meshCoverRadius(origin.x, origin.y, size.width, size.height) * amount
                val reveal = Path().apply {
                    addOval(
                        Rect(
                            left = origin.x - radius,
                            top = origin.y - radius,
                            right = origin.x + radius,
                            bottom = origin.y + radius,
                        ),
                    )
                }
                clipPath(reveal) { this@drawWithContent.drawContent() }
            },
    ) {
        FocusMesh(MeshKind.Connection, Modifier.fillMaxSize())
    }
}

@Composable
fun FocusBrand(small: Boolean = false, modifier: Modifier = Modifier) {
    val mark = if (small) 34.dp else 40.dp
    val word = if (small) 24.sp else 28.sp
    Row(
        modifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Image(
            painter = painterResource(R.drawable.ic_focus_mark),
            contentDescription = null,
            modifier = Modifier.size(mark),
            contentScale = ContentScale.Fit,
        )
        Text(
            buildAnnotatedString {
                withStyle(
                    SpanStyle(
                        fontFamily = Onest,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = word,
                        color = Ink,
                        letterSpacing = (-0.8).sp,
                    ),
                ) { append("Focus") }
                withStyle(
                    SpanStyle(
                        fontFamily = Onest,
                        fontWeight = FontWeight.Medium,
                        fontSize = 13.sp,
                        color = Color(0xFFCBCBD2),
                    ),
                ) { append(" VPN") }
            },
        )
    }
}

@Composable
fun FocusAction(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    secondary: Boolean = false,
    enabled: Boolean = true,
    showArrow: Boolean = true,
) {
    val bg = if (secondary) Color(0xFF1E1E27) else White
    val fg = if (secondary) Ink else BgBase
    val shape = RoundedCornerShape(18.dp)
    Row(
        modifier
            .fillMaxWidth()
            .height(56.dp)
            .scaledClick(enabled = enabled, onClick = onClick)
            .then(
                if (!secondary && enabled) {
                    Modifier.shadow(
                        elevation = 10.dp,
                        shape = shape,
                        clip = false,
                        ambientColor = Color.White.copy(alpha = 0.25f),
                        spotColor = Color.White.copy(alpha = 0.25f),
                    )
                } else {
                    Modifier
                },
            )
            .clip(shape)
            .background(if (enabled) bg else bg.copy(alpha = 0.45f))
            .then(
                if (secondary) Modifier.border(1.dp, Color(0xFF30303A), shape) else Modifier,
            )
            .padding(horizontal = 18.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        Text(
            text,
            color = fg,
            fontFamily = Onest,
            fontWeight = FontWeight.SemiBold,
            fontSize = 16.sp,
        )
        if (showArrow) {
            IconArrowRight(fg, Modifier.padding(start = 10.dp).size(17.dp))
        }
    }
}

@Composable
fun Modifier.scaledClick(enabled: Boolean = true, onClick: () -> Unit): Modifier {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    return this
        .graphicsLayer {
            val scale = if (enabled && pressed) 0.96f else 1f
            scaleX = scale
            scaleY = scale
        }
        .clickable(
            enabled = enabled,
            interactionSource = interaction,
            indication = LocalIndication.current,
            onClick = onClick,
        )
}

@Composable
fun SignalMark(pingMs: Int?, modifier: Modifier = Modifier) {
    val lit = signalBars(pingMs)
    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        Row(
            Modifier.height(12.dp),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            listOf(5.dp, 8.dp, 11.dp).forEachIndexed { index, bar ->
                Box(
                    Modifier
                        .width(2.5.dp)
                        .height(bar)
                        .clip(RoundedCornerShape(2.dp))
                        .background(if (index < lit) White else Color(0xFF53535B)),
                )
            }
        }
        Text(
            formatPing(pingMs),
            modifier = Modifier.padding(top = 4.dp),
            color = Color(0xFFB1B1BA),
            fontFamily = Onest,
            fontSize = 11.sp,
        )
    }
}

@Composable
private fun sheetBottomGap(): androidx.compose.ui.unit.Dp {
    val nav = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
    return if (nav < 36.dp) 36.dp else nav + 8.dp
}

@Composable
fun FocusSheet(
    visible: Boolean,
    title: String,
    onClose: () -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    if (!visible) return
    val reduceMotion = rememberReduceMotion()
    // 1 = the whole sheet is below the screen, 0 = seated. Same 340ms rise as the mock.
    val shift = remember { Animatable(if (reduceMotion) 0f else 1f) }
    val fade = remember { Animatable(if (reduceMotion) 1f else 0f) }
    LaunchedEffect(Unit) {
        if (!reduceMotion) {
            fade.animateTo(1f, tween(200))
        }
    }
    LaunchedEffect(Unit) {
        if (!reduceMotion) {
            shift.animateTo(0f, tween(340, easing = CubicBezierEasing(0.22f, 1f, 0.36f, 1f)))
        }
    }
    Dialog(
        onDismissRequest = onClose,
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        BoxWithConstraints(
            Modifier
                .fillMaxSize()
                .background(Color.Black.copy(alpha = 0.72f * fade.value))
                .clickable(
                    indication = null,
                    interactionSource = remember { MutableInteractionSource() },
                    onClick = onClose,
                ),
            contentAlignment = Alignment.BottomCenter,
        ) {
            Column(
                Modifier
                    .padding(start = 18.dp, end = 18.dp, top = 18.dp, bottom = sheetBottomGap())
                    .imePadding()
                    .fillMaxWidth()
                    .heightIn(max = maxHeight * 0.85f)
                    .graphicsLayer { translationY = shift.value * size.height }
                    .clip(RoundedCornerShape(26.dp))
                    .background(Color(0xFF1B1B20))
                    .border(1.dp, Color(0xFF38383F), RoundedCornerShape(26.dp))
                    .verticalScroll(rememberScrollState())
                    .clickable(
                        indication = null,
                        interactionSource = remember { MutableInteractionSource() },
                        onClick = {},
                    )
                    .padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(18.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        title,
                        modifier = Modifier.weight(1f),
                        color = Ink,
                        fontFamily = Onest,
                        fontWeight = FontWeight.Bold,
                        fontSize = 22.sp,
                    )
                    Box(
                        Modifier
                            .size(44.dp)
                            .clip(CircleShape)
                            .clickable(onClick = onClose),
                        contentAlignment = Alignment.Center,
                    ) {
                        IconClose(Ink, Modifier.size(20.dp))
                    }
                }
                content()
            }
        }
    }
}

enum class FocusTab { Connect, Locations, Account }

@Composable
fun FocusTabBar(active: FocusTab, onSelect: (FocusTab) -> Unit, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth().background(BgBase)) {
        Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0xFF252529)))
        Row(
            Modifier
                .fillMaxWidth()
                .padding(top = 10.dp, bottom = 9.dp),
        ) {
            TabItem("Подключение", active == FocusTab.Connect, { IconShield(it, Modifier.size(20.dp), if (active == FocusTab.Connect) 2.dp else 1.5.dp) }) {
                onSelect(FocusTab.Connect)
            }
            TabItem("Локации", active == FocusTab.Locations, { IconGlobe(it, Modifier.size(20.dp), if (active == FocusTab.Locations) 2.dp else 1.5.dp) }) {
                onSelect(FocusTab.Locations)
            }
            TabItem("Аккаунт", active == FocusTab.Account, { IconUser(it, Modifier.size(20.dp), if (active == FocusTab.Account) 2.dp else 1.5.dp) }) {
                onSelect(FocusTab.Account)
            }
        }
    }
}

@Composable
private fun androidx.compose.foundation.layout.RowScope.TabItem(
    label: String,
    selected: Boolean,
    icon: @Composable (Color) -> Unit,
    onClick: () -> Unit,
) {
    val content = if (selected) White else Color(0xFFE6E6EE)
    Column(
        Modifier
            .weight(1f)
            .padding(horizontal = 4.dp, vertical = 6.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(if (selected) Color(0xFF2A2A32) else Color.Transparent)
            .clickable(onClick = onClick)
            .padding(horizontal = 6.dp, vertical = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        icon(content)
        Text(
            label,
            color = content,
            fontFamily = Onest,
            fontWeight = FontWeight.Medium,
            fontSize = 11.sp,
            textAlign = TextAlign.Center,
            maxLines = 1,
            modifier = Modifier.padding(top = 2.dp),
        )
    }
}

@Composable
fun CountryMark(code: String, modifier: Modifier = Modifier) {
    val key = code.trim().uppercase()
    Box(
        modifier
            .size(36.dp)
            .clip(CircleShape)
            .border(1.dp, Color.White.copy(alpha = 0.1f), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        if (key.length == 2 && key in knownFlags) {
            androidx.compose.foundation.Canvas(Modifier.fillMaxSize()) {
                when (key) {
                    "NL" -> {
                        drawRect(Color(0xFFAE1C28), size = androidx.compose.ui.geometry.Size(size.width, size.height / 3f))
                        drawRect(Color.White, topLeft = Offset(0f, size.height / 3f), size = androidx.compose.ui.geometry.Size(size.width, size.height / 3f))
                        drawRect(Color(0xFF21468B), topLeft = Offset(0f, size.height * 2f / 3f), size = androidx.compose.ui.geometry.Size(size.width, size.height / 3f))
                    }
                    "DE" -> {
                        drawRect(Color.Black, size = androidx.compose.ui.geometry.Size(size.width, size.height / 3f))
                        drawRect(Color(0xFFDD0000), topLeft = Offset(0f, size.height / 3f), size = androidx.compose.ui.geometry.Size(size.width, size.height / 3f))
                        drawRect(Color(0xFFFFCE00), topLeft = Offset(0f, size.height * 2f / 3f), size = androidx.compose.ui.geometry.Size(size.width, size.height / 3f))
                    }
                    "RO" -> {
                        drawRect(Color(0xFF002B7F), size = androidx.compose.ui.geometry.Size(size.width / 3f, size.height))
                        drawRect(Color(0xFFFCD116), topLeft = Offset(size.width / 3f, 0f), size = androidx.compose.ui.geometry.Size(size.width / 3f, size.height))
                        drawRect(Color(0xFFCE1126), topLeft = Offset(size.width * 2f / 3f, 0f), size = androidx.compose.ui.geometry.Size(size.width / 3f, size.height))
                    }
                    "FI" -> {
                        drawRect(Color.White)
                        drawRect(Color(0xFF002F6C), topLeft = Offset(size.width * 0.28f, 0f), size = androidx.compose.ui.geometry.Size(size.width * 0.18f, size.height))
                        drawRect(Color(0xFF002F6C), topLeft = Offset(0f, size.height * 0.4f), size = androidx.compose.ui.geometry.Size(size.width, size.height * 0.2f))
                    }
                    "CH" -> {
                        drawRect(Color(0xFFDA291C))
                        drawRect(Color.White, topLeft = Offset(size.width * 0.42f, size.height * 0.22f), size = androidx.compose.ui.geometry.Size(size.width * 0.16f, size.height * 0.56f))
                        drawRect(Color.White, topLeft = Offset(size.width * 0.22f, size.height * 0.42f), size = androidx.compose.ui.geometry.Size(size.width * 0.56f, size.height * 0.16f))
                    }
                    "JP" -> {
                        drawRect(Color.White)
                        drawCircle(Color(0xFFBC002D), radius = size.minDimension * 0.22f, center = center)
                    }
                    "US" -> {
                        drawRect(Color.White)
                        val stripe = size.height / 6f
                        repeat(6) { i ->
                            if (i % 2 == 0) {
                                drawRect(Color(0xFFB22234), topLeft = Offset(0f, stripe * i), size = androidx.compose.ui.geometry.Size(size.width, stripe))
                            }
                        }
                        drawRect(Color(0xFF3C3B6E), size = androidx.compose.ui.geometry.Size(size.width * 0.46f, size.height * 0.5f))
                    }
                    "GB", "UK" -> {
                        drawRect(Color(0xFF012169))
                        drawLine(Color.White, Offset(0f, 0f), Offset(size.width, size.height), strokeWidth = size.minDimension * 0.16f)
                        drawLine(Color.White, Offset(size.width, 0f), Offset(0f, size.height), strokeWidth = size.minDimension * 0.16f)
                        drawLine(Color(0xFFC8102E), Offset(0f, 0f), Offset(size.width, size.height), strokeWidth = size.minDimension * 0.08f)
                        drawLine(Color(0xFFC8102E), Offset(size.width, 0f), Offset(0f, size.height), strokeWidth = size.minDimension * 0.08f)
                        drawRect(Color.White, topLeft = Offset(size.width * 0.38f, 0f), size = androidx.compose.ui.geometry.Size(size.width * 0.24f, size.height))
                        drawRect(Color.White, topLeft = Offset(0f, size.height * 0.38f), size = androidx.compose.ui.geometry.Size(size.width, size.height * 0.24f))
                        drawRect(Color(0xFFC8102E), topLeft = Offset(size.width * 0.42f, 0f), size = androidx.compose.ui.geometry.Size(size.width * 0.16f, size.height))
                        drawRect(Color(0xFFC8102E), topLeft = Offset(0f, size.height * 0.42f), size = androidx.compose.ui.geometry.Size(size.width, size.height * 0.16f))
                    }
                    "SG" -> {
                        drawRect(Color.White, topLeft = Offset(0f, size.height / 2f), size = androidx.compose.ui.geometry.Size(size.width, size.height / 2f))
                        drawRect(Color(0xFFEF3340), size = androidx.compose.ui.geometry.Size(size.width, size.height / 2f))
                        drawCircle(Color.White, radius = size.minDimension * 0.12f, center = Offset(size.width * 0.32f, size.height * 0.26f))
                    }
                }
            }
        } else {
            Box(Modifier.fillMaxSize().background(Color(0xFF29292F)), contentAlignment = Alignment.Center) {
                Text(
                    key.take(2).ifBlank { "•" },
                    color = Ink,
                    fontFamily = Onest,
                    fontWeight = FontWeight.Medium,
                    fontSize = 12.sp,
                )
            }
        }
    }
}

private val knownFlags = setOf("NL", "DE", "RO", "FI", "CH", "JP", "US", "GB", "UK", "SG")

@Composable
fun rememberReduceMotion(): Boolean {
    val context = LocalContext.current
    return remember {
        Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    }
}

@Composable
fun MutedCopy(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        modifier = modifier,
        color = TextMuted,
        fontFamily = Onest,
        fontSize = 16.sp,
        lineHeight = 24.sp,
    )
}
