package com.focusvpn.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class Tokens(
    @SerialName("access_token") val accessToken: String,
    @SerialName("refresh_token") val refreshToken: String,
    @SerialName("expires_in") val expiresIn: Int = 0,
)

@Serializable
data class UserDTO(val id: String, val email: String, val role: String = "user")

@Serializable
data class AuthResponse(val user: UserDTO, val tokens: Tokens)

@Serializable
data class EndpointDTO(
    val id: String,
    val node: String,
    val country: String = "",
    val region: String = "",
    val protocol: String = "",
    val score: Double = 0.0,
    val host: String = "",
    val port: Int = 0,
)

@Serializable
data class ServersResponse(val endpoints: List<EndpointDTO> = emptyList())

@Serializable
data class ConnectionDTO(val id: String, val status: String)

@Serializable
data class CreateConnectionResponse(
    val connection: ConnectionDTO,
    val candidates: List<CandidateDTO> = emptyList(),
    @SerialName("config_id") val configId: String,
    @SerialName("config_version") val configVersion: Int = 0,
)

@Serializable
data class CandidateDTO(
    val endpoint: CandidateEndpointDTO = CandidateEndpointDTO(),
    val node: String = "",
    val score: Double = 0.0,
)

@Serializable
data class CandidateEndpointDTO(
    val id: String = "",
    val host: String = "",
    val port: Int = 0,
    val protocol: String = "",
)

@Serializable
data class ConfigPartsResponse(
    @SerialName("config_version") val configVersion: Int,
    val signature: String = "",
    val parts: Map<String, JsonElement> = emptyMap(),
)

@Serializable
data class CreateDeviceResponse(
    val device: DeviceDTO,
    @SerialName("device_token") val deviceToken: String,
)

@Serializable
data class DeviceDTO(
    val id: String,
    val name: String = "",
    val platform: String = "",
    val status: String = "",
)

@Serializable
data class DeviceListResponse(val devices: List<DeviceDTO> = emptyList())

@Serializable
data class MeResponse(
    val user: UserDTO,
    val subscription: MeSubscription? = null,
)

@Serializable
data class MeSubscription(
    val status: String = "",
    val plan: String = "",
    @SerialName("ends_at") val endsAt: String = "",
    @SerialName("max_devices") val maxDevices: Int = 1,
    @SerialName("devices_used") val devicesUsed: Int = 0,
)

@Serializable
data class TelegramStartResponse(
    @SerialName("deep_link") val deepLink: String,
    @SerialName("wait_token") val waitToken: String,
    @SerialName("expires_in") val expiresIn: Int = 300,
)

data class Session(
    val apiBase: String,
    val email: String,
    val accessToken: String,
    val refreshToken: String,
    val deviceId: String? = null,
    val deviceToken: String? = null,
    val privateKeyB64: String? = null,
    val publicKeyB64: String? = null,
    val selectedNode: String? = null,
    /** Wall-clock millis when [accessToken] expires. Null on sessions saved before refresh existed. */
    val accessExpiresAtMs: Long? = null,
)

/** When this access token should be treated as expired, or null if the server omitted `expires_in`. */
fun Tokens.accessExpiresAtMs(nowMs: Long = System.currentTimeMillis()): Long? =
    expiresIn.takeIf { it > 0 }?.let { nowMs + it * 1000L }

fun Session.withTokens(tokens: Tokens, nowMs: Long = System.currentTimeMillis()): Session = copy(
    accessToken = tokens.accessToken,
    refreshToken = tokens.refreshToken,
    accessExpiresAtMs = tokens.accessExpiresAtMs(nowMs),
)
