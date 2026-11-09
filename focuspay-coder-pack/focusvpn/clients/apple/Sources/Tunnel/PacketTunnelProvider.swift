import NetworkExtension

/// P3-M4c Packet Tunnel: NE settings from ConfigParts + AmneziaWG userspace IO.
/// Backend: amneziawg-apple WireGuardKitGo (`wgTurnOn`) when linked; otherwise NE-only.
final class PacketTunnelProvider: NEPacketTunnelProvider {
    private let engine = AmneziaTunnelEngine()

    override func startTunnel(options: [String: NSObject]?, completionHandler: @escaping (Error?) -> Void) {
        let proto = protocolConfiguration as? NETunnelProviderProtocol
        let providerCfg = proto?.providerConfiguration ?? [:]
        guard let cfg = TunnelConfig.fromProviderConfiguration(providerCfg) else {
            completionHandler(
                NSError(
                    domain: "FocusVPN",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "missing tunnel config in providerConfiguration"]
                )
            )
            return
        }
        guard cfg.jc > 0, cfg.jmin > 0, cfg.jmax >= cfg.jmin,
              !cfg.h1.isEmpty, !cfg.h2.isEmpty, !cfg.h3.isEmpty, !cfg.h4.isEmpty else {
            completionHandler(
                NSError(
                    domain: "FocusVPN",
                    code: 2,
                    userInfo: [NSLocalizedDescriptionKey: "invalid Jc/Jmin/Jmax or H1–H4 in tunnel config"]
                )
            )
            return
        }

        let remote = cfg.endpointHost.isEmpty ? "127.0.0.1" : cfg.endpointHost
        let settings = NEPacketTunnelNetworkSettings(tunnelRemoteAddress: remote)
        settings.mtu = NSNumber(value: max(1280, min(cfg.mtu, 9000)))

        let mask = TunnelConfig.ipv4SubnetMask(prefix: cfg.addressPrefix)
        let ipv4 = NEIPv4Settings(addresses: [cfg.addressHost], subnetMasks: [mask])
        ipv4.includedRoutes = Self.ipv4Routes(from: cfg.allowedIps)
        settings.ipv4Settings = ipv4
        settings.dnsSettings = NEDNSSettings(servers: cfg.dns)

        setTunnelNetworkSettings(settings) { [weak self] error in
            if let error {
                completionHandler(error)
                return
            }
            // utun exists after settings apply; start userspace AmneziaWG when go bridge linked.
            self?.engine.start(cfg: cfg)
            NSLog(
                "FocusVPN tunnel started endpoint=%@ jc=%d native=%d",
                cfg.endpoint, cfg.jc, self?.engine.nativeActive == true ? 1 : 0
            )
            completionHandler(nil)
        }
    }

    override func stopTunnel(with reason: NEProviderStopReason, completionHandler: @escaping () -> Void) {
        engine.stop()
        NSLog("FocusVPN tunnel stopped reason=%d", reason.rawValue)
        completionHandler()
    }

    private static func ipv4Routes(from allowedIps: [String]) -> [NEIPv4Route] {
        var routes: [NEIPv4Route] = []
        var hasDefault = false
        for cidr in allowedIps {
            if cidr.contains(":") { continue }
            let parts = cidr.split(separator: "/", maxSplits: 1)
            let host = String(parts[0])
            let prefix = parts.count == 2 ? (Int(parts[1]) ?? 32) : 32
            if host == "0.0.0.0" && prefix == 0 {
                routes.append(NEIPv4Route.default())
                hasDefault = true
                continue
            }
            let mask = TunnelConfig.ipv4SubnetMask(prefix: prefix)
            routes.append(NEIPv4Route(destinationAddress: host, subnetMask: mask))
        }
        if !hasDefault {
            routes.append(NEIPv4Route.default())
        }
        return routes
    }
}
