// TunnelConfig.swift — ConfigParts → NE tunnel settings (P3-M4b + P4-M8 H/S/I)
import Foundation

enum TunnelConfigError: Error, LocalizedError {
    case message(String)
    var errorDescription: String? {
        switch self {
        case .message(let m): return m
        }
    }
}

struct TunnelConfig: Equatable {
    let privateKeyB64: String
    let serverPublicKeyB64: String
    let addressCidr: String
    let dns: [String]
    let mtu: Int
    let endpoint: String
    let allowedIps: [String]
    let jc: Int
    let jmin: Int
    let jmax: Int
    let s1: Int
    let s2: Int
    let s3: Int
    let s4: Int
    let h1: String
    let h2: String
    let h3: String
    let h4: String
    let i1: String
    let i2: String
    let i3: String
    let i4: String
    let i5: String

    var addressHost: String {
        String(addressCidr.split(separator: "/").first ?? Substring(addressCidr))
    }

    var addressPrefix: Int {
        let parts = addressCidr.split(separator: "/", maxSplits: 1)
        if parts.count == 2, let p = Int(parts[1]) { return p }
        return 32
    }

    var endpointHost: String {
        let hostPort = endpoint.split(separator: "]", maxSplits: 1)
        if endpoint.hasPrefix("["), hostPort.count == 2 {
            return String(endpoint.dropFirst().prefix { $0 != "]" })
        }
        return String(endpoint.split(separator: ":").first ?? Substring(endpoint))
    }

    /// Serialize for NETunnelProviderProtocol.providerConfiguration (extension process).
    func asProviderConfiguration() -> [String: Any] {
        var dict: [String: Any] = [
            "private_key": privateKeyB64,
            "server_public_key": serverPublicKeyB64,
            "address": addressCidr,
            "dns": dns,
            "mtu": mtu,
            "endpoint": endpoint,
            "allowed_ips": allowedIps,
            "jc": jc,
            "jmin": jmin,
            "jmax": jmax,
            "s1": s1,
            "s2": s2,
            "s3": s3,
            "s4": s4,
            "h1": h1,
            "h2": h2,
            "h3": h3,
            "h4": h4,
            "config_bridge": true,
        ]
        if !i1.isEmpty { dict["i1"] = i1 }
        if !i2.isEmpty { dict["i2"] = i2 }
        if !i3.isEmpty { dict["i3"] = i3 }
        if !i4.isEmpty { dict["i4"] = i4 }
        if !i5.isEmpty { dict["i5"] = i5 }
        return dict
    }

    static func fromProviderConfiguration(_ dict: [String: Any]) -> TunnelConfig? {
        guard
            let priv = dict["private_key"] as? String, !priv.isEmpty,
            let serverPub = dict["server_public_key"] as? String,
            let address = dict["address"] as? String,
            let endpoint = dict["endpoint"] as? String
        else { return nil }
        let dns = dict["dns"] as? [String] ?? ["1.1.1.1"]
        let mtu = intValue(dict["mtu"]) ?? 1420
        let allowed = dict["allowed_ips"] as? [String] ?? ["0.0.0.0/0"]
        return TunnelConfig(
            privateKeyB64: priv,
            serverPublicKeyB64: serverPub,
            addressCidr: address,
            dns: dns.isEmpty ? ["1.1.1.1"] : dns,
            mtu: mtu,
            endpoint: endpoint,
            allowedIps: allowed,
            jc: intValue(dict["jc"]) ?? 0,
            jmin: intValue(dict["jmin"]) ?? 0,
            jmax: intValue(dict["jmax"]) ?? 0,
            s1: intValue(dict["s1"]) ?? 0,
            s2: intValue(dict["s2"]) ?? 0,
            s3: intValue(dict["s3"]) ?? 0,
            s4: intValue(dict["s4"]) ?? 0,
            h1: dict["h1"] as? String ?? "",
            h2: dict["h2"] as? String ?? "",
            h3: dict["h3"] as? String ?? "",
            h4: dict["h4"] as? String ?? "",
            i1: dict["i1"] as? String ?? "",
            i2: dict["i2"] as? String ?? "",
            i3: dict["i3"] as? String ?? "",
            i4: dict["i4"] as? String ?? "",
            i5: dict["i5"] as? String ?? ""
        )
    }

