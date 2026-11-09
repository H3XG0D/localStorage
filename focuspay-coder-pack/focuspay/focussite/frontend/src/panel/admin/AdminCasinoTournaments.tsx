import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Ban, Bookmark, ChevronDown, Pause, Play, Plus, RefreshCw, Rocket, Trophy, UserPlus, X } from "lucide-react";
import { toast } from "sonner";
import {
  blockCasinoTournamentParticipant,
  createCasinoTournament,
  getCasinoTournamentAccess,
  getCasinoTournamentParticipants,
  getCasinoTournaments,
  grantCasinoTournamentAccess,
  revokeCasinoTournamentAccess,
  setCasinoTournamentStatus,
  type Dict,
} from "@/panel/lib/adminApi";
import {
  Badge,
  Button,
  Card,
  Field,
  Input,
  PageHeader,
  Select,
  Table,
  type BadgeTone,
  type Column,
} from "@/panel/ui/primitives";

type PrizePlace = { place: number; prize_rub: number; share_pct: number };
type Form = typeof BASE_FORM;

const NUM = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

const STATUS_TONE: Record<string, BadgeTone> = {
  draft: "default",
  registration: "yellow",
  active: "green",
  finished: "default",
  cancelled: "red",
};

const STATUS_LABEL: Record<string, string> = {
  draft: "Черновик",
  registration: "Регистрация",
  active: "Идёт",
  finished: "Завершён",
  cancelled: "Отменён",
};

const ALL_GAMES = [
  { id: "pvp_dice", label: "Кубики" },
  { id: "baccara", label: "Баккара" },
  { id: "blackjack", label: "Блэкджек" },
  { id: "roulette", label: "Рулетка" },
  { id: "fixed_room", label: "Комнаты" },
  { id: "jackpot", label: "Джекпот" },
];

const BASE_FORM = {
  title: "Часовой турнир FocusBet",
  subtitle: "Час игры — реальные призы на вывод",
  code: "",
  duration_minutes: 60,
  entry_mode: "free",
  promo_code: "",
  entry_fee_rub: 0,
  starting_chips: 1000,
  min_bet_chips: 10,
  max_bet_chips: 1000,
  rebuy_enabled: false,
  rebuy_fee_rub: 100,
  rebuy_chips: 1000,
  max_rebuys_per_user: 1,
  prize_mode: "fixed",
  guaranteed_pool_rub: 0,
  entry_pool_share_pct: 80,
  require_exchange_history: true,
  min_exchange_count: 1,
  min_exchange_volume_rub: 0,
  min_rounds_for_prize: 5,
  max_participants: 500,
  min_participants: 2,
};

const DEFAULT_PLACES: PrizePlace[] = [
  { place: 1, prize_rub: 1000, share_pct: 50 },
  { place: 2, prize_rub: 500, share_pct: 25 },
  { place: 3, prize_rub: 500, share_pct: 25 },
];

