package com.focusvpn.app.vpn

import android.net.VpnService
import android.util.Log
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import libXray.DialerController
import libXray.LibXray

/**
 * Runs Xray inside the app process via libXray (MIT). Xray-core itself is
 * MPL-2.0 and is not modified. Sockets Xray opens are protected so they do
 * not loop back into the TUN.
 */
class XrayTunnelEngine(private val vpn: VpnService) {
    @Volatile
    var lastError: String? = null
        private set

    private var worker: Thread? = null

    fun start(tunFd: Int, xrayJson: String) {
        stop()
        lastError = null
        val protect = Protector(vpn)
        LibXray.registerDialerController(protect)
        LibXray.registerListenerController(protect)
        LibXray.setDNS(protect, "1.1.1.1:53")
        val request = invokeRequest("runXray", buildJsonObject { put("xrayJson", xrayJson) }.toString())
        worker = Thread({
            val raw = LibXray.invoke(request)
            val err = XrayInvoke.error(raw)
            if (err != null) {
                lastError = err
                Log.e(TAG, "runXray: $err")
            }
        }, "focusvpn-xray")
        worker?.start()
    }

    fun waitUntilRunning(timeoutMs: Long, cancelled: () -> Boolean = { false }): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (cancelled() || worker?.isAlive == false) return false
            if (isRunning()) return true
            Thread.sleep(200)
        }
        return isRunning()
    }

    fun stop() {
        try {
            LibXray.invoke(invokeRequest("stopXray", "{}"))
        } catch (e: Exception) {
            Log.w(TAG, "stopXray", e)
        }
        worker?.join(3_000)
        worker = null
        try {
            LibXray.resetDNS()
        } catch (e: Exception) {
            Log.w(TAG, "resetDNS", e)
        }
    }

    private fun isRunning(): Boolean {
        return XrayInvoke.running(LibXray.invoke(invokeRequest("getXrayState", "{}")))
    }

    private fun invokeRequest(method: String, payloadJson: String) = buildJsonObject {
        put("apiVersion", 3)
        put("method", method)
        put("payload", kotlinx.serialization.json.Json.parseToJsonElement(payloadJson))
    }.toString()

    private class Protector(private val vpn: VpnService) : DialerController {
        override fun protectFd(fd: Long): Boolean = vpn.protect(fd.toInt())
    }

    companion object {
        private const val TAG = "FocusVPN/Xray"
    }
}

/** Parses a libXray Invoke envelope. No native code, so JVM tests can call it. */
object XrayInvoke {
    private val json = kotlinx.serialization.json.Json { ignoreUnknownKeys = true }

    fun error(raw: String?): String? {
        if (raw.isNullOrBlank()) return "пустой ответ Xray"
        return try {
            val root = json.parseToJsonElement(raw).jsonObject
            val ok = root["success"]?.jsonPrimitive?.content == "true"
            if (ok) null else root["error"]?.jsonPrimitive?.contentOrNull?.ifBlank { null } ?: "Xray не запустился"
        } catch (_: Exception) {
            "некорректный ответ Xray"
        }
    }

    fun running(raw: String?): Boolean = try {
        val root = json.parseToJsonElement(raw ?: return false).jsonObject
        root["success"]?.jsonPrimitive?.content == "true" &&
            root["data"]?.jsonObject?.get("running")?.jsonPrimitive?.content == "true"
    } catch (_: Exception) {
        false
    }
}
