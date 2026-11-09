package com.focusvpn.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class ApiExceptionTest {
    private fun body(code: String, msg: String) =
        """{"error":{"code":"$code","message":"$msg","request_id":"r1"}}"""

    @Test
    fun exposesMachineCodeForBranching() {
        val e = ApiException(409, body("too_many_devices", "device limit reached for plan"))
        assertEquals("too_many_devices", e.errorCode)
        assertEquals("Достигнут лимит устройств для тарифа", e.message)
    }

    @Test
    fun unknownCodeFallsBackToServerMessageNotRawJson() {
        val e = ApiException(404, body("device_not_found", "device not found"))
        assertEquals("device not found", e.message)
        assertFalse(e.message!!.contains("{"))
    }

    @Test
    fun nonJsonBodyGetsGenericMessage() {
        val e = ApiException(502, "<html>Bad Gateway</html>")
        assertEquals("", e.errorCode)
        assertEquals("Ошибка сервера (502)", e.message)
    }
}
