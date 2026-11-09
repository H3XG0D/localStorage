package com.focusvpn.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.focusvpn.app.BuildConfig
import com.focusvpn.app.auth.telegramViewIntent
import com.focusvpn.app.ui.UiState
import com.focusvpn.app.ui.design.FocusAction
import com.focusvpn.app.ui.design.FocusBrand
import com.focusvpn.app.ui.design.FocusMesh
import com.focusvpn.app.ui.design.FocusSheet
import com.focusvpn.app.ui.design.IconArrowUpRight
import com.focusvpn.app.ui.design.IconChevron
import com.focusvpn.app.ui.design.IconFingerprint
import com.focusvpn.app.ui.design.IconGlobe
import com.focusvpn.app.ui.design.IconHelp
import com.focusvpn.app.ui.design.IconLogout
import com.focusvpn.app.ui.design.IconPhone
import com.focusvpn.app.ui.design.IconSettings
import com.focusvpn.app.ui.design.IconSparkles
import com.focusvpn.app.ui.design.MeshKind
import com.focusvpn.app.ui.design.MutedCopy
import com.focusvpn.app.ui.design.daysUntil
import com.focusvpn.app.ui.design.formatSubscriptionDate
import com.focusvpn.app.ui.design.ruDays
import com.focusvpn.app.ui.design.subscriptionActive
import com.focusvpn.app.ui.design.subscriptionProgress
import com.focusvpn.app.ui.theme.BgBase
import com.focusvpn.app.ui.theme.BgSurface
import com.focusvpn.app.ui.theme.Dim
import com.focusvpn.app.ui.theme.Ink
import com.focusvpn.app.ui.theme.Onest
import com.focusvpn.app.ui.theme.TextMuted
import com.focusvpn.app.ui.theme.White

private enum class AccountInfo { Subscription, Devices, Support, Privacy, About, Logout }

