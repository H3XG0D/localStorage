package com.focusvpn.app.auth

/**
 * Official client first, then the side-by-side package, then Telegram X.
 * An explicit package skips the system "Open with" dialog.
 */
val TELEGRAM_PACKAGES: List<String> = listOf(
    "org.telegram.messenger",
    "org.telegram.messenger.web",
    "org.thunderdog.challegram",
)

data class TelegramTarget(
    val uri: String,
    val packageName: String?,
)

fun telegramTarget(deepLink: String, installedPackages: Set<String>): TelegramTarget {
    if (!isTelegramHttpLink(deepLink)) {
        return TelegramTarget(deepLink, null)
    }
    val pkg = TELEGRAM_PACKAGES.firstOrNull { it in installedPackages }
    return TelegramTarget(deepLink, pkg)
}

fun isTelegramHttpLink(deepLink: String): Boolean {
    val host = try {
        java.net.URI(deepLink).host
    } catch (_: Exception) {
        return false
    }?.lowercase() ?: return false
    return host == "t.me" || host == "telegram.me"
}
