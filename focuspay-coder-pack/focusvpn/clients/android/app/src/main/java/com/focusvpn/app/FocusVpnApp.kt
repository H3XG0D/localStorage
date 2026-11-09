package com.focusvpn.app

import android.app.Application
import com.focusvpn.app.data.ControlPlaneClient
import com.focusvpn.app.data.SessionStore

class FocusVpnApp : Application() {
    lateinit var sessions: SessionStore
        private set
    lateinit var api: ControlPlaneClient
        private set

    override fun onCreate() {
        super.onCreate()
        sessions = SessionStore(this)
        val base = sessions.load()?.apiBase ?: BuildConfig.DEFAULT_API_BASE
        api = ControlPlaneClient(base)
    }
}
