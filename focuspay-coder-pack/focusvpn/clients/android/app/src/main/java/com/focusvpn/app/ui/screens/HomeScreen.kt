package com.focusvpn.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.focusvpn.app.ui.UiState
import com.focusvpn.app.ui.design.ConnectionMeshLayer
import com.focusvpn.app.ui.design.CountryMark
import com.focusvpn.app.ui.design.FocusBrand
import com.focusvpn.app.ui.design.IconArrowDownLeft
import com.focusvpn.app.ui.design.IconArrowUpRight
import com.focusvpn.app.ui.design.IconChevron
import com.focusvpn.app.ui.design.IconPower
import com.focusvpn.app.ui.design.IconShield
import com.focusvpn.app.ui.design.IconSparkles
import com.focusvpn.app.ui.design.IconZap
import com.focusvpn.app.ui.design.SignalMark
import com.focusvpn.app.vpn.formatMbps
import com.focusvpn.app.vpn.shownPing
import com.focusvpn.app.ui.design.countryLabel
import com.focusvpn.app.ui.design.formatDuration
import com.focusvpn.app.ui.design.subscriptionActive
import com.focusvpn.app.ui.theme.BgBase
import com.focusvpn.app.ui.theme.BgSurface
import com.focusvpn.app.ui.theme.Danger
import com.focusvpn.app.ui.theme.Dim
import com.focusvpn.app.ui.theme.Ink
import com.focusvpn.app.ui.theme.Line
import com.focusvpn.app.ui.theme.Onest
import com.focusvpn.app.ui.theme.TextMuted
import com.focusvpn.app.ui.theme.White
import kotlinx.coroutines.delay

