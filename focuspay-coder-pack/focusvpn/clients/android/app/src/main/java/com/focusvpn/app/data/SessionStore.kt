package com.focusvpn.app.data

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Persistent session (tokens + device keys). Keystore-backed master key. */
class SessionStore(context: Context) {
    private val prefs = EncryptedSharedPreferences.create(
        context,
        "myvpn_session",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun load(): Session? {
        val api = prefs.getString(K_API, null) ?: return null
        val email = prefs.getString(K_EMAIL, null) ?: return null
        val access = prefs.getString(K_ACCESS, null) ?: return null
        val refresh = prefs.getString(K_REFRESH, null) ?: return null
        return Session(
            apiBase = api,
            email = email,
            accessToken = access,
            refreshToken = refresh,
            deviceId = prefs.getString(K_DEVICE_ID, null),
            deviceToken = prefs.getString(K_DEVICE_TOKEN, null),
            privateKeyB64 = prefs.getString(K_PRIV, null),
            publicKeyB64 = prefs.getString(K_PUB, null),
            selectedNode = prefs.getString(K_NODE, null),
            accessExpiresAtMs = prefs.getLong(K_ACCESS_EXP, 0L).takeIf { it > 0L },
        )
    }

    fun save(s: Session) {
        prefs.edit()
            .putString(K_API, s.apiBase)
            .putString(K_EMAIL, s.email)
            .putString(K_ACCESS, s.accessToken)
            .putString(K_REFRESH, s.refreshToken)
            .putString(K_DEVICE_ID, s.deviceId)
            .putString(K_DEVICE_TOKEN, s.deviceToken)
            .putString(K_PRIV, s.privateKeyB64)
            .putString(K_PUB, s.publicKeyB64)
            .putString(K_NODE, s.selectedNode)
            .putLong(K_ACCESS_EXP, s.accessExpiresAtMs ?: 0L)
            .apply()
    }

    fun clear() {
        prefs.edit().clear().apply()
    }

    companion object {
        private const val K_API = "api_base"
        private const val K_EMAIL = "email"
        private const val K_ACCESS = "access"
        private const val K_REFRESH = "refresh"
        private const val K_DEVICE_ID = "device_id"
        private const val K_DEVICE_TOKEN = "device_token"
        private const val K_PRIV = "priv"
        private const val K_PUB = "pub"
        private const val K_NODE = "node"
        private const val K_ACCESS_EXP = "access_exp"
    }
}
