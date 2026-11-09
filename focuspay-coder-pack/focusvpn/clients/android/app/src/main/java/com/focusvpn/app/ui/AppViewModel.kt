package com.focusvpn.app.ui

import android.content.ActivityNotFoundException
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.focusvpn.app.BuildConfig
import com.focusvpn.app.FocusVpnApp
import com.focusvpn.app.data.AccessSession
import com.focusvpn.app.data.ApiException
import com.focusvpn.app.data.AuthResponse
import com.focusvpn.app.data.ControlPlaneClient
import com.focusvpn.app.data.EndpointDTO
import com.focusvpn.app.data.Session
import com.focusvpn.app.data.SessionRevokedException
import com.focusvpn.app.data.accessExpiresAtMs
import com.focusvpn.app.notify.AppNotices
import com.focusvpn.app.notify.placeLabels
import com.focusvpn.app.notify.subscriptionNotice
import com.focusvpn.app.notify.updateNotice
import com.focusvpn.app.update.RemoteAppVersion
import com.focusvpn.app.update.fetchVersionManifest
import com.focusvpn.app.update.offerFromManifest
import com.focusvpn.app.vpn.ActiveTunnel
import com.focusvpn.app.vpn.IfaceCounters
import com.focusvpn.app.vpn.Probe
import com.focusvpn.app.vpn.TcpPing
import com.focusvpn.app.vpn.TunnelEvents
import com.focusvpn.app.vpn.XrayClientConfig
import com.focusvpn.app.vpn.probes
import com.focusvpn.app.vpn.readTunCounters
import com.focusvpn.app.vpn.throughputMbps
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.isActive
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class UiState(
    val loggedIn: Boolean = false,
    val busy: Boolean = false,
    val awaitingTelegram: Boolean = false,
    val error: String? = null,
    val apiBase: String = "",
    val email: String = "",
    val subscriptionUntil: String? = null,
    val devicesUsed: Int = 0,
    val maxDevices: Int = 1,
    val plan: String = "",
    val endpoints: List<EndpointDTO> = emptyList(),
    val selectedNode: String? = null,
    val connected: Boolean = false,
    val connecting: Boolean = false,
    val endpointHint: String? = null,
    val lastJc: Int? = null,
    val connectionId: String? = null,
    val deviceLimitBlocked: Boolean = false,
    val updateOffer: RemoteAppVersion? = null,
    val updateChecked: Boolean = false,
    val pingMs: Map<String, Int> = emptyMap(),
    val downMbps: Double? = null,
    val upMbps: Double? = null,
)

