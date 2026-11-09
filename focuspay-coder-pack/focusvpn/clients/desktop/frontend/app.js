/* FocusVPN desktop UI — same screens as Android. Bindings: window.go.app.App */

const BOT = "https://t.me/focusvpn1_bot";
const screens = ["auth", "home", "locations", "account"];
const countries = {
  NL: "Нидерланды", DE: "Германия", RO: "Румыния", FI: "Финляндия", CH: "Швейцария",
  GB: "Великобритания", UK: "Великобритания", US: "США", JP: "Япония", SG: "Сингапур",
  FR: "Франция", SE: "Швеция", PL: "Польша", CA: "Канада",
};
const europe = ["NL","DE","FI","CH","GB","UK","FR","SE","PL","AT","BE","CZ","DK","EE","ES","IE","IT","LT","LU","LV","NO","PT","RO","SK"];
const asia = ["JP","SG","KR","HK","TW","IN","ID","TH","VN","AE"];
const america = ["US","CA","BR","MX","AR"];

let endpoints = [];
let pings = {};
let region = "all";
let selectedNode = "";
let connectedAt = 0;
let linkTimer = 0;
let waitTimer = 0;
let busy = false;

function api() {
  if (window.go && window.go.app && window.go.app.App) return window.go.app.App;
  if (window.go && window.go.main && window.go.main.App) return window.go.main.App;
  return null;
}

function pick(obj, a, b, fallback) {
  if (!obj) return fallback;
  if (obj[a] != null && obj[a] !== "") return obj[a];
  if (obj[b] != null && obj[b] !== "") return obj[b];
  return fallback;
}

function show(name) {
  screens.forEach((id) => {
    document.getElementById("screen-" + id).classList.toggle("active", id === name);
  });
  const tabs = name !== "auth";
  document.getElementById("tabbar").hidden = !tabs;
  document.querySelectorAll(".tabbar button").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.nav === name);
  });
  if (name === "locations") renderLocations();
  if (name === "account") loadAccount();
}

function setErr(id, msg) {
  const el = document.getElementById(id);
  if (el) el.textContent = msg || "";
}

function openExternal(url) {
  if (window.runtime && window.runtime.BrowserOpenURL) window.runtime.BrowserOpenURL(url);
  else window.open(url, "_blank", "noopener");
}

function countryLabel(code) {
  const key = String(code || "").trim().toUpperCase();
  if (!key) return "Сервер";
  return countries[key] || key;
}

function flag(code) {
  const key = String(code || "").trim().toUpperCase();
  if (key.length !== 2) return "⚡";
  return String.fromCodePoint(...[...key].map((ch) => 0x1f1e6 + ch.charCodeAt(0) - 65));
}

function bucket(regionName, country) {
  const r = String(regionName || "").trim().toLowerCase();
  const c = String(country || "").trim().toUpperCase();
  if (r === "europe" || r === "eu" || r.startsWith("eu-") || r.startsWith("eu_") || europe.includes(c)) return "europe";
  if (r === "asia" || r === "apac" || r.startsWith("ap-") || asia.includes(c)) return "asia";
  if (["america", "americas", "us", "na", "sa"].includes(r) || r.startsWith("us-") || america.includes(c)) return "america";
  return "";
}

function daysUntil(iso) {
  if (!iso) return null;
  const day = String(iso).slice(0, 10);
  const t = Date.parse(day + "T00:00:00Z");
  if (Number.isNaN(t)) return null;
  const now = new Date();
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((t - today) / 86400000);
}

function subscriptionActive(iso) {
  const d = daysUntil(iso);
  return d != null && d >= 0;
}

function ruDays(n) {
  const abs = Math.abs(n) % 100;
  const tail = abs % 10;
  if (abs >= 11 && abs <= 14) return "дней";
  if (tail === 1) return "день";
  if (tail >= 2 && tail <= 4) return "дня";
  return "дней";
}

function ruDevices(n) {
  const abs = Math.abs(n) % 100;
  const tail = abs % 10;
  if (abs >= 11 && abs <= 14) return "устройств";
  if (tail === 1) return "устройство";
  if (tail >= 2 && tail <= 4) return "устройства";
  return "устройств";
}

