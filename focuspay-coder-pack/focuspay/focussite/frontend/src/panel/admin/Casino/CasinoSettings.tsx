import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { Bot, CheckCircle2, Clock3, MessageCircle, RefreshCw, Unlink } from "lucide-react";
import { toast } from "sonner";
import { useHashSectionScroll } from "@/panel/admin/Casino/CasinoHouseReadiness";
import {
  assignCasinoCreatorAccount,
  confirmCasinoGameChatBinding,
  disableCasinoGameChatBinding,
  getCasinoBotStatus,
  getCasinoCreatorAccount,
  getCasinoGameChatBinding,
  getCasinoSettings,
  patchCasinoSettings,
  revokeCasinoCreatorAccount,
  type AdminCasinoBotStatus,
  type AdminCasinoCreatorAccount,
  type AdminCasinoGameChatBinding,
} from "@/panel/lib/adminApi";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  Button,
  Card,
  DangerZone,
  Field,
  Input,
  Modal,
  PageHeader,
  SaveBar,
  SettingsSection,
  ValidationSummary,
  useDirtyForm,
} from "@/panel/ui/primitives";
import {
  CasinoTierGrids,
  bonusesFromApi,
  cashbackTiersFromApi,
  cashbackTierErrors,
  commissionTiersFromApi,
  commissionTierErrors,
  parseBonusesForSave,
  parseCashbackTiersForSave,
  parseCommissionTiersForSave,
  type BonusRow,
  type CashbackTierRow,
  type CommissionTierRow,
} from "@/panel/admin/Casino/CasinoTierGrids";
import {
  GAME_OPTIONS,
  SECTION_HINTS,
  SETTINGS_SECTIONS,
  cloneSnapshot,
  countDirtySections,
  isFormDirty,
  liveCommissionExample,
  liveWageringExample,
  toForm,
  validateForm,
  type NumericField,
  type SettingsForm,
  type SettingsSectionId,
  type SettingsSnapshot,
} from "@/panel/admin/Casino/casinoSettingsModel";

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof PanelApiError ? error.message : fallback;
}

function ToggleRow({
  id,
  label,
  checked,
  disabled,
  onChange,
}: {
  id?: string;
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-3 rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-3 text-[13px] hover:bg-[var(--bg-overlay)]">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        disabled={disabled}
        className="h-4 w-4 accent-[var(--accent)]"
      />
      <span>{label}</span>
    </label>
  );
}

function NumField({
  id,
  label,
  value,
  disabled,
  onChange,
  step = "1",
  min,
  max,
}: {
  id: string;
  label: string;
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
  step?: string;
  min?: string;
  max?: string;
}) {
  return (
    <Field label={label}>
      <Input
        id={id}
        type="number"
        step={step}
        min={min}
        max={max}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </Field>
  );
}

