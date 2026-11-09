package com.focusvpn.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.focusvpn.app.data.EndpointDTO
import com.focusvpn.app.ui.design.CountryMark
import com.focusvpn.app.ui.design.FocusAction
import com.focusvpn.app.ui.design.SignalMark
import com.focusvpn.app.vpn.shownPing
import com.focusvpn.app.ui.design.IconCheck
import com.focusvpn.app.ui.design.IconChevron
import com.focusvpn.app.ui.design.IconClose
import com.focusvpn.app.ui.design.IconGlobe
import com.focusvpn.app.ui.design.IconSearch
import com.focusvpn.app.ui.design.MutedCopy
import com.focusvpn.app.ui.design.countryLabel
import com.focusvpn.app.ui.design.endpointMatches
import com.focusvpn.app.ui.theme.BgBase
import com.focusvpn.app.ui.theme.BgSurface
import com.focusvpn.app.ui.theme.Danger
import com.focusvpn.app.ui.theme.Dim
import com.focusvpn.app.ui.theme.Ink
import com.focusvpn.app.ui.theme.Line
import com.focusvpn.app.ui.theme.Onest
import com.focusvpn.app.ui.theme.TextMuted
import com.focusvpn.app.ui.theme.White

private val filters = listOf(
    "all" to "Все",
    "europe" to "Европа",
    "asia" to "Азия",
    "america" to "Америка",
)

@Composable
fun LocationsScreen(
    endpoints: List<EndpointDTO>,
    selected: String?,
    pings: Map<String, Int>,
    busy: Boolean,
    error: String?,
    onRefresh: () -> Unit,
    onSelect: (String?) -> Unit,
) {
    var query by rememberSaveable { mutableStateOf("") }
    var region by rememberSaveable { mutableStateOf("all") }
    LaunchedEffect(Unit) { if (endpoints.isEmpty()) onRefresh() }
    val results = endpoints.filter { endpointMatches(it, query, region) }
    Column(Modifier.fillMaxSize().background(BgBase).statusBarsPadding()) {
        Column(
            Modifier.padding(start = 24.dp, end = 24.dp, top = 24.dp, bottom = 10.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                "Локации",
                color = Ink,
                fontFamily = Onest,
                fontWeight = FontWeight.SemiBold,
                fontSize = 32.sp,
                letterSpacing = (-0.8).sp,
            )
            MutedCopy("Выберите страну подключения.")
            Row(
                Modifier
                    .fillMaxWidth()
                    .height(54.dp)
                    .clip(RoundedCornerShape(16.dp))
                    .background(BgSurface)
                    .border(1.dp, Line, RoundedCornerShape(16.dp))
                    .padding(start = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconSearch(TextMuted, Modifier.size(18.dp))
                BasicTextField(
                    value = query,
                    onValueChange = { query = it },
                    modifier = Modifier.weight(1f).padding(horizontal = 9.dp),
                    textStyle = TextStyle(color = Ink, fontFamily = Onest, fontSize = 16.sp),
                    singleLine = true,
                    cursorBrush = SolidColor(Ink),
                    decorationBox = { inner ->
                        Box {
                            if (query.isEmpty()) {
                                Text("Страна или город…", color = Dim, fontFamily = Onest, fontSize = 16.sp)
                            }
                            inner()
                        }
                    },
                )
                if (query.isNotEmpty()) {
                    Box(
                        Modifier.size(44.dp).clickable { query = "" },
                        contentAlignment = Alignment.Center,
                    ) {
                        IconClose(Ink, Modifier.size(16.dp))
                    }
                }
            }
            Row(
                Modifier.horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                filters.forEach { (id, label) ->
                    val on = region == id
                    Box(
                        Modifier
                            .height(44.dp)
                            .clip(RoundedCornerShape(16.dp))
                            .background(if (on) White else BgSurface)
                            .clickable { region = id }
                            .padding(horizontal = 15.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            label,
                            color = if (on) BgBase else TextMuted,
                            fontFamily = Onest,
                            fontWeight = FontWeight.SemiBold,
                            fontSize = 14.sp,
                        )
                    }
                }
            }
        }
        Column(
            Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (!error.isNullOrBlank()) Text(error, color = Danger, fontFamily = Onest, fontSize = 14.sp)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("ДОСТУПНЫЕ ЛОКАЦИИ", color = TextMuted, fontFamily = Onest, fontWeight = FontWeight.SemiBold, fontSize = 11.sp, letterSpacing = 1.sp)
                Text(
                    if (busy && endpoints.isEmpty()) "…" else "${results.size} / ${endpoints.size}",
                    color = TextMuted,
                    fontFamily = Onest,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 11.sp,
                    letterSpacing = 1.sp,
                )
            }
            val showAuto = query.isBlank() && region == "all"
            if (showAuto) {
                LocationRow(
                    title = "Авто",
                    detail = "Самый быстрый сервер",
                    code = "",
                    pingMs = shownPing(pings, null),
                    selected = selected.isNullOrBlank(),
                    onClick = { onSelect(null) },
                )
            }
            results.forEach { ep ->
                LocationRow(
                    title = countryLabel(ep.country),
                    detail = listOf(ep.region, ep.node, ep.protocol).filter { it.isNotBlank() }.joinToString(" · "),
                    code = ep.country,
                    pingMs = pings[ep.node],
                    selected = ep.node == selected,
                    onClick = { onSelect(ep.node) },
                )
            }
            if (results.isEmpty() && !(query.isBlank() && region == "all")) {
                Column(
                    Modifier.fillMaxWidth().padding(top = 48.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    IconGlobe(Dim, Modifier.size(35.dp))
                    Text("Пока ничего не нашли", color = Ink, fontFamily = Onest, fontWeight = FontWeight.SemiBold, fontSize = 20.sp)
                    Text(
                        "Попробуйте другую страну, город\nили сбросьте фильтры.",
                        color = TextMuted,
                        fontFamily = Onest,
                        fontSize = 16.sp,
                        lineHeight = 24.sp,
                        textAlign = TextAlign.Center,
                    )
                    FocusAction(
                        text = "Сбросить поиск",
                        onClick = {
                            query = ""
                            region = "all"
                        },
                        secondary = true,
                        showArrow = false,
                    )
                }
            }
        }
    }
}

@Composable
private fun LocationRow(
    title: String,
    detail: String,
    code: String,
    pingMs: Int?,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .height(82.dp)
            .clip(RoundedCornerShape(18.dp))
            .background(if (selected) androidx.compose.ui.graphics.Color(0xFF1C1C24) else BgSurface)
            .border(1.dp, if (selected) androidx.compose.ui.graphics.Color(0xFF8A8A96) else Line, RoundedCornerShape(18.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CountryMark(code)
        Column(Modifier.weight(1f).padding(horizontal = 10.dp)) {
            Text(title, color = Ink, fontFamily = Onest, fontWeight = FontWeight.Medium, fontSize = 15.sp)
            Text(detail, color = TextMuted, fontFamily = Onest, fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp))
        }
        SignalMark(pingMs, Modifier.padding(end = 8.dp))
        if (selected) IconCheck(White, Modifier.size(18.dp)) else IconChevron(TextMuted, Modifier.size(17.dp))
    }
}
