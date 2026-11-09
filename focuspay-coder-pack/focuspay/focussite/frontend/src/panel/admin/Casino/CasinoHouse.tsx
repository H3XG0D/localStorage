import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import {
  ChevronDown,
  ChevronUp,
  ExternalLink,
  MessageCircle,
  Pencil,
  Plus,
  RefreshCw,
  ShieldCheck,
  Wallet,
} from "lucide-react";
import { toast } from "sonner";
import { CasinoHouseReadiness, useHashSectionScroll } from "@/panel/admin/Casino/CasinoHouseReadiness";
import { CasinoRobotProfileEditor } from "@/panel/admin/Casino/CasinoRobotProfileEditor";
import { DEFAULT_TEST_STAKE_RUB } from "@/panel/admin/Casino/casinoHousePresets";
import {
  activateCasinoHousePolicy,
  adjustCasinoHouseAccount,
  createCasinoHousePolicy,
  createCasinoHouseProfile,
  fundCasinoHouseAccount,
  getCasinoHouseAccounts,
  getCasinoHouseLedger,
  getCasinoHousePolicies,
  getCasinoHouseProfiles,
  getCasinoHouseReadiness,
  type AdminCasinoGameType,
  type AdminCasinoHouseAccount,
  type AdminCasinoHouseLedgerEntry,
  type AdminCasinoHousePolicy,
  type AdminCasinoHouseProfile,
  type AdminCasinoHouseReadiness,
} from "@/panel/lib/adminApi";
import { PanelApiError } from "@/panel/lib/panelApi";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, Table, type Column } from "@/panel/ui/primitives";

const GAME_TYPES: AdminCasinoGameType[] = ["cub"];

function message(error: unknown, fallback: string): string {
  return error instanceof PanelApiError ? error.message : fallback;
}

function rub(value: number): string {
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
}

function date(value: string): string {
  return new Date(value).toLocaleString("ru-RU");
}