/** Ready-made tournaments: one click fills the whole form. */
const PRESETS: {
  id: string;
  name: string;
  tagline: string;
  form: Partial<Form>;
  places: PrizePlace[];
}[] = [
  {
    id: "sprint",
    name: "Часовой спринт",
    tagline: "Вход свободный · 1 час · призы 1000 / 500 / 500 ₽",
    form: { ...BASE_FORM },
    places: DEFAULT_PLACES,
  },
  {
    id: "promo",
    name: "Промо-турнир",
    tagline: "Вход по промокоду · 1 час · призы 1000 / 500 / 500 ₽",
    form: {
      ...BASE_FORM,
      title: "Промо-турнир FocusBet",
      subtitle: "Вход по промокоду из рассылки",
      entry_mode: "promo",
      promo_code: "RACE",
    },
    places: DEFAULT_PLACES,
  },
  {
    id: "buyin",
    name: "Платный с фондом",
    tagline: "Взнос 100 ₽ · фонд копится из взносов · с докупкой",
    form: {
      ...BASE_FORM,
      title: "Турнир с бай-ином",
      subtitle: "Фонд растёт с каждым участником",
      entry_mode: "paid",
      entry_fee_rub: 100,
      prize_mode: "dynamic",
      guaranteed_pool_rub: 1000,
      entry_pool_share_pct: 80,
      rebuy_enabled: true,
    },
    places: [
      { place: 1, prize_rub: 0, share_pct: 50 },
      { place: 2, prize_rub: 0, share_pct: 30 },
      { place: 3, prize_rub: 0, share_pct: 20 },
    ],
  },
  {
    id: "daily",
    name: "Дневной",
    tagline: "Сутки · стек 5000 фишек · призы 3000 / 1500 / 500 ₽",
    form: {
      ...BASE_FORM,
      title: "Дневной турнир FocusBet",
      subtitle: "Сутки игры — кто соберёт больше фишек",
      duration_minutes: 1440,
      starting_chips: 5000,
      max_bet_chips: 5000,
      min_rounds_for_prize: 15,
    },
    places: [
      { place: 1, prize_rub: 3000, share_pct: 50 },
      { place: 2, prize_rub: 1500, share_pct: 30 },
      { place: 3, prize_rub: 500, share_pct: 20 },
    ],
  },
  {
    id: "weekly",
    name: "Недельный",
    tagline: "7 дней · стек 10 000 фишек · призы 10 000 / 5000 / 2500 / 1500 / 1000 ₽",
    form: {
      ...BASE_FORM,
      title: "Недельный турнир FocusBet",
      subtitle: "Неделя гонки за главным призом",
      duration_minutes: 10080,
      starting_chips: 10000,
      max_bet_chips: 10000,
      min_rounds_for_prize: 30,
      rebuy_enabled: true,
      rebuy_fee_rub: 200,
      rebuy_chips: 10000,
      max_rebuys_per_user: 3,
    },
    places: [
      { place: 1, prize_rub: 10000, share_pct: 50 },
      { place: 2, prize_rub: 5000, share_pct: 25 },
      { place: 3, prize_rub: 2500, share_pct: 12 },
      { place: 4, prize_rub: 1500, share_pct: 8 },
      { place: 5, prize_rub: 1000, share_pct: 5 },
    ],
  },
  {
    id: "night",
    name: "Вечерний марафон",
    tagline: "3 часа · стек 5000 фишек · призы 3000 / 1500 / 500 ₽",
    form: {
      ...BASE_FORM,
      title: "Вечерний марафон FocusBet",
      subtitle: "Три часа игры и крупный банк",
      duration_minutes: 180,
      starting_chips: 5000,
      max_bet_chips: 5000,
      min_rounds_for_prize: 10,
    },
    places: [
      { place: 1, prize_rub: 3000, share_pct: 60 },
      { place: 2, prize_rub: 1500, share_pct: 30 },
      { place: 3, prize_rub: 500, share_pct: 10 },
    ],
  },
];

/** Ready durations: from a coffee-break sprint to a month-long marathon. */
const DURATIONS = [
  { label: "1 час", minutes: 60 },
  { label: "3 часа", minutes: 180 },
  { label: "12 часов", minutes: 720 },
  { label: "Сутки", minutes: 1440 },
  { label: "3 дня", minutes: 4320 },
  { label: "Неделя", minutes: 10080 },
  { label: "2 недели", minutes: 20160 },
  { label: "Месяц", minutes: 43200 },
];

const START_OPTIONS = [
  { id: "now", label: "Сейчас", minutes: 0 },
  { id: "15", label: "Через 15 минут", minutes: 15 },
  { id: "60", label: "Через час", minutes: 60 },
  { id: "custom", label: "Своё время", minutes: -1 },
];

function num(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function str(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

function fmtTime(iso: unknown): string {
  const raw = str(iso);
  if (!raw) return "—";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function durationLabel(minutes: number): string {
  if (minutes >= 10080 && minutes % 10080 === 0) {
    const weeks = minutes / 10080;
    return weeks === 1 ? "1 неделя" : `${weeks} недели`;
  }
  if (minutes >= 1440 && minutes % 1440 === 0) {
    const days = minutes / 1440;
    return days === 1 ? "1 день" : `${days} дня`;
  }
  if (minutes % 60 === 0) return `${minutes / 60} ч`;
  return `${minutes} мин`;
}

function entryLabel(form: Form): string {
  if (form.entry_mode === "free") return "вход свободный";
  if (form.entry_mode === "promo") return `вход по коду ${form.promo_code || "—"}`;
  if (form.entry_mode === "paid") return `взнос ${NUM.format(form.entry_fee_rub)} ₽`;
  return `код ${form.promo_code || "—"} или ${NUM.format(form.entry_fee_rub)} ₽`;
}

function prizeLabel(form: Form, places: PrizePlace[]): string {
  if (form.prize_mode === "dynamic") {
    return `фонд от ${NUM.format(form.guaranteed_pool_rub)} ₽ + ${form.entry_pool_share_pct}% взносов на ${places.length} мест`;
  }
  const total = places.reduce((sum, place) => sum + place.prize_rub, 0);
  return `призы ${places.map((place) => NUM.format(place.prize_rub)).join(" / ")} ₽ (всего ${NUM.format(total)} ₽)`;
}

const SAVED_KEY = "focuspay_tournament_presets";

type SavedPreset = { id: string; name: string; form: Form; places: PrizePlace[]; games: string[] };

function loadSaved(): SavedPreset[] {
  try {
    const raw = window.localStorage.getItem(SAVED_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as SavedPreset[]) : [];
  } catch {
    return [];
  }
}

function storeSaved(items: SavedPreset[]) {
  try {
    window.localStorage.setItem(SAVED_KEY, JSON.stringify(items));
  } catch {
    /* private mode — scenarios just won't persist */
  }
}

/** One labelled block of the advanced form, with a plain-language explanation. */
function Section({ title, hint, children }: { title: string; hint: string; children: ReactNode }) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-elevated)] p-4">
      <div className="text-[13px] font-semibold">{title}</div>
      <p className="mt-0.5 mb-3 text-[11.5px] leading-snug text-[var(--text-muted)]">{hint}</p>
      <div className="grid gap-3 md:grid-cols-3">{children}</div>
    </div>
  );
}