const months = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"];
function formatDate(iso) {
  const day = String(iso || "").slice(0, 10);
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!m) return null;
  return `${Number(m[3])} ${months[Number(m[2]) - 1]} ${m[1]}`;
}

function planPeriod(plan) {
  switch (String(plan || "").toLowerCase()) {
    case "week": return 7;
    case "month": return 30;
    case "quarter":
    case "q3": return 90;
    default: return null;
  }
}

function progress(ends, plan) {
  if (!subscriptionActive(ends)) return 0;
  const period = planPeriod(plan);
  if (!period) return 1;
  const left = daysUntil(ends);
  if (left == null) return 1;
  return Math.max(0, Math.min(1, left / period));
}

function formatMbps(v, ok) {
  if (!ok || v == null || Number.isNaN(v) || v < 0) return "—";
  const n = Math.min(v, 9999);
  return n >= 100 ? String(Math.round(n)) : n.toFixed(1);
}

function signalHTML(ms) {
  const known = ms != null && ms >= 0;
  const lit = !known ? 0 : ms <= 80 ? 3 : ms <= 160 ? 2 : 1;
  const heights = [5, 8, 11];
  const bars = heights.map((h, i) => `<b class="${i < lit ? "on" : ""}" style="height:${h}px"></b>`).join("");
  const label = known ? `${Math.min(ms, 9999)} мс` : "—";
  return `<i>${bars}</i>${label}`;
}

function paintClock() {
  if (!connectedAt) return;
  const sec = Math.max(0, Math.floor((Date.now() - connectedAt) / 1000));
  const mm = String(Math.floor(sec / 60)).padStart(2, "0");
  const ss = String(sec % 60).padStart(2, "0");
  const hint = document.getElementById("status-hint");
  if (hint) hint.textContent = `${mm}:${ss}`;
}

function shownPing(node) {
  const values = Object.values(pings).filter((n) => n >= 0);
  if (!node) return values.length ? Math.min(...values) : null;
  return pings[node] != null ? pings[node] : null;
}

function selectedEndpoint(node) {
  return endpoints.find((ep) => (ep.node || ep.Node) === node) || null;
}

function closeSheet() {
  document.getElementById("sheet").hidden = true;
  document.getElementById("sheet-body").innerHTML = "";
}

function openSheet(title, html) {
  document.getElementById("sheet-title").textContent = title;
  document.getElementById("sheet-body").innerHTML = html;
  document.getElementById("sheet").hidden = false;
}

async function refreshStatus() {
  const a = api();
  if (!a) return null;
  const st = await a.Status();
  const loggedIn = !!(st.logged_in || st.LoggedIn);
  const state = String(pick(st, "state", "State", "disconnected")).toLowerCase();
  const node = pick(st, "selected_node", "SelectedNode", "");
  selectedNode = node || "";
  const ends = pick(st, "ends_at", "EndsAt", "");
  const plan = pick(st, "plan", "Plan", "");
  const home = document.getElementById("screen-home");
  const on = state === "connected";
  home.classList.toggle("on", on || state === "connecting");
  const btn = document.getElementById("btn-connect");
  btn.classList.toggle("on", on);
  btn.classList.toggle("busy", state === "connecting");
  document.getElementById("power-label").textContent = state === "connecting" ? "Отменить" : on ? "Отключить" : "Подключить";
  document.getElementById("power-ico").innerHTML = state === "connecting"
    ? `<svg viewBox="0 0 24 24" width="36" height="36"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="18 12"><animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="0.8s" repeatCount="indefinite"/></circle></svg>`
    : `<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 3v8"/><path d="M7.2 6.2a8 8 0 1 0 9.6 0"/></svg>`;
  document.getElementById("status-text").textContent = state === "connecting" ? "Устанавливаем соединение…" : on ? "Соединение установлено" : "Вы не подключены";
  const hint = document.getElementById("status-hint");
  if (on) {
    if (!connectedAt) connectedAt = Date.now();
    paintClock();
  } else {
    connectedAt = 0;
    hint.textContent = state === "connecting" ? "Можно отменить в любой момент" : "Нажмите кнопку для подключения";
  }
  const ep = selectedEndpoint(node);
  document.getElementById("home-flag").textContent = ep ? flag(ep.country || ep.Country) : "⚡";
  document.getElementById("home-title").textContent = ep ? countryLabel(ep.country || ep.Country) : (node || "Авто");
  document.getElementById("home-detail").textContent = ep
    ? [ep.region || ep.Region, ep.node || ep.Node].filter(Boolean).join(" · ")
    : (node ? "Выбранный сервер" : "Переключение само");
  document.getElementById("home-sub").textContent = ep
    ? `${countryLabel(ep.country || ep.Country)} · ${ep.node || ep.Node}`
    : (node || "Самый быстрый сервер");
  document.getElementById("home-signal").innerHTML = signalHTML(shownPing(node));
  document.getElementById("plus-badge").hidden = !subscriptionActive(ends);
  document.getElementById("plus-badge").dataset.plan = plan;
  if (on) await refreshLink();
  return { loggedIn, state, node, ends, plan, email: pick(st, "email", "Email", "") };
}

