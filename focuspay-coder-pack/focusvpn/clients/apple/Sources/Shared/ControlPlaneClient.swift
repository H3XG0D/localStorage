// ControlPlaneClient.swift — FocusVPN Control Plane HTTP (URLSession)
import Foundation

enum APIError: Error, LocalizedError {
    case http(Int, String)
    case decode(Error)
    case message(String)

    var errorDescription: String? {
        switch self {
        case .http(let code, let body): return "HTTP \(code): \(body)"
        case .decode(let e): return e.localizedDescription
        case .message(let m): return m
        }
    }
}

final class ControlPlaneClient: @unchecked Sendable {
    private var apiBase: String
    private let session: URLSession
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        return d
    }()

    init(apiBase: String, session: URLSession = .shared) {
        self.apiBase = apiBase.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        // keep trailing structure: strip only trailing slash
        while self.apiBase.hasSuffix("/") { self.apiBase.removeLast() }
        self.session = session
    }

    func setApiBase(_ base: String) {
        var b = base
        while b.hasSuffix("/") { b.removeLast() }
        apiBase = b
    }

    func register(email: String, password: String) async throws -> AuthResponse {
        try await post("/v1/auth/register", body: ["email": email, "password": password])
    }

    func login(email: String, password: String) async throws -> AuthResponse {
        try await post("/v1/auth/login", body: ["email": email, "password": password])
    }

    func listServers(access: String) async throws -> ServersResponse {
        try await get("/v1/servers", access: access)
    }

    func createDevice(access: String, name: String, publicKeyB64: String, platform: String) async throws -> CreateDeviceResponse {
        try await post(
            "/v1/devices",
            body: [
                "name": name,
                "platform": platform,
                "public_key": publicKeyB64,
            ],
            access: access
        )
    }

    func createConnection(
        access: String,
        deviceId: String,
        preferredNode: String? = nil
    ) async throws -> CreateConnectionResponse {
        var body: [String: String] = [
            "device_id": deviceId,
            "protocol": "amneziawg",
        ]
        if let preferredNode, !preferredNode.isEmpty {
            body["preferred_node"] = preferredNode
        }
        return try await post("/v1/connections", body: body, access: access)
    }

    func getConfig(configId: String, deviceToken: String) async throws -> ConfigPartsResponse {
        var req = URLRequest(url: url("/v1/configurations/\(configId)"))
        req.httpMethod = "GET"
        req.setValue(deviceToken, forHTTPHeaderField: "X-Device-Token")
        return try await execute(req)
    }

    func disconnect(access: String, connectionId: String) async throws {
        var req = URLRequest(url: url("/v1/connections/\(connectionId)"))
        req.httpMethod = "DELETE"
        req.setValue("Bearer \(access)", forHTTPHeaderField: "Authorization")
        let (_, resp) = try await session.data(for: req)
        guard let http = resp as? HTTPURLResponse else { throw APIError.message("no response") }
        if !(200..<300).contains(http.statusCode) && http.statusCode != 204 {
            throw APIError.http(http.statusCode, "")
        }
    }

    // MARK: - HTTP

    private func url(_ path: String) -> URL {
        URL(string: apiBase + path)!
    }

    private func get<T: Decodable>(_ path: String, access: String) async throws -> T {
        var req = URLRequest(url: url(path))
        req.httpMethod = "GET"
        req.setValue("Bearer \(access)", forHTTPHeaderField: "Authorization")
        return try await execute(req)
    }

    private func post<T: Decodable>(_ path: String, body: [String: String], access: String? = nil) async throws -> T {
        var req = URLRequest(url: url(path))
        req.httpMethod = "POST"
        req.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        if let access { req.setValue("Bearer \(access)", forHTTPHeaderField: "Authorization") }
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await execute(req)
    }

    private func execute<T: Decodable>(_ req: URLRequest) async throws -> T {
        let (data, resp) = try await session.data(for: req)
        guard let http = resp as? HTTPURLResponse else { throw APIError.message("no response") }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.http(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decode(error)
        }
    }

    /// X25519 keypair — public derived from private (CryptoKit).
    static func keygen() -> (privB64: String, pubB64: String) {
        X25519Keys.generate()
    }
}
