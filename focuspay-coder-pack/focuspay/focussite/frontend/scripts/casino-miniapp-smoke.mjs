// UI integration smoke with a synthetic Telegram bridge and intercepted API.
// No request is allowed to leave localhost. Run against Vite on port 5187.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true });
const output = process.env.SMOKE_OUTPUT || '/tmp/casino-miniapp-smoke';
await mkdir(output, { recursive: true });
try {
  for (const theme of ['light', 'dark']) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => { errors.push(error.message); console.error(error.message); });
    let rolls = 0, balances = 0, logins = 0;
    const table = { table_id: 'qa', game_type: 'pvp_dice', status: 'running', state_version: 1,
      stake_rub: '10.00', pot_rub: '20.00', commission_rub: '1.00', max_seats: 2,
      my_seat_no: 1, can_roll: true, can_start: false, can_add_bot: false,
      free_seats: [], game_state: { phase: 'rolling', rounds: 1, rolls: {} },
      roster: [1,2].map(n => ({ seat_no: n, participant_kind: 'player', is_you: n === 1,
        pips: null, actor: { id: n, display_name: `QA ${n}`, level: 1 } })),
    };
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.hostname !== '127.0.0.1') return route.abort();
      if (!url.pathname.startsWith('/api/')) return route.continue();
      let body = {}, status = 200;
      if (url.pathname === '/api/auth/me') { body = { detail: 'unauthorized' }; status = 401; }
      else if (url.pathname.endsWith('/telegram-miniapp')) {
        assert.equal(route.request().postDataJSON().init_data, 'synthetic-ui-credentials');
        logins++; body = { access_token: 'synthetic-ui-session', user: { id: 1, telegram_id: 123, display_name: 'QA' } };
      } else if (url.pathname.endsWith('/tables/qa/roll')) {
        rolls++; await new Promise(resolve => setTimeout(resolve, 100));
        body = { table: { ...table, state_version: 2, can_roll: false, game_state: { ...table.game_state, rolls: { s1r0: 5 } } } };
      } else if (url.pathname.endsWith('/tables/qa')) body = { ...table }; // Deliberately stale poll after the action.
      else if (url.pathname.endsWith('/balance')) { balances++; body = { available_rub: 90, total_rub: 90 }; }
      else if (url.pathname.endsWith('/lobby')) body = { games: [], open_duels: [], open_rooms: [], stats: {} };
      else if (url.pathname.includes('/inbox')) body = { items: [], sessions: [], unread: 0 };
      else if (url.pathname.includes('/players/me')) body = { actor: { id: 1, display_name: 'QA' }, stats: {}, profile: {} };
      else if (url.pathname.includes('/chat')) body = { messages: [], items: [] };
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.addInitScript(({ theme }) => {
      const events = {};
      const button = () => ({ isVisible: false, handlers: new Set(), text: '',
        show() { this.isVisible = true; }, hide() { this.isVisible = false; },
        setText(text) { this.text = text; }, setParams() {},
        onClick(fn) { this.handlers.add(fn); }, offClick(fn) { this.handlers.delete(fn); },
      });
      const themeParams = theme === 'light' ? { bg_color: '#ffffff', text_color: '#111111' } : { bg_color: '#0a0a0a', text_color: '#ffffff' };
      window.Telegram = { WebApp: { initData: 'synthetic-ui-credentials', platform: 'android', themeParams,
        viewportStableHeight: 844, ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {},
        MainButton: button(), BackButton: button(),
        onEvent(name, fn) { (events[name] ||= new Set()).add(fn); },
        offEvent(name, fn) { events[name]?.delete(fn); },
      } };
      window.qaEvents = events;
    }, { theme });
    await page.goto('http://127.0.0.1:5187/casino/tg/tables/qa');
    await page.waitForSelector('[data-casino-v2-table="qa"]');
    await page.waitForFunction(() => window.Telegram.WebApp.MainButton.isVisible);
    assert.equal(logins, 1);
    assert.equal(await page.evaluate(() => document.documentElement.style.colorScheme), theme);
    assert.equal(await page.evaluate(() => window.Telegram.WebApp.BackButton.isVisible), true);
    await page.evaluate(() => { const handlers = [...window.Telegram.WebApp.MainButton.handlers]; handlers.forEach(fn => { fn(); fn(); }); });
    await page.waitForTimeout(1600);
    assert.equal(rolls, 1, 'double tap must create one action');
    assert.equal(await page.evaluate(() => window.Telegram.WebApp.MainButton.isVisible), false, 'stale polling must not restore old controls');
    assert.ok(balances >= 2, 'balance must be refreshed after action');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, 'no horizontal overflow');
    await page.screenshot({ path: `${output}/${theme}.png`, fullPage: true });
    await page.evaluate(() => window.Telegram.WebApp.BackButton.handlers.forEach(fn => fn()));
    await page.waitForURL('**/casino/tg');
    await page.waitForFunction(() => !window.Telegram.WebApp.BackButton.isVisible);
    assert.equal(await page.evaluate(() => window.Telegram.WebApp.BackButton.isVisible), false);
    assert.deepEqual(errors, []);
    console.log(`PASS ${theme}: Telegram login, MainButton dedupe, stale poll, balance refresh, Back, mobile layout`);
    await context.close();
  }
} finally { await browser.close(); }