    static func fromParts(_ parts: [String: Any], privateKeyB64: String) throws -> TunnelConfig {
        guard !privateKeyB64.isEmpty else { throw TunnelConfigError.message("config: empty private key") }
        guard let iface = parts["interface"] as? [String: Any] else {
            throw TunnelConfigError.message("config: missing interface")
        }
        guard let peer = parts["peer"] as? [String: Any] else {
            throw TunnelConfigError.message("config: missing peer")
        }
        guard let address = iface["address"] as? String else {
            throw TunnelConfigError.message("config: missing interface.address")
        }
        guard let serverPub = peer["server_public_key"] as? String else {
            throw TunnelConfigError.message("config: missing peer.server_public_key")
        }
        guard let endpoint = peer["endpoint"] as? String else {
            throw TunnelConfigError.message("config: missing peer.endpoint")
        }
        let dns: [String]
        if let arr = iface["dns"] as? [String] {
            dns = arr
        } else if let arr = iface["dns"] as? [Any] {
            dns = arr.compactMap { $0 as? String }
        } else {
            dns = ["1.1.1.1"]
        }
        let mtu = intValue(iface["mtu"]) ?? 1420
        let allowed: [String]
        if let arr = peer["allowed_ips"] as? [String] {
            allowed = arr
        } else if let arr = peer["allowed_ips"] as? [Any] {
            allowed = arr.compactMap { $0 as? String }
        } else {
            allowed = ["0.0.0.0/0"]
        }
        let proto = parts["protocol"] as? [String: Any]
        let obf = proto?["obfuscation"] as? [String: Any]
        let h1 = obf?["init_packet_magic_header"] as? String ?? ""
        let h2 = obf?["response_packet_magic_header"] as? String ?? ""
        let h3 = obf?["underload_packet_magic_header"] as? String ?? ""
        let h4 = obf?["transport_packet_magic_header"] as? String ?? ""
        guard !h1.isEmpty, !h2.isEmpty, !h3.isEmpty, !h4.isEmpty else {
            throw TunnelConfigError.message("config: H1–H4 magic headers required")
        }
        return TunnelConfig(
            privateKeyB64: privateKeyB64,
            serverPublicKeyB64: serverPub,
            addressCidr: address,
            dns: dns.isEmpty ? ["1.1.1.1"] : dns,
            mtu: mtu,
            endpoint: endpoint,
            allowedIps: allowed,
            jc: intValue(obf?["junk_packet_count"]) ?? 0,
            jmin: intValue(obf?["junk_min_size"]) ?? 0,
            jmax: intValue(obf?["junk_max_size"]) ?? 0,
            s1: intValue(obf?["init_packet_junk_size"]) ?? 0,
            s2: intValue(obf?["response_packet_junk_size"]) ?? 0,
            s3: intValue(obf?["cookie_reply_junk_size"]) ?? 0,
            s4: intValue(obf?["transport_packet_junk_size"]) ?? 0,
            h1: h1,
            h2: h2,
            h3: h3,
            h4: h4,
            i1: obf?["special_junk_i1"] as? String ?? "",
            i2: obf?["special_junk_i2"] as? String ?? "",
            i3: obf?["special_junk_i3"] as? String ?? "",
            i4: obf?["special_junk_i4"] as? String ?? "",
            i5: obf?["special_junk_i5"] as? String ?? ""
        )
    }

    /// IPv4 dotted mask for a prefix length (e.g. 32 → 255.255.255.255).
    static func ipv4SubnetMask(prefix: Int) -> String {
        let p = min(max(prefix, 0), 32)
        var mask: UInt32 = 0
        if p > 0 {
            mask = UInt32.max << (32 - p)
        }
        return [
            (mask >> 24) & 0xff,
            (mask >> 16) & 0xff,
            (mask >> 8) & 0xff,
            mask & 0xff,
        ].map(String.init).joined(separator: ".")
    }

    private static func intValue(_ any: Any?) -> Int? {
        switch any {
        case let i as Int: return i
        case let d as Double: return Int(d)
        case let n as NSNumber: return n.intValue
        default: return nil
        }
    }
}
