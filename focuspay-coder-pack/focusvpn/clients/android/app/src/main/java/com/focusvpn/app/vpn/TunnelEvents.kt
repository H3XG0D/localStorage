package com.focusvpn.app.vpn

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/** Service → UI. "Up" means a request through the tunnel succeeded. */
object TunnelEvents {
    sealed interface Status {
        data object Idle : Status
        data object Connecting : Status
        data class Up(val node: String) : Status
        data class Down(val message: String) : Status
    }

    private val _status = MutableStateFlow<Status>(Status.Idle)
    val status: StateFlow<Status> = _status

    fun update(status: Status) {
        _status.value = status
    }
}
