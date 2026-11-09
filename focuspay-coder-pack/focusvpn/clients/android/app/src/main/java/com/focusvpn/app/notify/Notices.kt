package com.focusvpn.app.notify

import com.focusvpn.app.data.EndpointDTO
import com.focusvpn.app.ui.design.countryLabel
import com.focusvpn.app.ui.design.daysUntil
import com.focusvpn.app.ui.design.formatSubscriptionDate
import java.time.LocalDate

/** One shade event. [key] is remembered so the same fact is not posted twice. */
data class Notice(
    val key: String,
    val title: String,
    val text: String,
)

const val STATUS_CONNECTING = "Подключаемся…"
const val AUTO_PLACE = "Авто — самый быстрый"

/** Android 13+ runtime prompt. Asked at most once, and never when already granted. */
fun shouldAskNotificationAccess(sdkInt: Int, granted: Boolean, alreadyAsked: Boolean): Boolean =
    sdkInt >= 33 && !granted && !alreadyAsked

fun updateNotice(versionCode: Int, versionName: String): Notice {
    val name = versionName.trim().ifBlank { versionCode.toString() }
    return Notice(
        key = "update:$versionCode",
        title = "Доступно обновление",
        text = name,
    )
}

/**
 * Tomorrow or today: the subscription is ending. Any later visit: it has ended.
 * Earlier than one day ahead stays quiet. Null when there is no date.
 */
fun subscriptionNotice(endsAt: String?, today: LocalDate = LocalDate.now()): Notice? {
    val raw = endsAt?.trim().orEmpty()
    if (raw.isEmpty()) return null
    val days = daysUntil(raw, today) ?: return null
    val date = raw.take(10)
    val pretty = formatSubscriptionDate(raw) ?: date
    return when {
        days == 0L || days == 1L -> Notice("sub:$date:ending", "Подписка заканчивается", pretty)
        days < 0L -> Notice("sub:$date:ended", "Подписка закончилась", pretty)
        else -> null
    }
}

/** Null when there is nothing new to post. */
fun pendingNotice(notice: Notice?, seen: Set<String>): Notice? {
    if (notice == null || notice.key.isBlank() || notice.key in seen) return null
    return notice
}

/** «Германия · DE1» from the server list. A blank country keeps the node id. */
fun nodePlaceLabel(node: String, country: String): String {
    val name = country.trim().takeIf { it.isNotEmpty() }?.let { countryLabel(it) }
    return listOfNotNull(name, node.trim().takeIf { it.isNotEmpty() })
        .joinToString(" · ")
        .ifBlank { AUTO_PLACE }
}

fun placeLabels(endpoints: List<EndpointDTO>): Map<String, String> =
    endpoints.mapNotNull { ep ->
        val node = ep.node.takeIf { it.isNotBlank() } ?: return@mapNotNull null
        node to nodePlaceLabel(node, ep.country)
    }.toMap()

/**
 * Connected line. A known country wins. Otherwise an unselected location
 * reads as the automatic pick, and a chosen node falls back to its id.
 */
fun connectedStatusText(node: String, labels: Map<String, String>, auto: Boolean): String {
    val known = labels[node]?.takeIf { it.isNotBlank() }
    val place = known ?: if (auto) AUTO_PLACE else node.trim().ifBlank { AUTO_PLACE }
    return "Подключено · $place"
}