async function refreshLink() {
  const a = api();
  if (!a || !a.Link) return;
  const link = await a.Link();
  const ok = !!(link.ok || link.OK);
  const down = link.down_mbps != null ? link.down_mbps : link.DownMbps;
  const up = link.up_mbps != null ? link.up_mbps : link.UpMbps;
  document.getElementById("down-mbps").textContent = formatMbps(down, ok);
  document.getElementById("up-mbps").textContent = formatMbps(up, ok);
}

async function loadLocations() {
  const a = api();
  if (!a) return;
  setErr("loc-err", "");
  try {
    const res = await a.ListServers();
    endpoints = res.endpoints || res.Endpoints || [];
    renderLocations();
    endpoints.forEach((ep) => {
      const host = ep.host || ep.Host;
      const port = ep.port || ep.Port || 443;
      const node = ep.node || ep.Node;
      if (!host || !a.Ping) return;
      a.Ping(host, port).then((ms) => {
        if (ms >= 0) pings[node] = ms;
        renderLocations();
        refreshStatus();
      }).catch(() => {});
    });
  } catch (e) {
    setErr("loc-err", String(e));
  }
}

function renderLocations() {
  const q = document.getElementById("loc-query").value.trim().toLowerCase();
  document.getElementById("loc-clear").hidden = !q;
  const list = document.getElementById("locations-list");
  const results = endpoints.filter((ep) => {
    if (region !== "all" && bucket(ep.region || ep.Region, ep.country || ep.Country) !== region) return false;
    if (!q) return true;
    const hay = [ep.country, ep.Country, countryLabel(ep.country || ep.Country), ep.region, ep.Region, ep.node, ep.Node, ep.protocol, ep.Protocol]
      .filter(Boolean).join(" ").toLowerCase();
    return hay.includes(q);
  });
  document.getElementById("loc-count").textContent = `${results.length} / ${endpoints.length}`;
  const selected = selectedNode;
  list.innerHTML = "";
  const showAuto = !q && region === "all";
  if (showAuto) list.appendChild(locationRow("Авто", "Самый быстрый сервер", "", shownPing(""), !selected, ""));
  results.forEach((ep) => {
    const node = ep.node || ep.Node;
    const code = ep.country || ep.Country || "";
    const detail = [ep.region || ep.Region, node, ep.protocol || ep.Protocol].filter(Boolean).join(" · ");
    list.appendChild(locationRow(countryLabel(code), detail, code, pings[node], node === selected, node));
  });
  const empty = results.length === 0 && !showAuto;
  document.getElementById("loc-empty").hidden = !empty;
  list.hidden = empty && !showAuto;
}

function locationRow(title, detail, code, ping, on, node) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "row" + (on ? " on" : "");
  btn.innerHTML = `<span class="flag">${flag(code)}</span><span class="loc-text"><b>${title}</b><small>${detail}</small></span><span class="signal">${signalHTML(ping)}</span>${on ? "✓" : `<svg class="chev" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m9 6 6 6-6 6"/></svg>`}`;
  btn.addEventListener("click", () => chooseNode(node));
  return btn;
}

async function chooseNode(node) {
  const a = api();
  selectedNode = node || "";
  try {
    await a.SelectNode(node || "");
    const st = await refreshStatus();
    if (st && (st.state === "connected" || st.state === "connecting")) {
      await a.Disconnect();
      await a.Connect();
      await refreshStatus();
    }
    show("home");
  } catch (e) {
    setErr("loc-err", String(e));
  }
}

