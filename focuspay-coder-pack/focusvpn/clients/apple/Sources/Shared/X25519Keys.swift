// X25519Keys.swift — device keypair via CryptoKit (ADR-005)
import CryptoKit
import Foundation

enum X25519Keys {
    /// Returns (privateKeyB64, publicKeyB64) — public is derived from private.
    static func generate() -> (privB64: String, pubB64: String) {
        let priv = Curve25519.KeyAgreement.PrivateKey()
        let pub = priv.publicKey
        return (
            priv.rawRepresentation.base64EncodedString(),
            pub.rawRepresentation.base64EncodedString()
        )
    }

    static func publicFromPrivate(privateKeyB64: String) throws -> String {
        guard let data = Data(base64Encoded: privateKeyB64) else {
            throw APIError.message("invalid private key b64")
        }
        let priv = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: data)
        return priv.publicKey.rawRepresentation.base64EncodedString()
    }
}
