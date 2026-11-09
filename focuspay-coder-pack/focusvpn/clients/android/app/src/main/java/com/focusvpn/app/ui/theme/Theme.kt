package com.focusvpn.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.focusvpn.app.R

// Monochrome UI from the Focus VPN mock. Color lives in the mesh, not the chrome.
val BgBase = Color(0xFF0A0A0E)
val Canvas = Color(0xFF050507)
val BgSurface = Color(0xFF15151C)
val BgCard = Color(0xFF1E1E27)
val Raised = BgCard
val BgInput = Color(0xFF111115)
val Border = Color(0xFF24242C)
val Line = Border
val TextPrimary = Color(0xFFF7F7FB)
val Ink = TextPrimary
val TextMuted = Color(0xFFA2A2AE)
val TextLabel = Color(0xFF878793)
val Dim = TextLabel
val White = Color(0xFFFAFAFC)
val Accent = White
val AccentSoft = Color(0xFF2E2E38)
val Danger = Color(0xFFFF6B76)
val DangerSoft = Color(0xFF3A2226)
val Ok = White
val OkSoft = Color(0xFF1E1E27)
val Amber = Color(0xFFB2B2BC)
val AmberSoft = Color(0xFF1E1E27)

val Onest = FontFamily(
    Font(R.font.onest_regular, FontWeight.Normal),
    Font(R.font.onest_medium, FontWeight.Medium),
    Font(R.font.onest_semibold, FontWeight.SemiBold),
    Font(R.font.onest_bold, FontWeight.Bold),
    Font(R.font.onest_extrabold, FontWeight.ExtraBold),
)

private val Scheme = darkColorScheme(
    primary = White,
    onPrimary = BgBase,
    background = BgBase,
    onBackground = TextPrimary,
    surface = BgSurface,
    onSurface = TextPrimary,
    error = Danger,
    outline = Border,
)

val FocusTypography = Typography(
    headlineLarge = TextStyle(
        fontFamily = Onest,
        fontSize = 32.sp,
        fontWeight = FontWeight.SemiBold,
        color = TextPrimary,
        letterSpacing = (-0.8).sp,
        lineHeight = 40.sp,
    ),
    headlineMedium = TextStyle(
        fontFamily = Onest,
        fontSize = 22.sp,
        fontWeight = FontWeight.Bold,
        color = TextPrimary,
    ),
    titleMedium = TextStyle(
        fontFamily = Onest,
        fontSize = 16.sp,
        fontWeight = FontWeight.SemiBold,
        color = TextPrimary,
    ),
    bodyLarge = TextStyle(
        fontFamily = Onest,
        fontSize = 16.sp,
        fontWeight = FontWeight.Normal,
        color = TextPrimary,
        lineHeight = 24.sp,
    ),
    bodyMedium = TextStyle(
        fontFamily = Onest,
        fontSize = 14.sp,
        fontWeight = FontWeight.Normal,
        color = TextMuted,
        lineHeight = 20.sp,
    ),
    labelSmall = TextStyle(
        fontFamily = Onest,
        fontSize = 11.sp,
        fontWeight = FontWeight.SemiBold,
        color = TextMuted,
        letterSpacing = 1.sp,
    ),
)

@Composable
fun FocusVpnTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = Scheme, typography = FocusTypography, content = content)
}
