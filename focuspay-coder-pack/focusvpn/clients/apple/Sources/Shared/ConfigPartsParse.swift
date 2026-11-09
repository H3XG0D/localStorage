// ConfigPartsParse.swift — Jc/Jmin/Jmax + H/S/I + peer endpoint from ConfigParts
import Foundation

enum ConfigPartsParse {
    struct Obfuscation: Equatable {
        let junkPacketCount: Int
        let junkMinSize: Int
        let junkMaxSize: Int
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
    }

    static func obfuscation(from parts: [String: Any]) -> Obfuscation? {
        guard
            let protocolObj = parts["protocol"] as? [String: Any],
            let obf = protocolObj["obfuscation"] as? [String: Any],
            let jc = intValue(obf["junk_packet_count"]),
            let jmin = intValue(obf["junk_min_size"]),
            let jmax = intValue(obf["junk_max_size"]),
            let h1 = obf["init_packet_magic_header"] as? String, !h1.isEmpty,
            let h2 = obf["response_packet_magic_header"] as? String, !h2.isEmpty,
            let h3 = obf["underload_packet_magic_header"] as? String, !h3.isEmpty,
            let h4 = obf["transport_packet_magic_header"] as? String, !h4.isEmpty
        else { return nil }
        return Obfuscation(
            junkPacketCount: jc,
            junkMinSize: jmin,
            junkMaxSize: jmax,
            s1: intValue(obf["init_packet_junk_size"]) ?? 0,
            s2: intValue(obf["response_packet_junk_size"]) ?? 0,
            s3: intValue(obf["cookie_reply_junk_size"]) ?? 0,
            s4: intValue(obf["transport_packet_junk_size"]) ?? 0,
            h1: h1,
            h2: h2,
            h3: h3,
            h4: h4,
            i1: obf["special_junk_i1"] as? String ?? "",
            i2: obf["special_junk_i2"] as? String ?? "",
            i3: obf["special_junk_i3"] as? String ?? "",
            i4: obf["special_junk_i4"] as? String ?? "",
            i5: obf["special_junk_i5"] as? String ?? ""
        )
    }

    static func peerEndpoint(from parts: [String: Any]) -> String? {
        guard let peer = parts["peer"] as? [String: Any] else { return nil }
        return peer["endpoint"] as? String
    }

    static func partsDictionary(from response: ConfigPartsResponse) -> [String: Any] {
        response.parts.mapValues { $0.value }
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
