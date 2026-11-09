import Foundation
import Combine

@MainActor
final class AppModel: ObservableObject {
    @Published var loggedIn = false
    @Published var busy = false
    @Published var error: String?
    @Published var apiBase = "http://127.0.0.1:18080"
    @Published var email = ""
    @Published var endpoints: [EndpointDTO] = []
    @Published var selectedNode: String?
    @Published var connected = false
    @Published var endpointHint: String?
    @Published var lastJc: Int?
    @Published var connectionId: String?

    private var session: Session?
    private var api = ControlPlaneClient(apiBase: "http://127.0.0.1:18080")
    let tunnel = TunnelController()

    init() {
        if let s = SessionStore.load() {
            session = s
            api.setApiBase(s.apiBase)
            apiBase = s.apiBase
            email = s.email
            selectedNode = s.selectedNode
            loggedIn = true
            Task { await refreshServers() }
        }
    }

    func login(email: String, password: String, apiBase: String) async {
        await auth(email: email, password: password, apiBase: apiBase, register: false)
    }

    func register(email: String, password: String, apiBase: String) async {
        await auth(email: email, password: password, apiBase: apiBase, register: true)
    }

    private func auth(email: String, password: String, apiBase: String, register: Bool) async {
        busy = true
        error = nil
        defer { busy = false }
        do {
            api.setApiBase(apiBase)
            let auth: AuthResponse
            if register {
                auth = try await api.register(email: email, password: password)
            } else {
                do {
                    auth = try await api.login(email: email, password: password)
                } catch {
                    auth = try await api.register(email: email, password: password)
                }
            }
            let keys = ControlPlaneClient.keygen()
            #if os(macOS)
            let platform = "macos"
            #else
            let platform = "ios"
            #endif
            let dev = try await api.createDevice(
                access: auth.tokens.accessToken,
                name: "apple",
                publicKeyB64: keys.pubB64,
                platform: platform
            )
            var s = Session(
                apiBase: apiBase,
                email: email,
                accessToken: auth.tokens.accessToken,
                refreshToken: auth.tokens.refreshToken,
                deviceId: dev.device.id,
                deviceToken: dev.deviceToken,
                privateKeyB64: keys.privB64,
                publicKeyB64: keys.pubB64,
                selectedNode: nil
            )
            while s.apiBase.hasSuffix("/") { s.apiBase.removeLast() }
            try SessionStore.save(s)
            session = s
            self.apiBase = s.apiBase
            self.email = email
            loggedIn = true
            await refreshServers()
        } catch {
            self.error = error.localizedDescription
        }
    }

    func refreshServers() async {
        guard let s = session else { return }
        busy = true
        error = nil
        defer { busy = false }
        do {
            let list = try await api.listServers(access: s.accessToken)
            endpoints = list.endpoints
            if selectedNode == nil {
                selectedNode = s.selectedNode ?? list.endpoints.first?.node
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    func selectNode(_ node: String) {
        guard var s = session else { return }
        s.selectedNode = node
        session = s
        try? SessionStore.save(s)
        selectedNode = node
    }

    func connect() async {
        guard let s = session, let deviceId = s.deviceId, let deviceToken = s.deviceToken,
              let priv = s.privateKeyB64 else { return }
        busy = true
        error = nil
        defer { busy = false }
        do {
            let conn = try await api.createConnection(
                access: s.accessToken,
                deviceId: deviceId,
                preferredNode: s.selectedNode
            )
            let cfgResp = try await api.getConfig(configId: conn.configId, deviceToken: deviceToken)
            let parts = ConfigPartsParse.partsDictionary(from: cfgResp)
            let tunnelCfg = try TunnelConfig.fromParts(parts, privateKeyB64: priv)
            connectionId = conn.connection.id
            endpointHint = tunnelCfg.endpoint
            lastJc = tunnelCfg.jc > 0 ? tunnelCfg.jc : nil
            try await tunnel.start(config: tunnelCfg)
            connected = true
        } catch {
            connected = false
            self.error = error.localizedDescription
        }
    }

    func disconnect() async {
        if let s = session, let cid = connectionId {
            try? await api.disconnect(access: s.accessToken, connectionId: cid)
        }
        tunnel.stop()
        connected = false
        connectionId = nil
    }

    func logout() {
        SessionStore.clear()
        session = nil
        loggedIn = false
        email = ""
        endpoints = []
        selectedNode = nil
        connected = false
        connectionId = nil
        apiBase = "http://127.0.0.1:18080"
    }
}