@Composable
fun AccountScreen(
    state: UiState,
    botDeepLink: String,
    onRebindDevice: () -> Unit,
    onLogout: () -> Unit,
) {
    val ctx = LocalContext.current
    var info by androidx.compose.runtime.remember { mutableStateOf<AccountInfo?>(null) }
    val active = subscriptionActive(state.subscriptionUntil)
    val days = state.subscriptionUntil?.let { daysUntil(it) }?.coerceAtLeast(0)
    val openBot = {
        ctx.startActivity(telegramViewIntent(ctx.packageManager, botDeepLink))
    }
    val name = state.email.substringBefore("@").ifBlank { state.email }.ifBlank { "Focus" }
    Column(
        Modifier
            .fillMaxSize()
            .background(BgBase)
            .verticalScroll(rememberScrollState())
            .statusBarsPadding()
            .padding(horizontal = 22.dp)
            .padding(top = 18.dp, bottom = 8.dp),
    ) {
        Row(Modifier.fillMaxWidth().padding(bottom = 24.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(
                "Аккаунт",
                modifier = Modifier.weight(1f),
                color = Ink,
                fontFamily = Onest,
                fontWeight = FontWeight.SemiBold,
                fontSize = 32.sp,
                letterSpacing = (-0.8).sp,
            )
            Box(
                Modifier.size(44.dp).clip(CircleShape).clickable { info = AccountInfo.About },
                contentAlignment = Alignment.Center,
            ) {
                IconSettings(Ink, Modifier.size(20.dp))
            }
        }
        Row(Modifier.padding(bottom = 24.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(contentAlignment = Alignment.BottomEnd) {
                Box(
                    Modifier
                        .size(52.dp)
                        .clip(CircleShape)
                        .background(Color(0xFF29292F))
                        .border(1.dp, Color(0xFF414149), CircleShape),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(name.take(1).uppercase(), color = Ink, fontFamily = Onest, fontWeight = FontWeight.Medium, fontSize = 24.sp)
                }
                if (active) {
                    Box(
                        Modifier
                            .size(18.dp)
                            .clip(CircleShape)
                            .background(White)
                            .border(2.dp, BgBase, CircleShape),
                        contentAlignment = Alignment.Center,
                    ) {
                        IconSparkles(BgBase, Modifier.size(10.dp))
                    }
                }
            }
            Column(Modifier.padding(start = 14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                Text(name, color = Ink, fontFamily = Onest, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                Text(state.email.ifBlank { "FocusVPN" }, color = TextMuted, fontFamily = Onest, fontSize = 13.sp)
            }
        }
        Box(
            Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(24.dp))
                .border(1.dp, Color.White.copy(alpha = 0.12f), RoundedCornerShape(24.dp)),
        ) {
            FocusMesh(MeshKind.Profile, Modifier.matchParentSize())
            Column(Modifier.padding(20.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "Focus",
                        color = White,
                        fontFamily = Onest,
                        fontWeight = FontWeight.ExtraBold,
                        fontSize = 28.sp,
                        letterSpacing = (-0.7).sp,
                    )
                    Text(
                        " " + (state.plan.ifBlank { "VPN" }),
                        color = White,
                        fontFamily = Onest,
                        fontWeight = FontWeight.Medium,
                        fontSize = 25.sp,
                        letterSpacing = (-0.7).sp,
                    )
                    Spacer(Modifier.weight(1f))
                    if (active) {
                        Row(
                            Modifier
                                .clip(RoundedCornerShape(20.dp))
                                .background(Color.White.copy(alpha = 0.12f))
                                .border(1.dp, Color.White.copy(alpha = 0.19f), RoundedCornerShape(20.dp))
                                .padding(horizontal = 8.dp, vertical = 5.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Box(Modifier.size(4.dp).clip(CircleShape).background(White))
                            Text(
                                "Активна",
                                modifier = Modifier.padding(start = 5.dp),
                                color = White,
                                fontFamily = Onest,
                                fontWeight = FontWeight.Medium,
                                fontSize = 11.sp,
                            )
                        }
                    }
                }
                Text(
                    if (active) "До ${state.maxDevices} ${ruDevices(state.maxDevices)}." else "Подписка не активна.",
                    modifier = Modifier.padding(top = 8.dp),
                    color = Color(0xFFEEE7FA),
                    fontFamily = Onest,
                    fontSize = 14.sp,
                )
                Row(
                    Modifier.fillMaxWidth().padding(top = 24.dp),
                    verticalAlignment = Alignment.Bottom,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text("Ваша подписка до", color = Color(0xFFE0D3F2), fontFamily = Onest, fontSize = 12.sp)
                        Text(
                            state.subscriptionUntil?.let { formatSubscriptionDate(it) } ?: "Нет активной подписки",
                            modifier = Modifier.padding(top = 5.dp),
                            color = White,
                            fontFamily = Onest,
                            fontWeight = FontWeight.SemiBold,
                            fontSize = 16.sp,
                        )
                    }
                    if (days != null && active) {
                        Row(verticalAlignment = Alignment.Bottom) {
                            Text(
                                days.toString(),
                                color = White,
                                fontFamily = Onest,
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 30.sp,
                                lineHeight = 35.sp,
                            )
                            Text(
                                " ${ruDays(days)}",
                                color = Color(0xFFF1E1E7),
                                fontFamily = Onest,
                                fontSize = 12.sp,
                                modifier = Modifier.padding(bottom = 4.dp),
                            )
                        }
                    }
                }
                Box(
                    Modifier
                        .padding(top = 14.dp)
                        .fillMaxWidth()
                        .height(3.dp)
                        .clip(RoundedCornerShape(3.dp))
                        .background(Color.White.copy(alpha = 0.18f)),
                ) {
                    Box(
                        Modifier
                            .fillMaxWidth(subscriptionProgress(state.subscriptionUntil, state.plan))
                            .height(3.dp)
                            .background(Color.White.copy(alpha = 0.8f)),
                    )
                }
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(top = 12.dp)
                        .height(48.dp)
                        .clickable {
                            info = AccountInfo.Subscription
                        },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "Управлять подпиской",
                        modifier = Modifier.weight(1f),
                        color = White,
                        fontFamily = Onest,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 14.sp,
                    )
                    IconArrowUpRight(White, Modifier.size(15.dp))
                }
            }
        }
        Row(
            Modifier.fillMaxWidth().padding(top = 16.dp, bottom = 24.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceEvenly,
        ) {
            Stat(Icon = { IconGlobe(Color(0xFFBBBAC4), Modifier.size(18.dp)) }, value = state.endpoints.size.toString(), label = "локаций")
            Box(Modifier.size(width = 1.dp, height = 19.dp).background(Color(0xFF24242C)))
            Stat(
                Icon = { IconPhone(Color(0xFFBBBAC4), Modifier.size(18.dp)) },
                value = "${state.devicesUsed}/${state.maxDevices}",
                label = "устройств",
            )
        }
        Text(
            "ВАШ АККАУНТ",
            color = Dim,
            fontFamily = Onest,
            fontWeight = FontWeight.SemiBold,
            fontSize = 11.sp,
            letterSpacing = 1.2.sp,
            modifier = Modifier.padding(bottom = 12.dp),
        )
        Column(
            Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(20.dp))
                .background(BgSurface)
                .padding(horizontal = 16.dp),
        ) {
            MenuRow("Мои устройства", "${state.devicesUsed} из ${state.maxDevices}", showDivider = true, icon = { IconPhone(Color(0xFFBCBCC5), Modifier.size(18.dp)) }) {
                info = AccountInfo.Devices
            }
            MenuRow("Приватность", "", showDivider = true, icon = { IconFingerprint(Color(0xFFBCBCC5), Modifier.size(18.dp)) }) {
                info = AccountInfo.Privacy
            }
            MenuRow("Помощь и поддержка", "", showDivider = false, icon = { IconHelp(Color(0xFFBCBCC5), Modifier.size(18.dp)) }) {
                info = AccountInfo.Support
            }
        }
        Row(
            Modifier
                .fillMaxWidth()
                .height(52.dp)
                .clickable { info = AccountInfo.Logout },
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconLogout(TextMuted, Modifier.size(15.dp))
            Text("Выйти из аккаунта", modifier = Modifier.padding(start = 8.dp), color = TextMuted, fontFamily = Onest, fontSize = 14.sp)
        }
    }

    val title = when (info) {
        AccountInfo.Subscription -> "Ваша подписка"
        AccountInfo.Devices -> "Ваши устройства"
        AccountInfo.Support -> "Поможем разобраться"
        AccountInfo.Privacy -> "Приватность"
        AccountInfo.About -> "О Focus VPN"
        AccountInfo.Logout -> "Выйти из аккаунта?"
        null -> ""
    }
    FocusSheet(visible = info != null, title = title, onClose = { info = null }) {
        when (info) {
            AccountInfo.Subscription -> {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconSparkles(Ink, Modifier.size(25.dp))
                    Text(
                        state.plan.ifBlank { "Focus VPN" },
                        modifier = Modifier.padding(start = 10.dp),
                        color = Ink,
                        fontFamily = Onest,
                        fontWeight = FontWeight.Bold,
                        fontSize = 23.sp,
                    )
                }
                MutedCopy(
                    if (active) {
                        "Подписка до ${state.subscriptionUntil?.let { formatSubscriptionDate(it) } ?: "—"}. " +
                            "До ${state.maxDevices} ${ruDevices(state.maxDevices)}."
                    } else {
                        "Сейчас нет активной подписки. Оформить её можно в Telegram-боте."
                    },
                )
                FocusAction(text = "Открыть Telegram", onClick = openBot, showArrow = false)
            }
            AccountInfo.Devices -> {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconPhone(Ink, Modifier.size(26.dp))
                    Column(Modifier.padding(start = 16.dp)) {
                        Text("Это устройство", color = Ink, fontFamily = Onest, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                        Text(
                            "${state.devicesUsed} из ${state.maxDevices}",
                            color = TextMuted,
                            fontFamily = Onest,
                            fontSize = 16.sp,
                        )
                    }
                }
                if (state.deviceLimitBlocked) {
                    MutedCopy("VPN уже привязан к другому устройству. Можно отвязать его и привязать этот телефон.")
                    FocusAction(
                        text = "Отвязать и привязать это",
                        onClick = onRebindDevice,
                        enabled = !state.busy,
                        showArrow = false,
                    )
                } else {
                    MutedCopy("В подписку входит ${state.maxDevices} ${ruDevices(state.maxDevices)}. Сейчас занято ${state.devicesUsed}.")
                }
                if (!state.error.isNullOrBlank()) {
                    Text(state.error, color = com.focusvpn.app.ui.theme.Danger, fontFamily = Onest, fontSize = 14.sp)
                }
            }
            AccountInfo.Privacy -> {
                IconFingerprint(Ink, Modifier.size(32.dp))
                MutedCopy("Приложение не ведёт историю посещённых сайтов.")
                MutedCopy("Российские сайты и приложения идут с IP телефона. Зарубежный трафик проходит через VPN.")
            }
            AccountInfo.Support -> {
                Text("Как подключиться?", color = Ink, fontFamily = Onest, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                MutedCopy("Откройте «Подключение», выберите локацию и нажмите кнопку питания.")
                Text("Где получить код?", color = Ink, fontFamily = Onest, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                MutedCopy("Код присылает Telegram-бот FocusVPN после входа.")
                Text("Почему часть сайтов открывается с моим IP?", color = Ink, fontFamily = Onest, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                MutedCopy("Российские сайты и приложения специально идут мимо туннеля, с адреса телефона.")
                FocusAction(text = "Написать в бот", onClick = openBot, showArrow = false)
            }
            AccountInfo.About -> {
                FocusBrand()
                MutedCopy("Версия ${BuildConfig.VERSION_NAME}")
                MutedCopy("Подключение, локации и подписка берутся из вашего аккаунта FocusVPN.")
            }
            AccountInfo.Logout -> {
                MutedCopy("Соединение будет остановлено. Войти снова можно кодом из бота или через Telegram.")
                FocusAction(text = "Выйти", onClick = onLogout, showArrow = false)
                FocusAction(text = "Остаться", onClick = { info = null }, secondary = true, showArrow = false)
            }
            null -> Unit
        }
    }
}

@Composable
private fun Stat(Icon: @Composable () -> Unit, value: String, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon()
        Text(
            value,
            modifier = Modifier.padding(start = 8.dp),
            color = Ink,
            fontFamily = Onest,
            fontWeight = FontWeight.Bold,
            fontSize = 16.sp,
        )
        Text(
            " $label",
            color = TextMuted,
            fontFamily = Onest,
            fontSize = 13.sp,
        )
    }
}

@Composable
private fun MenuRow(
    label: String,
    hint: String,
    showDivider: Boolean,
    icon: @Composable () -> Unit,
    onClick: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .height(56.dp)
            .clickable(onClick = onClick),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        icon()
        Text(
            label,
            modifier = Modifier.weight(1f).padding(start = 12.dp),
            color = Ink,
            fontFamily = Onest,
            fontWeight = FontWeight.Medium,
            fontSize = 14.sp,
        )
        if (hint.isNotBlank()) {
            Text(hint, color = Dim, fontFamily = Onest, fontSize = 12.sp, modifier = Modifier.padding(end = 6.dp))
        }
        IconChevron(Dim, Modifier.size(15.dp))
    }
    if (showDivider) {
        Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0xFF2A2A30)))
    }
}

private fun ruDevices(n: Int): String {
    val abs = kotlin.math.abs(n) % 100
    val tail = abs % 10
    return when {
        abs in 11..14 -> "устройств"
        tail == 1 -> "устройство"
        tail in 2..4 -> "устройства"
        else -> "устройств"
    }
}