async function loadAccount() {
  const a = api();
  if (!a || !a.Account) return;
  setErr("account-err", "");
  try {
    const acc = await a.Account();
    const email = pick(acc, "email", "Email", "");
    const plan = pick(acc, "plan", "Plan", "");
    const ends = pick(acc, "ends_at", "EndsAt", "");
    const max = pick(acc, "max_devices", "MaxDevices", 0) || 0;
    const used = pick(acc, "devices_used", "DevicesUsed", 0) || 0;
    const devices = acc.devices || acc.Devices || [];
    const name = (email.split("@")[0] || email || "Focus");
    document.getElementById("avatar").textContent = (name[0] || "F").toUpperCase();
    document.getElementById("who-name").textContent = name;
    document.getElementById("who-email").textContent = email || "FocusVPN";
    document.getElementById("plan-name").textContent = plan || "VPN";
    const active = subscriptionActive(ends);
    document.getElementById("sub-pill").hidden = !active;
    document.getElementById("sub-devices").textContent = active ? `До ${max} ${ruDevices(max)}.` : "Подписка не активна.";
    document.getElementById("sub-until").textContent = formatDate(ends) || "Нет активной подписки";
    const days = daysUntil(ends);
    const daysEl = document.getElementById("sub-days");
    daysEl.hidden = !(active && days != null);
    if (active && days != null) {
      daysEl.querySelector("b").textContent = String(days);
      daysEl.querySelector("span").textContent = ruDays(days);
    }
    document.getElementById("sub-bar").style.width = `${progress(ends, plan) * 100}%`;
    document.getElementById("stat-locs").textContent = String(endpoints.length);
    document.getElementById("stat-devs").textContent = `${used}/${max || "—"}`;
    document.getElementById("menu-devs").textContent = `${used} из ${max}`;
    document.getElementById("screen-account").dataset.devices = JSON.stringify(devices);
  } catch (e) {
    setErr("account-err", String(e));
  }
}

let adminOK = false;

function missingList(rt) {
  const items = (rt && (rt.missing || rt.Missing)) || [];
  return items.map((m) => m.title || m.Title).filter(Boolean);
}

async function ensureRuntime() {
  const a = api();
  if (!a || !a.Runtime) return true;
  const rt = await a.Runtime();
  if (rt.ready || rt.Ready) return true;
  const names = missingList(rt);
  openSheet("Нужно докачать", `
    <p>Без этого подключение не запустится${names.length ? ": " + names.join(", ") : ""}.</p>
    <p>Файл берётся с официального выпуска и кладётся только в папку FocusVPN на этом компьютере.</p>
    <p class="err" id="rt-err"></p>
    <button class="btn" id="rt-go" type="button">Скачать</button>
  `);
  document.getElementById("rt-go").addEventListener("click", async () => {
    const btn = document.getElementById("rt-go");
    btn.disabled = true;
    btn.textContent = "Скачиваем…";
    try {
      await a.InstallRuntime();
      closeSheet();
      await toggleConnect();
    } catch (e) {
      document.getElementById("rt-err").textContent = String(e);
      btn.disabled = false;
      btn.textContent = "Скачать";
    }
  });
  return false;
}

function showAdminSheet() {
  openSheet("Нужны права", `
    <p>Чтобы создать сетевой интерфейс, система спросит разрешение администратора. Это окно Linux или запрос Windows.</p>
    <p class="err" id="adm-err"></p>
    <button class="btn" id="adm-go" type="button">Разрешить</button>
  `);
  document.getElementById("adm-go").addEventListener("click", async () => {
    const btn = document.getElementById("adm-go");
    btn.disabled = true;
    btn.textContent = "Запрашиваем…";
    try {
      if (api().AllowAdmin) await api().AllowAdmin();
      adminOK = true;
      closeSheet();
      await toggleConnect();
    } catch (e) {
      document.getElementById("adm-err").textContent = String(e);
      btn.disabled = false;
      btn.textContent = "Разрешить";
    }
  });
}

