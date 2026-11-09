package com.focusvpn.app.ui

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.net.VpnService
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.focusvpn.app.BuildConfig
import com.focusvpn.app.auth.telegramViewIntent
import com.focusvpn.app.FocusVpnApp
import com.focusvpn.app.notify.AppNotices
import com.focusvpn.app.notify.shouldAskNotificationAccess
import com.focusvpn.app.ui.design.FocusAction
import com.focusvpn.app.ui.design.FocusSheet
import com.focusvpn.app.ui.design.FocusTab
import com.focusvpn.app.ui.design.FocusTabBar
import com.focusvpn.app.ui.design.MutedCopy
import com.focusvpn.app.ui.screens.AccountScreen
import com.focusvpn.app.ui.screens.AuthScreen
import com.focusvpn.app.ui.screens.HomeScreen
import com.focusvpn.app.ui.screens.LocationsScreen
import com.focusvpn.app.ui.theme.BgBase
import com.focusvpn.app.ui.theme.Danger
import com.focusvpn.app.ui.theme.Onest
import com.focusvpn.app.update.ApkInstall
import com.focusvpn.app.vpn.FocusVpnService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private const val BOT_START = "https://t.me/${BuildConfig.TELEGRAM_BOT_USERNAME}"

@Composable
fun FocusVpnAppRoot(app: FocusVpnApp) {
    val vm: AppViewModel = viewModel(factory = AppViewModel.factory(app))
    val state by vm.state.collectAsState()
    val nav = rememberNavController()
    val ctx = LocalContext.current
    val backStack by nav.currentBackStackEntryAsState()
    val route = backStack?.destination?.route
    val showTabs = state.loggedIn && route != null && route != "auth"
    val scope = rememberCoroutineScope()
    var updating by remember { mutableStateOf(false) }
    var updateError by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) { vm.checkForUpdate() }

    val vpnPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            vm.connect {
                startVpn(ctx as Activity)
            }
        }
    }
    var notifAsked by remember { mutableStateOf(AppNotices.alreadyAsked(ctx)) }
    var notifGranted by remember { mutableStateOf(AppNotices.granted(ctx)) }
    val notifPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        notifGranted = granted
        notifAsked = true
        AppNotices.markAsked(ctx)
        if (granted) vm.publishPendingNotices()
    }
    val askNotifications = state.loggedIn && route == "home" && state.updateChecked &&
        state.updateOffer == null &&
        shouldAskNotificationAccess(Build.VERSION.SDK_INT, notifGranted, notifAsked)

    fun openTab(tab: FocusTab) {
        val dest = when (tab) {
            FocusTab.Connect -> "home"
            FocusTab.Locations -> "locations"
            FocusTab.Account -> "account"
        }
        nav.navigate(dest) {
            popUpTo(nav.graph.findStartDestination().id) { saveState = true }
            launchSingleTop = true
            restoreState = true
        }
    }

    fun stopTunnel() {
        vm.disconnect()
        ctx.startService(
            Intent(ctx, FocusVpnService::class.java).setAction(FocusVpnService.ACTION_DISCONNECT),
        )
    }

    Scaffold(
        containerColor = BgBase,
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        bottomBar = {
            if (showTabs) {
                FocusTabBar(
                    active = when (route) {
                        "locations" -> FocusTab.Locations
                        "account" -> FocusTab.Account
                        else -> FocusTab.Connect
                    },
                    onSelect = ::openTab,
                    modifier = Modifier.navigationBarsPadding(),
                )
            }
        },
    ) { pad ->
        NavHost(
            navController = nav,
            startDestination = if (state.loggedIn) "home" else "auth",
            modifier = Modifier.padding(pad),
            enterTransition = { EnterTransition.None },
            exitTransition = { ExitTransition.None },
            popEnterTransition = { EnterTransition.None },
            popExitTransition = { ExitTransition.None },
        ) {
            composable("auth") {
                AuthScreen(
                    busy = state.busy,
                    awaitingTelegram = state.awaitingTelegram,
                    error = state.error,
                    onTelegramLogin = {
                        vm.loginWithTelegram({ link ->
                            ctx.startActivity(telegramViewIntent(ctx.packageManager, link))
                        }) {
                            nav.navigate("home") { popUpTo("auth") { inclusive = true } }
                        }
                    },
                    onCodeLogin = { code ->
                        vm.loginWithCode(code) {
                            nav.navigate("home") { popUpTo("auth") { inclusive = true } }
                        }
                    },
                )
            }
            composable("home") {
                HomeScreen(
                    state = state,
                    onConnectToggle = {
                        if (state.connected || state.connecting) {
                            stopTunnel()
                        } else if (!state.busy) {
                            val prep = VpnService.prepare(ctx)
                            if (prep != null) vpnPermission.launch(prep)
                            else {
                                vm.connect { startVpn(ctx as Activity) }
                            }
                        }
                    },
                    onOpenLocations = { openTab(FocusTab.Locations) },
                    onOpenAccount = { openTab(FocusTab.Account) },
                )
            }
            composable("locations") {
                LocationsScreen(
                    endpoints = state.endpoints,
                    selected = state.selectedNode,
                    pings = state.pingMs,
                    busy = state.busy,
                    error = state.error,
                    onRefresh = { vm.refreshServers() },
                    onSelect = { node ->
                        val switching = vm.shouldRebuildTunnel(node)
                        vm.selectNode(node)
                        openTab(FocusTab.Connect)
                        if (switching) {
                            vm.reconnect(
                                stopService = {
                                    ctx.startService(
                                        Intent(ctx, FocusVpnService::class.java)
                                            .setAction(FocusVpnService.ACTION_DISCONNECT),
                                    )
                                },
                                startService = { startVpn(ctx as Activity) },
                            )
                        }
                    },
                )
            }
            composable("account") {
                AccountScreen(
                    state = state,
                    botDeepLink = BOT_START,
                    onRebindDevice = { vm.rebindThisDevice { vm.refreshAccount() } },
                    onLogout = {
                        stopTunnel()
                        vm.logout()
                        nav.navigate("auth") { popUpTo(0) }
                    },
                )
            }
        }
    }
    val offer = state.updateOffer
    FocusSheet(
        visible = offer != null,
        title = "Доступно обновление",
        onClose = { if (!updating) vm.dismissUpdate() },
    ) {
        MutedCopy("Версия ${offer?.versionName.orEmpty()}. Её можно поставить здесь, без новой загрузки из бота.")
        if (!updateError.isNullOrBlank()) {
            Text(updateError.orEmpty(), color = Danger, fontFamily = Onest, fontWeight = FontWeight.Medium, fontSize = 14.sp)
        }
        FocusAction(
            text = if (updating) "Скачиваем…" else "Обновить",
            enabled = !updating,
            showArrow = false,
            onClick = {
                val url = offer?.url ?: return@FocusAction
                if (!ApkInstall.canInstall(ctx)) {
                    ApkInstall.openPermission(ctx)
                    return@FocusAction
                }
                updating = true
                updateError = null
                scope.launch {
                    try {
                        val file = withContext(Dispatchers.IO) { ApkInstall.download(ctx, url) }
                        ApkInstall.install(ctx, file)
                    } catch (e: Exception) {
                        updateError = e.message ?: "Не удалось скачать обновление"
                    } finally {
                        updating = false
                    }
                }
            },
        )
    }
    FocusSheet(
        visible = askNotifications,
        title = "Уведомления",
        onClose = {
            notifAsked = true
            AppNotices.markAsked(ctx)
        },
    ) {
        MutedCopy("Статус подключения будет в шторке. Туда же придёт обновление приложения и напоминание, когда подписка заканчивается.")
        FocusAction(
            text = "Разрешить",
            showArrow = false,
            onClick = { notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS) },
        )
    }
}

private fun startVpn(activity: Activity) {
    activity.startForegroundService(
        Intent(activity, FocusVpnService::class.java).setAction(FocusVpnService.ACTION_CONNECT),
    )
}
