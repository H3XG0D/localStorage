// AwgConfig.swift — AmneziaWG UAPI + awg-quick (matches clients/shared/tunnel; P4-M8 H/S/I)
import Foundation

enum AwgConfigError: Error, LocalizedError {
    case message(String)
    var errorDescription: String? {
        switch self {
        case .message(let m): return m
        }
    }
}

enum AwgConfig {
    /// Userspace IPC "set" string for amneziawg-go / WireGuardKitGo `wgTurnOn`.
    static func toUapi(_ cfg: TunnelConfig) throws -> String {
        guard cfg.jc > 0, cfg.jmin > 0, cfg.jmax > 0 else {
            throw AwgConfigError.message("Jc/Jmin/Jmax must be positive")
        }
        guard cfg.jmax >= cfg.jmin else {
            throw AwgConfigError.message("Jmax must be >= Jmin")
        }
        guard !cfg.h1.isEmpty, !cfg.h2.isEmpty, !cfg.h3.isEmpty, !cfg.h4.isEmpty else {
            throw AwgConfigError.message("H1–H4 magic headers required")
        }
        guard cfg.s1 >= 0, cfg.s2 >= 0, cfg.s3 >= 0, cfg.s4 >= 0 else {
            throw AwgConfigError.message("S1–S4 must be non-negative")
        }
        guard !cfg.endpoint.isEmpty else {
            throw AwgConfigError.message("endpoint required")
        }
        let privHex = try b64KeyToHex(cfg.privateKeyB64)
        let pubHex = try b64KeyToHex(cfg.serverPublicKeyB64)
        let allowed = cfg.allowedIps.isEmpty ? ["0.0.0.0/0", "::/0"] : cfg.allowedIps

        var out = ""
        out += "private_key=\(privHex)\n"
        out += "jc=\(cfg.jc)\n"
        out += "jmin=\(cfg.jmin)\n"
        out += "jmax=\(cfg.jmax)\n"
        out += "s1=\(cfg.s1)\n"
        out += "s2=\(cfg.s2)\n"
        out += "s3=\(cfg.s3)\n"
        out += "s4=\(cfg.s4)\n"
        out += "h1=\(cfg.h1)\n"
        out += "h2=\(cfg.h2)\n"
        out += "h3=\(cfg.h3)\n"
        out += "h4=\(cfg.h4)\n"
        let special = [cfg.i1, cfg.i2, cfg.i3, cfg.i4, cfg.i5]
        for (idx, v) in special.enumerated() where !v.isEmpty {
            out += "i\(idx + 1)=\(v)\n"
        }
        out += "replace_peers=true\n"
        out += "public_key=\(pubHex)\n"
        out += "endpoint=\(cfg.endpoint)\n"
        out += "replace_allowed_ips=true\n"
        for ip in allowed {
            out += "allowed_ip=\(ip)\n"
        }
        out += "persistent_keepalive_interval=25\n"
        return out
    }

    /// awg-quick .conf body (PrivateKey stays base64 — never leave the device).
    static func toAwgQuick(_ cfg: TunnelConfig) throws -> String {
        guard cfg.jc > 0, cfg.jmin > 0, cfg.jmax > 0 else {
            throw AwgConfigError.message("Jc/Jmin/Jmax must be positive")
        }
        guard !cfg.h1.isEmpty, !cfg.h2.isEmpty, !cfg.h3.isEmpty, !cfg.h4.isEmpty else {
            throw AwgConfigError.message("H1–H4 magic headers required")
        }
        let allowed = cfg.allowedIps.isEmpty ? ["0.0.0.0/0", "::/0"] : cfg.allowedIps
        var out = "[Interface]\n"
        out += "PrivateKey = \(cfg.privateKeyB64)\n"
        out += "Address = \(cfg.addressCidr)\n"
        if !cfg.dns.isEmpty {
            out += "DNS = \(cfg.dns.joined(separator: ", "))\n"
        }
        if cfg.mtu > 0 {
            out += "MTU = \(cfg.mtu)\n"
        }
        out += "Jc = \(cfg.jc)\n"
        out += "Jmin = \(cfg.jmin)\n"
        out += "Jmax = \(cfg.jmax)\n"
        out += "S1 = \(cfg.s1)\n"
        out += "S2 = \(cfg.s2)\n"
        out += "S3 = \(cfg.s3)\n"
        out += "S4 = \(cfg.s4)\n"
        out += "H1 = \(cfg.h1)\n"
        out += "H2 = \(cfg.h2)\n"
        out += "H3 = \(cfg.h3)\n"
        out += "H4 = \(cfg.h4)\n"
        let special = [cfg.i1, cfg.i2, cfg.i3, cfg.i4, cfg.i5]
        for (idx, v) in special.enumerated() where !v.isEmpty {
            out += "I\(idx + 1) = \(v)\n"
        }
        out += "\n[Peer]\n"
        out += "PublicKey = \(cfg.serverPublicKeyB64)\n"
        out += "Endpoint = \(cfg.endpoint)\n"
        out += "AllowedIPs = \(allowed.joined(separator: ", "))\n"
        out += "PersistentKeepalive = 25\n"
        return out
    }

    static func b64KeyToHex(_ b64: String) throws -> String {
        guard let raw = Data(base64Encoded: b64.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            throw AwgConfigError.message("invalid base64 key")
        }
        guard raw.count == 32 else {
            throw AwgConfigError.message("want 32-byte key, got \(raw.count)")
        }
        return raw.map { String(format: "%02x", $0) }.joined()
    }
}
