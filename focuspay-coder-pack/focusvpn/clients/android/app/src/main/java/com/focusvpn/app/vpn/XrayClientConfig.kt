package com.focusvpn.app.vpn

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

/** One VLESS server from ConfigParts["xray"]. Order is the failover order. */
data class VlessServer(
    val node: String,
    val address: String,
    val port: Int,
    val sni: String,
    val host: String,
    val path: String,
    val transport: String,
    val mode: String,
)

/** What the app needs to open a tunnel. The VLESS UUID is the credential. */
data class XrayProfile(
    val uuid: String,
    val servers: List<VlessServer>,
)

/**
 * Builds the Xray JSON the Android TUN inbound consumes.
 * Kept free of Android and libXray types so unit tests can run on the JVM.
 */
object XrayClientConfig {
    /** Local SOCKS used to probe the tunnel. The VPN app's own sockets never enter its TUN. */
    const val SOCKS_PORT = 10808

    fun fromParts(parts: Map<String, JsonElement>): XrayProfile {
        val xray = parts["xray"]?.jsonObject ?: error("config: missing xray")
        val uuid = xray.str("uuid")
        require(uuid.isNotBlank()) { "config: missing xray.uuid" }
        val listed = xray["servers"]?.jsonArray?.map { serverFrom(it.jsonObject) }.orEmpty()
        val servers = listed.ifEmpty { listOf(serverFrom(xray)) }
        require(servers.isNotEmpty() && servers.all { it.path.isNotBlank() && it.address.isNotBlank() }) {
            "config: xray server address and path are required"
        }
        return XrayProfile(uuid, servers)
    }

