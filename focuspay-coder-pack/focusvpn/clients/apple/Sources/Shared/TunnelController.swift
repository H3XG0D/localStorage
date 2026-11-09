// TunnelController.swift — NETunnelProviderManager (wireguard-apple pattern)
import Combine
import Foundation
import NetworkExtension

@MainActor
final class TunnelController: ObservableObject {
    static let providerBundleId = "com.focusvpn.app.tunnel"

    @Published private(set) var status: NEVPNStatus = .invalid

    private var manager: NETunnelProviderManager?
    private var observer: NSObjectProtocol?

    init() {
        observer = NotificationCenter.default.addObserver(
            forName: .NEVPNStatusDidChange,
            object: nil,
            queue: .main
        ) { [weak self] note in
            Task { @MainActor in
                if let conn = note.object as? NEVPNConnection {
                    self?.status = conn.status
                }
            }
        }
    }

    deinit {
        if let observer { NotificationCenter.default.removeObserver(observer) }
    }

    func prepare() async throws {
        let managers = try await NETunnelProviderManager.loadAllFromPreferences()
        if let existing = managers.first {
            manager = existing
        } else {
            let m = NETunnelProviderManager()
            let proto = NETunnelProviderProtocol()
            proto.providerBundleIdentifier = Self.providerBundleId
            proto.serverAddress = "FocusVPN"
            m.protocolConfiguration = proto
            m.localizedDescription = "FocusVPN"
            m.isEnabled = true
            try await m.saveToPreferences()
            try await m.loadFromPreferences()
            manager = m
        }
        status = manager?.connection.status ?? .invalid
    }

    func start(config: TunnelConfig) async throws {
        try await prepare()
        guard let manager else { throw APIError.message("tunnel manager missing") }
        if let proto = manager.protocolConfiguration as? NETunnelProviderProtocol {
            proto.serverAddress = config.endpointHost
            proto.providerConfiguration = config.asProviderConfiguration()
            manager.protocolConfiguration = proto
            manager.isEnabled = true
            try await manager.saveToPreferences()
            try await manager.loadFromPreferences()
        }
        try manager.connection.startVPNTunnel()
    }

    func stop() {
        manager?.connection.stopVPNTunnel()
    }
}
