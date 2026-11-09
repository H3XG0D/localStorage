import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Eye, Filter, Search } from "lucide-react";
import {
  getCasinoGame,
  getCasinoGames,
  type AdminCasinoGame,
  type AdminCasinoGameDetail,
  type AdminCasinoGamesQuery,
  type AdminCasinoGameStatus,
  type AdminCasinoGameType,
} from "@/panel/lib/adminApi";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  Badge,
  Button,
  Card,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  type BadgeTone,
} from "@/panel/ui/primitives";

interface FilterForm {
  game_type: AdminCasinoGameType | "";
  status: AdminCasinoGameStatus | "";
  player_id: string;
}

const EMPTY_FILTERS: FilterForm = { game_type: "", status: "", player_id: "" };
const DEFAULT_QUERY: AdminCasinoGamesQuery = { limit: 100 };

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof PanelApiError ? error.message : fallback;
}

function statusTone(status: string): BadgeTone {
  if (status === "finished") return "green";
  if (status === "active") return "yellow";
  if (status === "cancelled") return "red";
  return "default";
}

function statusLabel(status: string): string {
  if (status === "finished") return "Завершена";
  if (status === "active") return "Активна";
  if (status === "cancelled") return "Отменена";
  return status || "Неизвестно";
}

function formatRub(value: number): string {
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || "—";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function CasinoGames() {
  const [searchParams] = useSearchParams();
  const urlPlayerId = searchParams.get("player_id")?.trim() ?? "";
  const [games, setGames] = useState<AdminCasinoGame[]>([]);
  const [filters, setFilters] = useState<FilterForm>(
    urlPlayerId ? { ...EMPTY_FILTERS, player_id: urlPlayerId } : EMPTY_FILTERS,
  );
  const [appliedQuery, setAppliedQuery] = useState<AdminCasinoGamesQuery>(DEFAULT_QUERY);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filterError, setFilterError] = useState<string | null>(null);
  const listRequestId = useRef(0);

  const [selectedGameId, setSelectedGameId] = useState<string | null>(null);
  const [selectedGame, setSelectedGame] = useState<AdminCasinoGameDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const detailRequestId = useRef(0);

  const loadGames = useCallback(async (query: AdminCasinoGamesQuery) => {
    const requestId = ++listRequestId.current;
    setLoading(true);
    setLoadError(null);
    try {
      const result = await getCasinoGames(query);
      if (requestId !== listRequestId.current) return;
      setGames(result);
    } catch (error) {
      if (requestId !== listRequestId.current) return;
      setGames([]);
      setLoadError(getErrorMessage(error, "Не удалось загрузить список игр"));
    } finally {
      if (requestId === listRequestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const playerId = urlPlayerId ? Number(urlPlayerId) : undefined;
    const query: AdminCasinoGamesQuery =
      playerId !== undefined && Number.isInteger(playerId) && playerId > 0
        ? { ...DEFAULT_QUERY, player_id: playerId }
        : DEFAULT_QUERY;
    setAppliedQuery(query);
    void loadGames(query);
    return () => {
      listRequestId.current += 1;
      detailRequestId.current += 1;
    };
  }, [loadGames, urlPlayerId]);

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const playerIdText = filters.player_id.trim();
    const playerId = playerIdText ? Number(playerIdText) : undefined;
    if (
      playerId !== undefined &&
      (!Number.isFinite(playerId) || !Number.isInteger(playerId) || playerId <= 0)
    ) {
      setFilterError("ID игрока должен быть положительным целым числом");
      return;
    }

    setFilterError(null);
    const query: AdminCasinoGamesQuery = {
      limit: 100,
      game_type: filters.game_type || undefined,
      status: filters.status || undefined,
      player_id: playerId,
    };
    setAppliedQuery(query);
    void loadGames(query);
  };

  const resetFilters = () => {
    setFilters(EMPTY_FILTERS);
    setFilterError(null);
    setAppliedQuery(DEFAULT_QUERY);
    void loadGames(DEFAULT_QUERY);
  };

  const loadGameDetail = async (gameId: string) => {
    const requestId = ++detailRequestId.current;
    setSelectedGameId(gameId);
    setSelectedGame(null);
    setDetailLoading(true);
    setDetailError(null);
    try {
      const detail = await getCasinoGame(gameId);
      if (requestId !== detailRequestId.current) return;
      setSelectedGame(detail);
    } catch (error) {
      if (requestId !== detailRequestId.current) return;
      setDetailError(getErrorMessage(error, "Не удалось загрузить детали игры"));
    } finally {
      if (requestId === detailRequestId.current) setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    detailRequestId.current += 1;
    setSelectedGameId(null);
    setSelectedGame(null);
    setDetailLoading(false);
    setDetailError(null);
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Казино — Игры" subtitle="Поиск игр и просмотр полного игрового события" />

      <Card>
        <form onSubmit={applyFilters} className="space-y-3">
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-[var(--text-secondary)]" aria-hidden />
            <h2 className="text-[14px] font-semibold">Фильтры</h2>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <Field label="Тип игры">
              <Select
                value={filters.game_type}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    game_type: event.target.value as AdminCasinoGameType | "",
                  }))
                }
                disabled={loading}
              >
                <option value="">Все типы</option>
                <option value="pvp_dice">PVP — кубики</option>
                <option value="baccara">Баккара</option>
                <option value="blackjack">Блэкджек</option>
                <option value="raffle">FocusLucky</option>
                <option value="cub">Кубик против казино</option>
              </Select>
            </Field>
            <Field label="Статус">
              <Select
                value={filters.status}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    status: event.target.value as AdminCasinoGameStatus | "",
                  }))
                }
                disabled={loading}
              >
                <option value="">Все статусы</option>
                <option value="active">Активна</option>
                <option value="finished">Завершена</option>
                <option value="cancelled">Отменена</option>
              </Select>
            </Field>
            <Field label="ID игрока">
              <div className="relative">
                <Search
                  className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-muted)]"
                  aria-hidden
                />
                <Input
                  type="number"
                  step="1"
                  min="1"
                  inputMode="numeric"
                  placeholder="Telegram ID"
                  value={filters.player_id}
                  onChange={(event) => {
                    setFilters((current) => ({ ...current, player_id: event.target.value }));
                    setFilterError(null);
                  }}
                  disabled={loading}
                  className="pl-9"
                />
              </div>
            </Field>
          </div>
          {filterError && (
            <div className="text-[12px] text-[var(--red)]" role="alert">
              {filterError}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" disabled={loading}>
              {loading ? "Поиск…" : "Применить"}
            </Button>
            <Button type="button" onClick={resetFilters} disabled={loading}>
              Сбросить
            </Button>
          </div>
        </form>
      </Card>

      <Card className="overflow-hidden p-0">
        {loading ? (
          <div className="p-10 text-center text-[13px] text-[var(--text-muted)]" aria-busy="true">
            Загрузка игр…
          </div>
        ) : loadError ? (
          <div className="space-y-3 p-6" role="alert">
            <div className="text-[13px] text-[var(--red)]">{loadError}</div>
            <Button type="button" size="sm" onClick={() => void loadGames(appliedQuery)}>
              Повторить
            </Button>
          </div>
        ) : games.length === 0 ? (
          <div className="p-10 text-center text-[13px] text-[var(--text-muted)]">
            Игры по заданным фильтрам не найдены
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr className="border-b border-[var(--border)]">
                  <th className="px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">ID</th>
                  <th className="px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Тип</th>
                  <th className="px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Дата</th>
                  <th className="px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Статус</th>
                  <th className="px-3 py-2.5 text-right text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Ставка</th>
                  <th className="px-3 py-2.5 text-right text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Комиссия</th>
                  <th className="px-3 py-2.5 text-right text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Владельцу</th>
                  <th className="px-3 py-2.5 text-center text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Детали</th>
                </tr>
              </thead>
              <tbody>
                {games.map((game) => (
                  <tr
                    key={game.game_id}
                    className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-elevated)]"
                  >
                    <td className="px-3 py-2.5 font-mono">{game.game_id.slice(0, 8)}…</td>
                    <td className="px-3 py-2.5 capitalize">{game.game_type}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-[var(--text-secondary)]">
                      {formatDate(game.created_at)}
                    </td>
                    <td className="px-3 py-2.5">
                      <Badge tone={statusTone(game.status)}>{statusLabel(game.status)}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-right font-mono font-semibold tabular-nums">
                      {formatRub(game.bet_amount_rub)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-right font-mono tabular-nums text-[var(--text-secondary)]">
                      {formatRub(game.commission_rub)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-right font-mono font-semibold tabular-nums text-[var(--green)]">
                      {formatRub(game.owner_cut_rub)}
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => void loadGameDetail(game.game_id)}
                        aria-label={`Открыть игру ${game.game_id}`}
                      >
                        <Eye className="h-4 w-4" aria-hidden />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={selectedGameId !== null}
        title="Детали игры"
        size="lg"
        onClose={closeDetail}
        footer={
          <Button type="button" onClick={closeDetail}>
            Закрыть
          </Button>
        }
      >
        {detailLoading ? (
          <div className="py-12 text-center text-[13px] text-[var(--text-muted)]" aria-busy="true">
            Загрузка деталей…
          </div>
        ) : detailError ? (
          <div className="space-y-3" role="alert">
            <div className="text-[13px] text-[var(--red)]">{detailError}</div>
            {selectedGameId && (
              <Button type="button" size="sm" onClick={() => void loadGameDetail(selectedGameId)}>
                Повторить
              </Button>
            )}
          </div>
        ) : !selectedGame ? (
          <div className="py-12 text-center text-[13px] text-[var(--text-muted)]">
            Детали игры не получены
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <DetailField label="ID игры" value={selectedGame.game_id} mono />
              <DetailField label="Тип" value={selectedGame.game_type} />
              <DetailField label="Создана" value={formatDate(selectedGame.created_at)} />
              <DetailField
                label="Завершена"
                value={selectedGame.finished_at ? formatDate(selectedGame.finished_at) : "—"}
              />
              <DetailField
                label="Игроки"
                value={selectedGame.players.length ? selectedGame.players.join(", ") : "—"}
              />
              <DetailField label="Победитель" value={String(selectedGame.winner_id ?? "—")} />
              <DetailField label="Ставка" value={formatRub(selectedGame.bet_amount_rub)} />
              <DetailField label="Комиссия" value={formatRub(selectedGame.commission_rub)} />
            </div>
            <div className="border-t border-[var(--border)] pt-4">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                Данные игры (JSONB)
              </div>
              <pre className="overflow-x-auto rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-3 text-[12px] text-[var(--text-secondary)]">
                {JSON.stringify(selectedGame.game_data ?? {}, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

function DetailField({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{label}</div>
      <div className={`mt-1 break-all text-[13px] ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  );
}