@Composable
fun HomeScreen(
    state: UiState,
    onConnectToggle: () -> Unit,
    onOpenLocations: () -> Unit,
    onOpenAccount: () -> Unit,
) {
    val active = state.connected || state.connecting
    var boxOrigin by remember { mutableStateOf(Offset.Zero) }
    var powerCenter by remember { mutableStateOf(Offset(0f, 320f)) }
    var startedAt by remember { mutableStateOf<Long?>(null) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(state.connected) {
        startedAt = if (state.connected) System.currentTimeMillis() else null
    }
    LaunchedEffect(startedAt) {
        if (startedAt == null) return@LaunchedEffect
        while (true) {
            now = System.currentTimeMillis()
            delay(1000)
        }
    }
    val seconds = startedAt?.let { ((now - it) / 1000).coerceAtLeast(0) } ?: 0
    val place = selectedPlace(state)
    Box(
        Modifier
            .fillMaxSize()
            .background(BgBase)
            .onGloballyPositioned { boxOrigin = it.boundsInRoot().topLeft },
    ) {
        ConnectionMeshLayer(
            active = active,
            origin = powerCenter,
            modifier = Modifier.fillMaxSize(),
        )
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .statusBarsPadding()
                .padding(horizontal = 24.dp)
                .padding(top = 22.dp, bottom = 16.dp),
        ) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                FocusBrand(small = true, modifier = Modifier.weight(1f))
                if (subscriptionActive(state.subscriptionUntil)) {
                    Row(
                        Modifier
                            .height(34.dp)
                            .clip(RoundedCornerShape(11.dp))
                            .background(BgSurface)
                            .border(1.dp, Color(0xFF2E2E38), RoundedCornerShape(11.dp))
                            .clickable(onClick = onOpenAccount)
                            .padding(horizontal = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        IconSparkles(Ink, Modifier.size(11.dp))
                        Text(
                            "PLUS",
                            modifier = Modifier.padding(start = 5.dp),
                            color = Ink,
                            fontFamily = Onest,
                            fontWeight = FontWeight.SemiBold,
                            fontSize = 12.sp,
                            letterSpacing = 1.sp,
                        )
                    }
                }
            }
            Spacer(Modifier.height(24.dp))
            Text(
                "Подключение",
                color = Ink,
                fontFamily = Onest,
                fontWeight = FontWeight.SemiBold,
                fontSize = 32.sp,
                lineHeight = 40.sp,
                letterSpacing = (-0.8).sp,
            )
            Text(
                place.subtitle,
                modifier = Modifier.padding(top = 8.dp),
                color = if (active) Color(0xFFDDD6ED) else TextMuted,
                fontFamily = Onest,
                fontSize = 15.sp,
                lineHeight = 22.sp,
            )
            Box(
                Modifier
                    .fillMaxWidth()
                    .padding(top = 28.dp, bottom = 8.dp),
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    Modifier
                        .size(180.dp)
                        .connectPress(
                            enabled = state.connected || state.connecting || !state.busy,
                            connected = state.connected,
                            onClick = onConnectToggle,
                        )
                        .background(if (state.connected) White else Color(0xFF1F1F27))
                        .border(1.dp, if (state.connected) White else Color(0xFF3E3E4A), CircleShape)
                        .onGloballyPositioned { coords ->
                            powerCenter = coords.boundsInRoot().center - boxOrigin
                        },
                    contentAlignment = Alignment.Center,
                ) {
                    if (!state.connected) {
                        Box(
                            Modifier
                                .align(Alignment.TopCenter)
                                .fillMaxWidth()
                                .height(36.dp)
                                .background(
                                    Brush.verticalGradient(
                                        listOf(Color.White.copy(alpha = 0.07f), Color.Transparent),
                                    ),
                                ),
                        )
                    }
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        if (state.connecting) {
                            CircularProgressIndicator(color = Ink, strokeWidth = 2.dp, modifier = Modifier.size(36.dp))
                        } else {
                            IconPower(
                                color = if (state.connected) BgBase else Ink,
                                modifier = Modifier.size(48.dp),
                            )
                        }
                        Text(
                            when {
                                state.connecting -> "Отменить"
                                state.connected -> "Отключить"
                                else -> "Подключить"
                            },
                            modifier = Modifier.padding(top = 12.dp),
                            color = if (state.connected) BgBase else Ink,
                            fontFamily = Onest,
                            fontWeight = FontWeight.Medium,
                            fontSize = 15.sp,
                        )
                    }
                }
            }
            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconShield(
                        color = if (active) White else TextMuted,
                        modifier = Modifier.size(13.dp),
                        strokeWidth = 2.dp,
                    )
                    Text(
                        when {
                            state.connecting -> "Устанавливаем соединение…"
                            state.connected -> "Соединение установлено"
                            else -> "Вы не подключены"
                        },
                        modifier = Modifier.padding(start = 6.dp),
                        color = if (active) White else TextMuted,
                        fontFamily = Onest,
                        fontWeight = FontWeight.Medium,
                        fontSize = 15.sp,
                    )
                }
                Text(
                    when {
                        state.connected -> formatDuration(seconds)
                        state.connecting -> "Можно отменить в любой момент"
                        else -> "Нажмите кнопку для подключения"
                    },
                    modifier = Modifier.padding(top = 8.dp),
                    color = if (active) Color(0xFFDDD6ED) else Dim,
                    fontFamily = Onest,
                    fontSize = 13.sp,
                )
                if (!state.error.isNullOrBlank()) {
                    Text(
                        state.error,
                        modifier = Modifier.padding(top = 8.dp),
                        color = Danger,
                        fontFamily = Onest,
                        fontSize = 13.sp,
                        textAlign = TextAlign.Center,
                    )
                }
            }
            Column(
                Modifier
                    .padding(top = 24.dp)
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(18.dp))
                    .background(BgSurface.copy(alpha = if (active) 0.72f else 1f))
                    .border(1.dp, Color(0xFF2A2A30), RoundedCornerShape(18.dp))
                    .clickable(onClick = onOpenLocations)
                    .padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 10.dp),
            ) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "ВАША ЛОКАЦИЯ",
                        modifier = Modifier.weight(1f),
                        color = TextMuted,
                        fontFamily = Onest,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 11.sp,
                        letterSpacing = 1.sp,
                    )
                    IconZap(TextMuted, Modifier.size(12.dp))
                }
                Row(
                    Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    CountryMark(place.code)
                    Column(Modifier.weight(1f).padding(horizontal = 10.dp)) {
                        Text(place.title, color = Ink, fontFamily = Onest, fontWeight = FontWeight.Medium, fontSize = 15.sp)
                        Text(place.detail, color = TextMuted, fontFamily = Onest, fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp))
                    }
                    SignalMark(shownPing(state.pingMs, place.node), Modifier.padding(end = 10.dp))
                    IconChevron(TextMuted, Modifier.size(17.dp))
                }
            }
            Row(
                Modifier
                    .padding(top = 12.dp)
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(16.dp))
                    .background(Color(0x800A0A0E))
                    .padding(vertical = 20.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                SpeedMetric(down = true, mbps = state.downMbps, modifier = Modifier.weight(1f))
                Box(Modifier.size(width = 1.dp, height = 19.dp).background(Line))
                SpeedMetric(down = false, mbps = state.upMbps, modifier = Modifier.weight(1f))
            }
            Text(
                "Российские сайты и приложения идут с IP телефона",
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                color = if (active) Color(0xFFDDD6ED) else Dim,
                fontFamily = Onest,
                fontSize = 11.sp,
                lineHeight = 17.sp,
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Composable
private fun SpeedMetric(down: Boolean, mbps: Double?, modifier: Modifier = Modifier) {
    val tint = if (mbps != null) White else Dim
    Row(
        modifier,
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (down) {
            IconArrowDownLeft(tint, Modifier.size(14.dp))
        } else {
            IconArrowUpRight(tint, Modifier.size(14.dp), strokeWidth = 2.dp)
        }
        Text(
            formatMbps(mbps),
            modifier = Modifier.padding(start = 5.dp),
            color = Ink,
            fontFamily = Onest,
            fontWeight = FontWeight.SemiBold,
            fontSize = 16.sp,
        )
        Text(
            " Мбит/с",
            color = Color(0xFFB2B2BC),
            fontFamily = Onest,
            fontSize = 12.sp,
        )
    }
}

private data class Place(val code: String, val title: String, val subtitle: String, val detail: String, val node: String?)

private fun selectedPlace(state: UiState): Place {
    val node = state.endpointHint?.takeIf { it.isNotBlank() } ?: state.selectedNode?.takeIf { it.isNotBlank() }
    val ep = state.endpoints.firstOrNull { it.node == node }
    if (ep == null) {
        val name = node ?: "Авто"
        return Place(
            code = "",
            title = if (node == null) "Авто" else name,
            subtitle = if (node == null) "Самый быстрый сервер" else name,
            detail = if (node == null) "Переключение само" else "Выбранный сервер",
            node = node,
        )
    }
    return Place(
        code = ep.country,
        title = countryLabel(ep.country),
        subtitle = "${countryLabel(ep.country)} · ${ep.node}",
        detail = listOf(ep.region, ep.node).filter { it.isNotBlank() }.joinToString(" · ").ifBlank { ep.protocol },
        node = ep.node,
    )
}

/**
 * Press feedback is a slight scale. The default ripple is a square the size of
 * this box; the circle is only the clipped fill, so that square showed up
 * around the button on every press.
 */
@Composable
private fun Modifier.connectPress(
    enabled: Boolean,
    connected: Boolean,
    onClick: () -> Unit,
): Modifier {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val glow = if (connected) Color.White.copy(alpha = 0.33f) else Color.Black.copy(alpha = 0.33f)
    val elevation = if (connected) 18.dp else 16.dp
    return this
        .graphicsLayer {
            val scale = if (enabled && pressed) 0.96f else 1f
            scaleX = scale
            scaleY = scale
            shape = CircleShape
            clip = true
            shadowElevation = elevation.toPx()
            ambientShadowColor = glow
            spotShadowColor = glow
        }
        .clickable(
            enabled = enabled,
            interactionSource = interaction,
            indication = null,
            onClick = onClick,
        )
}
