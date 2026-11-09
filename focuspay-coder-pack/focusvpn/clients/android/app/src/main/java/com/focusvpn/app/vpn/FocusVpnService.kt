package com.focusvpn.app.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.util.Log
import androidx.core.app.NotificationCompat
import com.focusvpn.app.MainActivity
import com.focusvpn.app.R
import com.focusvpn.app.notify.STATUS_CONNECTING
import com.focusvpn.app.notify.connectedStatusText
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URL
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * VpnService + Xray TUN (libXray). Tries each server in the order the control
 * plane sent. "Connected" is reported only after a request through the tunnel
 * succeeds.
 *
 * All tun/engine work runs on one worker thread, so attempts never overlap.
 * Every connect/disconnect bumps [generation]; an attempt that sees a newer
 * generation stops quietly and leaves status reporting to the newer request.
 */
class FocusVpnService : VpnService() {
    private var tun: ParcelFileDescriptor? = null
    private var engine: XrayTunnelEngine? = null
    private val worker: ExecutorService = Executors.newSingleThreadExecutor { r -> Thread(r, "focusvpn-connect") }

    @Volatile
    private var generation = 0

    @Volatile
    private var lastStartId = 0

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        lastStartId = startId
        when (intent?.action) {
            ACTION_CONNECT -> connect()
            ACTION_DISCONNECT -> disconnect()
        }
        return START_NOT_STICKY
    }

    private fun connect() {
        val profile = ActiveTunnel.profile
        if (profile == null) {
            // startForegroundService obliges us to post a notification even when bailing out.
            startForeground(NOTIF_ID, buildNotification(STATUS_CONNECTING))
            ++generation
            TunnelEvents.update(TunnelEvents.Status.Down("нет профиля подключения"))
            worker.execute { teardown() }
            return
        }
        val gen = ++generation
        TunnelEvents.update(TunnelEvents.Status.Connecting)
        startForeground(NOTIF_ID, buildNotification(STATUS_CONNECTING))
        worker.execute {
            // A server switch can skip the previous disconnect's teardown once
            // this attempt bumps generation. Stop the old engine on this thread.
            releaseAttempt()
            val stale = { gen != generation }
            var failure = "не удалось подключиться"
            val directPrefixes = assets.open("ru-prefixes.txt").use { RuDirect.read(it) }
            for (server in profile.servers) {
                if (stale()) break
                try {
                    val established = openTun()
                    val json = XrayClientConfig.document(
                        server, profile.uuid, established.fd, directPrefixes = directPrefixes,
                    )
                    val eng = XrayTunnelEngine(this)
                    engine = eng
                    eng.start(established.fd, json)
                    if (!eng.waitUntilRunning(8_000, stale)) {
                        failure = eng.lastError ?: "Xray не запустился"
                        Log.w(TAG, "server ${server.node} ${server.transport}: $failure")
                        releaseAttempt()
                        continue
                    }
                    // The node-agent adds this UUID after the control plane returns,
                    // so the first probes can fail for a few seconds on a fresh connect.
                    if (!stale() && probeUntil(12_000, stale)) {
                        if (stale()) break
                        TunnelEvents.update(TunnelEvents.Status.Up(server.node))
                        showStatus(
                            connectedStatusText(server.node, ActiveTunnel.placeLabels, ActiveTunnel.autoPlace),
                        )
                        Log.i(TAG, "up ${server.node} ${server.transport}")
                        return@execute
                    }
                    failure = "сервер ${server.node} не ответил"
                    Log.w(TAG, failure)
                } catch (e: Exception) {
                    failure = e.message ?: failure
                    Log.e(TAG, "server ${server.node}", e)
                }
                releaseAttempt()
            }
            if (stale()) {
                releaseAttempt()
                return@execute
            }
            TunnelEvents.update(TunnelEvents.Status.Down(failure))
            teardown()
        }
    }

    private fun openTun(): ParcelFileDescriptor {
        releaseTun()
        val builder = Builder()
            .setSession("FocusVPN")
            .setMtu(1400)
            .addAddress(TUN_ADDRESS, 32)
            .addAddress(TUN_ADDRESS_V6, 128)
            .addDnsServer("1.1.1.1")
            .addRoute("0.0.0.0", 0)
            .addRoute("::", 0)
        if (Build.VERSION.SDK_INT >= 29) {
            builder.setMetered(false)
        }
        builder.setBlocking(true)
        val established = builder.establish() ?: error("VpnService.establish вернул null")
        tun = established
        return established
    }

    private fun probeUntil(timeoutMs: Long, cancelled: () -> Boolean): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (cancelled()) return false
            if (probe()) return true
            Thread.sleep(400)
        }
        return false
    }

    /**
     * Android excludes the VPN app from its own TUN, so a direct request from this
     * process succeeds on the phone's own network and used to report "connected"
     * while every other app had no DNS. The SOCKS inbound is inside Xray, so this
     * request only succeeds when VLESS itself does.
     */
    private fun probe(): Boolean {
        val proxy = Proxy(Proxy.Type.SOCKS, InetSocketAddress("127.0.0.1", XrayClientConfig.SOCKS_PORT))
        val conn = (URL(PROBE_URL).openConnection(proxy) as HttpURLConnection).apply {
            connectTimeout = 4_000
            readTimeout = 4_000
            instanceFollowRedirects = false
            requestMethod = "GET"
        }
        return try {
            val code = conn.responseCode
            code in 200..399
        } catch (e: Exception) {
            Log.w(TAG, "probe", e)
            false
        } finally {
            conn.disconnect()
        }
    }

    private fun disconnect() {
        val gen = ++generation
        TunnelEvents.update(TunnelEvents.Status.Idle)
        worker.execute {
            if (gen == generation) teardown()
        }
    }

    private fun releaseAttempt() {
        engine?.stop()
        engine = null
        releaseTun()
    }

    private fun releaseTun() {
        tun?.close()
        tun = null
    }

    private fun teardown() {
        releaseAttempt()
        // Leave ActiveTunnel.profile alone. A switch writes the next profile
        // before CONNECT, and a late teardown must not erase it.
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelfResult(lastStartId)
    }

    /** Another VPN app took over, or the user revoked consent in settings. */
    override fun onRevoke() {
        ++generation
        TunnelEvents.update(TunnelEvents.Status.Down("VPN отключён системой"))
        worker.execute { teardown() }
    }

    override fun onDestroy() {
        ++generation
        worker.shutdownNow()
        engine?.stop()
        releaseTun()
        ActiveTunnel.clear()
        if (TunnelEvents.status.value !is TunnelEvents.Status.Idle &&
            TunnelEvents.status.value !is TunnelEvents.Status.Down
        ) {
            TunnelEvents.update(TunnelEvents.Status.Down("VPN остановлен"))
        }
        super.onDestroy()
    }

    private fun showStatus(text: String) {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIF_ID, buildNotification(text))
    }

    private fun buildNotification(text: String): Notification {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL, getString(R.string.vpn_channel_status), NotificationManager.IMPORTANCE_LOW),
            )
        }
        val pi = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL)
            .setContentTitle(getString(R.string.vpn_notification_title))
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setContentIntent(pi)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    companion object {
        const val ACTION_CONNECT = "com.focusvpn.app.CONNECT"
        const val ACTION_DISCONNECT = "com.focusvpn.app.DISCONNECT"
        private const val CHANNEL = "focusvpn-status"
        private const val NOTIF_ID = 42
        private const val TAG = "FocusVPN/Service"
        private const val TUN_ADDRESS = "10.77.0.2"
        private const val TUN_ADDRESS_V6 = "fd00:7777::2"
        private const val PROBE_URL = "https://www.gstatic.com/generate_204"
    }
}
