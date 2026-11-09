package com.focusvpn.app.ui.design

import com.focusvpn.app.data.EndpointDTO
import java.time.LocalDate
import java.time.format.DateTimeParseException
import java.time.temporal.ChronoUnit

private val europeCountries = setOf(
    "NL", "DE", "FI", "CH", "GB", "UK", "FR", "SE", "PL", "AT", "BE", "CZ", "DK", "EE",
    "ES", "IE", "IT", "LT", "LU", "LV", "NO", "PT", "RO", "SK",
)
private val asiaCountries = setOf("JP", "SG", "KR", "HK", "TW", "IN", "ID", "TH", "VN", "AE")
private val americaCountries = setOf("US", "CA", "BR", "MX", "AR")

private val countryNames = mapOf(
    "NL" to "Нидерланды",
    "DE" to "Германия",
    "RO" to "Румыния",
    "FI" to "Финляндия",
    "CH" to "Швейцария",
    "GB" to "Великобритания",
    "UK" to "Великобритания",
    "US" to "США",
    "JP" to "Япония",
    "SG" to "Сингапур",
    "FR" to "Франция",
    "SE" to "Швеция",
    "PL" to "Польша",
    "CA" to "Канада",
)

fun countryLabel(code: String): String {
    val key = code.trim().uppercase()
    if (key.isEmpty()) return "Сервер"
    return countryNames[key] ?: code.trim()
}

/** Maps API region strings such as `eu-central` / `us-east` onto the mock's chips. */
fun regionBucket(region: String, country: String): String {
    val r = region.trim().lowercase()
    val c = country.trim().uppercase()
    return when {
        r == "europe" || r == "eu" || r.startsWith("eu-") || r.startsWith("eu_") || c in europeCountries -> "europe"
        r == "asia" || r == "apac" || r.startsWith("ap-") || r.startsWith("as-") || c in asiaCountries -> "asia"
        r == "america" || r == "americas" || r == "us" || r == "na" || r == "sa" ||
            r.startsWith("us-") || r.startsWith("na-") || r.startsWith("sa-") || c in americaCountries -> "america"
        else -> ""
    }
}

fun endpointMatches(endpoint: EndpointDTO, query: String, bucket: String): Boolean {
    if (bucket != "all" && regionBucket(endpoint.region, endpoint.country) != bucket) return false
    val q = query.trim().lowercase()
    if (q.isEmpty()) return true
    val hay = listOf(
        endpoint.country,
        countryLabel(endpoint.country),
        endpoint.region,
        endpoint.node,
        endpoint.protocol,
    ).joinToString(" ").lowercase()
    return hay.contains(q)
}

fun parseIsoDate(iso: String): LocalDate? {
    val raw = iso.trim().take(10)
    if (raw.length < 10) return null
    return try {
        LocalDate.parse(raw)
    } catch (_: DateTimeParseException) {
        null
    }
}

fun daysUntil(iso: String, today: LocalDate = LocalDate.now()): Long? {
    val date = parseIsoDate(iso) ?: return null
    return ChronoUnit.DAYS.between(today, date)
}

/** Period length for the progress bar. Unknown codes stay a full bar. */
fun planPeriodDays(plan: String): Int? = when (plan.trim().lowercase()) {
    "week" -> 7
    "month" -> 30
    "quarter", "q3" -> 90
    else -> null
}

/** Share of the plan still left. 1 when the plan length is unknown, 0 when inactive. */
fun subscriptionProgress(endsAt: String?, plan: String, today: LocalDate = LocalDate.now()): Float {
    if (!subscriptionActive(endsAt, today)) return 0f
    val period = planPeriodDays(plan) ?: return 1f
    val left = daysUntil(endsAt.orEmpty(), today) ?: return 1f
    if (period <= 0) return 1f
    return (left.toFloat() / period.toFloat()).coerceIn(0f, 1f)
}

fun subscriptionActive(iso: String?, today: LocalDate = LocalDate.now()): Boolean {
    if (iso.isNullOrBlank()) return false
    val days = daysUntil(iso, today) ?: return false
    return days >= 0
}

private val months = listOf(
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

fun formatSubscriptionDate(iso: String): String? {
    val date = parseIsoDate(iso) ?: return null
    return "${date.dayOfMonth} ${months[date.monthValue - 1]} ${date.year}"
}

fun ruDays(n: Long): String {
    val abs = kotlin.math.abs(n) % 100
    val tail = abs % 10
    return when {
        abs in 11..14 -> "дней"
        tail == 1L -> "день"
        tail in 2..4 -> "дня"
        else -> "дней"
    }
}

fun formatDuration(seconds: Long): String {
    val safe = seconds.coerceAtLeast(0)
    val h = safe / 3600
    val m = (safe / 60) % 60
    val s = safe % 60
    return "%02d:%02d:%02d".format(h, m, s)
}
