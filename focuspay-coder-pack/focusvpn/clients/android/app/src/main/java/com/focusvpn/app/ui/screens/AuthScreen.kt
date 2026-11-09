package com.focusvpn.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.focusvpn.app.ui.design.FocusAction
import com.focusvpn.app.ui.design.FocusBrand
import com.focusvpn.app.ui.design.FocusMesh
import com.focusvpn.app.ui.design.FocusSheet
import com.focusvpn.app.ui.design.scaledClick
import com.focusvpn.app.ui.design.IconKey
import com.focusvpn.app.ui.design.IconSend
import com.focusvpn.app.ui.design.IconShield
import com.focusvpn.app.ui.design.MeshKind
import com.focusvpn.app.ui.design.MutedCopy
import com.focusvpn.app.ui.theme.BgBase
import com.focusvpn.app.ui.theme.BgInput
import com.focusvpn.app.ui.theme.Danger
import com.focusvpn.app.ui.theme.Dim
import com.focusvpn.app.ui.theme.Ink
import com.focusvpn.app.ui.theme.Line
import com.focusvpn.app.ui.theme.Onest
import com.focusvpn.app.ui.theme.Raised
import com.focusvpn.app.ui.theme.TextMuted

@Composable
fun AuthScreen(
    busy: Boolean,
    awaitingTelegram: Boolean,
    error: String?,
    onTelegramLogin: () -> Unit,
    onCodeLogin: (String) -> Unit,
) {
    var sheet by rememberSaveable { mutableStateOf<String?>(null) }
    var code by rememberSaveable { mutableStateOf("") }
    Column(
        Modifier
            .fillMaxSize()
            .background(BgBase)
            .verticalScroll(rememberScrollState())
            .navigationBarsPadding(),
    ) {
        Box(Modifier.fillMaxWidth().height(316.dp)) {
            FocusMesh(MeshKind.Login, Modifier.fillMaxSize())
            Box(Modifier.fillMaxSize().background(BgBase.copy(alpha = 0.12f)))
            FocusBrand(
                small = true,
                modifier = Modifier.statusBarsPadding().padding(horizontal = 26.dp, vertical = 26.dp),
            )
        }
        Column(
            Modifier
                .fillMaxWidth()
                .offsetBody()
                .clip(RoundedCornerShape(topStart = 34.dp, topEnd = 34.dp))
                .background(BgBase)
                .padding(horizontal = 24.dp)
                .padding(top = 32.dp, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(28.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(
                    "Добро пожаловать\nв Focus VPN",
                    color = Ink,
                    fontFamily = Onest,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 32.sp,
                    lineHeight = 40.sp,
                    letterSpacing = (-1).sp,
                )
                Text(
                    "Войдите по коду доступа\nили через свой Telegram.",
                    color = TextMuted,
                    fontFamily = Onest,
                    fontSize = 16.sp,
                    lineHeight = 24.sp,
                )
            }
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                FocusAction(text = "Войти по коду", onClick = { sheet = "code" }, enabled = !busy)
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Box(Modifier.weight(1f).height(1.dp).background(Line))
                    Text("или", color = Dim, fontFamily = Onest, fontSize = 13.sp)
                    Box(Modifier.weight(1f).height(1.dp).background(Line))
                }
                Row(
                    Modifier
                        .fillMaxWidth()
                        .height(56.dp)
                        .scaledClick(enabled = !busy, onClick = onTelegramLogin)
                        .clip(RoundedCornerShape(18.dp))
                        .background(ColorTelegram)
                        .border(1.dp, ColorTelegramBorder, RoundedCornerShape(18.dp)),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center,
                ) {
                    IconSend(Ink, Modifier.size(20.dp))
                    Text(
                        when {
                            busy && sheet != "code" -> "Открываем Telegram…"
                            awaitingTelegram && sheet != "code" -> "Ждём подтверждение…"
                            else -> "Войти через Telegram"
                        },
                        modifier = Modifier.padding(start = 10.dp),
                        color = Ink,
                        fontFamily = Onest,
                        fontWeight = FontWeight.Medium,
                        fontSize = 16.sp,
                    )
                }
                if (!error.isNullOrBlank() && sheet != "code") {
                    Text(error, color = Danger, fontFamily = Onest, fontSize = 14.sp, lineHeight = 21.sp)
                }
            }
            Text(
                buildAnnotatedString {
                    append("Продолжая, вы принимаете условия сервиса\nи ")
                    withStyle(SpanStyle(color = Color(0xFF9B9BA5))) {
                        append("политику конфиденциальности")
                    }
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { sheet = "privacy" }
                    .padding(vertical = 12.dp),
                color = Dim,
                fontFamily = Onest,
                fontSize = 12.sp,
                lineHeight = 18.sp,
                textAlign = TextAlign.Center,
            )
        }
    }
    FocusSheet(
        visible = sheet == "code",
        title = "Ваш код доступа",
        onClose = { sheet = null },
    ) {
        Box(
            Modifier.size(52.dp).clip(RoundedCornerShape(16.dp)).background(Raised),
            contentAlignment = Alignment.Center,
        ) {
            IconKey(Ink, Modifier.size(24.dp))
        }
        MutedCopy("Введите код из бота FocusVPN. Это буквы и цифры, которые бот присылает после входа.")
        Text("Код доступа", color = Ink, fontFamily = Onest, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
        BasicTextField(
            value = code,
            onValueChange = { code = it.uppercase().filter { ch -> ch.isLetterOrDigit() }.take(8) },
            modifier = Modifier
                .fillMaxWidth()
                .height(62.dp)
                .clip(RoundedCornerShape(16.dp))
                .background(BgInput)
                .border(
                    1.dp,
                    if (!error.isNullOrBlank()) Danger else ColorCodeBorder,
                    RoundedCornerShape(16.dp),
                )
                .padding(horizontal = 12.dp),
            textStyle = androidx.compose.ui.text.TextStyle(
                color = Ink,
                fontFamily = Onest,
                fontWeight = FontWeight.Medium,
                fontSize = 25.sp,
                letterSpacing = 6.sp,
                textAlign = TextAlign.Center,
            ),
            keyboardOptions = KeyboardOptions(
                capitalization = KeyboardCapitalization.Characters,
                keyboardType = KeyboardType.Ascii,
            ),
            singleLine = true,
            cursorBrush = SolidColor(Ink),
            decorationBox = { inner ->
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    if (code.isEmpty()) {
                        Text("КОД", color = Dim, fontFamily = Onest, fontSize = 25.sp, letterSpacing = 6.sp)
                    }
                    inner()
                }
            },
        )
        if (!error.isNullOrBlank()) {
            Text(error, color = Danger, fontFamily = Onest, fontSize = 14.sp, lineHeight = 21.sp)
        }
        FocusAction(
            text = if (busy) "Проверяем код…" else "Войти в Focus",
            onClick = { onCodeLogin(code.trim()) },
            enabled = !busy && code.length >= 6,
        )
    }
    FocusSheet(
        visible = sheet == "privacy",
        title = "О конфиденциальности",
        onClose = { sheet = null },
    ) {
        IconShield(Ink, Modifier.size(30.dp))
        MutedCopy("Код входа проверяется на сервере FocusVPN. История сайтов приложением не собирается.")
        MutedCopy("Российские сайты и приложения идут с IP телефона. Зарубежный трафик проходит через VPN.")
        FocusAction(text = "Понятно", onClick = { sheet = null }, secondary = true, showArrow = false)
    }
}

private val ColorTelegram = androidx.compose.ui.graphics.Color(0xFF1B1B20)
private val ColorTelegramBorder = androidx.compose.ui.graphics.Color(0xFF36363D)
private val ColorCodeBorder = androidx.compose.ui.graphics.Color(0xFF474750)

private fun Modifier.offsetBody(): Modifier = offset(y = (-38).dp)
