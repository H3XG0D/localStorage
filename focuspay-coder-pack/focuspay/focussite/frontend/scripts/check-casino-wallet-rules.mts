/**
 * Casino wallet amount/fee rules (client-only until APIs land).
 * Run: npx tsx scripts/check-casino-wallet-rules.mts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  CARD_STEP_RUB,
  CARD_MIN_WITHDRAW_RUB,
  CARD_WITHDRAW_FEE_RUB,
  BTC_WITHDRAW_FEE_USD,
  LTC_WITHDRAW_FEE_USD,
  TRX_WITHDRAW_FEE_USD,
  CASHIER_DEPOSIT_METHODS,
  CASHIER_WITHDRAW_METHODS,
  WITHDRAW_CHIPS_RUB,
  amountStepError,
  availableAfterWagering,
  cashierAmountError,
  cashierWithdrawFeeSubtitle,
  cashierWithdrawSpec,
  isMultipleOfCardStep,
  parseRubAmount,
  payoutAmountRub,
  spendableBalanceRub,
  stubCashierDepositRequisites,
  stubDepositRequisites,
  withdrawalCancellable,
  withdrawalPhase,
  WITHDRAWAL_PHASE_COPY,
  isActiveWithdrawal,
  shortRequisites,
  withdrawNetworkFeeRub,
  withdrawSubmitError,
  CASINO_PENDING_MAX,
  CASINO_PENDING_MAX_MSG,
  casinoCreateBlockReason,
  casinoCreateWaitMessage,
  latestWithdrawalCreatedAtMs,
  withdrawalStatusTone,
  gameResultTone,
  isCasinoGameLedgerNote,
  isCasinoDepositLedgerNote,
  ledgerKind,
  isDepositLedgerEntry,
  depositLedgerTitle,
  unpackLedgerEntries,
  walletCountLabel,
  withdrawalsForHistoryTab,
} from "../src/casino/casinoWalletRules.ts";
import { formatFeeLabel } from "../src/casino/casinoCurrency.ts";
import {
  currentCommissionHeadline,
  formatPct,
  levelCommissionPair,
  nextLevelCopy,
} from "../src/casino/casinoLevelCopy.ts";

assert.equal(CARD_STEP_RUB, 250);
assert.equal(CARD_MIN_WITHDRAW_RUB, 20000);
assert.deepEqual([...WITHDRAW_CHIPS_RUB], [20000, 30000, 50000]);
assert.equal(isMultipleOfCardStep(250), true);
assert.equal(isMultipleOfCardStep(500), true);
assert.equal(isMultipleOfCardStep(2500), true);
assert.equal(isMultipleOfCardStep(100), false);
assert.equal(isMultipleOfCardStep(249), false);
assert.equal(isMultipleOfCardStep(251), false);
assert.equal(isMultipleOfCardStep(0), false);
assert.equal(isMultipleOfCardStep(-250), false);
assert.equal(parseRubAmount("1 000"), 1000);
assert.equal(parseRubAmount("250,00"), 250);
assert.equal(amountStepError(100), "Сумма должна быть кратна 250 ₽");
assert.equal(amountStepError(250), null);

assert.deepEqual(withdrawNetworkFeeRub("card", null, 80), { feeRub: 100, feeUsd: 1.25 });
assert.deepEqual(withdrawNetworkFeeRub("crypto", "btc", 80), { feeRub: 200, feeUsd: 2.5 });
assert.deepEqual(withdrawNetworkFeeRub("crypto", "ltc", 80), { feeRub: 200, feeUsd: 2.5 });
assert.deepEqual(withdrawNetworkFeeRub("crypto", "usdt", 80), { feeRub: 320, feeUsd: 4 });
assert.deepEqual(withdrawNetworkFeeRub("crypto", "usdt", null), { feeRub: null, feeUsd: 4 });
assert.deepEqual(withdrawNetworkFeeRub("crypto", "btc", null), { feeRub: null, feeUsd: 2.5 });
assert.deepEqual(withdrawNetworkFeeRub("crypto", "trx", 80), { feeRub: 200, feeUsd: 2.5 });
assert.equal(CARD_WITHDRAW_FEE_RUB, 100);
assert.equal(BTC_WITHDRAW_FEE_USD, 2.5);
assert.equal(LTC_WITHDRAW_FEE_USD, 2.5);
assert.equal(TRX_WITHDRAW_FEE_USD, 2.5);
assert.equal(formatFeeLabel({ feeRub: 200, feeUsd: 2.5 }, "rub", 80), "200 ₽");
assert.equal(formatFeeLabel({ feeRub: 200, feeUsd: 2.5 }, "usdt", 80), "2.50 USDT");
assert.equal(formatFeeLabel({ feeRub: 100, feeUsd: 1.25 }, "usdt", 80), "1.25 USDT");
assert.equal(cashierWithdrawFeeSubtitle("card", "100 ₽"), "от 20 000 ₽ · комиссия 100 ₽");
assert.equal(cashierWithdrawFeeSubtitle("btc", "2.50 USDT"), "комиссия 2.50 USDT");

assert.equal(payoutAmountRub(250, 0), 250);
assert.equal(payoutAmountRub(500, 100), 400);
assert.equal(payoutAmountRub(1000, 200), 800);
assert.equal(payoutAmountRub(1000, 400), 600);
assert.equal(payoutAmountRub(250, null), null);

assert.equal(
  withdrawSubmitError({
    amountRub: 250,
    method: "card",
    crypto: null,
    usdtRub: 80,
    requisites: "2200700123456789",
    availableRub: 1000,
  }),
  "Минимум для карты: 20 000 ₽",
);
assert.equal(
  withdrawSubmitError({
    amountRub: 20000,
    method: "card",
    crypto: null,
    usdtRub: 80,
    requisites: "2200700123456789",
    availableRub: 20000,
  }),
  null,
);
assert.equal(
  withdrawSubmitError({
    amountRub: 250,
    method: "crypto",
    crypto: "usdt",
    usdtRub: 80,
    requisites: "Txxxxxxxx",
    availableRub: 1000,
  }),
    "Сумма слишком мала: комиссия 320.00 ₽",
);
assert.equal(
  withdrawSubmitError({
    amountRub: 1000,
    method: "crypto",
    crypto: "usdt",
    usdtRub: 80,
    requisites: "Txxxxxxxx",
    availableRub: 1000,
  }),
  null,
);
assert.equal(
  withdrawSubmitError({
    amountRub: 20000,
    method: "card",
    crypto: null,
    usdtRub: null,
    requisites: "2200",
  }),
  "Укажите номер карты",
);

const cardStub = stubDepositRequisites("card", 1000);
assert.equal(cardStub.methodLabel, "Карта");
assert.equal(cardStub.lines.at(-1)?.value, "1 000 ₽");
const sbpStub = stubDepositRequisites("sbp", 250);
assert.equal(sbpStub.methodLabel, "СБП");
assert.equal(sbpStub.lines.at(-1)?.value, "250 ₽");

assert.equal(availableAfterWagering(1000, 400), 600);
assert.equal(availableAfterWagering(100, 400), 0);
assert.equal(spendableBalanceRub({ available_rub: 6790.3, balance_rub: 7290.3 }), 6790.3);
assert.equal(spendableBalanceRub({ balance_rub: 7290.3 }), 7290.3);
assert.equal(spendableBalanceRub(null), 0);
assert.equal(withdrawalPhase({ status: "pending" }), "awaiting");
assert.equal(withdrawalPhase({ status: "pending", operator_id: 3 }), "processing");
assert.equal(withdrawalPhase({ phase: "processing", status: "pending" }), "processing");
assert.equal(isActiveWithdrawal({ phase: "awaiting" }), true);
assert.equal(isActiveWithdrawal({ phase: "paid" }), false);
assert.equal(withdrawalCancellable({ cancellable: true }), true);
assert.equal(withdrawalCancellable({ cancellable: false, phase: "awaiting" }), false);
assert.equal(WITHDRAWAL_PHASE_COPY.processing.hint.includes("3 часов"), true);
assert.equal(shortRequisites("card", "2200700123456789"), "•••• 6789");
assert.equal(CASINO_PENDING_MAX, 5);
assert.equal(
  casinoCreateBlockReason({ activeCount: 5 }),
  CASINO_PENDING_MAX_MSG,
);
assert.equal(casinoCreateBlockReason({ activeCount: 1, lastCreatedAtMs: null }), null);
assert.equal(
  casinoCreateWaitMessage(1_000, 1_000 + 60_000),
  "Следующую заявку можно создать через 4 мин.",
);
assert.equal(casinoCreateWaitMessage(1_000, 1_000 + 5 * 60_000), null);
assert.equal(
  latestWithdrawalCreatedAtMs([{ created_at: "2026-09-01T10:00:00Z" }, { created_at: "2026-09-01T12:00:00Z" }]),
  Date.parse("2026-09-01T12:00:00Z"),
);
assert.equal(withdrawalStatusTone("awaiting"), "pending");
assert.equal(withdrawalStatusTone("processing"), "pending");
assert.equal(withdrawalStatusTone("paid"), "success");
assert.equal(withdrawalStatusTone("rejected"), "fail");
assert.equal(withdrawalStatusTone("canceled"), "fail");
assert.equal(gameResultTone("win"), "success");
assert.equal(gameResultTone("loss"), "fail");
assert.equal(gameResultTone("refund"), "fail");
assert.equal(gameResultTone("push"), "neutral");
assert.equal(isCasinoDepositLedgerNote("Casino deposit: external deal #9", "casino-deposit-9"), true);
assert.equal(isCasinoGameLedgerNote("Casino v2 stake: t1"), true);
assert.equal(isCasinoGameLedgerNote("Casino win: g1"), true);
assert.equal(isCasinoGameLedgerNote("Casino volume level bonus at 500 ₽ weekly wager"), false);
assert.equal(isCasinoGameLedgerNote("FocusLucky, 2 место"), true);
assert.equal(isCasinoGameLedgerNote("Fixed room refund fr-1"), true);
assert.equal(ledgerKind({ type: "accrual", note: "Casino deposit: external deal #2" }), "deposit");
assert.equal(ledgerKind({ type: "spend", note: "Casino v2 stake: t1" }), "game");
assert.equal(ledgerKind({ type: "accrual", note: "Casino win: g1" }), "game");
assert.equal(ledgerKind({ type: "adjustment", note: "FocusLucky, 2 место", amount_rub: 2500 }), "game");
assert.equal(ledgerKind({ type: "accrual", note: "Fixed room refund fr-1", amount_rub: 50 }), "game");
assert.equal(ledgerKind({ type: "accrual", note: "Casino volume level bonus at 500 ₽ weekly wager", order_id: "clb:1" }), "deposit");
assert.equal(ledgerKind({ type: "accrual", note: "Казино: недельный кешбек 2%" }), "deposit");
assert.equal(ledgerKind({ type: "adjustment", note: "Промокод HELLO", amount_rub: 250 }), "deposit");
assert.equal(ledgerKind({ type: "adjustment", note: "FocusLucky, 1 место", amount_rub: 4000 }), "game");
assert.equal(ledgerKind({ type: "hold", note: "something" }), "other");
assert.equal(isDepositLedgerEntry({ type: "spend", note: "Casino v2 stake: t1" }), false);
assert.equal(depositLedgerTitle({ note: "Casino deposit: external deal #4" }), "Пополнение");
assert.equal(depositLedgerTitle({ note: "Casino volume level bonus at 500", order_id: "clb:1" }), "Бонус уровня");
assert.equal(depositLedgerTitle({ note: "Казино: недельный кешбек 2%" }), "Кешбэк");
assert.equal(walletCountLabel(false, 3), "—");
assert.equal(walletCountLabel(true, 3), "3");
assert.equal(walletCountLabel(true, 0), "0");
assert.equal(unpackLedgerEntries({ entries: [{ note: "a" }] }).length, 1);
assert.equal(unpackLedgerEntries([{ note: "a" }, { note: "b" }]).length, 2);
assert.deepEqual(
  withdrawalsForHistoryTab([
    { id: 1, phase: "paid" },
    { id: 2, phase: "awaiting" },
    { id: 3, phase: "canceled" },
    { id: 4, phase: "processing" },
  ]).map((row) => row.id),
  [2, 4, 1, 3],
);

const profileSource = readFileSync(new URL("../src/casino/CasinoProfile.tsx", import.meta.url), "utf8");
assert.equal(profileSource.includes("/user/balance/withdraw"), false);
assert.equal(profileSource.includes('value="0"'), false);
assert.equal(profileSource.includes("walletCountLabel"), true);
assert.equal(profileSource.includes("getLedger"), true);
assert.equal(profileSource.includes("getWithdrawals"), true);
assert.equal(profileSource.includes("/user/referral/withdraw"), false);
assert.equal(profileSource.includes("withdraw("), false);
assert.equal(profileSource.includes("data-casino-next-level"), true);
assert.equal(profileSource.includes("data-casino-commission"), true);
assert.equal(profileSource.includes("data-casino-own-profile"), true);
assert.equal(profileSource.includes("CASINO_BALANCE_EVENT"), true);
assert.equal(profileSource.includes("spendableBalanceRub"), true);
assert.equal(profileSource.includes("data-casino-deposit"), false);
assert.equal(profileSource.includes("data-casino-withdraw"), false);
assert.equal(profileSource.includes("data-casino-deposit-modal"), false);

const cashierSource = readFileSync(new URL("../src/casino/CasinoCashier.tsx", import.meta.url), "utf8");
assert.equal(cashierSource.includes("/user/balance/withdraw"), false);
assert.equal(cashierSource.includes("await withdraw("), true);
assert.equal(cashierSource.includes('source: "casino"'), true);
assert.equal(cashierSource.includes("data-casino-deposit-soon"), false);
assert.equal(cashierSource.includes("Пополнение скоро"), false);
assert.equal(cashierSource.includes("data-casino-crypto-deposit"), true);
assert.equal(cashierSource.includes("issueCasinoCryptoAddress"), true);
assert.equal(cashierSource.includes("Зачислим после 1 подтверждения по курсу продажи"), true);
assert.equal(cashierSource.includes("bc1qfocuspaydemo"), false);
assert.equal(cashierSource.includes("ltc1qfocuspaydemo"), false);
assert.equal(cashierSource.includes("stubCashierDepositRequisites"), false);
assert.equal(cashierSource.includes("depositStubOpen"), false);
assert.equal(cashierSource.includes("CASHIER_DEPOSIT_METHODS"), false);
assert.equal(cashierSource.includes("/user/balance/deposit"), false);
assert.equal(cashierSource.includes("data-casino-deposit"), true);
assert.equal(cashierSource.includes("data-casino-withdraw"), true);
assert.equal(cashierSource.includes("data-casino-deposit-modal"), true);
assert.equal(cashierSource.includes("data-casino-withdraw-modal"), true);
assert.equal(cashierSource.includes("casino-cashier-tabs"), false);
assert.equal(cashierSource.includes("WITHDRAW_CHIPS_RUB"), true);
assert.equal(cashierSource.includes("CARD_MIN_WITHDRAW_RUB"), true);
assert.equal(cashierSource.includes("CASINO_BALANCE_EVENT"), true);
assert.equal(cashierSource.includes("setInterval(reloadMoney, 5000)"), true);
assert.equal(cashierSource.includes("cancelWithdrawal"), true);
assert.equal(cashierSource.includes("data-casino-cashier-active"), true);
assert.equal(cashierSource.includes("data-casino-withdraw-gate"), true);
assert.equal(cashierSource.includes("casinoCreateBlockReason"), true);
assert.equal(cashierSource.includes("CasinoWithdrawalCard"), true);
assert.equal(cashierSource.includes("setMethodId(null)"), true);
assert.equal(cashierSource.includes("formatFeeLabel"), true);
assert.equal(cashierSource.includes("useCasinoCurrency"), true);
assert.equal(cashierSource.includes("feeLabelText"), false);
assert.equal(cashierSource.includes("create_withdrawal"), false);

const shellSource = readFileSync(new URL("../src/casino/CasinoShell.tsx", import.meta.url), "utf8");
assert.equal(shellSource.includes("data-casino-header-deposit"), true);
assert.equal(shellSource.includes("data-casino-header-withdraw"), true);
assert.equal(shellSource.includes("spendableBalanceRub"), true);
assert.equal(shellSource.includes("casino-brand-sub"), false);
assert.equal(shellSource.includes("data-casino-search"), false);
assert.equal(shellSource.includes("casino-header-search"), false);
assert.equal(shellSource.includes("useCasinoCurrency"), true);
assert.equal(shellSource.includes("focuspay_casino_currency"), false);

const cssSource = readFileSync(new URL("../src/casino/casino.css", import.meta.url), "utf8");
assert.equal(cssSource.includes("casino-cashier-tabs"), false);
assert.equal(cssSource.includes("casino-brand-sub"), false);
assert.equal(cssSource.includes("casino-header-search"), false);
assert.equal(cssSource.includes("casino-status-badge"), true);
assert.equal(cssSource.includes('data-casino-status-tone="pending"'), true);
assert.equal(cssSource.includes('data-casino-status-tone="success"'), true);
assert.equal(cssSource.includes('data-casino-status-tone="fail"'), true);
assert.match(cssSource, /background:\s*rgba\(0,\s*0,\s*0,\s*0\.72\)/);
assert.match(cssSource, /\.casino-tile-grid[\s\S]{0,160}minmax\(200px,\s*1fr\)/);
assert.match(cssSource, /\.casino-profile-history-grid[\s\S]{0,160}minmax\(280px/);
assert.match(cssSource, /\.casino-profile-history-actions \.casino-btn[\s\S]{0,80}min-height:\s*26px/);
assert.equal(profileSource.includes("casino-profile-history-grid"), true);

const lobbySource = readFileSync(new URL("../src/casino/CasinoLobby.tsx", import.meta.url), "utf8");
assert.equal(lobbySource.includes("data-casino-search-results"), false);
assert.equal(lobbySource.includes("fuzzySearch"), false);

const walletSource = readFileSync(new URL("../src/casino/CasinoWallet.tsx", import.meta.url), "utf8");
assert.equal(walletSource.includes("/user/balance/withdraw"), false);
assert.equal(walletSource.includes("getWithdrawals"), true);
assert.equal(walletSource.includes("getLedger"), true);
assert.equal(walletSource.includes("getCasinoPlayerHistory"), true);
assert.equal(walletSource.includes("data-casino-wallet-history"), true);
assert.equal(walletSource.includes("data-casino-wallet-active"), true);
assert.equal(walletSource.includes('data-casino-wallet-tab="deposit"'), true);
assert.equal(walletSource.includes('data-casino-wallet-tab="withdraw"'), true);
assert.equal(walletSource.includes('data-casino-wallet-tab="games"'), true);
assert.equal(walletSource.includes("cancelWithdrawal"), true);
assert.equal(walletSource.includes("CasinoWithdrawalCard"), true);
assert.equal(walletSource.includes("До 5 заявок в работе"), true);
assert.equal(walletSource.includes("CASINO_BALANCE_EVENT"), true);
assert.equal(walletSource.includes("setInterval(reload, 5000)"), true);
assert.equal(walletSource.includes("spendableBalanceRub"), true);
assert.equal(walletSource.includes("isDepositLedgerEntry"), true);
assert.equal(walletSource.includes("gameResultTone"), true);
assert.equal(walletSource.includes("walletCountLabel"), true);
assert.equal(walletSource.includes('value="0"'), false);

const wdCardSource = readFileSync(new URL("../src/casino/CasinoWithdrawalCard.tsx", import.meta.url), "utf8");
assert.equal(wdCardSource.includes("casino-status-badge"), true);
assert.equal(wdCardSource.includes("withdrawalStatusTone"), true);

const opsPayouts = readFileSync(new URL("../src/panel/operator/OperatorCasinoPayouts.tsx", import.meta.url), "utf8");
assert.equal(opsPayouts.includes("getCasinoPayouts"), true);
assert.equal(opsPayouts.includes("rejectCasinoPayout"), true);
assert.equal(opsPayouts.includes("Передать на выплату"), true);
assert.equal(opsPayouts.includes("На выплате · обычно до 3 часов"), true);
assert.equal(opsPayouts.includes("Взять в работу"), false);
assert.equal(opsPayouts.includes("CasinoCreatorPayouts"), false);
assert.equal(opsPayouts.includes("К выплате ₽"), true);
assert.equal(opsPayouts.includes("payoutFigures"), true);

const opsRoutes = readFileSync(new URL("../src/panel/operator/OperatorRoutes.tsx", import.meta.url), "utf8");
assert.equal(opsRoutes.includes("/ops/casino-payouts"), true);
assert.equal(opsRoutes.includes("casino.payout"), true);

assert.equal(CASHIER_DEPOSIT_METHODS.length, 7);
assert.equal(CASHIER_WITHDRAW_METHODS.length, 7);
assert.equal(CASHIER_WITHDRAW_METHODS[0]?.subtitle, "от 20 000 ₽ · комиссия 100 ₽");
assert.equal(CASHIER_WITHDRAW_METHODS[1]?.subtitle, "комиссия $4");
assert.equal(CASHIER_WITHDRAW_METHODS[4]?.subtitle, "комиссия $2.50");
assert.equal(CASHIER_WITHDRAW_METHODS[5]?.subtitle, "комиссия $2.50");
assert.equal(CASHIER_WITHDRAW_METHODS[6]?.id, "trx");
assert.equal(CASHIER_WITHDRAW_METHODS[6]?.subtitle, "комиссия $2.50");
assert.equal(cashierAmountError("sbp", 100), "Сумма должна быть кратна 250 ₽");
assert.equal(cashierAmountError("card", 250), null);
assert.equal(cashierAmountError("btc", 100), null);
assert.equal(cashierAmountError("btc", 0), "Укажите сумму");
assert.deepEqual(cashierWithdrawSpec("card"), { method: "card", crypto: null, network: null });
assert.deepEqual(cashierWithdrawSpec("usdt_trc20"), { method: "crypto", crypto: "usdt", network: "TRC20" });
assert.deepEqual(cashierWithdrawSpec("trx"), { method: "crypto", crypto: "trx", network: null });
assert.equal(stubCashierDepositRequisites("btc", 1000).methodLabel, "Bitcoin");
assert.equal(stubCashierDepositRequisites("sbp", 250).methodLabel, "СБП");

const ownLevel = {
  index: 1,
  cashback_percent: "2.00",
  commission_complete_rate: "5.00",
  commission_active_rate: "15.00",
};
const nextLevel = {
  index: 2,
  cashback_percent: "5.00",
  commission_complete_rate: "4.00",
  commission_active_rate: "12.00",
  remaining_wager_rub: "3859.00",
  reach_bonus_rub: "500.00",
};
assert.equal(formatPct("5.00"), "5%");
assert.equal(formatPct("2.50"), "2.5%");
assert.equal(
  currentCommissionHeadline({
    level: ownLevel,
    next_level: nextLevel,
    own: { commission_profile: "wagering_complete", commission_rate: "5.00" },
  }),
  "Комиссия сейчас 5%",
);
assert.equal(levelCommissionPair(ownLevel), "Комиссия 5%");
assert.match(
  nextLevelCopy(
    { is_own: true, level: ownLevel, next_level: nextLevel },
    { includeBonus: true },
  ),
  /500/,
);
assert.doesNotMatch(
  nextLevelCopy(
    { is_own: false, level: ownLevel, next_level: nextLevel },
    { includeBonus: false },
  ),
  /500/,
);
assert.match(
  nextLevelCopy({
    is_own: true,
    level: ownLevel,
    next_level: nextLevel,
  }),
  /комиссия 4% \(сейчас 5%\)/,
);
assert.equal(
  nextLevelCopy({
    level: { ...ownLevel, index: 5, commission_active_rate: "8.00", commission_complete_rate: "2.50" },
    next_level: null,
    own: { commission_rate: "2.50" },
  }),
  "Максимальный уровень. Комиссия 2.5%.",
);
assert.doesNotMatch(
  nextLevelCopy({
    is_own: true,
    level: { ...ownLevel, commission_active_rate: "8.00", commission_complete_rate: "2.50", cashback_percent: "10.00" },
    next_level: {
      index: 5,
      cashback_percent: "15.00",
      commission_active_rate: "8.00",
      commission_complete_rate: "2.50",
      remaining_wager_rub: "100000",
      reach_bonus_rub: "5000.00",
    },
  }),
  /комиссия/,
);

console.log("check-casino-wallet-rules: ok");
