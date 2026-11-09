package com.focusvpn.app.auth

import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri

fun installedTelegramPackages(pm: PackageManager): Set<String> =
    TELEGRAM_PACKAGES.mapNotNull { pkg ->
        try {
            pm.getPackageInfo(pkg, 0)
            pkg
        } catch (_: PackageManager.NameNotFoundException) {
            null
        }
    }.toSet()

fun telegramViewIntent(pm: PackageManager, deepLink: String): Intent {
    val target = telegramTarget(deepLink, installedTelegramPackages(pm))
    return Intent(Intent.ACTION_VIEW, Uri.parse(target.uri)).apply {
        target.packageName?.let { setPackage(it) }
    }
}