async function toggleConnect() {
  if (busy) return;
  const a = api();
  const st = await refreshStatus();
  if (st && (st.state === "connected" || st.state === "connecting")) {
    busy = true;
    setErr("home-err", "");
    try { await a.Disconnect(); } catch (e) { setErr("home-err", String(e)); }
    finally { busy = false; await refreshStatus(); }
    return;
  }
  if (!(await ensureRuntime())) return;
  if (a.Runtime && !adminOK) {
    const rt = await a.Runtime();
    if (rt.need_admin || rt.NeedAdmin) {
      showAdminSheet();
      return;
    }
  }
  busy = true;
  setErr("home-err", "");
  try {
    await a.Connect();
  } catch (e) {
    const msg = String(e);
    if (msg.includes("права администратора")) showAdminSheet();
    else if (msg.includes("не найден xray") || msg.includes("Скачать")) {
      adminOK = false;
      await ensureRuntime();
    } else setErr("home-err", msg);
  } finally {
    busy = false;
    await refreshStatus();
  }
}

function codeSheet() {
  openSheet("Ваш код доступа", `
    <p>Введите код из бота FocusVPN. Это буквы и цифры, которые бот присылает после входа.</p>
    <input id="code-input" class="code-input" maxlength="8" placeholder="КОД" autocomplete="off" />
    <p class="err" id="code-err"></p>
    <button class="btn" id="code-go" type="button" disabled style="margin-top:16px">Войти в Focus</button>
  `);
  const input = document.getElementById("code-input");
  const go = document.getElementById("code-go");
  input.addEventListener("input", () => {
    input.value = input.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8);
    go.disabled = input.value.length < 6;
  });
  go.addEventListener("click", async () => {
    go.disabled = true;
    go.textContent = "Проверяем код…";
    try {
      await api().LoginCode(input.value.trim());
      closeSheet();
      await afterLogin();
    } catch (e) {
      document.getElementById("code-err").textContent = String(e);
      input.classList.add("bad");
      go.disabled = input.value.length < 6;
      go.textContent = "Войти в Focus";
    }
  });
  input.focus();
}

async function telegramLogin() {
  if (busy) return;
  const a = api();
  busy = true;
  setErr("auth-err", "");
  document.getElementById("tg-label").textContent = "Открываем Telegram…";
  try {
    const start = await a.TelegramStart();
    const link = start.deep_link || start.DeepLink;
    const token = start.wait_token || start.WaitToken;
    if (link) openExternal(link);
    document.getElementById("tg-label").textContent = "Ждём подтверждение…";
    busy = false;
    clearInterval(waitTimer);
    const deadline = Date.now() + ((start.expires_in || start.ExpiresIn || 300) * 1000);
    waitTimer = setInterval(async () => {
      if (Date.now() > deadline) {
        clearInterval(waitTimer);
        document.getElementById("tg-label").textContent = "Войти через Telegram";
        setErr("auth-err", "Время ожидания Telegram истекло");
        return;
      }
      try {
        const wait = await a.TelegramWait(token);
        if (wait.ready || wait.Ready) {
          clearInterval(waitTimer);
          document.getElementById("tg-label").textContent = "Войти через Telegram";
          await afterLogin();
        }
      } catch (e) {
        clearInterval(waitTimer);
        document.getElementById("tg-label").textContent = "Войти через Telegram";
        setErr("auth-err", String(e));
      }
    }, 2000);
  } catch (e) {
    busy = false;
    document.getElementById("tg-label").textContent = "Войти через Telegram";
    setErr("auth-err", String(e));
  }
}

async function afterLogin() {
  show("home");
  await refreshStatus();
  await loadLocations();
  await refreshStatus();
}

function paintChips() {
  const host = document.getElementById("loc-chips");
  host.innerHTML = "";
  [["all", "Все"], ["europe", "Европа"], ["asia", "Азия"], ["america", "Америка"]].forEach(([id, label]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.className = id === region ? "on" : "";
    b.addEventListener("click", () => { region = id; paintChips(); renderLocations(); });
    host.appendChild(b);
  });
}

