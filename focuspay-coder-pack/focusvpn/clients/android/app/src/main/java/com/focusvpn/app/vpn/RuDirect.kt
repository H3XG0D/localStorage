package com.focusvpn.app.vpn

import java.io.File
import java.io.InputStream

/**
 * Russian destinations leave the phone on its own IP.
 *
 * TSPU and Russian services ban a VPN address after they see it talking to
 * them. Domestic apps (MAX, Yandex Delivery, banks) also refuse a foreign exit.
 * Suffixes cover names that are not under .ru. Prefixes are a RIPE snapshot
 * of resources registered to RU — see assets/ru-prefixes.txt.
 */
internal object RuDirect {
    val domainSuffixes: List<String> = listOf(
        "ru",
        "su",
        "xn--p1ai",
        "moscow",
        "tatar",
        "yandex.net",
        "yandex.com",
        "yandex.cloud",
        "yastatic.net",
        "yandexcloud.net",
        "vk.com",
        "vk.me",
        "userapi.com",
        "vkuser.net",
        "vk-portal.net",
        "mycdn.me",
        "2gis.com",
        "avito.st",
        "wbstatic.net",
        "ozonusercontent.com",
        "sberbank.com",
    )

    private val privateCidrs: List<String> = listOf(
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )

    fun domainRules(): List<String> = domainSuffixes.map { "domain:$it" }

    fun ipRules(countryPrefixes: List<String> = prefixes): List<String> = privateCidrs + countryPrefixes

    fun matches(host: String): Boolean {
        val name = host.trim().trim('.').lowercase()
        if (name.isEmpty()) return false
        return domainSuffixes.any { suffix -> name == suffix || name.endsWith(".$suffix") }
    }

    fun read(stream: InputStream): List<String> = stream.bufferedReader().use { reader ->
        reader.lineSequence()
            .map { it.substringBefore('#').trim() }
            .filter { it.isNotEmpty() }
            .toList()
    }

    val prefixes: List<String> by lazy { read(openSnapshot()) }

    private fun openSnapshot(): InputStream {
        RuDirect::class.java.getResourceAsStream("/ru-prefixes.txt")?.let { return it }
        val candidates = listOf(
            File("src/main/assets/ru-prefixes.txt"),
            File("app/src/main/assets/ru-prefixes.txt"),
            File("clients/android/app/src/main/assets/ru-prefixes.txt"),
        )
        val file = candidates.firstOrNull { it.isFile }
            ?: error("ru-prefixes.txt is missing (run scripts/refresh-ru-prefixes.py)")
        return file.inputStream()
    }
}
