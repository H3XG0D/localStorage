package com.focusvpn.app.crypto

import org.bouncycastle.math.ec.rfc7748.X25519
import java.security.SecureRandom
import java.util.Base64

/**
 * X25519 key material for WireGuard / AmneziaWG peers.
 * Private keys never leave the device (ADR-005).
 */
object X25519Keys {
    /** Returns (privateKeyB64, publicKeyB64). */
    fun generate(): Pair<String, String> {
        val priv = ByteArray(X25519.SCALAR_SIZE)
        X25519.generatePrivateKey(SecureRandom(), priv)
        val pub = ByteArray(X25519.POINT_SIZE)
        X25519.generatePublicKey(priv, 0, pub, 0)
        val enc = Base64.getEncoder()
        return enc.encodeToString(priv) to enc.encodeToString(pub)
    }

    /** Derive public key from a base64 private key (for tests / rotation). */
    fun publicFromPrivate(privateKeyB64: String): String {
        val priv = Base64.getDecoder().decode(privateKeyB64)
        require(priv.size == X25519.SCALAR_SIZE) { "private key must be 32 bytes" }
        val pub = ByteArray(X25519.POINT_SIZE)
        X25519.generatePublicKey(priv, 0, pub, 0)
        return Base64.getEncoder().encodeToString(pub)
    }
}