export function CasinoHouse() {
  const [accounts, setAccounts] = useState<AdminCasinoHouseAccount[]>([]);
  const [profiles, setProfiles] = useState<AdminCasinoHouseProfile[]>([]);
  const [policies, setPolicies] = useState<AdminCasinoHousePolicy[]>([]);
  const [ledger, setLedger] = useState<AdminCasinoHouseLedgerEntry[]>([]);
  const [readiness, setReadiness] = useState<AdminCasinoHouseReadiness | null>(null);
  const [testStake, setTestStake] = useState(String(DEFAULT_TEST_STAKE_RUB));
  const [selectedAccount, setSelectedAccount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accountAction, setAccountAction] = useState<"fund" | "adjust" | null>(null);
  const [profileEditor, setProfileEditor] = useState<AdminCasinoHouseProfile | null>(null);
  const [policyEditorOpen, setPolicyEditorOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [creatingBot, setCreatingBot] = useState(false);
  useHashSectionScroll(!loading);

  const stepRefs = {
    bank: useRef<HTMLElement>(null),
    profiles: useRef<HTMLElement>(null),
    limits: useRef<HTMLElement>(null),
    telegram: useRef<HTMLElement>(null),
  };

  const loadLedger = useCallback(async (accountId: number) => {
    try {
      setLedger(await getCasinoHouseLedger(accountId));
    } catch (loadError) {
      setLedger([]);
      toast.error(message(loadError, "Не удалось загрузить журнал банка"));
    }
  }, []);

  const loadReadiness = useCallback(async (stakeRub?: number) => {
    try {
      setReadiness(
        await getCasinoHouseReadiness({
          game_type: "pvp_dice",
          stake_rub: stakeRub,
        }),
      );
    } catch (loadError) {
      setReadiness(null);
      toast.error(message(loadError, "Не удалось проверить готовность ботов"));
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const stake = Number(testStake);
    const stakeRub = Number.isFinite(stake) && stake > 0 ? stake : DEFAULT_TEST_STAKE_RUB;
    try {
      const [nextAccounts, nextProfiles, nextPolicies] = await Promise.all([
        getCasinoHouseAccounts(),
        getCasinoHouseProfiles(),
        getCasinoHousePolicies(),
      ]);
      setAccounts(nextAccounts);
      setProfiles(nextProfiles);
      setPolicies(nextPolicies);
      const accountId = selectedAccount ?? nextAccounts[0]?.id ?? null;
      setSelectedAccount(accountId);
      if (accountId != null) await loadLedger(accountId);
      else setLedger([]);
      await loadReadiness(stakeRub);
    } catch (loadError) {
      setError(message(loadError, "Не удалось загрузить управление банком казино"));
    } finally {
      setLoading(false);
    }
  }, [loadLedger, loadReadiness, selectedAccount, testStake]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectAccount = (accountId: number) => {
    setSelectedAccount(accountId);
    void loadLedger(accountId);
  };

  const onAccountMutated = (account: AdminCasinoHouseAccount) => {
    setAccounts((items) => items.map((item) => (item.id === account.id ? account : item)));
    void loadLedger(account.id);
    void loadReadiness(Number(testStake) || DEFAULT_TEST_STAKE_RUB);
  };

  const onProfileSaved = (saved: AdminCasinoHouseProfile) => {
    setProfiles((items) => items.map((item) => (item.id === saved.id ? saved : item)));
    setProfileEditor(null);
    void loadReadiness(Number(testStake) || DEFAULT_TEST_STAKE_RUB);
  };

  const createPvpBot = async () => {
    const suffix = profiles.filter((profile) => profile.mode === "pvp_robot").length + 1;
    setCreatingBot(true);
    try {
      const created = await createCasinoHouseProfile({
        profile_key: `pvp-robot-${suffix}`,
        display_name: `PvP Robot ${suffix}`,
        mode: "pvp_robot",
        allowed_games: ["pvp_dice"],
        is_active: true,
      });
      setProfiles((items) => [...items, created]);
      toast.success("PvP-робот создан");
      void loadReadiness(Number(testStake) || DEFAULT_TEST_STAKE_RUB);
    } catch (createError) {
      toast.error(message(createError, "Не удалось создать PvP-робота"));
    } finally {
      setCreatingBot(false);
    }
  };

  const activeAccount = accounts.find((account) => account.id === selectedAccount) ?? null;
  const pvpProfiles = profiles.filter((profile) => profile.mode === "pvp_robot");

  return (
    <div className="space-y-5">
      <PageHeader
        title="Казино — Роботы PvP"
        subtitle="За 2 минуты: пополнить банк → включить ботов → задать лимит проигрыша"
        actions={
          <Button type="button" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden />
            Обновить
          </Button>
        }
      />

      {loading ? (
        <Card className="py-12 text-center text-[13px] text-[var(--text-muted)]" aria-busy="true">
          Загрузка настройки PvP-ботов…
        </Card>
      ) : error ? (
        <Card className="space-y-3">
          <div role="alert" className="text-[13px] text-[var(--red)]">
            {error}
          </div>
          {error.includes("Недостаточно прав") || error.toLowerCase().includes("finance") ? (
            <p className="text-[12px] leading-relaxed text-[var(--text-muted)]">
              Раздел «Роботы PvP» доступен только finance owner (Telegram ID из{" "}
              <span className="font-mono">FINANCE_OWNER_TELEGRAM_ID</span>).
            </p>
          ) : null}
          <Button type="button" size="sm" onClick={() => void load()}>
            Повторить
          </Button>
        </Card>
      ) : (
        <>
          <CasinoHouseReadiness readiness={readiness} />

          <section ref={stepRefs.bank} id="house-step-bank" className="space-y-3 scroll-mt-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-[14px] font-semibold">Шаг 1 — Банк казино</h2>
                <p className="mt-1 max-w-2xl text-[12px] text-[var(--text-muted)]">
                  Это деньги house-счёта. Когда бот проигрывает игроку, выплата идёт из банка. Без
                  свободного баланса стол с ботами не создастся.
                </p>
              </div>
              {activeAccount && (
                <div className="flex gap-2">
                  <Button type="button" size="sm" onClick={() => setAccountAction("fund")}>
                    <Wallet className="h-3.5 w-3.5" aria-hidden />
                    Пополнить
                  </Button>
                  <Button type="button" size="sm" variant="secondary" onClick={() => setAccountAction("adjust")}>
                    <Pencil className="h-3.5 w-3.5" aria-hidden />
                    Корректировка
                  </Button>
                </div>
              )}
            </div>
            {accounts.length === 0 ? (
              <Card className="text-[13px] text-[var(--text-muted)]">Счета house не найдены.</Card>
            ) : (
              <div className="grid gap-4 lg:grid-cols-3">
                {accounts.map((account) => (
                  <button
                    key={account.id}
                    type="button"
                    onClick={() => selectAccount(account.id)}
                    className={`rounded-[var(--radius-lg)] border bg-[var(--bg-surface)] p-5 text-left transition-colors ${
                      selectedAccount === account.id
                        ? "border-[var(--accent)] ring-1 ring-[var(--accent)]/40"
                        : "border-[var(--border)] hover:border-[var(--border-strong)]"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="font-medium text-[13px]">{account.display_name}</div>
                        <div className="mt-1 font-mono text-[11px] text-[var(--text-muted)]">{account.account_key}</div>
                      </div>
                      <Badge tone={account.is_active ? "green" : "red"}>
                        {account.is_active ? "Включён" : "Выключен"}
                      </Badge>
                    </div>
                    <div className="mt-5 grid grid-cols-3 gap-2">
                      <div>
                        <div className="text-[11px] text-[var(--text-muted)]">Баланс</div>
                        <div className="mt-1 font-mono text-[13px] font-semibold">{rub(account.balance_rub)}</div>
                      </div>
                      <div>
                        <div className="text-[11px] text-[var(--text-muted)]">Резерв</div>
                        <div className="mt-1 font-mono text-[13px]">{rub(account.reserved_rub)}</div>
                      </div>
                      <div>
                        <div className="text-[11px] text-[var(--text-muted)]">Свободно</div>
                        <div className="mt-1 font-mono text-[13px] text-[var(--green)]">{rub(account.available_rub)}</div>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>

          <section ref={stepRefs.profiles} id="house-step-profiles" className="space-y-3 scroll-mt-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-[14px] font-semibold">Шаг 2 — PvP-роботы</h2>
                <p className="mt-1 max-w-2xl text-[12px] text-[var(--text-muted)]">
                  Это не Telegram-бот. Здесь настраиваются house-роботы, которые садятся за V2-стол.
                  Нужен тип <span className="font-mono">pvp_robot</span> и игра{" "}
                  <span className="font-mono">pvp_dice</span>.
                </p>
              </div>
              <Button type="button" size="sm" onClick={() => void createPvpBot()} disabled={creatingBot}>
                <Plus className="h-3.5 w-3.5" aria-hidden />
                {creatingBot ? "Создание…" : "Ещё один PvP-бот"}
              </Button>
            </div>
            <div className="grid gap-4 xl:grid-cols-2">
              {profiles.map((profile) => (
                <Card key={profile.id} className="space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-medium text-[13px]">{profile.display_name}</div>
                      <div className="mt-1 font-mono text-[11px] text-[var(--text-muted)]">
                        {profile.profile_key} · {profile.mode}
                      </div>
                    </div>
                    <Badge tone={profile.is_active ? "green" : "default"}>
                      {profile.is_active ? "Включён" : "Выключен"}
                    </Badge>
                  </div>
                  {profile.mode !== "pvp_robot" && (
                    <div className="rounded-[var(--radius)] border border-[var(--yellow)]/30 bg-[var(--yellow-bg)] px-3 py-2 text-[11px] text-[var(--text-secondary)]">
                      Для V2-столов смените тип на PvP-бот в настройках профиля.
                    </div>
                  )}
                  <div className="grid grid-cols-2 gap-3 text-[12px]">
                    <div>
                      <span className="text-[var(--text-muted)]">Ставки: </span>
                      <span className="font-mono">
                        {rub(profile.min_bet_rub)}–{rub(profile.max_bet_rub)}
                      </span>
                    </div>
                    <div>
                      <span className="text-[var(--text-muted)]">Макс. проигрыш: </span>
                      <span className="font-mono">{rub(profile.max_exposure_rub)}</span>
                    </div>
                    <div>
                      <span className="text-[var(--text-muted)]">Параллельно: </span>
                      {profile.max_concurrent_games}
                    </div>
                    <div>
                      <span className="text-[var(--text-muted)]">Игры: </span>
                      {profile.allowed_games.join(", ") || "—"}
                    </div>
                  </div>
                  <Button type="button" size="sm" onClick={() => setProfileEditor(profile)}>
                    <Pencil className="h-3.5 w-3.5" aria-hidden />
                    Настроить
                  </Button>
                </Card>
              ))}
            </div>
            {profiles.length === 0 && (
              <Card className="text-[13px] text-[var(--text-muted)]">Профили роботов не найдены.</Card>
            )}
          </section>

          <section ref={stepRefs.limits} id="house-step-limits" className="space-y-3 scroll-mt-4">
            <div>
              <h2 className="text-[14px] font-semibold">Шаг 3 — Проверка ёмкости</h2>
              <p className="mt-1 max-w-2xl text-[12px] text-[var(--text-muted)]">
                Укажите типичную ставку стола и посмотрите, сколько ботов можно посадить одновременно.
              </p>
            </div>
            <Card className="flex flex-wrap items-end gap-3">
              <Field label="Тестовая ставка (₽)">
                <Input
                  type="number"
                  min="1"
                  step="1"
                  value={testStake}
                  onChange={(event) => setTestStake(event.target.value)}
                />
              </Field>
              <Button
                type="button"
                size="sm"
                onClick={() => void loadReadiness(Number(testStake) || DEFAULT_TEST_STAKE_RUB)}
              >
                Проверить
              </Button>
              {readiness && (
                <p className="text-[13px] text-[var(--text-primary)]">
                  При ставке {rub(readiness.stake_rub)} можно посадить до{" "}
                  <span className="font-semibold">{readiness.max_bots_capacity}</span> бот(ов). Активных
                  PvP-профилей: {pvpProfiles.filter((profile) => profile.is_active).length}.
                </p>
              )}
            </Card>
          </section>

          <section ref={stepRefs.telegram} id="house-step-telegram" className="scroll-mt-4">
            <Card className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 text-[14px] font-semibold">
                  <MessageCircle className="h-4 w-4 text-[var(--text-secondary)]" aria-hidden />
                  Шаг 4 — Telegram-чат (отдельно)
                </div>
                <p className="mt-1 max-w-xl text-[12px] text-[var(--text-muted)]">
                  Привязка игрового Telegram-бота и группы — в разделе «Настройки казино». Это не
                  включает house PvP-роботов.
                </p>
              </div>
              <Link
                to="/x8/casino/settings"
                className="inline-flex items-center gap-1.5 rounded-[var(--radius)] border border-[var(--border-strong)] px-3 py-2 text-[12px] text-[var(--green)] hover:border-[var(--accent)]"
              >
                Настройки казино
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              </Link>
            </Card>
          </section>

          <Card className="space-y-3">
            <button
              type="button"
              className="flex w-full items-center justify-between gap-3 text-left"
              onClick={() => setAdvancedOpen((open) => !open)}
            >
              <div>
                <h2 className="text-[14px] font-semibold">Дополнительно: журнал и Cub</h2>
                <p className="mt-1 text-[12px] text-[var(--text-muted)]">
                  Журнал банка и правила house-игры cub против казино.
                </p>
              </div>
              {advancedOpen ? (
                <ChevronUp className="h-4 w-4 text-[var(--text-muted)]" aria-hidden />
              ) : (
                <ChevronDown className="h-4 w-4 text-[var(--text-muted)]" aria-hidden />
              )}
            </button>

            {advancedOpen && (
              <div className="space-y-5 border-t border-[var(--border)] pt-4">
                <div className="space-y-3">
                  <h3 className="text-[13px] font-semibold">
                    Журнал операций{activeAccount ? ` — ${activeAccount.display_name}` : ""}
                  </h3>
                  <Table columns={ledgerColumns} rows={ledger} empty="Операций пока нет" />
                </div>

                <div className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h3 className="text-[13px] font-semibold">Cub против казино (house_robot)</h3>
                      <p className="mt-1 text-[12px] text-[var(--text-muted)]">
                        Версии правил для cub, не для PvP V2-столов.
                      </p>
                    </div>
                    <Button type="button" size="sm" onClick={() => setPolicyEditorOpen(true)}>
                      <Plus className="h-3.5 w-3.5" aria-hidden />
                      Новая версия
                    </Button>
                  </div>
                  <Table
                    columns={policyColumns((policy) => {
                      if (
                        window.confirm(
                          `Активировать policy ${policy.policy_key} v${policy.version}? Текущая активная версия этой игры будет отключена.`,
                        )
                      ) {
                        void activateCasinoHousePolicy(policy.id)
                          .then(() => {
                            toast.success("Версия правил активирована");
                            void load();
                          })
                          .catch((actionError) =>
                            toast.error(message(actionError, "Не удалось активировать версию правил")),
                          );
                      }
                    })}
                    rows={policies}
                    empty="Версии правил не найдены"
                  />
                </div>
              </div>
            )}
          </Card>
        </>
      )}

      {activeAccount && accountAction && (
        <AccountMutationModal
          account={activeAccount}
          mode={accountAction}
          onClose={() => setAccountAction(null)}
          onSaved={onAccountMutated}
        />
      )}
      {profileEditor && (
        <CasinoRobotProfileEditor
          profile={profileEditor}
          onClose={() => setProfileEditor(null)}
          onSaved={onProfileSaved}
        />
      )}
      {policyEditorOpen && (
        <PolicyModal
          onClose={() => setPolicyEditorOpen(false)}
          onSaved={() => {
            setPolicyEditorOpen(false);
            void load();
          }}
        />
      )}
    </div>
  );
}

const ledgerColumns: Column<AdminCasinoHouseLedgerEntry>[] = [
  { key: "created_at", label: "Дата", render: (item) => date(item.created_at) },
  {
    key: "entry_type",
    label: "Операция",
    render: (item) => <span className="font-mono text-[12px]">{item.entry_type}</span>,
  },
  {
    key: "amount_rub",
    label: "Сумма",
    align: "right",
    render: (item) => (
      <span className={`font-mono ${item.amount_rub >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
        {item.amount_rub >= 0 ? "+" : ""}
        {rub(item.amount_rub)}
      </span>
    ),
  },
  {
    key: "balance_after_rub",
    label: "Баланс",
    align: "right",
    render: (item) => <span className="font-mono">{rub(item.balance_after_rub)}</span>,
  },
  { key: "reason", label: "Причина" },
];

function policyColumns(onActivate: (policy: AdminCasinoHousePolicy) => void): Column<AdminCasinoHousePolicy>[] {
  return [
    {
      key: "policy_key",
      label: "Политика",
      render: (item) => (
        <div>
          <div className="font-medium">{item.policy_key}</div>
          <div className="font-mono text-[11px] text-[var(--text-muted)]">
            v{item.version} · {item.game_type}
          </div>
        </div>
      ),
    },
    {
      key: "payout_multiplier",
      label: "Выплата",
      align: "right",
      render: (item) => <span className="font-mono">×{item.payout_multiplier}</span>,
    },
    {
      key: "win_probability",
      label: "Вероятность",
      align: "right",
      render: (item) => (
        <span className="font-mono">
          {(item.win_probability * 100).toLocaleString("ru-RU", { maximumFractionDigits: 4 })}%
        </span>
      ),
    },
    {
      key: "is_active",
      label: "Статус",
      render: (item) =>
        item.is_active ? (
          <Badge tone="green">Активна</Badge>
        ) : (
          <Button type="button" size="sm" onClick={() => onActivate(item)}>
            Активировать
          </Button>
        ),
    },
  ];
}

function AccountMutationModal({
  account,
  mode,
  onClose,
  onSaved,
}: {
  account: AdminCasinoHouseAccount;
  mode: "fund" | "adjust";
  onClose: () => void;
  onSaved: (account: AdminCasinoHouseAccount) => void;
}) {
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    const amountRub = Number(amount);
    if (
      !Number.isFinite(amountRub) ||
      amountRub === 0 ||
      (mode === "fund" && amountRub < 0) ||
      !reason.trim()
    ) {
      toast.error(mode === "fund" ? "Укажите положительную сумму и причину" : "Укажите ненулевую сумму и причину");
      return;
    }
    const verb = mode === "fund" ? "Пополнить" : "Скорректировать";
    if (!window.confirm(`${verb} банк на ${rub(amountRub)}? Операция будет внесена в неизменяемый журнал.`)) return;
    setSaving(true);
    try {
      const saved =
        mode === "fund"
          ? await fundCasinoHouseAccount(account.id, {
              amount_rub: amountRub,
              reason: reason.trim(),
              idempotency_key: crypto.randomUUID(),
            })
          : await adjustCasinoHouseAccount(account.id, {
              amount_rub: amountRub,
              reason: reason.trim(),
              idempotency_key: crypto.randomUUID(),
            });
      onSaved(saved);
      toast.success("Операция банка сохранена");
      onClose();
    } catch (submitError) {
      toast.error(message(submitError, "Не удалось выполнить операцию банка"));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal
      open
      title={mode === "fund" ? "Пополнение банка" : "Корректировка банка"}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={saving}>
            Отмена
          </Button>
          <Button type="button" variant="primary" onClick={() => void submit()} disabled={saving}>
            {saving ? "Сохранение…" : "Подтвердить"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-[12px] text-[var(--text-muted)]">
          Счёт: {account.display_name}. Свободно до операции: {rub(account.available_rub)}.
        </p>
        <Field label={mode === "fund" ? "Сумма пополнения (₽)" : "Сумма корректировки (₽)"}>
          <Input
            type="number"
            step="0.01"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            placeholder={mode === "fund" ? "1000" : "-100 или 100"}
            disabled={saving}
          />
        </Field>
        <Field label="Причина">
          <Input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Основание операции"
            disabled={saving}
          />
        </Field>
      </div>
    </Modal>
  );
}

function PolicyModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [key, setKey] = useState("");
  const [gameType, setGameType] = useState<AdminCasinoGameType>("cub");
  const [multiplier, setMultiplier] = useState("2");
  const [probability, setProbability] = useState("0.5");
  const [terms, setTerms] = useState("{}");
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    let parsedTerms: Record<string, unknown>;
    try {
      parsedTerms = JSON.parse(terms) as Record<string, unknown>;
      if (Array.isArray(parsedTerms) || !parsedTerms) throw new Error();
    } catch {
      toast.error("Terms должны быть JSON-объектом");
      return;
    }
    const payout = Number(multiplier);
    const probabilityValue = Number(probability);
    if (
      !key.trim() ||
      !Number.isFinite(payout) ||
      payout < 0 ||
      !Number.isFinite(probabilityValue) ||
      probabilityValue <= 0 ||
      probabilityValue >= 1
    ) {
      toast.error("Проверьте ключ, выплату и вероятность");
      return;
    }
    setSaving(true);
    try {
      await createCasinoHousePolicy({
        policy_key: key.trim(),
        game_type: gameType,
        payout_multiplier: payout,
        win_probability: probabilityValue,
        terms: parsedTerms,
      });
      toast.success("Версия правил создана");
      onSaved();
    } catch (submitError) {
      toast.error(message(submitError, "Не удалось создать версию правил"));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal
      open
      title="Новая версия правил"
      onClose={onClose}
      size="lg"
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={saving}>
            Отмена
          </Button>
          <Button type="button" variant="primary" onClick={() => void submit()} disabled={saving}>
            {saving ? "Создание…" : "Создать версию"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Ключ policy">
          <Input value={key} onChange={(event) => setKey(event.target.value)} placeholder="cub-standard" />
        </Field>
        <Field label="Игра">
          <Select value={gameType} onChange={(event) => setGameType(event.target.value as AdminCasinoGameType)}>
            {GAME_TYPES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Множитель выплаты">
          <Input
            type="number"
            min="0"
            step="0.000001"
            value={multiplier}
            onChange={(event) => setMultiplier(event.target.value)}
          />
        </Field>
        <Field label="Вероятность выигрыша (0–1)">
          <Input
            type="number"
            min="0"
            max="1"
            step="0.00000001"
            value={probability}
            onChange={(event) => setProbability(event.target.value)}
          />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Terms (JSON)">
            <textarea
              value={terms}
              onChange={(event) => setTerms(event.target.value)}
              className="min-h-28 w-full rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-3 font-mono text-[12px] outline-none focus:border-[var(--text-muted)]"
            />
          </Field>
        </div>
        <div className="sm:col-span-2 flex items-start gap-2 rounded-[var(--radius)] border border-[var(--yellow)]/30 bg-[var(--yellow-bg)] p-3 text-[12px] text-[var(--text-secondary)]">
          <ShieldCheck className="h-4 w-4 shrink-0 text-[var(--yellow)]" aria-hidden />
          После создания версия не активируется автоматически. Проверьте параметры и активируйте её отдельно.
        </div>
      </div>
    </Modal>
  );
}