class AppViewModel(
    private val app: FocusVpnApp,
) : ViewModel() {
    private val _state = MutableStateFlow(UiState(apiBase = BuildConfig.DEFAULT_API_BASE))
    val state: StateFlow<UiState> = _state

    @Volatile private var session: Session? = app.sessions.load()
    @Volatile private var accessGate: AccessSession? = null
    private var connectJob: Job? = null
    private var connectGen = 0
    private var telegramJob: Job? = null
    private var telegramGen = 0

    /** While true, a service Idle from the tunnel we just stopped must not clear the new attempt. */
    private var reconnecting = false

    init {
        session?.let { s ->
            accessGate = openGate(s)
            app.api.setApiBase(s.apiBase)
            _state.update {
                it.copy(
                    loggedIn = true,
                    apiBase = s.apiBase,
                    email = s.email,
                    selectedNode = s.selectedNode,
                )
            }
            refreshServers()
            refreshAccount()
        }
        viewModelScope.launch {
            TunnelEvents.status.collect { status ->
                when (status) {
                    TunnelEvents.Status.Idle -> if (!reconnecting) _state.update {
                        it.copy(connected = false, connecting = false, busy = false)
                    }
                    TunnelEvents.Status.Connecting -> _state.update {
                        it.copy(connected = false, connecting = true, busy = true, error = null)
                    }
                    is TunnelEvents.Status.Up -> _state.update {
                        it.copy(
                            connected = true,
                            connecting = false,
                            busy = false,
                            error = null,
                            endpointHint = status.node,
                        )
                    }
                    is TunnelEvents.Status.Down -> _state.update {
                        it.copy(connected = false, connecting = false, busy = false, error = status.message)
                    }
                }
            }
        }
        watchLink()
    }

    fun loginWithTelegram(openUrl: (String) -> Unit, onOk: () -> Unit) {
        val gen = ++telegramGen
        telegramJob?.cancel()
        telegramJob = viewModelScope.launch {
            fun current() = gen == telegramGen
            _state.update { it.copy(busy = true, awaitingTelegram = false, error = null) }
            try {
                val start = withContext(Dispatchers.IO) {
                    app.api.setApiBase(_state.value.apiBase.ifBlank { BuildConfig.DEFAULT_API_BASE })
                    app.api.telegramLoginStart()
                }
                if (!current()) return@launch
                openUrl(start.deepLink)
                if (!current()) return@launch
                // The system chooser can sit on this screen. A disabled button
                // stays on "Открываем Telegram…" until the poll times out if the
                // user never picks an app.
                _state.update { it.copy(busy = false, awaitingTelegram = true) }
                var auth: AuthResponse? = null
                for (attempt in 0 until POLL_ATTEMPTS) {
                    delay(POLL_INTERVAL_MS)
                    if (!current()) return@launch
                    val polled = withContext(Dispatchers.IO) { app.api.telegramLoginWait(start.waitToken) }
                    if (!current()) return@launch
                    if (polled != null) {
                        auth = polled
                        break
                    }
                }
                if (!current()) return@launch
                val a = auth ?: throw IllegalStateException("Время ожидания Telegram истекло")
                finishAuth(a, onOk)
            } catch (e: CancellationException) {
                throw e
            } catch (e: ActivityNotFoundException) {
                if (!current()) return@launch
                _state.update {
                    it.copy(busy = false, awaitingTelegram = false, error = "Не удалось открыть Telegram")
                }
            } catch (e: Exception) {
                if (!current()) return@launch
                _state.update {
                    it.copy(busy = false, awaitingTelegram = false, error = e.message ?: "telegram login failed")
                }
            }
        }
    }

    fun loginWithCode(code: String, onOk: () -> Unit) {
        telegramGen++
        telegramJob?.cancel()
        viewModelScope.launch {
            _state.update { it.copy(busy = true, awaitingTelegram = false, error = null) }
            try {
                val auth = withContext(Dispatchers.IO) {
                    app.api.setApiBase(_state.value.apiBase.ifBlank { BuildConfig.DEFAULT_API_BASE })
                    app.api.telegramLoginCode(code.trim())
                }
                finishAuth(auth, onOk)
            } catch (e: Exception) {
                _state.update { it.copy(busy = false, error = e.message ?: "invalid code") }
            }
        }
    }

    private suspend fun finishAuth(auth: AuthResponse, onOk: () -> Unit) {
        val apiBase = _state.value.apiBase.ifBlank { BuildConfig.DEFAULT_API_BASE }.trimEnd('/')
        val s = withContext(Dispatchers.IO) {
            app.api.setApiBase(apiBase)
            ensureDeviceSession(apiBase, auth)
        }
        app.sessions.save(s)
        accessGate?.close()
        accessGate = openGate(s)
        _state.update {
            it.copy(
                loggedIn = true,
                busy = false,
                awaitingTelegram = false,
                email = auth.user.email,
                apiBase = apiBase,
                deviceLimitBlocked = false,
            )
        }
        refreshServers()
        refreshAccount()
        onOk()
    }

    private fun ensureDeviceSession(apiBase: String, auth: AuthResponse): Session {
        val access = auth.tokens.accessToken
        val (priv, pub) = ControlPlaneClient.keygen()
        try {
            val dev = app.api.createDevice(access, "android", pub)
            return issuedSession(apiBase, auth, dev.device.id, dev.deviceToken, priv, pub)
        } catch (e: ApiException) {
            if (e.code != 409) throw e
            revokeActiveDevices(access)
            val dev = app.api.createDevice(access, "android", pub)
            return issuedSession(apiBase, auth, dev.device.id, dev.deviceToken, priv, pub)
        }
    }

    private fun issuedSession(
        apiBase: String,
        auth: AuthResponse,
        deviceId: String,
        deviceToken: String,
        priv: String,
        pub: String,
    ): Session = Session(
        apiBase = apiBase,
        email = auth.user.email,
        accessToken = auth.tokens.accessToken,
        refreshToken = auth.tokens.refreshToken,
        deviceId = deviceId,
        deviceToken = deviceToken,
        privateKeyB64 = priv,
        publicKeyB64 = pub,
        accessExpiresAtMs = auth.tokens.accessExpiresAtMs(),
    )

    private fun openGate(s: Session): AccessSession {
        session = s
        return AccessSession(
            initial = s,
            refresh = { token -> app.api.refresh(token) },
            onSession = { next ->
                session = next
                app.sessions.save(next)
            },
        )
    }

    /**
     * Runs [block] with a live access token, refreshing once when the JWT is
     * near expiry or the control plane rejects it. A dead refresh family logs out.
     */
    private fun <T> authed(block: (Session) -> T): T {
        val gate = accessGate
        if (gate == null) {
            sessionDied()
            throw SessionRevokedException(
                ApiException(401, """{"error":{"code":"invalid_token","message":"invalid token"}}"""),
            )
        }
        try {
            return gate.call(block)
        } catch (e: SessionRevokedException) {
            sessionDied()
            throw e
        }
    }

    private fun sessionDied() {
        val gate = accessGate
        accessGate = null
        gate?.close()
        telegramGen++
        telegramJob?.cancel()
        connectGen++
        ActiveTunnel.clear()
        session = null
        app.sessions.clear()
        _state.update {
            UiState(
                apiBase = BuildConfig.DEFAULT_API_BASE,
                updateOffer = it.updateOffer,
                updateChecked = it.updateChecked,
            )
        }
    }

    // GET /v1/devices also lists revoked devices; only active ones count toward the limit.
    private fun revokeActiveDevices(access: String) {
        app.api.listDevices(access).devices
            .filter { it.status == "active" }
            .forEach { app.api.deleteDevice(access, it.id) }
    }

    fun rebindThisDevice(onDone: () -> Unit) {
        if (accessGate == null) return
        viewModelScope.launch {
            _state.update { it.copy(busy = true, error = null) }
            try {
                withContext(Dispatchers.IO) {
                    val listed = authed { app.api.listDevices(it.accessToken) }
                    listed.devices.filter { it.status == "active" }.forEach { dev ->
                        authed { app.api.deleteDevice(it.accessToken, dev.id) }
                    }
                    val (priv, pub) = ControlPlaneClient.keygen()
                    val created = authed { app.api.createDevice(it.accessToken, "android", pub) }
                    accessGate?.update {
                        it.copy(
                            deviceId = created.device.id,
                            deviceToken = created.deviceToken,
                            privateKeyB64 = priv,
                            publicKeyB64 = pub,
                        )
                    }
                }
                if (session == null) return@launch
                _state.update { it.copy(busy = false, deviceLimitBlocked = false) }
                refreshAccount()
                onDone()
            } catch (_: SessionRevokedException) {
            } catch (e: Exception) {
                if (session == null) return@launch
                _state.update { it.copy(busy = false, error = e.message) }
            }
        }
    }

    fun refreshAccount() {
        if (session == null) return
        viewModelScope.launch {
            try {
                val me = withContext(Dispatchers.IO) { authed { app.api.me(it.accessToken) } }
                if (session == null) return@launch
                val until = me.subscription?.endsAt?.take(10)
                _state.update {
                    it.copy(
                        subscriptionUntil = until,
                        plan = me.subscription?.plan.orEmpty(),
                        maxDevices = me.subscription?.maxDevices ?: 1,
                        devicesUsed = me.subscription?.devicesUsed ?: it.devicesUsed,
                    )
                }
                AppNotices.deliver(app, subscriptionNotice(until))
            } catch (_: SessionRevokedException) {
            } catch (_: Exception) {
            }
        }
    }

    fun refreshServers() {
        if (session == null) return
        viewModelScope.launch {
            _state.update { it.copy(busy = true, error = null) }
            try {
                val list = withContext(Dispatchers.IO) {
                    authed { app.api.listServers(it.accessToken) }
                }
                val node = session?.selectedNode
                if (session == null) return@launch
                _state.update {
                    it.copy(
                        busy = false,
                        endpoints = list.endpoints,
                        selectedNode = node?.takeIf { it.isNotBlank() },
                    )
                }
            } catch (_: SessionRevokedException) {
            } catch (e: Exception) {
                if (session == null) return@launch
                _state.update { it.copy(busy = false, error = e.message) }
            }
        }
    }

    fun selectNode(node: String?) {
        val gate = accessGate ?: return
        val picked = node?.takeIf { it.isNotBlank() }
        try {
            gate.update { it.copy(selectedNode = picked) }
        } catch (_: SessionRevokedException) {
            return
        }
        if (session == null) return
        _state.update { it.copy(selectedNode = picked) }
    }

    /** True when a live tunnel is on a different node than the one just picked. */
    fun shouldRebuildTunnel(node: String?): Boolean {
        if (!_state.value.connected && !_state.value.connecting) return false
        val picked = node?.takeIf { it.isNotBlank() }
        val live = _state.value.endpointHint?.takeIf { it.isNotBlank() }
            ?: _state.value.selectedNode?.takeIf { it.isNotBlank() }
        return picked != live
    }

    fun connect(onReady: () -> Unit) {
        if (session?.deviceId == null || session?.deviceToken == null) return
        if (_state.value.connecting || _state.value.connected) return
        val gen = ++connectGen
        _state.update { it.copy(busy = true, connecting = true, error = null, deviceLimitBlocked = false) }
        launchProvision(gen, onReady)
    }

    /**
     * Stop the current tunnel, drop its allocation, and open one on [session]'s node.
     * [stopService] must run before the new profile is written so the old engine can exit.
     */
    fun reconnect(stopService: () -> Unit, startService: () -> Unit) {
        val s = session ?: return
        if (s.deviceId == null || s.deviceToken == null) return
        reconnecting = true
        val gen = ++connectGen
        connectJob?.cancel()
        connectJob = null
        val cid = _state.value.connectionId
        _state.update {
            it.copy(
                busy = true,
                connecting = true,
                connected = false,
                endpointHint = null,
                error = null,
                deviceLimitBlocked = false,
            )
        }
        stopService()
        connectJob = viewModelScope.launch {
            try {
                if (cid != null) {
                    withContext(Dispatchers.IO) {
                        runCatching { authed { app.api.disconnect(it.accessToken, cid) } }
                    }
                }
                if (!isActive || gen != connectGen) {
                    reconnecting = false
                    return@launch
                }
                if (establish(gen) == null) {
                    reconnecting = false
                    return@launch
                }
                reconnecting = false
                TunnelEvents.update(TunnelEvents.Status.Connecting)
                startService()
            } catch (e: CancellationException) {
                reconnecting = false
                throw e
            } catch (_: SessionRevokedException) {
                reconnecting = false
            } catch (e: ApiException) {
                failProvision(e)
            } catch (e: Exception) {
                failProvision(e)
            }
        }
    }

    fun checkForUpdate() {
        viewModelScope.launch {
            val body = withContext(Dispatchers.IO) { fetchVersionManifest() }
            val offer = body?.let { offerFromManifest(it, BuildConfig.VERSION_CODE) }
            _state.update { it.copy(updateOffer = offer, updateChecked = true) }
            if (offer != null) {
                AppNotices.deliver(app, updateNotice(offer.versionCode, offer.versionName))
            }
        }
    }

    fun dismissUpdate() {
        _state.update { it.copy(updateOffer = null) }
    }

    /** Retry shade events that arrived before the user allowed notifications. */
    fun publishPendingNotices() {
        val offer = _state.value.updateOffer
        if (offer != null) {
            AppNotices.deliver(app, updateNotice(offer.versionCode, offer.versionName))
        }
        AppNotices.deliver(app, subscriptionNotice(_state.value.subscriptionUntil))
    }

    private fun launchProvision(gen: Int, onReady: () -> Unit) {
        connectJob = viewModelScope.launch {
            try {
                if (establish(gen) == null) return@launch
                TunnelEvents.update(TunnelEvents.Status.Connecting)
                onReady()
            } catch (e: CancellationException) {
                throw e
            } catch (_: SessionRevokedException) {
            } catch (e: ApiException) {
                failProvision(e)
            } catch (e: Exception) {
                failProvision(e)
            }
        }
    }

    private suspend fun establish(gen: Int): String? {
        val connId = try {
            withContext(Dispatchers.IO) {
                val opened = authed { s ->
                    val deviceId = s.deviceId ?: return@authed null
                    val deviceToken = s.deviceToken ?: return@authed null
                    val conn = app.api.createConnection(
                        s.accessToken,
                        deviceId,
                        preferredNode = s.selectedNode,
                    )
                    Triple(conn, deviceToken, s.selectedNode.isNullOrBlank())
                } ?: return@withContext null
                val (conn, deviceToken, autoPlace) = opened
                val parts = app.api.getConfig(conn.configId, deviceToken).parts
                ActiveTunnel.profile = XrayClientConfig.fromParts(parts)
                ActiveTunnel.placeLabels = placeLabels(_state.value.endpoints)
                ActiveTunnel.autoPlace = autoPlace
                conn.connection.id
            }
        } catch (_: SessionRevokedException) {
            return null
        } ?: return null
        if (gen != connectGen) {
            ActiveTunnel.clear()
            runCatching {
                withContext(Dispatchers.IO) { authed { app.api.disconnect(it.accessToken, connId) } }
            }
            return null
        }
        _state.update { it.copy(connectionId = connId, lastJc = null) }
        return connId
    }

    private fun failProvision(e: Exception) {
        reconnecting = false
        ActiveTunnel.clear()
        val blocked = e is ApiException && e.code == 409 && e.errorCode == "too_many_devices"
        _state.update {
            it.copy(
                busy = false,
                connecting = false,
                error = e.message,
                connected = false,
                deviceLimitBlocked = blocked,
            )
        }
    }

    fun disconnect() {
        connectGen++
        connectJob?.cancel()
        connectJob = null
        val cid = _state.value.connectionId
        viewModelScope.launch {
            try {
                if (session != null && cid != null) {
                    withContext(Dispatchers.IO) { authed { app.api.disconnect(it.accessToken, cid) } }
                }
            } catch (_: Exception) {
            }
            ActiveTunnel.clear()
            TunnelEvents.update(TunnelEvents.Status.Idle)
            _state.update {
                it.copy(
                    connected = false,
                    connecting = false,
                    busy = false,
                    connectionId = null,
                    lastJc = null,
                    endpointHint = null,
                )
            }
        }
    }

    fun logout() {
        connectJob?.cancel()
        connectJob = null
        sessionDied()
    }

    /**
     * Ping is a TCP handshake to the node (the app itself is outside the tunnel).
     * Speed is the tun interface counter, so it stays empty until the tunnel exists.
     */
    private fun watchLink() {
        viewModelScope.launch {
            var previous: IfaceCounters? = null
            var previousAt = 0L
            var tick = 0
            while (isActive) {
                val snap = _state.value
                val active = snap.loggedIn && (snap.connected || snap.connecting)
                val wantPing = snap.loggedIn && tick % 4 == 0
                tick++
                val targets = if (wantPing) {
                    val listed = snap.endpoints.map { Probe(it.node, it.host, it.port) }
                    val fallback = ActiveTunnel.profile?.servers.orEmpty().map {
                        Probe(it.node, it.address, it.port)
                    }
                    probes(listed, fallback)
                } else {
                    emptyList()
                }
                val baseline = previous
                val baselineAt = previousAt
                val readAt = System.currentTimeMillis()
                val counters = if (active) withContext(Dispatchers.IO) { readTunCounters() } else null
                val speed = if (counters != null && baseline != null) {
                    throughputMbps(baseline, counters, readAt - baselineAt)
                } else {
                    null
                }
                if (active && counters != null) {
                    previous = counters
                    previousAt = readAt
                } else {
                    previous = null
                }
                if (wantPing && targets.isNotEmpty()) {
                    val round = targets
                    launch(Dispatchers.IO) {
                        val fresh = coroutineScope {
                            round.map { target ->
                                async {
                                    TcpPing.millis(target.host, target.port, 1_200)?.let { target.node to it }
                                }
                            }.awaitAll().filterNotNull().toMap()
                        }
                        if (!isActive) return@launch
                        _state.update { cur ->
                            if (!cur.loggedIn) {
                                cur
                            } else {
                                cur.copy(
                                    pingMs = cur.pingMs.filterKeys { node -> round.any { it.node == node } } + fresh,
                                )
                            }
                        }
                    }
                }
                if (!isActive) return@launch
                _state.update { cur ->
                    val tunnel = cur.loggedIn && (cur.connected || cur.connecting)
                    cur.copy(
                        downMbps = if (tunnel) speed?.down else null,
                        upMbps = if (tunnel) speed?.up else null,
                    )
                }
                delay(1_000)
            }
        }
    }

    companion object {
        private const val POLL_ATTEMPTS = 60
        private const val POLL_INTERVAL_MS = 2000L

        fun factory(app: FocusVpnApp) = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T = AppViewModel(app) as T
        }
    }
}
