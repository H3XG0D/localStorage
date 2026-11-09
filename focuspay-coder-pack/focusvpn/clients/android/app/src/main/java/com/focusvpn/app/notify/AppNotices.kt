package com.focusvpn.app.notify

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.focusvpn.app.MainActivity
import com.focusvpn.app.R

/** Posts a [Notice] once. A missing permission does not consume the key. */
object AppNotices {
    private const val PREFS = "focusvpn_notices"
    private const val KEY_ASKED = "asked"
    private const val KEY_SEEN = "seen"
    private const val ALERT_CHANNEL = "focusvpn-alerts"

    fun alreadyAsked(context: Context): Boolean =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY_ASKED, false)

    fun markAsked(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_ASKED, true)
            .apply()
    }

    fun granted(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < 33) return true
        return ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
    }

    fun deliver(context: Context, notice: Notice?) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val seen = prefs.getStringSet(KEY_SEEN, emptySet()).orEmpty()
        val fresh = pendingNotice(notice, seen) ?: return
        if (!granted(context)) return
        show(context, fresh)
        prefs.edit().putStringSet(KEY_SEEN, seen + fresh.key).apply()
    }

    private fun show(context: Context, notice: Notice) {
        val nm = context.getSystemService(NotificationManager::class.java) ?: return
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(
                NotificationChannel(
                    ALERT_CHANNEL,
                    context.getString(R.string.vpn_channel_alerts),
                    NotificationManager.IMPORTANCE_DEFAULT,
                ),
            )
        }
        val open = PendingIntent.getActivity(
            context,
            notice.key.hashCode(),
            Intent(context, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(context, ALERT_CHANNEL)
            .setContentTitle(notice.title)
            .setContentText(notice.text)
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        nm.notify(notice.key.hashCode(), notification)
    }
}
