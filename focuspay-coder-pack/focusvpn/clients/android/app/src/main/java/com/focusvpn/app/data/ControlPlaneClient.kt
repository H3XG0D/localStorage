package com.focusvpn.app.data

import com.focusvpn.app.crypto.X25519Keys
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.ConnectionPool
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.net.SocketTimeoutException
import java.util.concurrent.TimeUnit

/**
 * [errorCode] is the CP envelope `error.code` for branching; [message] is
 * user-facing Russian text, never the raw JSON body.
 */
class ApiException(val code: Int, val body: String) : Exception(humanize(code, body)) {
    val errorCode: String = parseErrorCode(body)

    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        private fun envelope(body: String) = runCatching {
            json.parseToJsonElement(body).jsonObject["error"]?.jsonObject
        }.getOrNull()

        fun parseErrorCode(body: String): String =
            envelope(body)?.get("code")?.jsonPrimitive?.contentOrNull.orEmpty()

        fun humanize(code: Int, body: String): String = when (parseErrorCode(body)) {
            "too_many_devices" -> "Достигнут лимит устройств для тарифа"
            "invalid_code", "expired" -> "Код неверный или устарел — запросите новый в боте"
            "invalid_token", "expired_token", "unauthorized" -> "Сессия истекла — войдите снова"
            "subscription_expired" -> "Подписка не активна — продлите в Telegram-боте"
            "rate_limited" -> "Слишком много попыток — подождите минуту"
            "node_unavailable" -> "Сервер недоступен — выберите другую локацию"
            else -> envelope(body)?.get("message")?.jsonPrimitive?.contentOrNull
                ?: "Ошибка сервера ($code)"
        }
    }
}