export function AdminCasinoTournaments() {
  const [rows, setRows] = useState<Dict[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [participants, setParticipants] = useState<Dict[]>([]);
  const [access, setAccess] = useState<Dict[]>([]);
  const [accessIdentity, setAccessIdentity] = useState("");
  const [accessNote, setAccessNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [presetId, setPresetId] = useState(PRESETS[0].id);
  const [form, setForm] = useState<Form>({ ...BASE_FORM });
  const [places, setPlaces] = useState<PrizePlace[]>(DEFAULT_PLACES);
  const [games, setGames] = useState<string[]>(ALL_GAMES.map((game) => game.id));
  const [startWhen, setStartWhen] = useState("now");
  const [customStart, setCustomStart] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [saved, setSaved] = useState<SavedPreset[]>(() => loadSaved());
  const [saveName, setSaveName] = useState("");
  const detailsRef = useRef<HTMLDivElement>(null);

  function selectTournament(id: number) {
    setSelectedId(id);
    detailsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getCasinoTournaments();
      const list = Array.isArray(res.tournaments) ? res.tournaments : [];
      setRows(list);
      setSelectedId((current) => current ?? (list[0] ? num(list[0].id) : null));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось загрузить турниры");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    if (selectedId == null) return;
    let alive = true;
    void (async () => {
      try {
        const res = await getCasinoTournamentParticipants(selectedId);
        if (alive) setParticipants(Array.isArray(res.participants) ? res.participants : []);
      } catch {
        if (alive) setParticipants([]);
      }
      try {
        const res = await getCasinoTournamentAccess(selectedId);
        if (alive) setAccess(Array.isArray(res.access) ? res.access : []);
      } catch {
        if (alive) setAccess([]);
      }
    })();
    return () => {
      alive = false;
    };
  }, [selectedId, rows]);

  const selected = useMemo(() => rows.find((row) => num(row.id) === selectedId) || null, [rows, selectedId]);
  const live = useMemo(() => rows.filter((row) => ["registration", "active"].includes(str(row.status))), [rows]);

  function applyPreset(id: string) {
    const preset = PRESETS.find((item) => item.id === id);
    if (!preset) return;
    setPresetId(id);
    setForm({ ...BASE_FORM, ...preset.form });
    setPlaces(preset.places.map((place) => ({ ...place })));
    setGames(ALL_GAMES.map((game) => game.id));
  }

  function applySaved(preset: SavedPreset) {
    setPresetId(preset.id);
    setForm({ ...BASE_FORM, ...preset.form });
    setPlaces(preset.places.map((place) => ({ ...place })));
    setGames([...preset.games]);
  }

  function saveScenario() {
    const name = saveName.trim() || form.title.trim();
    if (!name) {
      toast.error("Назовите сценарий");
      return;
    }
    const preset: SavedPreset = { id: `saved:${Date.now()}`, name, form: { ...form }, places: places.map((p) => ({ ...p })), games: [...games] };
    const next = [...saved.filter((item) => item.name !== name), preset];
    setSaved(next);
    storeSaved(next);
    setPresetId(preset.id);
    setSaveName("");
    toast.success(`Сценарий «${name}» сохранён`);
  }

  function removeScenario(id: string) {
    const next = saved.filter((item) => item.id !== id);
    setSaved(next);
    storeSaved(next);
  }

  function startsAtIso(): string | null {
    if (startWhen === "custom") return customStart ? new Date(customStart).toISOString() : null;
    const option = START_OPTIONS.find((item) => item.id === startWhen);
    const minutes = option && option.minutes > 0 ? option.minutes : 0;
    return new Date(Date.now() + minutes * 60_000).toISOString();
  }

  /** Create + open registration (+ start right away when "Сейчас" is picked). */
  async function launch() {
    if (busy) return;
    setBusy(true);
    try {
      const created = await createCasinoTournament({
        ...form,
        starts_at: startsAtIso(),
        code: form.code.trim() || null,
        promo_code: form.promo_code.trim() || null,
        prize_places: places,
        allowed_games: games,
      });
      const id = num((created as Dict).id ?? (created as Dict).tournament_id);
      if (id) {
        await setCasinoTournamentStatus(id, startWhen === "now" ? "active" : "registration");
      }
      toast.success(startWhen === "now" ? "Турнир запущен — игроки уже могут заходить" : "Турнир создан, набор открыт");
      await reload();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось запустить турнир");
    } finally {
      setBusy(false);
    }
  }

  async function onStatus(id: number, status: string) {
    if (busy) return;
    setBusy(true);
    try {
      await setCasinoTournamentStatus(id, status);
      toast.success(status === "finished" ? "Турнир завершён, призы начислены" : `Статус: ${STATUS_LABEL[status] || status}`);
      await reload();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось сменить статус");
    } finally {
      setBusy(false);
    }
  }

  async function onBlock(userId: number, blocked: boolean) {
    if (selectedId == null) return;
    try {
      await blockCasinoTournamentParticipant(selectedId, userId, blocked);
      toast.success(blocked ? "Участник исключён из призов" : "Участник возвращён");
      const res = await getCasinoTournamentParticipants(selectedId);
      setParticipants(Array.isArray(res.participants) ? res.participants : []);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось обновить участника");
    }
  }

  async function onGrantAccess() {
    if (selectedId == null) return;
    const identity = accessIdentity.trim();
    if (!identity) {
      toast.error("Вставьте Telegram ID или @username");
      return;
    }
    setBusy(true);
    try {
      const res = await grantCasinoTournamentAccess(selectedId, identity, accessNote.trim());
      setAccess(Array.isArray(res.access) ? res.access : []);
      setAccessIdentity("");
      setAccessNote("");
      toast.success("Доступ выдан — юзер зайдёт без истории обменов");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось выдать доступ");
    } finally {
      setBusy(false);
    }
  }

  async function onRevokeAccess(userId: number) {
    if (selectedId == null) return;
    try {
      const res = await revokeCasinoTournamentAccess(selectedId, userId);
      setAccess(Array.isArray(res.access) ? res.access : []);
      toast.success("Доступ отозван");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось отозвать доступ");
    }
  }

  const tournamentColumns: Column<Dict>[] = [
    {
      key: "title",
      label: "Турнир",
      render: (row) => (
        <div className="flex flex-col">
          <span className="font-semibold">
            {num(row.id) === selectedId ? <span className="mr-1.5 text-[var(--green)]">●</span> : null}
            {str(row.title)}
          </span>
          <span className="text-[11px] text-[var(--text-muted)]">
            {durationLabel(num(row.duration_minutes))} · {fmtTime(row.starts_at)}
          </span>
        </div>
      ),
    },
    {
      key: "status",
      label: "Статус",
      render: (row) => <Badge tone={STATUS_TONE[str(row.status)] || "default"}>{STATUS_LABEL[str(row.status)] || str(row.status)}</Badge>,
    },
    {
      key: "entry",
      label: "Вход",
      render: (row) =>
        str(row.entry_mode) === "free"
          ? "свободный"
          : str(row.entry_mode) === "promo"
            ? `код ${str(row.promo_code) || "—"}`
            : `${NUM.format(num(row.entry_fee_rub))} ₽`,
    },
    { key: "player_count", label: "Игроков", align: "right", render: (row) => NUM.format(num(row.player_count)) },
    { key: "pool", label: "Фонд", align: "right", render: (row) => `${NUM.format(num(row.prize_pool_rub))} ₽` },
    {
      key: "actions",
      label: "",
      render: (row) => {
        const id = num(row.id);
        const status = str(row.status);
        return (
          <div className="flex flex-wrap justify-end gap-1.5">
            {status === "draft" ? (
              <Button size="sm" variant="primary" disabled={busy} onClick={() => void onStatus(id, "registration")}>
                <Play size={13} /> Набор
              </Button>
            ) : null}
            {status === "registration" ? (
              <Button size="sm" variant="primary" disabled={busy} onClick={() => void onStatus(id, "active")}>
                <Rocket size={13} /> Старт
              </Button>
            ) : null}
            {status === "active" ? (
              <Button size="sm" disabled={busy} onClick={() => void onStatus(id, "finished")}>
                <Pause size={13} /> Завершить
              </Button>
            ) : null}
            {status === "draft" || status === "registration" ? (
              <Button size="sm" variant="danger" disabled={busy} onClick={() => void onStatus(id, "cancelled")}>
                <X size={13} />
              </Button>
            ) : null}
          </div>
        );
      },
    },
  ];

  const participantColumns: Column<Dict>[] = [
    { key: "final_rank", label: "#", width: "48px", render: (row) => str(row.final_rank) || str(row.rank) || "—" },
    { key: "display_name", label: "Игрок", render: (row) => str(row.display_name) || `ID ${str(row.user_id)}` },
    { key: "chips_balance", label: "Фишки", align: "right", render: (row) => NUM.format(num(row.chips_balance)) },
    { key: "rounds_played", label: "Раундов", align: "right", render: (row) => NUM.format(num(row.rounds_played)) },
    { key: "prize_rub", label: "Приз", align: "right", render: (row) => (num(row.prize_rub) > 0 ? `${NUM.format(num(row.prize_rub))} ₽` : "—") },
    {
      key: "block",
      label: "",
      render: (row) => (
        <Button size="sm" variant={row.blocked ? "secondary" : "danger"} onClick={() => void onBlock(num(row.user_id), !row.blocked)}>
          <Ban size={13} /> {row.blocked ? "Вернуть" : "Исключить"}
        </Button>
      ),
    },
  ];

  const accessColumns: Column<Dict>[] = [
    {
      key: "user",
      label: "Игрок",
      render: (row) => (str(row.username) ? `@${str(row.username)}` : `ID ${str(row.user_id)}`),
    },
    { key: "note", label: "Комментарий", render: (row) => str(row.note) || "—" },
    {
      key: "joined",
      label: "Вошёл",
      render: (row) => <Badge tone={row.joined ? "green" : "default"}>{row.joined ? "да" : "ещё нет"}</Badge>,
    },
    { key: "created_at", label: "Выдан", render: (row) => fmtTime(row.created_at) },
    {
      key: "revoke",
      label: "",
      render: (row) => (
        <Button size="sm" variant="danger" onClick={() => void onRevokeAccess(num(row.user_id))}>
          <X size={13} /> Отозвать
        </Button>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Турниры казино"
        subtitle="Выберите готовый сценарий и запустите турнир одной кнопкой"
        actions={
          <Button variant="secondary" disabled={loading} onClick={() => void reload()}>
            <RefreshCw size={14} /> Обновить
          </Button>
        }
      />

      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">1. Выберите сценарий</div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {PRESETS.map((preset) => {
            const on = preset.id === presetId;
            return (
              <button
                key={preset.id}
                type="button"
                onClick={() => applyPreset(preset.id)}
                className={`rounded-[var(--radius-lg)] border p-4 text-left transition ${
                  on
                    ? "border-[var(--yellow)] bg-[var(--yellow-bg)]"
                    : "border-[var(--border)] bg-[var(--bg-elevated)] hover:border-[var(--border-strong)]"
                }`}
              >
                <div className="flex items-center gap-2 text-[13.5px] font-semibold">
                  <Trophy size={15} /> {preset.name}
                </div>
                <div className="mt-1 text-[11.5px] leading-snug text-[var(--text-muted)]">{preset.tagline}</div>
              </button>
            );
          })}
        </div>

        {saved.length ? (
          <>
            <div className="mt-5 text-[13.5px] font-semibold">Мои сценарии</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {saved.map((preset) => (
                <span
                  key={preset.id}
                  className={`inline-flex items-center gap-1 rounded-full border px-1 py-0.5 ${
                    presetId === preset.id ? "border-[var(--yellow)] bg-[var(--yellow-bg)]" : "border-[var(--border-strong)]"
                  }`}
                >
                  <Button size="sm" variant="secondary" onClick={() => applySaved(preset)}>
                    <Bookmark size={13} /> {preset.name}
                  </Button>
                  <button
                    type="button"
                    aria-label={`Удалить сценарий ${preset.name}`}
                    className="px-1 text-[var(--text-muted)] hover:text-[var(--red)]"
                    onClick={() => removeScenario(preset.id)}
                  >
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
          </>
        ) : null}

        <div className="mt-5 text-[13.5px] font-semibold">2. Когда начинаем</div>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <div className="flex flex-wrap gap-2">
            {START_OPTIONS.map((option) => (
              <Button
                key={option.id}
                size="sm"
                variant={startWhen === option.id ? "primary" : "secondary"}
                onClick={() => setStartWhen(option.id)}
              >
                {option.label}
              </Button>
            ))}
          </div>
          {startWhen === "custom" ? (
            <div className="w-56">
              <Input type="datetime-local" value={customStart} onChange={(e) => setCustomStart(e.target.value)} />
            </div>
          ) : null}
        </div>

        <div className="mt-5 text-[13.5px] font-semibold">3. Сколько длится</div>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <div className="flex flex-wrap gap-2">
            {DURATIONS.map((option) => (
              <Button
                key={option.minutes}
                size="sm"
                variant={form.duration_minutes === option.minutes ? "primary" : "secondary"}
                onClick={() => setForm({ ...form, duration_minutes: option.minutes })}
              >
                {option.label}
              </Button>
            ))}
          </div>
          <div className="w-44">
            <Field label="Своя длительность, мин" hint="от 5 минут до 30 дней">
              <Input
                type="number"
                min={5}
                max={43200}
                value={form.duration_minutes}
                onChange={(e) => setForm({ ...form, duration_minutes: num(e.target.value) })}
              />
            </Field>
          </div>
        </div>

        <div className="mt-5 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-elevated)] p-4">
          <div className="text-[13px] font-semibold">{form.title}</div>
          <div className="mt-1 text-[12px] leading-relaxed text-[var(--text-muted)]">
            {durationLabel(form.duration_minutes)} · {entryLabel(form)} · стек {NUM.format(form.starting_chips)} фишек ·{" "}
            {prizeLabel(form, places)}
            {form.rebuy_enabled ? ` · докупка ${NUM.format(form.rebuy_fee_rub)} ₽` : " · без докупки"}
            {form.require_exchange_history
              ? ` · только клиенты от ${Math.max(1, form.min_exchange_count)} обменов${
                  form.min_exchange_volume_rub > 0 ? ` на ${NUM.format(form.min_exchange_volume_rub)} ₽` : ""
                }`
              : ""}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button variant="primary" disabled={busy} onClick={() => void launch()}>
              <Rocket size={14} /> {startWhen === "now" ? "Запустить сейчас" : "Открыть набор"}
            </Button>
            <button
              type="button"
              className="inline-flex items-center gap-1 text-[12px] text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              onClick={() => setAdvanced((value) => !value)}
            >
              <ChevronDown size={13} className={advanced ? "rotate-180 transition" : "transition"} />
              Тонкая настройка
            </button>
          </div>
        </div>

        {advanced ? (
          <div className="mt-5 flex flex-col gap-3 border-t border-[var(--border)] pt-5">
            <Section title="Как называется" hint="Эти три строки игрок видит на карточке турнира.">
              <Field label="Название">
                <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </Field>
              <Field label="Подзаголовок">
                <Input value={form.subtitle} onChange={(e) => setForm({ ...form, subtitle: e.target.value })} />
              </Field>
              <Field label="Код турнира" hint="Для ссылок. Пусто — сгенерируем">
                <Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} />
              </Field>
            </Section>

            <Section title="Кого пускаем" hint="Свободный вход — заходит любой клиент. Промокод — только по коду из рассылки. Взнос — списывается с баланса и может пополнять призовой фонд.">
              <Field label="Вход">
                <Select value={form.entry_mode} onChange={(e) => setForm({ ...form, entry_mode: e.target.value })}>
                  <option value="free">Свободный</option>
                  <option value="promo">Только по промокоду</option>
                  <option value="paid">Платный взнос</option>
                  <option value="promo_or_paid">Промокод или взнос</option>
                </Select>
              </Field>
              {form.entry_mode === "promo" || form.entry_mode === "promo_or_paid" ? (
                <Field label="Промокод" hint="Игрок вводит его при регистрации или в кассе">
                  <Input value={form.promo_code} onChange={(e) => setForm({ ...form, promo_code: e.target.value.toUpperCase() })} />
                </Field>
              ) : null}
              {form.entry_mode === "paid" || form.entry_mode === "promo_or_paid" ? (
                <Field label="Взнос, ₽">
                  <Input type="number" min={0} value={form.entry_fee_rub} onChange={(e) => setForm({ ...form, entry_fee_rub: num(e.target.value) })} />
                </Field>
              ) : null}
            </Section>

            <Section title="Чем играют" hint="Фишки — турнирная валюта, на реальный баланс они не влияют. Все участники получают одинаковый стартовый стек.">
              <Field label="Стартовый стек, фишек">
                <Input type="number" min={1} value={form.starting_chips} onChange={(e) => setForm({ ...form, starting_chips: num(e.target.value) })} />
              </Field>
              <Field label="Мин. ставка, фишек">
                <Input type="number" min={1} value={form.min_bet_chips} onChange={(e) => setForm({ ...form, min_bet_chips: num(e.target.value) })} />
              </Field>
              <Field label="Макс. ставка, фишек">
                <Input type="number" min={1} value={form.max_bet_chips} onChange={(e) => setForm({ ...form, max_bet_chips: num(e.target.value) })} />
              </Field>
            </Section>

            <Section
              title="Что выигрывают"
              hint={
                form.prize_mode === "fixed"
                  ? "Фиксированный фонд: сколько впишете в места, столько и выплатим рублями на вывод."
                  : "Накопительный фонд: гарантия плюс доля взносов. Места делят фонд по процентам."
              }
            >
              <Field label="Призовой фонд">
                <Select value={form.prize_mode} onChange={(e) => setForm({ ...form, prize_mode: e.target.value })}>
                  <option value="fixed">Фиксированный</option>
                  <option value="dynamic">Накопительный из взносов</option>
                </Select>
              </Field>
              {form.prize_mode === "dynamic" ? (
                <>
                  <Field label="Гарантия фонда, ₽" hint="Выплатим даже при малом числе участников">
                    <Input
                      type="number"
                      min={0}
                      value={form.guaranteed_pool_rub}
                      onChange={(e) => setForm({ ...form, guaranteed_pool_rub: num(e.target.value) })}
                    />
                  </Field>
                  <Field label="Доля взносов в фонд, %" hint="Остальное остаётся казино">
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      value={form.entry_pool_share_pct}
                      onChange={(e) => setForm({ ...form, entry_pool_share_pct: num(e.target.value) })}
                    />
                  </Field>
                </>
              ) : null}
            </Section>

            <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-elevated)] p-4">
              <div className="text-[13px] font-semibold">Призовые места</div>
              <p className="mt-0.5 mb-3 text-[11.5px] leading-snug text-[var(--text-muted)]">
                {form.prize_mode === "fixed"
                  ? "Работает колонка «₽»: это и есть приз за место."
                  : "Работает колонка «%»: доля фонда за место, сумма процентов должна быть 100."}
              </p>
              <div className="flex flex-col gap-2">
                {places.map((place, index) => (
                  <div key={place.place} className="flex items-center gap-2">
                    <span className="w-16 text-[12px] text-[var(--text-muted)]">{place.place} место</span>
                    <Input
                      type="number"
                      min={0}
                      disabled={form.prize_mode === "dynamic"}
                      value={place.prize_rub}
                      onChange={(e) => {
                        const next = [...places];
                        next[index] = { ...place, prize_rub: num(e.target.value) };
                        setPlaces(next);
                      }}
                    />
                    <span className="text-[12px] text-[var(--text-muted)]">₽</span>
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      disabled={form.prize_mode === "fixed"}
                      value={place.share_pct}
                      onChange={(e) => {
                        const next = [...places];
                        next[index] = { ...place, share_pct: num(e.target.value) };
                        setPlaces(next);
                      }}
                    />
                    <span className="text-[12px] text-[var(--text-muted)]">%</span>
                    <Button
                      size="sm"
                      variant="secondary"
                      aria-label={`Убрать ${place.place} место`}
                      onClick={() => setPlaces(places.filter((_, i) => i !== index).map((row, i) => ({ ...row, place: i + 1 })))}
                    >
                      <X size={13} />
                    </Button>
                  </div>
                ))}
                <div className="flex flex-wrap items-center gap-3">
                  <Button size="sm" variant="secondary" onClick={() => setPlaces([...places, { place: places.length + 1, prize_rub: 0, share_pct: 0 }])}>
                    <Plus size={13} /> Добавить место
                  </Button>
                  <span className="text-[11.5px] text-[var(--text-muted)]">
                    {form.prize_mode === "fixed"
                      ? `Итого ${NUM.format(places.reduce((sum, place) => sum + place.prize_rub, 0))} ₽`
                      : `Сумма долей ${places.reduce((sum, place) => sum + place.share_pct, 0)}%`}
                  </span>
                </div>
              </div>
            </div>

            <Section title="Докупка стека" hint="Разрешает проигравшему купить новый стек за рубли. Деньги идут в фонд, если он накопительный.">
              <Field label="Режим">
                <Select value={form.rebuy_enabled ? "on" : "off"} onChange={(e) => setForm({ ...form, rebuy_enabled: e.target.value === "on" })}>
                  <option value="off">Без докупки</option>
                  <option value="on">С докупкой</option>
                </Select>
              </Field>
              {form.rebuy_enabled ? (
                <>
                  <Field label="Цена докупки, ₽">
                    <Input type="number" min={0} value={form.rebuy_fee_rub} onChange={(e) => setForm({ ...form, rebuy_fee_rub: num(e.target.value) })} />
                  </Field>
                  <Field label="Фишек за докупку">
                    <Input type="number" min={1} value={form.rebuy_chips} onChange={(e) => setForm({ ...form, rebuy_chips: num(e.target.value) })} />
                  </Field>
                  <Field label="Лимит докупок" hint="0 — без лимита">
                    <Input
                      type="number"
                      min={0}
                      value={form.max_rebuys_per_user}
                      onChange={(e) => setForm({ ...form, max_rebuys_per_user: num(e.target.value) })}
                    />
                  </Field>
                </>
              ) : null}
            </Section>

            <Section title="Защита от накруток" hint="Гейт по обменам отсекает мультиаккаунты, минимум раундов — тех, кто зашёл и не играл. За столом в любом случае не больше одного бота.">
              <Field label="Только клиенты с обменами">
                <Select
                  value={form.require_exchange_history ? "on" : "off"}
                  onChange={(e) => setForm({ ...form, require_exchange_history: e.target.value === "on" })}
                >
                  <option value="on">Да</option>
                  <option value="off">Нет</option>
                </Select>
              </Field>
              {form.require_exchange_history ? (
                <>
                  <Field label="Мин. количество обменов" hint="Сколько оплаченных заявок нужно клиенту">
                    <Input
                      type="number"
                      min={1}
                      value={form.min_exchange_count}
                      onChange={(e) => setForm({ ...form, min_exchange_count: num(e.target.value) })}
                    />
                  </Field>
                  <Field label="Мин. объём обменов, ₽" hint="0 — сумма не важна">
                    <Input
                      type="number"
                      min={0}
                      value={form.min_exchange_volume_rub}
                      onChange={(e) => setForm({ ...form, min_exchange_volume_rub: num(e.target.value) })}
                    />
                  </Field>
                </>
              ) : null}
              <Field label="Мин. раундов для приза">
                <Input
                  type="number"
                  min={0}
                  value={form.min_rounds_for_prize}
                  onChange={(e) => setForm({ ...form, min_rounds_for_prize: num(e.target.value) })}
                />
              </Field>
              <Field label="Максимум участников">
                <Input type="number" min={2} value={form.max_participants} onChange={(e) => setForm({ ...form, max_participants: num(e.target.value) })} />
              </Field>
              <Field label="Минимум участников" hint="Меньше — отмена с возвратом взносов">
                <Input type="number" min={2} value={form.min_participants} onChange={(e) => setForm({ ...form, min_participants: num(e.target.value) })} />
              </Field>
            </Section>

            <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-elevated)] p-4">
              <div className="text-[13px] font-semibold">Игры турнира</div>
              <p className="mt-0.5 mb-3 text-[11.5px] leading-snug text-[var(--text-muted)]">
                Где можно тратить турнирные фишки. Выключенные игры останутся на обычный рублёвый баланс.
              </p>
              <div className="flex flex-wrap gap-2">
                {ALL_GAMES.map((game) => {
                  const on = games.includes(game.id);
                  return (
                    <Button
                      key={game.id}
                      size="sm"
                      variant={on ? "primary" : "secondary"}
                      onClick={() => setGames(on ? games.filter((id) => id !== game.id) : [...games, game.id])}
                    >
                      {game.label}
                    </Button>
                  );
                })}
              </div>
            </div>

            <div className="flex flex-wrap items-end gap-3 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-elevated)] p-4">
              <div className="w-64">
                <Field label="Сохранить как сценарий" hint="Появится кнопкой сверху — запуск в один клик">
                  <Input value={saveName} placeholder={form.title} onChange={(e) => setSaveName(e.target.value)} />
                </Field>
              </div>
              <Button variant="secondary" onClick={saveScenario}>
                <Bookmark size={14} /> Сохранить
              </Button>
            </div>
          </div>
        ) : null}
      </Card>

      <Card>
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="text-[13.5px] font-semibold">Турниры</div>
          <span className="text-[12px] text-[var(--text-muted)]">
            {live.length ? `${live.length} идёт или набирает` : "активных нет"}
          </span>
        </div>
        <Table
          columns={tournamentColumns}
          rows={rows}
          empty={loading ? "Загрузка…" : "Турниров ещё нет — запустите первый сверху"}
          onRowClick={(row) => selectTournament(num(row.id))}
        />
      </Card>

      <div ref={detailsRef} className="flex flex-col gap-5">
      {selected ? (
        <Card>
          <div className="mb-3 text-[13.5px] font-semibold">Участники · {str(selected.title)}</div>
          <Table columns={participantColumns} rows={participants} empty="Пока никто не зарегистрировался" />
        </Card>
      ) : null}

      {selected ? (
        <Card>
          <div className="mb-1 text-[13.5px] font-semibold">Персональный доступ · {str(selected.title)}</div>
          <p className="mb-3 text-[11.5px] leading-snug text-[var(--text-muted)]">
            Вставьте Telegram ID или @username — человек войдёт в этот турнир без истории обменов.
            Взнос и промокод, если они настроены, остаются в силе.
          </p>
          <div className="mb-4 flex flex-wrap items-end gap-3">
            <div className="w-56">
              <Field label="Telegram ID или @username">
                <Input
                  value={accessIdentity}
                  placeholder="@nickname"
                  onChange={(e) => setAccessIdentity(e.target.value)}
                />
              </Field>
            </div>
            <div className="w-72">
              <Field label="Комментарий" hint="Зачем выдали — видно только в панели">
                <Input value={accessNote} onChange={(e) => setAccessNote(e.target.value)} />
              </Field>
            </div>
            <Button variant="primary" disabled={busy} onClick={() => void onGrantAccess()}>
              <UserPlus size={14} /> Выдать доступ
            </Button>
          </div>
          <Table columns={accessColumns} rows={access} empty="Персональных доступов нет" />
        </Card>
      ) : null}
      </div>
    </div>
  );
}
