package com.focusvpn.app.vpn

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class XrayClientConfigTest {
    @Test
    fun parsesServerListAndBuildsTunDocument() {
        val parts = Json.parseToJsonElement(
            """
            {"xray":{
              "uuid":"11111111-1111-1111-1111-111111111111",
              "servers":[
                {"node":"DE2","address":"de2.example","port":443,"sni":"de2.example","host":"de2.example","path":"/api/de2","transport":"ws"},
                {"node":"DE2","address":"de2.example","port":443,"path":"/cdn/de2","transport":"xhttp","mode":"auto","sni":"de2.example","host":"de2.example"}
              ]
            }}
            """.trimIndent(),
        ).jsonObject
        val profile = XrayClientConfig.fromParts(parts)
        assertEquals("11111111-1111-1111-1111-111111111111", profile.uuid)
        assertEquals(listOf("ws", "xhttp"), profile.servers.map { it.transport })

        val doc = Json.parseToJsonElement(XrayClientConfig.document(profile.servers[1], profile.uuid, tunFd = 17)).jsonObject
        assertEquals("17", doc["env"]!!.jsonObject["xray.tun.fd"]!!.jsonPrimitive.content)
        val inbounds = doc["inbounds"]!!.jsonArray
        assertEquals("tun", inbounds[0].jsonObject["protocol"]!!.jsonPrimitive.content)
        assertEquals("socks", inbounds[1].jsonObject["protocol"]!!.jsonPrimitive.content)
        assertEquals("10808", inbounds[1].jsonObject["port"]!!.jsonPrimitive.content)
        val outbound = doc["outbounds"]!!.jsonArray[0].jsonObject
        val stream = outbound["streamSettings"]!!.jsonObject
        assertEquals("xhttp", stream["network"]!!.jsonPrimitive.content)
        assertEquals("/cdn/de2", stream["xhttpSettings"]!!.jsonObject["path"]!!.jsonPrimitive.content)
        assertEquals("auto", stream["xhttpSettings"]!!.jsonObject["mode"]!!.jsonPrimitive.content)
        assertEquals("de2.example", stream["xhttpSettings"]!!.jsonObject["host"]!!.jsonPrimitive.content)
        assertEquals("http/1.1", stream["tlsSettings"]!!.jsonObject["alpn"]!!.jsonArray[0].jsonPrimitive.content)
        assertEquals("dns-out", doc["outbounds"]!!.jsonArray[1].jsonObject["tag"]!!.jsonPrimitive.content)
        assertEquals("direct", doc["outbounds"]!!.jsonArray[2].jsonObject["tag"]!!.jsonPrimitive.content)
        assertEquals("freedom", doc["outbounds"]!!.jsonArray[2].jsonObject["protocol"]!!.jsonPrimitive.content)
        assertEquals("proxy", doc["outbounds"]!!.jsonArray[0].jsonObject["tag"]!!.jsonPrimitive.content)
        val rules = doc["routing"]!!.jsonObject["rules"]!!.jsonArray
        val dnsRule = rules[0].jsonObject
        assertEquals("53", dnsRule["port"]!!.jsonPrimitive.content)
        assertEquals("dns-out", dnsRule["outboundTag"]!!.jsonPrimitive.content)
        assertEquals("IPIfNonMatch", doc["routing"]!!.jsonObject["domainStrategy"]!!.jsonPrimitive.content)
        val domains = rules[1].jsonObject["domain"]!!.jsonArray.map { it.jsonPrimitive.content }
        assertEquals("direct", rules[1].jsonObject["outboundTag"]!!.jsonPrimitive.content)
        assertTrue(domains.contains("domain:ru"))
        assertTrue(domains.contains("domain:yandex.net"))
        assertTrue(domains.contains("domain:vk.com"))
        val cidrs = rules[2].jsonObject["ip"]!!.jsonArray.map { it.jsonPrimitive.content }
        assertEquals("direct", rules[2].jsonObject["outboundTag"]!!.jsonPrimitive.content)
        assertTrue(cidrs.contains("10.0.0.0/8"))
        assertTrue(cidrs.any { cidrContains(it, "77.88.8.8") })
        assertFalse(cidrs.any { cidrContains(it, "1.1.1.1") })
        assertFalse(cidrs.any { cidrContains(it, "8.8.8.8") })
        val dnsServers = doc["dns"]!!.jsonObject["servers"]!!.jsonArray
        assertEquals("77.88.8.8", dnsServers[0].jsonObject["address"]!!.jsonPrimitive.content)
        assertTrue(dnsServers[0].jsonObject["domains"]!!.jsonArray.any { it.jsonPrimitive.content == "domain:yandex.net" })
        assertEquals("https://1.1.1.1/dns-query", dnsServers[1].jsonPrimitive.content)
        assertFalse(outbound.toString().contains("flow"))

        val ws = Json.parseToJsonElement(XrayClientConfig.document(profile.servers[0], profile.uuid, tunFd = 17)).jsonObject
        val wsStream = ws["outbounds"]!!.jsonArray[0].jsonObject["streamSettings"]!!.jsonObject
        assertEquals("http/1.1", wsStream["tlsSettings"]!!.jsonObject["alpn"]!!.jsonArray[0].jsonPrimitive.content)
    }

    @Test
    fun russianAppsMatchDirectSuffixes() {
        listOf(
            "max.ru",
            "web.max.ru",
            "i.oneme.ru",
            "ws-api.oneme.ru",
            "calls.okcdn.ru",
            "eda.yandex.ru",
            "tc.mobile.yandex.net",
            "vk.com",
            "api.userapi.com",
        ).forEach { assertTrue(it, RuDirect.matches(it)) }
        listOf("google.com", "www.gstatic.com", "example.ru.com", "corrupt").forEach {
            assertFalse(it, RuDirect.matches(it))
        }
    }

    @Test
    fun invokeErrorReadsLibXrayEnvelope() {
        assertEquals(null, XrayInvoke.error("""{"success":true,"data":{},"error":""}"""))
        assertEquals("bad config", XrayInvoke.error("""{"success":false,"error":"bad config"}"""))
    }
}

private fun cidrContains(cidr: String, ip: String): Boolean {
    if (!cidr.contains('.') || ip.contains(':')) return false
    val (addr, bitsText) = cidr.split("/")
    val bits = bitsText.toInt()
    val mask = if (bits == 0) 0L else (0xffffffffL shl (32 - bits)) and 0xffffffffL
    return (packV4(addr) and mask) == (packV4(ip) and mask)
}

private fun packV4(ip: String): Long {
    var n = 0L
    for (octet in ip.split(".")) n = (n shl 8) or octet.toLong()
    return n
}
