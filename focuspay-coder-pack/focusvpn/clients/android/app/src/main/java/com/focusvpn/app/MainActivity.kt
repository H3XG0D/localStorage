package com.focusvpn.app

import android.graphics.Color
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.focusvpn.app.ui.FocusVpnAppRoot
import com.focusvpn.app.ui.theme.FocusVpnTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.parseColor("#0A0A0E")),
        )
        val app = application as FocusVpnApp
        setContent {
            FocusVpnTheme {
                FocusVpnAppRoot(app = app)
            }
        }
    }
}
