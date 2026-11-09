// Browser preview mock. Wails injects window.go.app.App before this file runs.
(function () {
  if (window.go && window.go.app && window.go.app.App) return;
  const delay = (ms) => new Promise((r) => setTimeout(r, ms));
  const hash = location.hash.replace("#", "");
  let loggedIn = hash === "home" || hash === "locations" || hash === "account" || hash === "on";
  let state = hash === "on" ? "connected" : "disconnected";
  let selected = "";
  let samples = hash === "on" ? 2 : 0;
  const servers = [
    { node: "DE2", country: "DE", region: "Франкфурт", protocol: "vless", host: "147.45.39.132", port: 443 },
    { node: "NL1", country: "NL", region: "Амстердам", protocol: "vless", host: "193.233.82.168", port: 443 },
    { node: "GB1", country: "GB", region: "Лондон", protocol: "vless", host: "193.149.189.177", port: 443 },
    { node: "RO1", country: "RO", region: "Бухарест", protocol: "vless", host: "64.7.199.95", port: 443 },
  ];
  window.go = window.go || {};
  window.go.app = window.go.app || {};
  window.go.app.App = {
    Status: async () => ({
      logged_in: loggedIn,
      state,
      email: loggedIn ? "demo@focusvpn.dev" : "",
      selected_node: selected,
      plan: loggedIn ? "month" : "",
      ends_at: loggedIn ? "2026-11-12T00:00:00Z" : "",
      max_devices: loggedIn ? 3 : 0,
      devices_used: loggedIn ? 1 : 0,
    }),
    ListServers: async () => ({ endpoints: servers }),
    SelectNode: async (n) => { selected = n || ""; },
    Connect: async () => { state = "connecting"; await delay(500); state = "connected"; samples = 0; },
    Disconnect: async () => { state = "disconnecting"; await delay(250); state = "disconnected"; samples = 0; },
    Logout: async () => { loggedIn = false; state = "disconnected"; selected = ""; },
    TelegramStart: async () => ({ deep_link: "https://t.me/focusvpn1_bot?start=vpnauth_demo", wait_token: "wait", expires_in: 300 }),
    TelegramWait: async () => { loggedIn = true; return { ready: true }; },
    LoginCode: async (code) => {
      if (String(code).length < 6) throw new Error("Код неверный или устарел — запросите новый в боте");
      loggedIn = true;
    },
    Account: async () => ({
      email: "demo@focusvpn.dev",
      plan: "month",
      status: "active",
      ends_at: "2026-11-12T00:00:00Z",
      max_devices: 3,
      devices_used: 1,
      devices: [{ name: "desktop", platform: "linux" }],
    }),
    Ping: async () => 28 + Math.floor(Math.random() * 20),
    Link: async () => {
      samples += 1;
      if (state !== "connected" || samples < 2) return { ok: false, down_mbps: 0, up_mbps: 0 };
      return { ok: true, down_mbps: 12.4, up_mbps: 1.8 };
    },
  };
})();