function LiveExample({ form }: { form: SettingsForm }) {
  const house = liveCommissionExample(form);
  const wager = liveWageringExample(form);
  return (
    <div className="space-y-3 rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-3 text-[12.5px] leading-relaxed">
      {house ? (
        <p className="font-mono text-[var(--text-primary)]">
          Банк {house.bankRub.toLocaleString("ru-RU")} ₽, комиссия {house.commissionRub.toFixed(0)} ₽, доля создателя{" "}
          {house.creatorRub.toFixed(0)} ₽, EV игрока {house.evPct.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%
        </p>
      ) : (
        <p className="text-[var(--red)]">Доли не должны превышать комиссию — пример не считается.</p>
      )}
      {wager ? (
        <p className="text-[var(--text-secondary)]">
          Пример: депозит {wager.deposit.toFixed(0)} ₽ → казино должно получить {wager.houseTake.toFixed(2)} ₽ комиссии
          {wager.stakeNeeded != null && wager.commission != null
            ? ` → при комиссии ${wager.commission}% нужно поставить ${wager.stakeNeeded.toFixed(2)} ₽`
            : ""}
          .
        </p>
      ) : null}
      <p className="text-[11px] text-[var(--text-muted)]">
        Банк — две равные ставки. Комиссия и доля создателя берутся с проигравшей ставки. EV при честной 50/50 ≈ минус
        половина комиссии.
      </p>
    </div>
  );
}

function SettingsAside({
  active,
  form,
}: {
  active: SettingsSectionId;
  form: SettingsForm;
}) {
  const hint = SECTION_HINTS[active];
  return (
    <aside className="hidden w-[320px] shrink-0 xl:block">
      <div className="sticky top-4 space-y-4">
        <nav className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-surface)] p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Секции</p>
          <ul className="flex flex-col gap-0.5">
            {SETTINGS_SECTIONS.map((section) => (
              <li key={section.id}>
                <a
                  href={`#section-${section.id}`}
                  className={
                    active === section.id
                      ? "block rounded-[var(--radius)] bg-[var(--bg-elevated)] px-2 py-1.5 text-[12.5px] text-[var(--text-primary)]"
                      : "block rounded-[var(--radius)] px-2 py-1.5 text-[12.5px] text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]"
                  }
                >
                  {section.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-surface)] p-4">
          <h3 className="text-[13px] font-semibold">{hint.title}</h3>
          <p className="mt-2 text-[12.5px] leading-relaxed text-[var(--text-muted)]">{hint.body}</p>
        </div>
        {active === "commission" ? <LiveExample form={form} /> : null}
      </div>
    </aside>
  );
}

function CasinoChatBindingCard() {
  const [binding, setBinding] = useState<AdminCasinoGameChatBinding | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<"confirm" | "disable" | null>(null);
  const [botStatus, setBotStatus] = useState<AdminCasinoBotStatus | null>(null);

  const loadBinding = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [bindingResult, statusResult] = await Promise.allSettled([
        getCasinoGameChatBinding(),
        getCasinoBotStatus(),
      ]);
      if (bindingResult.status === "fulfilled") {
        setBinding(bindingResult.value);
      } else {
        setBinding(null);
        setError(getErrorMessage(bindingResult.reason, "Не удалось загрузить привязку игрового чата"));
      }
      setBotStatus(statusResult.status === "fulfilled" ? statusResult.value : null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadBinding();
  }, [loadBinding]);

  const confirmBinding = async () => {
    if (!binding || acting) return;
    if (!window.confirm("Подтвердить этот чат для PVP-игр? Текущий активный чат будет отключён.")) return;
    setActing("confirm");
    setError(null);
    try {
      setBinding(await confirmCasinoGameChatBinding(binding.id));
      toast.success("Игровой чат подтверждён и активирован");
    } catch (actionError) {
      const message = getErrorMessage(actionError, "Не удалось подтвердить игровой чат");
      setError(message);
      toast.error(message);
    } finally {
      setActing(null);
    }
  };

  const disableBinding = async () => {
    if (!binding || acting) return;
    const description =
      binding.status === "active"
        ? "Отключить активный игровой чат? Новые PVP-игры в нём больше не будут доступны."
        : "Отклонить запрос на привязку игрового чата?";
    if (!window.confirm(description)) return;
    setActing("disable");
    setError(null);
    try {
      await disableCasinoGameChatBinding(binding.id);
      setBinding(null);
      toast.success(binding.status === "active" ? "Игровой чат отключён" : "Запрос на привязку отклонён");
    } catch (actionError) {
      const message = getErrorMessage(actionError, "Не удалось отключить игровой чат");
      setError(message);
      toast.error(message);
    } finally {
      setActing(null);
    }
  };

  const title = binding?.chat_title?.trim() || "Без названия";
  const updatedAt = binding?.updated_at ? new Date(binding.updated_at).toLocaleString("ru-RU") : null;

  return (
    <Card id="section-chat" className="space-y-4 scroll-mt-20">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <MessageCircle className="h-4 w-4 text-[var(--text-secondary)]" aria-hidden />
            <h2 className="text-[14px] font-semibold">Telegram-чат PVP-игр</h2>
          </div>
          <p className="mt-1 text-[12px] text-[var(--text-muted)]">
            Бот отправляет запрос из группы, а активация доступна только после подтверждения здесь.
          </p>
        </div>
        <Button type="button" size="sm" onClick={() => void loadBinding()} disabled={loading || acting !== null}>
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          Обновить статус
        </Button>
      </div>

      {botStatus && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 py-2 text-[12px]">
          <span className="text-[var(--text-muted)]">Игровой бот:</span>
          {botStatus.configured && botStatus.username ? (
            <>
              <span className="font-mono text-[var(--text-primary)]">@{botStatus.username}</span>
              {botStatus.deep_link && (
                <a
                  href={botStatus.deep_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-mono text-[11px] text-[var(--text-secondary)] underline underline-offset-2"
                >
                  {botStatus.deep_link}
                </a>
              )}
            </>
          ) : (
            <span className="text-[var(--yellow)]">username не задан в конфигурации</span>
          )}
        </div>
      )}

      {error && (
        <div role="alert" className="text-[13px] text-[var(--red)]">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-[13px] text-[var(--text-muted)]" aria-busy="true">
          Загрузка статуса привязки…
        </div>
      ) : !binding ? (
        <div className="rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-4">
          <div className="flex items-center gap-2 text-[13px] font-medium">
            <Clock3 className="h-4 w-4 text-[var(--text-muted)]" aria-hidden />
            Статус: чат не привязан
          </div>
          <p className="mt-2 text-[12px] leading-relaxed text-[var(--text-muted)]">
            Добавьте игрового бота в нужную группу и выполните его команду привязки. После этого здесь появится запрос на
            подтверждение.
          </p>
        </div>
      ) : binding.status === "pending" ? (
        <div className="rounded-[var(--radius)] border border-[var(--yellow)]/30 bg-[var(--yellow-bg)] p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-[13px] font-semibold text-[var(--yellow)]">
                <Clock3 className="h-4 w-4" aria-hidden />
                Ожидает подтверждения
              </div>
              <div className="mt-2 text-[13px] text-[var(--text-primary)]">{title}</div>
              <div className="mt-1 font-mono text-[11px] text-[var(--text-muted)]">
                {binding.chat_type} · {binding.chat_id}
              </div>
              {binding.telegram_url && (
                <a
                  href={binding.telegram_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1 inline-block font-mono text-[11px] text-[var(--text-secondary)] underline underline-offset-2"
                >
                  Открыть игровой чат
                </a>
              )}
              {updatedAt && <div className="mt-1 text-[11px] text-[var(--text-muted)]">Запрошено: {updatedAt}</div>}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" size="sm" variant="danger" onClick={() => void disableBinding()} disabled={acting !== null}>
                <Unlink className="h-3.5 w-3.5" aria-hidden />
                {acting === "disable" ? "Отклонение…" : "Отклонить"}
              </Button>
              <Button type="button" size="sm" variant="primary" onClick={() => void confirmBinding()} disabled={acting !== null}>
                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
                {acting === "confirm" ? "Подтверждение…" : "Подтвердить"}
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-[13px] font-semibold">
                <CheckCircle2 className="h-4 w-4" aria-hidden />
                Активный игровой чат
              </div>
              <div className="mt-2 text-[13px] text-[var(--text-primary)]">{title}</div>
              <div className="mt-1 font-mono text-[11px] text-[var(--text-muted)]">
                {binding.chat_type} · {binding.chat_id}
              </div>
              {binding.telegram_url && (
                <a
                  href={binding.telegram_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1 inline-block font-mono text-[11px] text-[var(--text-secondary)] underline underline-offset-2"
                >
                  Открыть игровой чат
                </a>
              )}
              {binding.confirmed_at && (
                <div className="mt-1 text-[11px] text-[var(--text-muted)]">
                  Подтверждён: {new Date(binding.confirmed_at).toLocaleString("ru-RU")}
                </div>
              )}
            </div>
            <Button type="button" size="sm" variant="danger" onClick={() => void disableBinding()} disabled={acting !== null}>
              <Unlink className="h-3.5 w-3.5" aria-hidden />
              {acting === "disable" ? "Отключение…" : "Отключить чат"}
            </Button>
          </div>
        </div>
      )}

      <div className="rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-4 text-[12px] leading-relaxed text-[var(--text-muted)]">
        <h3 className="text-[12px] font-semibold text-[var(--text-secondary)]">Подготовка бота в BotFather</h3>
        <ol className="mt-2 list-decimal space-y-1 pl-4">
          <li>Откройте @BotFather и выберите уже используемого игрового бота.</li>
          <li>
            В <span className="font-mono">/setprivacy</span> отключите Group Privacy, чтобы бот получал игровые сообщения
            в группе.
          </li>
          <li>Добавьте бота в нужную группу и выдайте права, требуемые сценарием игр.</li>
          <li>Выполните команду привязки, которую отправляет игровой бот, затем вернитесь сюда и подтвердите запрос.</li>
        </ol>
        <p className="mt-2">Токен бота и другие секреты в панели не вводятся и не отображаются.</p>
      </div>
    </Card>
  );
}

export function CasinoSettings() {
  const [form, setForm] = useState<SettingsForm | null>(null);
  const [baseline, setBaseline] = useState<SettingsSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [focusToken, setFocusToken] = useState(0);
  const [reasonOpen, setReasonOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [activeSection, setActiveSection] = useState<SettingsSectionId>("commission");
  const [creator, setCreator] = useState<AdminCasinoCreatorAccount | null>(null);
  const [creatorUserId, setCreatorUserId] = useState("");
  const [creatorLoading, setCreatorLoading] = useState(true);
  const [creatorSaving, setCreatorSaving] = useState(false);
  const [creatorError, setCreatorError] = useState<string | null>(null);
  useHashSectionScroll(Boolean(form) && !loading);
  const [cashbackTiers, setCashbackTiers] = useState<CashbackTierRow[]>([]);
  const [commissionTiers, setCommissionTiers] = useState<CommissionTierRow[]>([]);
  const [bonusRows, setBonusRows] = useState<BonusRow[]>([]);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const settings = await getCasinoSettings();
      const nextForm = toForm(settings);
      const nextCashback = cashbackTiersFromApi(settings.cashback_volume_tiers);
      const nextCommission = commissionTiersFromApi(settings.commission_volume_tiers);
      const nextBonuses = bonusesFromApi(settings.level_reach_bonuses);
      setForm(nextForm);
      setCashbackTiers(nextCashback);
      setCommissionTiers(nextCommission);
      setBonusRows(nextBonuses);
      setBaseline(cloneSnapshot(nextForm, nextCashback, nextCommission, nextBonuses));
    } catch (error) {
      setForm(null);
      setBaseline(null);
      setLoadError(getErrorMessage(error, "Не удалось загрузить настройки казино"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const loadCreator = useCallback(async () => {
    setCreatorLoading(true);
    setCreatorError(null);
    try {
      setCreator(await getCasinoCreatorAccount());
    } catch (error) {
      setCreatorError(getErrorMessage(error, "Не удалось загрузить creator-доступ"));
    } finally {
      setCreatorLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCreator();
  }, [loadCreator]);

  useEffect(() => {
    if (!form) return;
    const root = document.querySelector("[data-panel-scroll]");
    if (!(root instanceof Element)) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const hit = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top)[0];
        const id = hit?.target.id.replace(/^section-/, "");
        if (id && SETTINGS_SECTIONS.some((section) => section.id === id)) {
          setActiveSection(id as SettingsSectionId);
        }
      },
      { root, rootMargin: "-12% 0px -70% 0px", threshold: [0.1, 0.25] },
    );
    for (const section of SETTINGS_SECTIONS) {
      const node = document.getElementById(`section-${section.id}`);
      if (node) observer.observe(node);
    }
    return () => observer.disconnect();
  }, [form]);

  const assignCreator = async () => {
    const webUserId = Number(creatorUserId);
    if (!Number.isInteger(webUserId) || webUserId <= 0) {
      setCreatorError("Укажите корректный ID существующего аккаунта сайта");
      return;
    }
    setCreatorSaving(true);
    setCreatorError(null);
    try {
      const account = await assignCasinoCreatorAccount(webUserId);
      setCreator(account);
      setCreatorUserId("");
      toast.success("Доступ к кабинету создателя выдан");
    } catch (error) {
      setCreatorError(getErrorMessage(error, "Не удалось выдать creator-доступ"));
    } finally {
      setCreatorSaving(false);
    }
  };

  const revokeCreator = async () => {
    if (!creator || creatorSaving) return;
    setCreatorSaving(true);
    setCreatorError(null);
    try {
      await revokeCasinoCreatorAccount();
      setCreator(null);
      toast.success("Доступ к кабинету создателя отозван");
    } catch (error) {
      setCreatorError(getErrorMessage(error, "Не удалось отозвать creator-доступ"));
    } finally {
      setCreatorSaving(false);
    }
  };

  const updateNumber = (field: NumericField, value: string) => {
    setForm((current) => {
      if (!current) return current;
      const next = { ...current, [field]: value };
      if (field === "commission_rate_wagering_active" || field === "commission_rate_wagering_complete") {
        setCommissionTiers((rows) => {
          if (!rows.length) return rows;
          const synced = [...rows];
          synced[0] = {
            ...synced[0],
            active_rate: field === "commission_rate_wagering_active" ? value : synced[0].active_rate,
            complete_rate: field === "commission_rate_wagering_complete" ? value : synced[0].complete_rate,
          };
          return synced;
        });
      }
      return next;
    });
    setSaveError(null);
  };

  const validation = useMemo(() => {
    const formResult = form ? validateForm(form) : { errors: [] as { id: string; message: string }[] };
    const tierErrors = [...cashbackTierErrors(cashbackTiers), ...commissionTierErrors(commissionTiers)];
    const errors = [...formResult.errors, ...tierErrors];
    return { errors, snapshot: errors.length ? undefined : formResult.snapshot };
  }, [form, cashbackTiers, commissionTiers]);
  const dirty =
    Boolean(form && baseline) &&
    isFormDirty(
      form!,
      baseline!.form,
      cashbackTiers,
      baseline!.cashbackTiers,
      commissionTiers,
      baseline!.commissionTiers,
      bonusRows,
      baseline!.bonusRows,
    );
  const dirtySectionCount =
    form && baseline
      ? countDirtySections(
          form,
          baseline.form,
          cashbackTiers,
          baseline.cashbackTiers,
          commissionTiers,
          baseline.commissionTiers,
          bonusRows,
          baseline.bonusRows,
        )
      : 0;
  const invalid = dirty && validation.errors.length > 0;
  useDirtyForm(dirty);

  const discard = () => {
    if (!baseline) return;
    const restored = cloneSnapshot(baseline.form, baseline.cashbackTiers, baseline.commissionTiers, baseline.bonusRows);
    setForm(restored.form);
    setCashbackTiers(restored.cashbackTiers);
    setCommissionTiers(restored.commissionTiers);
    setBonusRows(restored.bonusRows);
    setSaveError(null);
    setReason("");
  };

  const requestSave = () => {
    if (!form || saving) return;
    if (validation.errors.length) {
      setSaveError(validation.errors[0]?.message ?? "Проверьте значения формы");
      setFocusToken((token) => token + 1);
      toast.error(validation.errors[0]?.message ?? "Проверьте значения формы");
      return;
    }
    setReasonOpen(true);
  };

  const saveSettings = async () => {
    if (!form || saving) return;
    const trimmedReason = reason.trim();
    if (!trimmedReason) {
      setSaveError("Укажите причину изменения");
      toast.error("Укажите причину изменения");
      document.getElementById("casino-settings-reason")?.focus();
      return;
    }
    if (!validation.snapshot) {
      setSaveError(validation.errors[0]?.message ?? "Проверьте значения формы");
      setFocusToken((token) => token + 1);
      toast.error(validation.errors[0]?.message ?? "Проверьте значения формы");
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const saved = await patchCasinoSettings({
        ...validation.snapshot,
        reason: trimmedReason,
        cashback_volume_tiers: parseCashbackTiersForSave(cashbackTiers),
        commission_volume_tiers: parseCommissionTiersForSave(commissionTiers),
        level_reach_bonuses: parseBonusesForSave(bonusRows),
      });
      const nextForm = toForm(saved);
      const nextCashback = cashbackTiersFromApi(saved.cashback_volume_tiers);
      const nextCommission = commissionTiersFromApi(saved.commission_volume_tiers);
      const nextBonuses = bonusesFromApi(saved.level_reach_bonuses);
      setForm(nextForm);
      setCashbackTiers(nextCashback);
      setCommissionTiers(nextCommission);
      setBonusRows(nextBonuses);
      setBaseline(cloneSnapshot(nextForm, nextCashback, nextCommission, nextBonuses));
      setReason("");
      setReasonOpen(false);
      toast.success("Настройки сохранены");
    } catch (error) {
      const message = getErrorMessage(error, "Не удалось сохранить настройки");
      setSaveError(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="w-full space-y-5">
      <PageHeader title="Казино — Настройки" subtitle="Одна страница: секции, живой расчёт, сохранение только при изменениях" />

      <Card className="flex flex-wrap items-center justify-between gap-3 border-[var(--accent)]/30 bg-[var(--bg-elevated)]">
        <div className="flex items-start gap-3">
          <Bot className="mt-0.5 h-5 w-5 shrink-0 text-[var(--accent)]" aria-hidden />
          <div>
            <div className="text-[14px] font-semibold text-[var(--text-primary)]">PvP-боты за столом (банк и лимиты)</div>
            <p className="mt-1 max-w-xl text-[12px] leading-relaxed text-[var(--text-muted)]">
              Это не Telegram-бот ниже. Чтобы играть с ботами за V2-столом: пополните банк, включите PvP-роботов и задайте
              макс. проигрыш — в отдельном разделе.
            </p>
          </div>
        </div>
        <Link
          to="/x8/casino/house"
          className="inline-flex items-center gap-1.5 rounded-[var(--radius)] border border-[var(--accent)] bg-[var(--accent)]/10 px-3 py-2 text-[12px] font-medium text-[var(--text-primary)] hover:bg-[var(--accent)]/20"
        >
          Открыть «Роботы PvP»
        </Link>
      </Card>

      {loading ? (
        <Card className="py-12 text-center text-[13px] text-[var(--text-muted)]" aria-busy="true">
          Загрузка настроек…
        </Card>
      ) : loadError ? (
        <Card className="space-y-3">
          <div role="alert" className="text-[13px] text-[var(--red)]">
            {loadError}
          </div>
          <Button type="button" size="sm" onClick={() => void loadSettings()}>
            Повторить
          </Button>
        </Card>
      ) : !form ? (
        <Card className="py-12 text-center text-[13px] text-[var(--text-muted)]">Настройки не получены</Card>
      ) : (
        <div className="flex w-full items-start gap-6">
          <div className="flex min-w-0 flex-1 flex-col gap-5">
            <ValidationSummary errors={dirty ? validation.errors : []} focusToken={focusToken} />
            {saveError ? (
              <div className="rounded-[var(--radius)] border border-[var(--red)]/30 bg-[var(--red-bg)] px-3 py-2.5 text-[13px] text-[var(--red)]" role="alert">
                {saveError}
              </div>
            ) : null}

            <div className="xl:hidden">
              <LiveExample form={form} />
            </div>

            <Card id="section-commission" className="scroll-mt-20">
              <SettingsSection
                title="Комиссия и доли"
                description="Все проценты — доля от проигранной ставки, не от банка. Профиль «до отыгрыша» действует, пока депозит не закрыт комиссией. На уровнях выше первой ступени Creator, L1 и L2 режутся пропорционально комиссии игрока."
              >
                <NumField
                  id="field-wagering_percent"
                  label="Отыгрыш от пополнения (%)"
                  step="0.01"
                  min="0"
                  max="100"
                  value={form.wagering_percent}
                  disabled={saving}
                  onChange={(value) => updateNumber("wagering_percent", value)}
                />
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="flex flex-col gap-3">
                    <p className="text-[12px] font-semibold text-[var(--text-secondary)]">До отыгрыша</p>
                    <NumField id="field-commission_rate_wagering_active" label="Комиссия (%)" step="0.01" min="0" max="100" value={form.commission_rate_wagering_active} disabled={saving} onChange={(value) => updateNumber("commission_rate_wagering_active", value)} />
                    <NumField id="field-creator_cut_percent_wagering_active" label="Creator (%)" step="0.01" min="0" max="100" value={form.creator_cut_percent_wagering_active} disabled={saving} onChange={(value) => updateNumber("creator_cut_percent_wagering_active", value)} />
                    <NumField id="field-referral_l1_percent_wagering_active" label="Реферал L1 (%)" step="0.01" min="0" max="100" value={form.referral_l1_percent_wagering_active} disabled={saving} onChange={(value) => updateNumber("referral_l1_percent_wagering_active", value)} />
                    <NumField id="field-referral_l2_percent_wagering_active" label="Реферал L2 (%)" step="0.01" min="0" max="100" value={form.referral_l2_percent_wagering_active} disabled={saving} onChange={(value) => updateNumber("referral_l2_percent_wagering_active", value)} />
                  </div>
                  <div className="flex flex-col gap-3">
                    <p className="text-[12px] font-semibold text-[var(--text-secondary)]">После отыгрыша</p>
                    <NumField id="field-commission_rate_wagering_complete" label="Комиссия (%)" step="0.01" min="0" max="100" value={form.commission_rate_wagering_complete} disabled={saving} onChange={(value) => updateNumber("commission_rate_wagering_complete", value)} />
                    <NumField id="field-creator_cut_percent_wagering_complete" label="Creator (%)" step="0.01" min="0" max="100" value={form.creator_cut_percent_wagering_complete} disabled={saving} onChange={(value) => updateNumber("creator_cut_percent_wagering_complete", value)} />
                    <NumField id="field-referral_l1_percent_wagering_complete" label="Реферал L1 (%)" step="0.01" min="0" max="100" value={form.referral_l1_percent_wagering_complete} disabled={saving} onChange={(value) => updateNumber("referral_l1_percent_wagering_complete", value)} />
                    <NumField id="field-referral_l2_percent_wagering_complete" label="Реферал L2 (%)" step="0.01" min="0" max="100" value={form.referral_l2_percent_wagering_complete} disabled={saving} onChange={(value) => updateNumber("referral_l2_percent_wagering_complete", value)} />
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <NumField id="field-commission_cap_rub" label="Потолок комиссии (₽, 0 = выкл.)" min="0" value={form.commission_cap_rub} disabled={saving} onChange={(value) => updateNumber("commission_cap_rub", value)} />
                  <NumField id="field-commission_min_rub" label="Минимальная комиссия (₽, 0 = выкл.)" min="0" value={form.commission_min_rub} disabled={saving} onChange={(value) => updateNumber("commission_min_rub", value)} />
                </div>
              </SettingsSection>
            </Card>

            <Card id="section-limits" className="scroll-mt-20">
              <SettingsSection title="Лимиты" description="Глобальные границы ставки и темп игр. Пустые ячейки в таблице = эти значения.">
                <div className="grid gap-3 sm:grid-cols-2">
                  <NumField id="field-min_bet_rub" label="Минимальная ставка (₽)" min="0" value={form.min_bet_rub} disabled={saving} onChange={(value) => updateNumber("min_bet_rub", value)} />
                  <NumField id="field-max_bet_rub" label="Максимальная ставка (₽)" min="0" value={form.max_bet_rub} disabled={saving} onChange={(value) => updateNumber("max_bet_rub", value)} />
                  <NumField id="field-bet_step_rub" label="Шаг ставки (₽)" step="0.01" min="0" value={form.bet_step_rub} disabled={saving} onChange={(value) => updateNumber("bet_step_rub", value)} />
                  <NumField id="field-max_concurrent_games_per_player" label="Макс. одновременных игр" min="1" value={form.max_concurrent_games_per_player} disabled={saving} onChange={(value) => updateNumber("max_concurrent_games_per_player", value)} />
                  <NumField id="field-pending_invite_ttl_minutes" label="TTL приглашения (мин, 1–60)" min="1" max="60" value={form.pending_invite_ttl_minutes} disabled={saving} onChange={(value) => updateNumber("pending_invite_ttl_minutes", value)} />
                  <NumField id="field-move_timeout_minutes" label="Таймаут хода (мин)" min="1" value={form.move_timeout_minutes} disabled={saving} onChange={(value) => updateNumber("move_timeout_minutes", value)} />
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-left text-[12px]">
                    <thead className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">
                      <tr>
                        <th className="pb-2 font-semibold">Игра</th>
                        <th className="pb-2 font-semibold">Min ₽</th>
                        <th className="pb-2 font-semibold">Max ₽</th>
                        <th className="pb-2 font-semibold">Раундов / день</th>
                      </tr>
                    </thead>
                    <tbody>
                      {GAME_OPTIONS.map((game) => (
                        <tr key={game.key} className="border-t border-[var(--border)]">
                          <td className="py-2 pr-3 text-[13px] text-[var(--text-primary)]">{game.label}</td>
                          <td className="py-2 pr-2">
                            <Input
                              id={`field-per_game-${game.key}-min`}
                              type="number"
                              min="0"
                              placeholder="глобал"
                              value={form.per_game_limits[game.key].min}
                              disabled={saving}
                              onChange={(event) =>
                                setForm((current) =>
                                  current
                                    ? {
                                        ...current,
                                        per_game_limits: {
                                          ...current.per_game_limits,
                                          [game.key]: { ...current.per_game_limits[game.key], min: event.target.value },
                                        },
                                      }
                                    : current,
                                )
                              }
                            />
                          </td>
                          <td className="py-2 pr-2">
                            <Input
                              id={`field-per_game-${game.key}-max`}
                              type="number"
                              min="0"
                              placeholder="глобал"
                              value={form.per_game_limits[game.key].max}
                              disabled={saving}
                              onChange={(event) =>
                                setForm((current) =>
                                  current
                                    ? {
                                        ...current,
                                        per_game_limits: {
                                          ...current.per_game_limits,
                                          [game.key]: { ...current.per_game_limits[game.key], max: event.target.value },
                                        },
                                      }
                                    : current,
                                )
                              }
                            />
                          </td>
                          <td className="py-2">
                            <Input
                              id={`field-rounds-${game.key}`}
                              type="number"
                              min="0"
                              step="1"
                              placeholder="без лимита"
                              value={form.max_rounds_per_player_per_day[game.key]}
                              disabled={saving}
                              onChange={(event) =>
                                setForm((current) =>
                                  current
                                    ? {
                                        ...current,
                                        max_rounds_per_player_per_day: {
                                          ...current.max_rounds_per_player_per_day,
                                          [game.key]: event.target.value,
                                        },
                                      }
                                    : current,
                                )
                              }
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </SettingsSection>
            </Card>

            <Card id="section-holdem" className="scroll-mt-20">
              <SettingsSection title="Холдем" description="Кэш-стол на сайте. Бай-ин в ₽ становится стеком. Рейк — с банка руки, с потолком.">
                <div className="grid gap-3 sm:grid-cols-2">
                  <NumField id="field-holdem_small_blind_rub" label="Малый блайнд (₽)" min="0.01" step="0.01" value={form.holdem_small_blind_rub} disabled={saving} onChange={(value) => updateNumber("holdem_small_blind_rub", value)} />
                  <NumField id="field-holdem_big_blind_rub" label="Большой блайнд (₽)" min="0.01" step="0.01" value={form.holdem_big_blind_rub} disabled={saving} onChange={(value) => updateNumber("holdem_big_blind_rub", value)} />
                  <NumField id="field-holdem_rake_percent" label="Рейк (%)" min="0" max="100" step="0.01" value={form.holdem_rake_percent} disabled={saving} onChange={(value) => updateNumber("holdem_rake_percent", value)} />
                  <NumField id="field-holdem_rake_cap_rub" label="Потолок рейка (₽, 0 = без потолка)" min="0" value={form.holdem_rake_cap_rub} disabled={saving} onChange={(value) => updateNumber("holdem_rake_cap_rub", value)} />
                  <NumField id="field-holdem_action_timeout_seconds" label="Таймаут хода (сек, 5–300)" min="5" max="300" value={form.holdem_action_timeout_seconds} disabled={saving} onChange={(value) => updateNumber("holdem_action_timeout_seconds", value)} />
                  <NumField id="field-holdem_min_buyin_bb" label="Мин. бай-ин (BB)" min="2" value={form.holdem_min_buyin_bb} disabled={saving} onChange={(value) => updateNumber("holdem_min_buyin_bb", value)} />
                  <NumField id="field-holdem_max_buyin_bb" label="Макс. бай-ин (BB)" min="2" value={form.holdem_max_buyin_bb} disabled={saving} onChange={(value) => updateNumber("holdem_max_buyin_bb", value)} />
                </div>
              </SettingsSection>
            </Card>

            <Card id="section-draughts" className="scroll-mt-20">
              <SettingsSection title="Русские шашки" description="Двое, одна ставка. Рейк с банка — тот же процент и потолок, что у холдема. Таймаут хода сдаёт ставку. Бота нет.">
                <div className="grid gap-3 sm:grid-cols-2">
                  <NumField id="field-draughts_move_timeout_seconds" label="Таймаут хода (сек, 5–300)" min="5" max="300" value={form.draughts_move_timeout_seconds} disabled={saving} onChange={(value) => updateNumber("draughts_move_timeout_seconds", value)} />
                  <p className="text-sm opacity-70 sm:col-span-2">
                    Рейк {form.holdem_rake_percent}% , потолок {form.holdem_rake_cap_rub} ₽. Меняется в секции холдема.
                  </p>
                </div>
              </SettingsSection>
            </Card>

            <Card id="section-jackpot" className="scroll-mt-20">
              <SettingsSection title="Джекпот" description="Сбор с первой ставки. При 30 игроках спин сразу. Рейк с банка, не с проигравшей дуэли. Роботы в джекпот не садятся.">
                <div className="grid gap-3 sm:grid-cols-2">
                  <NumField id="field-jackpot_collect_seconds" label="Окно сбора (сек, 30–3600)" min="30" max="3600" value={form.jackpot_collect_seconds} disabled={saving} onChange={(value) => updateNumber("jackpot_collect_seconds", value)} />
                  <NumField id="field-jackpot_max_players" label="Макс. игроков (2–100)" min="2" max="100" value={form.jackpot_max_players} disabled={saving} onChange={(value) => updateNumber("jackpot_max_players", value)} />
                  <NumField id="field-jackpot_rake_percent" label="Рейк с банка (%)" min="0" max="100" step="0.01" value={form.jackpot_rake_percent} disabled={saving} onChange={(value) => updateNumber("jackpot_rake_percent", value)} />
                </div>
              </SettingsSection>
            </Card>

            <Card id="section-roulette_table" className="scroll-mt-20">
              <SettingsSection title="Рулетка стол" description="Общее колесо против дома. Каждый со своей ставкой, дом платит каждому. Комиссия как у 1×1. Пустой раунд не крутится.">
                <div className="grid gap-3 sm:grid-cols-2">
                  <NumField id="field-roulette_table_collect_seconds" label="Окно ставок (сек, 5–120)" min="5" max="120" value={form.roulette_table_collect_seconds} disabled={saving} onChange={(value) => updateNumber("roulette_table_collect_seconds", value)} />
                  <NumField id="field-roulette_table_max_players" label="Макс. игроков (2–48)" min="2" max="48" value={form.roulette_table_max_players} disabled={saving} onChange={(value) => updateNumber("roulette_table_max_players", value)} />
                </div>
              </SettingsSection>
            </Card>

            <Card id="section-clans" className="scroll-mt-20">
              <SettingsSection title="Кланы" description="Постоянные команды игроков. Оборот — сумма ставок участников за московскую неделю, пока они были в клане. Банка у клана нет.">
                <div className="grid gap-3 sm:grid-cols-2">
                  <ToggleRow id="field-clans_enabled" label="Кланы включены" checked={form.clans_enabled} disabled={saving} onChange={(checked) => setForm((current) => (current ? { ...current, clans_enabled: checked } : current))} />
                  <NumField id="field-clan_max_members" label="Макс. состав (2–50)" min="2" max="50" value={form.clan_max_members} disabled={saving} onChange={(value) => updateNumber("clan_max_members", value)} />
                </div>
              </SettingsSection>
            </Card>

            <Card id="section-fixed_rooms" className="scroll-mt-20">
              <SettingsSection title="Комнаты 2–N" description="Одинаковая ставка, N мест. Розыгрыш только при заполнении. HMAC commit-reveal, не билеты джекпота. Рейк с банка. Пустое место можно заполнить ботом.">
                <div className="grid gap-3 sm:grid-cols-2">
                  <NumField id="field-fixed_room_rake_percent" label="Рейк с банка (%)" min="0" max="100" step="0.01" value={form.fixed_room_rake_percent} disabled={saving} onChange={(value) => updateNumber("fixed_room_rake_percent", value)} />
                  <NumField id="field-fixed_room_max_seats" label="Макс. мест (2–20)" min="2" max="20" value={form.fixed_room_max_seats} disabled={saving} onChange={(value) => updateNumber("fixed_room_max_seats", value)} />
                  <NumField id="field-fixed_room_collect_seconds" label="Окно набора (сек, 30–3600)" min="30" max="3600" value={form.fixed_room_collect_seconds} disabled={saving} onChange={(value) => updateNumber("fixed_room_collect_seconds", value)} />
                </div>
              </SettingsSection>
            </Card>

            <Card id="section-clan_wars" className="scroll-mt-20">
              <SettingsSection title="Война кланов" description="Два клана, N бойцов со стороны. Ставки с кошельков игроков. У клана нет банка. HMAC выбирает клан, банк минус рейк делится между победителями.">
                <div className="grid gap-3 sm:grid-cols-2">
                  <NumField id="field-clan_war_rake_percent" label="Рейк с банка (%)" min="0" max="100" step="0.01" value={form.clan_war_rake_percent} disabled={saving} onChange={(value) => updateNumber("clan_war_rake_percent", value)} />
                  <NumField id="field-clan_war_max_fighters" label="Бойцов со стороны (1–20)" min="1" max="20" value={form.clan_war_max_fighters} disabled={saving} onChange={(value) => updateNumber("clan_war_max_fighters", value)} />
                  <NumField id="field-clan_war_collect_seconds" label="Окно набора (сек, 60–86400)" min="60" max="86400" value={form.clan_war_collect_seconds} disabled={saving} onChange={(value) => updateNumber("clan_war_collect_seconds", value)} />
                </div>
              </SettingsSection>
            </Card>

            <Card id="section-bankroll" className="scroll-mt-20">
              <SettingsSection title="Банкролл и защита" description="Порог и обязательства 0 = выключено. Формула max-stake уже применяется в расчётах раунда.">
                <div className="grid gap-3 sm:grid-cols-2">
                  <NumField id="field-max_profit_pct_per_round" label="Макс. выигрыш за раунд (% банка)" step="0.01" min="0" max="100" value={form.max_profit_pct_per_round} disabled={saving} onChange={(value) => updateNumber("max_profit_pct_per_round", value)} />
                  <NumField id="field-max_profit_pct_per_round_all" label="Макс. выигрыш всех (% банка)" step="0.01" min="0" max="100" value={form.max_profit_pct_per_round_all} disabled={saving} onChange={(value) => updateNumber("max_profit_pct_per_round_all", value)} />
                  <NumField id="field-bankroll_floor_rub" label="Порог банкролла (₽, 0 = выкл.)" min="0" value={form.bankroll_floor_rub} disabled={saving} onChange={(value) => updateNumber("bankroll_floor_rub", value)} />
                  <NumField id="field-liability_amount_rub" label="Потолок обязательств (₽, 0 = выкл.)" min="0" value={form.liability_amount_rub} disabled={saving} onChange={(value) => updateNumber("liability_amount_rub", value)} />
                </div>
              </SettingsSection>
            </Card>

            <div id="section-tiers" className="scroll-mt-20">
              <CasinoTierGrids
                cashbackTiers={cashbackTiers}
                commissionTiers={commissionTiers}
                bonusRows={bonusRows}
                shareBase={form}
                disabled={saving}
                onCashbackChange={setCashbackTiers}
                onCommissionChange={(rows) => {
                  setCommissionTiers(rows);
                  if (rows[0]) {
                    setForm((current) =>
                      current
                        ? {
                            ...current,
                            commission_rate_wagering_active: rows[0].active_rate,
                            commission_rate_wagering_complete: rows[0].complete_rate,
                          }
                        : current,
                    );
                  }
                }}
                onBonusChange={setBonusRows}
              />
            </div>

            <Card id="section-responsible" className="scroll-mt-20">
              <SettingsSection title="Ответственная игра" description="Тумблеры выключены по умолчанию. Ужесточение сразу, ослабление — после задержки.">
                <div className="grid gap-2 sm:grid-cols-2">
                  <ToggleRow id="field-deposit_limit_enabled" label="Лимит депозита" checked={form.deposit_limit_enabled} disabled={saving} onChange={(checked) => setForm((current) => (current ? { ...current, deposit_limit_enabled: checked } : current))} />
                  <ToggleRow id="field-loss_limit_enabled" label="Лимит проигрыша" checked={form.loss_limit_enabled} disabled={saving} onChange={(checked) => setForm((current) => (current ? { ...current, loss_limit_enabled: checked } : current))} />
                  <ToggleRow id="field-wager_limit_enabled" label="Лимит ставок" checked={form.wager_limit_enabled} disabled={saving} onChange={(checked) => setForm((current) => (current ? { ...current, wager_limit_enabled: checked } : current))} />
                  <ToggleRow id="field-session_limit_enabled" label="Лимит сессии" checked={form.session_limit_enabled} disabled={saving} onChange={(checked) => setForm((current) => (current ? { ...current, session_limit_enabled: checked } : current))} />
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <NumField id="field-reality_check_default_minutes" label="Напоминание (мин, 0 = выкл.)" min="0" value={form.reality_check_default_minutes} disabled={saving} onChange={(value) => updateNumber("reality_check_default_minutes", value)} />
                  <NumField id="field-self_exclusion_min_hours" label="Мин. самоисключение (ч)" min="1" value={form.self_exclusion_min_hours} disabled={saving} onChange={(value) => updateNumber("self_exclusion_min_hours", value)} />
                  <NumField id="field-timeout_max_hours" label="Макс. тайм-аут (ч)" min="1" value={form.timeout_max_hours} disabled={saving} onChange={(value) => updateNumber("timeout_max_hours", value)} />
                  <NumField id="field-limit_loosening_delay_hours" label="Задержка ослабления (ч)" min="0" value={form.limit_loosening_delay_hours} disabled={saving} onChange={(value) => updateNumber("limit_loosening_delay_hours", value)} />
                </div>
              </SettingsSection>
            </Card>

            <Card id="section-payouts" className="scroll-mt-20">
              <SettingsSection title="Пороги вывода" description="0 = порог выключен. Сейчас заявки всё равно идут вручную.">
                <div className="grid gap-3 sm:grid-cols-2">
                  <NumField id="field-min_withdrawal_rub" label="Минимальная сумма вывода создателя (₽)" min="0" value={form.min_withdrawal_rub} disabled={saving} onChange={(value) => updateNumber("min_withdrawal_rub", value)} />
                  <NumField id="field-withdrawal_auto_approve_max_rub" label="Автовывод до (₽, 0 = всё вручную)" min="0" value={form.withdrawal_auto_approve_max_rub} disabled={saving} onChange={(value) => updateNumber("withdrawal_auto_approve_max_rub", value)} />
                  <NumField id="field-withdrawal_manual_review_min_rub" label="Ручная проверка от (₽, 0 = выкл.)" min="0" value={form.withdrawal_manual_review_min_rub} disabled={saving} onChange={(value) => updateNumber("withdrawal_manual_review_min_rub", value)} />
                  <NumField id="field-withdrawal_daily_limit_rub" label="Дневной лимит вывода (₽, 0 = выкл.)" min="0" value={form.withdrawal_daily_limit_rub} disabled={saving} onChange={(value) => updateNumber("withdrawal_daily_limit_rub", value)} />
                  <NumField id="field-withdrawal_hourly_limit_rub" label="Часовой лимит вывода (₽, 0 = выкл.)" min="0" value={form.withdrawal_hourly_limit_rub} disabled={saving} onChange={(value) => updateNumber("withdrawal_hourly_limit_rub", value)} />
                </div>
              </SettingsSection>
            </Card>

            <Card id="section-fairness" className="scroll-mt-20">
              <SettingsSection title="Честность" description="Provably fair по умолчанию выключен для всех игр. Ротация сидов раскрывает предыдущий серверный сид.">
                <ToggleRow
                  id="field-seed_rotation_allowed"
                  label="Ротация сидов"
                  checked={form.seed_rotation_allowed}
                  disabled={saving}
                  onChange={(checked) => setForm((current) => (current ? { ...current, seed_rotation_allowed: checked } : current))}
                />
                <div className="grid gap-2 sm:grid-cols-2">
                  {GAME_OPTIONS.map((game) => (
                    <ToggleRow
                      key={game.key}
                      id={`field-fair-${game.key}`}
                      label={`Provably fair: ${game.label}`}
                      checked={form.provably_fair_enabled[game.key]}
                      disabled={saving}
                      onChange={(checked) =>
                        setForm((current) =>
                          current
                            ? {
                                ...current,
                                provably_fair_enabled: { ...current.provably_fair_enabled, [game.key]: checked },
                              }
                            : current,
                        )
                      }
                    />
                  ))}
                </div>
              </SettingsSection>
            </Card>

            <Card id="section-games" className="scroll-mt-20">
              <SettingsSection title="Включённые игры" description="Все поддерживаемые игры показаны даже при пустой конфигурации сервера.">
                <div className="grid gap-3 sm:grid-cols-2">
                  {GAME_OPTIONS.map((game) => (
                    <ToggleRow
                      key={game.key}
                      id={`field-game-${game.key}`}
                      label={game.label}
                      checked={form.enabled_games[game.key]}
                      disabled={saving}
                      onChange={(checked) =>
                        setForm((current) =>
                          current
                            ? { ...current, enabled_games: { ...current.enabled_games, [game.key]: checked } }
                            : current,
                        )
                      }
                    />
                  ))}
                </div>
                <div className="space-y-3 border-t border-[var(--border)] pt-4">
                  <h3 className="text-[13px] font-semibold">Кабинет создателя</h3>
                  <p className="text-[12px] text-[var(--text-muted)]">Доступ назначается существующему аккаунту сайта.</p>
                  {creatorError && (
                    <div role="alert" className="text-[13px] text-[var(--red)]">
                      {creatorError}
                    </div>
                  )}
                  {creatorLoading ? (
                    <div className="text-[13px] text-[var(--text-muted)]">Загрузка доступа…</div>
                  ) : creator ? (
                    <div className="space-y-2 rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-3">
                      <div className="text-[13px]">
                        <span className="text-[var(--text-muted)]">Текущий аккаунт: </span>
                        <span className="font-medium">{creator.display_name || creator.username || `ID ${creator.web_user_id}`}</span>
                        <span className="ml-2 font-mono text-[var(--text-muted)]">#{creator.web_user_id}</span>
                      </div>
                      <div className="break-all font-mono text-[12px] text-[var(--text-secondary)]">{creator.ref_link}</div>
                    </div>
                  ) : (
                    <div className="text-[13px] text-[var(--text-muted)]">Доступ ещё не выдан.</div>
                  )}
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <Input
                      type="number"
                      min="1"
                      value={creatorUserId}
                      onChange={(event) => setCreatorUserId(event.target.value)}
                      placeholder="ID существующего аккаунта сайта"
                      disabled={creatorSaving}
                    />
                    <Button type="button" onClick={() => void assignCreator()} disabled={creatorSaving}>
                      {creatorSaving ? "Назначение…" : creator ? "Заменить аккаунт" : "Выдать доступ"}
                    </Button>
                  </div>
                </div>
                <CasinoChatBindingCard />
              </SettingsSection>
            </Card>

            <div id="section-danger" className="scroll-mt-20 space-y-4">
              <DangerZone
                title="Опасная зона"
                description="Выключить все игры в форме. Чтобы это попало на сервер, сохраните настройки с причиной."
                confirmPhrase="ВЫКЛЮЧИТЬ"
                actionLabel="Выключить все игры"
                disabled={saving}
                onConfirm={() =>
                  setForm((current) => {
                    if (!current) return current;
                    const enabled_games = { ...current.enabled_games };
                    for (const game of GAME_OPTIONS) enabled_games[game.key] = false;
                    return { ...current, enabled_games };
                  })
                }
              />
              {creator ? (
                <DangerZone
                  title="Отозвать кабинет создателя"
                  description="Финансовая история сохранится. Действие выполняется сразу, без сохранения настроек."
                  confirmPhrase="ОТОЗВАТЬ"
                  actionLabel="Отозвать доступ"
                  disabled={creatorSaving}
                  onConfirm={() => void revokeCreator()}
                />
              ) : null}
            </div>

            <SaveBar
              dirty={dirty}
              invalid={invalid}
              dirtySectionCount={dirtySectionCount}
              saving={saving}
              onDiscard={discard}
              onSave={requestSave}
            />
          </div>

          <SettingsAside active={activeSection} form={form} />
        </div>
      )}

      <Modal
        open={reasonOpen}
        title="Причина изменения"
        onClose={() => setReasonOpen(false)}
        footer={
          <>
            <Button type="button" variant="ghost" onClick={() => setReasonOpen(false)} disabled={saving}>
              Отмена
            </Button>
            <Button type="button" variant="primary" onClick={() => void saveSettings()} disabled={saving || !reason.trim()}>
              {saving ? "Сохранение…" : "Сохранить"}
            </Button>
          </>
        }
      >
        <Field label="Что изменилось и почему">
          <textarea
            id="casino-settings-reason"
            required
            value={reason}
            maxLength={500}
            rows={4}
            onChange={(event) => {
              setReason(event.target.value);
              setSaveError(null);
            }}
            placeholder="Обязательно. Попадёт в журнал аудита одним batch_id"
            className="min-h-[96px] w-full rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--text-muted)]"
          />
        </Field>
      </Modal>
    </div>
  );
}
