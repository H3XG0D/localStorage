import { useEffect, useMemo, useState } from "react";
import { ArrowRight, CreditCard, Flame, ShieldCheck, Target, Trophy } from "lucide-react";
import { Link } from "react-router-dom";
import { getCasinoLobby, type CasinoLobbyResponse } from "@/lib/public";
import { CasinoGameTile } from "./CasinoGameTile";
import { casinoTo } from "./casinoPaths";
import {
  CASINO_CATALOG,
  FAVORITE_KEY,
  pushRecent,
  readIdList,
  visibleCasinoCatalog,
  writeIdList,
} from "./gameCatalog";

const PROMOS = [
  { id: "duels", kicker: "Кубики", title: "Стол с людьми", text: "Равные ставки, банк победителю. Бота можно добавить.", to: "/casino/play/pvp_dice?mode=players", Icon: Trophy },
  { id: "cards", kicker: "Карты", title: "Баккара и блэкджек", text: "Серверная тасовка. Ставка и число мест, бота можно добавить за столом.", to: "/casino/play/blackjack?mode=players", Icon: CreditCard },
  { id: "fair", kicker: "Честность", title: "Проверка раунда", text: "Серверный сид раскрывается после раунда. Можно пересчитать самому.", to: "/casino/fairness", Icon: ShieldCheck },
] as const;

