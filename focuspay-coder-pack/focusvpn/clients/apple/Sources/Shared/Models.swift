// Models.swift — Control Plane DTOs (mirrors clients/shared/apitypes)
import Foundation

struct Tokens: Codable {
    let accessToken: String
    let refreshToken: String
    let expiresIn: Int?

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case expiresIn = "expires_in"
    }
}

struct UserDTO: Codable {
    let id: String
    let email: String
    let role: String?
}

struct AuthResponse: Codable {
    let user: UserDTO
    let tokens: Tokens
}

struct EndpointDTO: Codable, Identifiable, Hashable {
    let id: String
    let node: String
    let country: String?
    let region: String?
    let protocolName: String?
    let score: Double?

    enum CodingKeys: String, CodingKey {
        case id, node, country, region, score
        case protocolName = "protocol"
    }
}

struct ServersResponse: Codable {
    let endpoints: [EndpointDTO]
}

struct ConnectionDTO: Codable {
    let id: String
    let status: String
}

struct CreateConnectionResponse: Codable {
    let connection: ConnectionDTO
    let candidates: [CandidateDTO]?
    let configId: String
    let configVersion: Int?

    enum CodingKeys: String, CodingKey {
        case connection, candidates
        case configId = "config_id"
        case configVersion = "config_version"
    }
}

struct CandidateDTO: Codable {
    let endpoint: CandidateEndpointDTO?
    let node: String?
    let score: Double?
}

struct CandidateEndpointDTO: Codable {
    let id: String?
    let host: String?
    let port: Int?
    let protocolName: String?

    enum CodingKeys: String, CodingKey {
        case id, host, port
        case protocolName = "protocol"
    }
}

struct ConfigPartsResponse: Codable {
    let configVersion: Int
    let signature: String?
    let parts: [String: AnyCodable]

    enum CodingKeys: String, CodingKey {
        case configVersion = "config_version"
        case signature, parts
    }
}

struct DeviceDTO: Codable {
    let id: String
    let name: String?
    let platform: String?
}

struct CreateDeviceResponse: Codable {
    let device: DeviceDTO
    let deviceToken: String

    enum CodingKeys: String, CodingKey {
        case device
        case deviceToken = "device_token"
    }
}

struct Session: Codable, Equatable {
    var apiBase: String
    var email: String
    var accessToken: String
    var refreshToken: String
    var deviceId: String?
    var deviceToken: String?
    var privateKeyB64: String?
    var publicKeyB64: String?
    var selectedNode: String?
}

/// Minimal AnyCodable for nested ConfigParts JSON.
struct AnyCodable: Codable {
    let value: Any

    init(_ value: Any) { self.value = value }

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { value = NSNull(); return }
        if let v = try? c.decode(Bool.self) { value = v; return }
        if let v = try? c.decode(Int.self) { value = v; return }
        if let v = try? c.decode(Double.self) { value = v; return }
        if let v = try? c.decode(String.self) { value = v; return }
        if let v = try? c.decode([String: AnyCodable].self) {
            value = v.mapValues { $0.value }
            return
        }
        if let v = try? c.decode([AnyCodable].self) {
            value = v.map { $0.value }
            return
        }
        throw DecodingError.dataCorruptedError(in: c, debugDescription: "unsupported JSON")
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch value {
        case is NSNull: try c.encodeNil()
        case let v as Bool: try c.encode(v)
        case let v as Int: try c.encode(v)
        case let v as Double: try c.encode(v)
        case let v as String: try c.encode(v)
        case let v as [String: Any]:
            try c.encode(v.mapValues { AnyCodable($0) })
        case let v as [Any]:
            try c.encode(v.map { AnyCodable($0) })
        default:
            throw EncodingError.invalidValue(value, .init(codingPath: c.codingPath, debugDescription: "unsupported"))
        }
    }
}
