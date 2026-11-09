const REASONS: Record<string, string> = {
  payfast: "Payfast ещё не подтвердил оплату",
  payfast_waiting: "Ждём подтверждения оплаты Payfast",
  payfast_not_paid_order: "Заявка не оплачена",
  payfast_live: "Payfast сейчас не подтверждает оплату",
  payfast_not_paid: "Payfast: оплаты ещё нет",
  payfast_awaiting_trader: "Payfast: ждёт подтверждения трейдера",
  payfast_check_pending: "Payfast: чек на проверке",
  payfast_recheck_requested: "Payfast: запрошена перепроверка",
  payfast_wait_timeout: "Payfast не подтвердил за 2 часа — отдано оператору",
  payfast_api_error: "Payfast не ответил",
  payfast_uuid_missing: "Заявка без привязки к Payfast",
  coin: "Монета не BTC/LTC",
  amount_cap: "Сумма выше лимита автопилота",
  not_banned: "Клиент забанен",
  override: "Автопилот выключен для клиента",
  paid_buys: "Мало оплаченных покупок",
  whitelist: "Клиента нет в белом списке",
  signer: "Кошелёк недоступен (предохранитель открыт)",
  hot_balance: "Мало денег на горячем кошельке",
  daily_cap: "Исчерпан дневной лимит выплат",
  no_address: "Нет адреса кошелька",
  no_crypto_amount: "Нет суммы монет",
  on_shift: "Оператор на смене — ведёт он",
  sell_requires_shift: "Продажа — только через оператора",
  user_override_off: "Автопилот выключен для клиента",
  user_override_on: "Автопилот включён вручную для клиента",
  amount_over_cap: "Сумма выше лимита автопилота",
  not_whitelisted: "Клиента нет в белом списке",
  insufficient_paid_buys: "Мало оплаченных покупок",
  auto_disabled: "Автопилот выключен",
  signer_circuit_open: "Кошелёк недоступен (предохранитель открыт)",
  shadow_would_auto: "Тест: выдали бы реквизиты автоматически",
  eligible: "Подходит — реквизиты выданы автоматически",
  gate_error: "Ошибка проверки — отправлено оператору",
  insufficient_funds: "Не хватило денег на горячем кошельке",
  funds_wait_timeout: "Пополнение не подтвердилось вовремя — отдано оператору",
  mempool_chain_limit: "Слишком длинная цепочка неподтверждённых — ждём блока",
  signer_rejected: "Кошелёк отказал",
  "signer_rejected:insufficient_funds": "Кошелёк: не хватило денег",
  "signer_rejected:mempool_chain_limit": "Кошелёк: длинная цепочка неподтверждённых",
};

export const TOPUP_ERRORS: Record<string, string> = {
  disabled: "На кошельке выключены доверенные пополнения (TRUSTED_TOPUPS_ENABLED)",
  not_in_wallet: "Такой транзакции нет в горячем кошельке",
  already_confirmed: "Уже подтверждено — доверять не нужно",
  conflicted: "Транзакция заменена или отменена",
  dropped: "Транзакции нет в mempool",
  not_incoming: "Это не входящий перевод",
  cap_exceeded: "Превышен лимит неподтверждённых доверенных пополнений",
  rpc_error: "Нода не ответила",
};

export const REQUEUE_ERRORS: Record<string, string> = {
  not_found: "Заявка не найдена",
  wrong_status: "Заявка уже не в статусе «завершена»",
  already_paid: "У заявки уже есть хеш выплаты",
  already_sent: "По заявке уже есть отправка",
  manual_send: "Заявку ведёт оператор с кошелька проекта",
  not_funds_failure: "Заявка ушла оператору не из-за нехватки денег",
};

export function reasonLabel(key: unknown): string {
  const k = String(key ?? "");
  if (REASONS[k]) return REASONS[k];
  const base = k.split(":")[0];
  return REASONS[base] ?? (k || "—");
}

export const CHECK_LABELS: Record<string, string> = {
  payfast: "Оплата Payfast",
  payfast_live: "Payfast сейчас",
  coin: "Монета BTC/LTC",
  amount_cap: "Сумма в лимите",
  not_banned: "Нет бана",
  override: "Настройка клиента",
  paid_buys: "Оплаченных покупок до заявки",
  whitelist: "Белый список",
  signer: "Кошелёк на связи",
  hot_balance: "Баланс горячего кошелька",
  daily_cap: "Дневной лимит",
};

export const MOMENT_BADGE: Record<string, { label: string; tone: "green" | "yellow" | "red" | "default" }> = {
  would_send_now: { label: "Сейчас ушло бы", tone: "green" },
  would_send: { label: "Ушло бы", tone: "green" },
  waiting_payfast: { label: "После Payfast", tone: "yellow" },
  blocked_now: { label: "Сейчас нет", tone: "yellow" },
  manual: { label: "Вручную", tone: "default" },
  already_sent: { label: "Уже ушло", tone: "default" },
};

export const PAYOUT_STATUS: Record<string, { label: string; tone: "green" | "yellow" | "red" | "default" }> = {
  queued: { label: "В очереди", tone: "yellow" },
  sent: { label: "Отправлено", tone: "green" },
  confirmed: { label: "Подтверждено", tone: "green" },
  failed: { label: "Ошибка", tone: "red" },
  requeued: { label: "Повтор", tone: "yellow" },
};