    fun document(
        server: VlessServer,
        uuid: String,
        tunFd: Int,
        mtu: Int = 1400,
        directPrefixes: List<String> = RuDirect.prefixes,
    ): String {
        // Nginx on the node speaks HTTP/1.1 only. The chrome fingerprint offers h2,
        // and XHTTP then never finishes the handshake. WS survives; XHTTP does not.
        val stream = buildJsonObject {
            put("network", server.transport)
            put("security", "tls")
            put("tlsSettings", buildJsonObject {
                put("serverName", server.sni)
                put("fingerprint", "chrome")
                put("alpn", buildJsonArray { add(JsonPrimitive("http/1.1")) })
            })
            if (server.transport == "xhttp") {
                put("xhttpSettings", buildJsonObject {
                    put("path", server.path)
                    if (server.host.isNotBlank()) put("host", server.host)
                    if (server.mode.isNotBlank()) put("mode", server.mode)
                })
            } else {
                put("wsSettings", buildJsonObject {
                    put("path", server.path)
                    put("headers", buildJsonObject { put("Host", server.host) })
                })
            }
        }
        return buildJsonObject {
            put("log", buildJsonObject { put("loglevel", "warning") })
            put("env", buildJsonObject { put("xray.tun.fd", tunFd.toString()) })
            // App DNS arrives as UDP/53 in the TUN. VLESS over WS/XHTTP cannot carry
            // that packet, so the built-in resolver answers it. Names that go direct
            // are resolved at Yandex DNS from the phone's own IP; everything else
            // stays on DoH. Both dials are protected sockets, not another trip through TUN.
            put("dns", buildJsonObject {
                put("queryStrategy", "UseIPv4")
                put("servers", buildJsonArray {
                    add(buildJsonObject {
                        put("address", "77.88.8.8")
                        put("port", 53)
                        put("domains", jsonStrings(RuDirect.domainRules()))
                    })
                    add(JsonPrimitive("https://1.1.1.1/dns-query"))
                })
            })
            put("inbounds", buildJsonArray {
                add(buildJsonObject {
                    put("tag", "tun-in")
                    put("port", 0)
                    put("protocol", "tun")
                    put("settings", buildJsonObject {
                        put("name", "xray0")
                        put("MTU", mtu)
                    })
                    put("sniffing", buildJsonObject {
                        put("enabled", true)
                        put("destOverride", buildJsonArray {
                            add(JsonPrimitive("http"))
                            add(JsonPrimitive("tls"))
                            add(JsonPrimitive("quic"))
                        })
                    })
                })
                add(buildJsonObject {
                    put("tag", "socks-in")
                    put("listen", "127.0.0.1")
                    put("port", SOCKS_PORT)
                    put("protocol", "socks")
                    put("settings", buildJsonObject { put("udp", false) })
                })
            })
            put("outbounds", buildJsonArray {
                add(buildJsonObject {
                    put("tag", "proxy")
                    put("protocol", "vless")
                    put("settings", buildJsonObject {
                        put("vnext", buildJsonArray {
                            add(buildJsonObject {
                                put("address", server.address)
                                put("port", server.port)
                                put("users", buildJsonArray {
                                    add(buildJsonObject {
                                        put("id", uuid)
                                        put("encryption", "none")
                                    })
                                })
                            })
                        })
                    })
                    put("streamSettings", stream)
                })
                add(buildJsonObject {
                    put("tag", "dns-out")
                    put("protocol", "dns")
                })
                // Not first: the first outbound is the default, and that must stay the tunnel.
                add(buildJsonObject {
                    put("tag", "direct")
                    put("protocol", "freedom")
                    put("settings", buildJsonObject { put("domainStrategy", "UseIPv4") })
                })
            })
            put("routing", buildJsonObject {
                // Domain rules first. Only a miss is resolved, so a Russian IP can
                // still leave directly when the name was not in the suffix list.
                // The resolved address is used for the decision; the outbound still dials the name.
                put("domainStrategy", "IPIfNonMatch")
                put("rules", buildJsonArray {
                    add(buildJsonObject {
                        put("type", "field")
                        put("inboundTag", buildJsonArray { add(JsonPrimitive("tun-in")) })
                        put("port", 53)
                        put("outboundTag", "dns-out")
                    })
                    add(buildJsonObject {
                        put("type", "field")
                        put("domain", jsonStrings(RuDirect.domainRules()))
                        put("outboundTag", "direct")
                    })
                    add(buildJsonObject {
                        put("type", "field")
                        put("ip", jsonStrings(RuDirect.ipRules(directPrefixes)))
                        put("outboundTag", "direct")
                    })
                })
            })
        }.toString()
    }

    private fun serverFrom(o: JsonObject): VlessServer {
        val transport = o.str("transport").ifBlank { o.str("network") }.ifBlank { "ws" }
        val host = o.str("host").ifBlank { o.str("sni") }.ifBlank { o.str("address") }
        val address = o.str("address").ifBlank { host }
        return VlessServer(
            node = o.str("node").ifBlank { address },
            address = address,
            port = o.int("port").takeIf { it > 0 } ?: 443,
            sni = o.str("sni").ifBlank { host },
            host = host.ifBlank { address },
            path = o.str("path"),
            transport = transport,
            mode = o.str("mode"),
        )
    }
}

private fun jsonStrings(values: List<String>) = buildJsonArray {
    values.forEach { add(JsonPrimitive(it)) }
}

private fun JsonObject.str(key: String): String =
    this[key]?.jsonPrimitive?.contentOrNull.orEmpty()

private fun JsonObject.int(key: String): Int =
    this[key]?.jsonPrimitive?.intOrNull
        ?: this[key]?.jsonPrimitive?.contentOrNull?.toIntOrNull()
        ?: 0

/** Process-local handoff. The UUID never goes through Intent extras. */
object ActiveTunnel {
    @Volatile
    var profile: XrayProfile? = null

    /** node id → «Германия · DE1», written with [profile]. */
    @Volatile
    var placeLabels: Map<String, String> = emptyMap()

    /** True when the user left the location on automatic. */
    @Volatile
    var autoPlace: Boolean = true

    fun clear() {
        profile = null
        placeLabels = emptyMap()
        autoPlace = true
    }
}