document.getElementById("btn-code").addEventListener("click", codeSheet);
document.getElementById("btn-telegram").addEventListener("click", telegramLogin);
document.getElementById("btn-privacy").addEventListener("click", () => {
  openSheet("О конфиденциальности", `<p>Код входа проверяется на сервере FocusVPN. История сайтов приложением не собирается.</p><p>Российские сайты и приложения идут с IP компьютера. Зарубежный трафик проходит через VPN.</p><button class="btn ghost" id="privacy-ok" type="button">Понятно</button>`);
  document.getElementById("privacy-ok").addEventListener("click", closeSheet);
});
document.getElementById("btn-connect").addEventListener("click", toggleConnect);
document.getElementById("home-location").addEventListener("click", () => show("locations"));
document.getElementById("plus-badge").addEventListener("click", () => show("account"));
document.getElementById("loc-query").addEventListener("input", renderLocations);
document.getElementById("loc-clear").addEventListener("click", () => { document.getElementById("loc-query").value = ""; renderLocations(); });
document.getElementById("loc-reset").addEventListener("click", () => { document.getElementById("loc-query").value = ""; region = "all"; paintChips(); renderLocations(); });
document.querySelectorAll(".tabbar button").forEach((btn) => btn.addEventListener("click", () => show(btn.dataset.nav)));
document.getElementById("sheet-bg").addEventListener("click", closeSheet);
document.getElementById("sheet-close").addEventListener("click", closeSheet);
document.getElementById("btn-manage").addEventListener("click", () => openExternal(BOT));
document.getElementById("btn-about").addEventListener("click", () => {
  openSheet("О Focus VPN", `<p>FocusVPN для Linux и Windows. Туннель — VLESS, тем же маршрутом, что приложение на телефоне.</p><button class="btn ghost" id="about-ok" type="button">Понятно</button>`);
  document.getElementById("about-ok").addEventListener("click", closeSheet);
});
document.querySelectorAll(".menu button").forEach((btn) => btn.addEventListener("click", () => {
  const kind = btn.dataset.sheet;
  if (kind === "support") {
    openSheet("Поможем разобраться", `<p>Напишите боту FocusVPN — там подписка, код входа и помощь.</p><button class="btn" id="open-bot" type="button">Открыть бота</button>`);
    document.getElementById("open-bot").addEventListener("click", () => openExternal(BOT));
  } else if (kind === "privacy") {
    openSheet("Приватность", `<p>История сайтов приложением не собирается. Российские имена и адреса идут мимо туннеля.</p>`);
  } else if (kind === "devices") {
    let devices = [];
    try { devices = JSON.parse(document.getElementById("screen-account").dataset.devices || "[]"); } catch (e) { devices = []; }
    const rows = devices.map((d) => `<div class="device"><b>${d.name || d.Name || "Устройство"}</b><small>${d.platform || d.Platform || ""}</small></div>`).join("") || "<p>Устройств пока нет.</p>";
    openSheet("Ваши устройства", rows);
  }
}));
document.getElementById("btn-logout").addEventListener("click", () => {
  openSheet("Выйти из аккаунта?", `<p>Сессия на этом компьютере будет сброшена. Подписка в Telegram останется.</p><button class="btn" id="logout-go" type="button">Выйти</button>`);
  document.getElementById("logout-go").addEventListener("click", async () => {
    try { await api().Logout(); } catch (e) { setErr("account-err", String(e)); }
    closeSheet();
    endpoints = [];
    pings = {};
    show("auth");
  });
});

async function boot() {
  paintChips();
  const a = api();
  if (!a) {
    setErr("auth-err", "Окно приложения недоступно");
    return;
  }
  try {
    const st = await refreshStatus();
    const hash = location.hash.replace("#", "");
    if (st && st.loggedIn) {
      show("home");
      await loadLocations();
      await refreshStatus();
      if (hash === "locations" || hash === "account") show(hash);
    } else show("auth");
    if (hash === "code") codeSheet();
    if (hash === "flow") {
      await a.LoginCode("AB12CD");
      await afterLogin();
      await toggleConnect();
      show("locations");
      document.getElementById("loc-query").value = "лон";
      renderLocations();
    }
  } catch (e) {
    show("auth");
  }
  setInterval(async () => {
    if (!document.getElementById("screen-home").classList.contains("active")) return;
    paintClock();
    await refreshLink();
    const a = api();
    if (a && a.Tunnel && connectedAt) {
      const tun = String(await a.Tunnel() || "").toLowerCase();
      if (tun === "disconnected" || tun === "error") {
        connectedAt = 0;
        await refreshStatus();
      }
    }
  }, 1000);
}

boot();