/** Control Plane HTTP client (mirrors AppCore / apitypes). */
class ControlPlaneClient(
    private var apiBase: String,
    private val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        // Do not reuse sockets. A mobile NAT drops an idle HTTP/2 connection
        // without a RST; the next call then sits there until "Read timed out"
        // and the control plane never sees it. A handshake per call is cheap.
        .connectionPool(ConnectionPool(0, 1, TimeUnit.SECONDS))
        .pingInterval(15, TimeUnit.SECONDS)
        .build(),
) {
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }
    private val jsonMedia = "application/json; charset=utf-8".toMediaType()

    fun setApiBase(base: String) {
        apiBase = base.trimEnd('/')
    }

    fun register(email: String, password: String): AuthResponse =
        post("/v1/auth/register", mapOf("email" to email, "password" to password))

    fun login(email: String, password: String): AuthResponse =
        post("/v1/auth/login", mapOf("email" to email, "password" to password))

    /** Rotates the refresh token. Bearer is the refresh token, not the access JWT (API.md §2). */
    fun refresh(refreshToken: String): Tokens =
        post("/v1/auth/refresh", emptyMap(), refreshToken)

    fun listServers(access: String): ServersResponse =
        get("/v1/servers", access)

    fun createDevice(access: String, name: String, publicKeyB64: String): CreateDeviceResponse =
        post(
            "/v1/devices",
            mapOf(
                "name" to name,
                "platform" to "android",
                "public_key" to publicKeyB64,
            ),
            access,
        )

    fun createConnection(
        access: String,
        deviceId: String,
        preferredNode: String? = null,
    ): CreateConnectionResponse {
        val body = mutableMapOf(
            "device_id" to deviceId,
            "protocol" to "vless",
        )
        if (!preferredNode.isNullOrBlank()) {
            body["preferred_node"] = preferredNode
        }
        return post("/v1/connections", body, access)
    }
    fun getConfig(configId: String, deviceToken: String): ConfigPartsResponse {
        val req = Request.Builder()
            .url("$apiBase/v1/configurations/$configId")
            .header("X-Device-Token", deviceToken)
            .get()
            .build()
        return execute(req)
    }

    fun telegramLoginStart(): TelegramStartResponse =
        post("/v1/auth/telegram/start", emptyMap())

    fun telegramLoginWait(waitToken: String): AuthResponse? {
        val req = Request.Builder()
            .url("$apiBase/v1/auth/telegram/wait?wait_token=${java.net.URLEncoder.encode(waitToken, "UTF-8")}")
            .get()
            .build()
        http.newCall(req).execute().use { resp ->
            val raw = resp.body?.string().orEmpty()
            if (resp.code == 202) return null
            if (!resp.isSuccessful) throw ApiException(resp.code, raw)
            return json.decodeFromString(raw)
        }
    }

    fun telegramLoginCode(code: String): AuthResponse =
        post("/v1/auth/telegram/code", mapOf("code" to code))

    fun me(access: String): MeResponse = get("/v1/me", access)

    fun listDevices(access: String): DeviceListResponse = get("/v1/devices", access)

    fun deleteDevice(access: String, deviceId: String) {
        val req = Request.Builder()
            .url("$apiBase/v1/devices/$deviceId")
            .header("Authorization", "Bearer $access")
            .delete()
            .build()
        http.newCall(req).execute().use { resp ->
            // 404 = already revoked, which is the outcome the caller wants.
            if (!resp.isSuccessful && resp.code != 204 && resp.code != 404) {
                throw ApiException(resp.code, resp.body?.string().orEmpty())
            }
        }
    }

    fun disconnect(access: String, connectionId: String) {
        val req = Request.Builder()
            .url("$apiBase/v1/connections/$connectionId")
            .header("Authorization", "Bearer $access")
            .delete()
            .build()
        http.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful && resp.code != 204) {
                throw ApiException(resp.code, resp.body?.string().orEmpty())
            }
        }
    }

    private inline fun <reified T> get(path: String, access: String): T {
        val req = Request.Builder()
            .url("$apiBase$path")
            .header("Authorization", "Bearer $access")
            .get()
            .build()
        return execute(req)
    }

    private inline fun <reified T> post(
        path: String,
        body: Map<String, String> = emptyMap(),
        access: String? = null,
    ): T {
        val payload = buildJsonObject {
            body.forEach { (k, v) -> put(k, v) }
        }.toString()
        val b = Request.Builder()
            .url("$apiBase$path")
            .post(payload.toRequestBody(jsonMedia))
        if (access != null) b.header("Authorization", "Bearer $access")
        return execute(b.build())
    }

    private inline fun <reified T> execute(req: Request): T = json.decodeFromString(exchange(req))

    /**
     * One fresh attempt after a read timeout. OkHttp will not retry a POST once
     * the bytes have been written, but a dead socket still reports "Read timed out"
     * (Android) or "timeout" (Okio) and the server never sees the request.
     * Creating a connection is idempotent, and these responses are tiny, so a
     * timeout means the request did not land.
     */
    private fun exchange(req: Request): String {
        var last: IOException? = null
        for (attempt in 0..1) {
            try {
                http.newCall(req).execute().use { resp ->
                    val raw = resp.body?.string().orEmpty()
                    if (!resp.isSuccessful) throw ApiException(resp.code, raw)
                    return raw
                }
            } catch (e: ApiException) {
                throw e
            } catch (e: IOException) {
                last = e
                if (attempt == 0 && staleSocket(e)) {
                    http.connectionPool.evictAll()
                    continue
                }
                if (staleSocket(e)) throw quietTimeout(e)
                throw e
            }
        }
        throw quietTimeout(last ?: IOException("timeout"))
    }

    private fun staleSocket(e: IOException): Boolean {
        if (e is SocketTimeoutException) return true
        var cur: Throwable? = e
        while (cur != null) {
            val msg = cur.message.orEmpty()
            if (msg.contains("timed out", ignoreCase = true) ||
                msg.contains("timeout", ignoreCase = true) ||
                msg.contains("connection reset", ignoreCase = true) ||
                msg.contains("unexpected end of stream", ignoreCase = true)
            ) {
                return true
            }
            cur = cur.cause
        }
        return false
    }

    private fun quietTimeout(e: IOException): IOException =
        IOException("Сервер не ответил — проверьте интернет и нажмите ещё раз", e)

    companion object {
        /** X25519 keypair — public is derived from private (never random). */
        fun keygen(): Pair<String, String> = X25519Keys.generate()

    }
}