function formatBet(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value)} ₽`;
}

function openedLabel(iso: string): string {
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return "открыта";
  const minutes = Math.max(0, Math.round((Date.now() - at) / 60000));
  if (minutes < 1) return "только что";
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.round(minutes / 60);
  return `${hours} ч`;
}

function isEnabled(id: string, enabledMap: Map<string, boolean>): boolean {
  if (id === "pvp_dice") return Boolean(enabledMap.get("pvp_dice") || enabledMap.get("cub"));
  if (id === "raffle") return true;
  if (id === "russian_draughts") return enabledMap.get(id) === true;
  return enabledMap.get(id) ?? true;
}

export function CasinoLobby() {
  const [lobby, setLobby] = useState<CasinoLobbyResponse | null>(null);
  const [lobbyReady, setLobbyReady] = useState(false);
  const [favorites, setFavorites] = useState<string[]>([]);

  useEffect(() => {
    getCasinoLobby()
      .then(setLobby)
      .catch(() =>
        setLobby({
          min_bet_rub: 0,
          max_bet_rub: 0,
          commission_percent: 0,
          games: CASINO_CATALOG.map((game) => ({
            id: game.id,
            name: game.name,
            category: game.category,
            emoji: game.emoji,
            enabled: true,
          })),
          open_duels: [],
          open_rooms: [],
        }),
      )
      .finally(() => setLobbyReady(true));
    setFavorites(readIdList(FAVORITE_KEY));
  }, []);

  const enabledMap = useMemo(() => {
    const map = new Map<string, boolean>();
    for (const game of lobby?.games ?? []) map.set(game.id, game.enabled);
    return map;
  }, [lobby]);

  const minBet = lobby?.min_bet_rub ?? 0;
  const commission = lobby?.commission_percent ?? 0;
  const showLobby = Boolean((lobby?.open_duels?.length ?? 0) > 0 || (lobby?.open_rooms?.length ?? 0) > 0);
  void showLobby;

  const visible = useMemo(() => visibleCasinoCatalog(), []);

  const catalog = useMemo(
    () => [...visible].sort((a, b) => Number(favorites.includes(b.id)) - Number(favorites.includes(a.id))),
    [favorites, visible],
  );

  function toggleFavorite(id: string) {
    setFavorites((current) => {
      const next = current.includes(id) ? current.filter((item) => item !== id) : [id, ...current];
      writeIdList(FAVORITE_KEY, next);
      return next;
    });
  }

  function onOpen(id: string) {
    pushRecent(id);
  }

  return (
    <div className="casino-lobby" data-casino-lobby="1">
      <section className="casino-hero" aria-labelledby="casino-hero-title">
        <div className="casino-hero-copy">
          <h1 id="casino-hero-title">
            Выберите стол.
            <br />
            <span>Начните раунд.</span>
          </h1>
          <p>Любимые игры. Свой темп. Ваш следующий ход.</p>
          <a className="casino-btn casino-find-table" href="#casino-games">
            Выбрать игру <ArrowRight size={17} aria-hidden />
          </a>
        </div>
        <div className="casino-hero-art">
          <img src="/casino/roulette-hero.png" width={961} height={784} alt="Рулетка, фишки и игровые карты" />
        </div>
      </section>

      <section className="casino-section casino-trn-lobby" id="tournaments" data-casino-trn-lobby="">
        <Link to={casinoTo("/casino/tournaments")} className="casino-trn-lobby-card">
          <span className="casino-trn-lobby-icon" aria-hidden>
            <Trophy size={22} />
          </span>
          <span className="casino-trn-lobby-copy">
            <em>Турниры</em>
            <strong>Играйте на фишки — призы рублями</strong>
            <span>Регистрация, турнирный баланс и живая сетка. Победители получают призы на вывод.</span>
          </span>
          <span className="casino-trn-lobby-cta">
            Открыть <ArrowRight size={16} aria-hidden />
          </span>
        </Link>
      </section>

      <section className="casino-promo" data-casino-promo="" aria-label="Анонсы">
        {PROMOS.map((promo) => (
          <Link key={promo.id} to={casinoTo(promo.to)} className="casino-promo-card">
            <span className="casino-promo-watermark" aria-hidden>
              <promo.Icon size={104} />
            </span>
            <span className="casino-promo-icon" aria-hidden>
              <promo.Icon size={17} />
            </span>
            <em>{promo.kicker}</em>
            <strong>{promo.title}</strong>
            <span>{promo.text}</span>
          </Link>
        ))}
      </section>

          <section className="casino-section casino-games" id="casino-games" tabIndex={-1}>
            <header className="casino-games-head">
              <h2 className="casino-section-title">
                <Flame size={21} aria-hidden />
                Лучшее от FocusBet
              </h2>
              <span className="casino-muted">
                {lobbyReady ? `от ${minBet ? formatBet(minBet) : "—"} · комиссия ${commission ? `${commission}%` : "—"}` : "…"}
              </span>
            </header>
            {catalog.length === 0 ? (
              <p className="casino-muted">Игр сейчас нет.</p>
            ) : (
              <div className="casino-tile-grid">
                {catalog.map((game) => (
                  <CasinoGameTile
                    key={game.id}
                    game={game}
                    enabled={isEnabled(game.id, enabledMap)}
                    favorite={favorites.includes(game.id)}
                    minBet={minBet}
                    commission={commission}
                    onFavorite={toggleFavorite}
                    onOpen={onOpen}
                  />
                ))}
              </div>
            )}
          </section>

          <section className="casino-section" id="rooms">
            <div className="casino-section-head">
              <h2 className="casino-section-title">Живые игры</h2>
              <Link to={casinoTo("/casino/play/pvp_dice?mode=players")}>Открыть лобби</Link>
            </div>
            {(lobby?.open_duels?.length ?? 0) === 0 && (lobby?.open_rooms?.length ?? 0) === 0 ? (
              <p className="casino-muted">
                Активных игр пока нет.{" "}
                <Link to={casinoTo("/casino/play/pvp_dice?mode=players")}>Открыть стол</Link>
              </p>
            ) : (
              <div className="casino-duel-row">
                {lobby?.open_duels?.map((duel) => (
                  <Link key={`duel-${duel.game_id}`} to={casinoTo(`/casino/duels/${duel.game_id}`)} className="casino-duel-card">
                    <span className="casino-duel-emoji" aria-hidden>
                      {duel.game_type === "blackjack" ? "🂡" : duel.game_type === "baccara" ? "🃏" : "🎲"}
                    </span>
                    <span>
                      <strong>Дуэль · {formatBet(duel.bet_rub)}</strong>
                      <span className="casino-muted">Открыта · {openedLabel(duel.opened_at)}</span>
                    </span>
                  </Link>
                ))}
                {lobby?.open_rooms?.map((room) => (
                  <Link key={room.room_id} to={casinoTo(`/casino/rooms/${room.room_id}`)} className="casino-duel-card">
                    <span className="casino-duel-emoji" aria-hidden>
                      <Target size={20} />
                    </span>
                    <span>
                      <strong>
                        {room.filled}/{room.seat_count}
                      </strong>
                      <span className="casino-muted">
                        {formatBet(room.stake_rub)} · {openedLabel(room.opened_at)}
                      </span>
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </section>

    </div>
  );
}
