package com.focusvpn.app.update

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

const val VERSION_MANIFEST_URL = "https://focuspay.org/vpn-version.json"

@Serializable
data class RemoteAppVersion(
    val versionCode: Int = 0,
    val versionName: String = "",
    val url: String = "",
)

private val json = Json { ignoreUnknownKeys = true }

fun isNewerVersion(remoteCode: Int, localCode: Int): Boolean = remoteCode > localCode

fun offerFromManifest(body: String, localCode: Int): RemoteAppVersion? {
    val remote = runCatching { json.decodeFromString<RemoteAppVersion>(body) }.getOrNull() ?: return null
    if (!isNewerVersion(remote.versionCode, localCode) || remote.url.isBlank()) return null
    return remote
}

/** Null when the file is missing or the network fails. Callers stay quiet. */
fun fetchVersionManifest(url: String = VERSION_MANIFEST_URL): String? {
    return try {
        val client = OkHttpClient.Builder()
            .connectTimeout(8, TimeUnit.SECONDS)
            .readTimeout(8, TimeUnit.SECONDS)
            .build()
        val req = Request.Builder().url(url).get().build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) return null
            resp.body?.string()
        }
    } catch (_: Exception) {
        null
    }
}
