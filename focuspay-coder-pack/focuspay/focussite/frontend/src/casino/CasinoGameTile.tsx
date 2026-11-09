import { ArrowRight, Star } from "lucide-react";
import { Link } from "react-router-dom";
import { casinoTo } from "./casinoPaths";
import { type CasinoCatalogGame } from "./gameCatalog";
import { gameRailIcon } from "./gameRailIcon";

const TILE_PHOTO: Record<string, string> = {
  pvp_dice: "/casino/dice-card.png",
  baccara: "/casino/baccara-card.jpg",
  blackjack: "/casino/blackjack-card.jpg",
  russian_draughts: "/casino/draughts-card.jpg",
  nardy: "/casino/nardy-card.jpg",
  holdem: "/casino/holdem-card.jpg",
  roulette: "/casino/roulette-card.jpg",
  jackpot: "/casino/jackpot-card.jpg",
  fixed_room: "/casino/rooms-card.jpg",
  raffle: "/casino/raffle-card.jpg",
};

function tilePhoto(gameId: string): string | null {
  return TILE_PHOTO[gameId] ?? null;
}

export function CasinoGameTile({
  game,
  enabled,
  favorite,
  minBet,
  commission,
  onFavorite,
  onOpen,
}: {
  game: CasinoCatalogGame;
  enabled: boolean;
  favorite: boolean;
  minBet: number;
  commission: number;
  onFavorite: (id: string) => void;
  onOpen: (id: string) => void;
}) {
  const meta = enabled
    ? `от ${Math.round(minBet)} ₽ · комиссия ${commission}%`
    : "выключено в настройках";
  const photo = tilePhoto(game.id);
  return (
    <Link
      to={casinoTo(game.href)}
      data-casino-tile={game.id}
      data-enabled={enabled ? "1" : "0"}
      className={`casino-tile${enabled ? "" : " is-off"}${favorite ? " is-favorite" : ""}`}
      onClick={() => onOpen(game.id)}
    >
      {photo ? <img className="casino-tile-photo" src={photo} alt="" width={960} height={540} /> : null}
      <span className="casino-tile-chip" aria-hidden>
        {gameRailIcon(game.id, game.emoji)}
      </span>
      <span className="casino-tile-play" aria-hidden>
        <ArrowRight size={16} />
      </span>
      <span className="casino-tile-caption">
        <span className="casino-tile-name">{game.name}</span>
        <span className="casino-tile-howto" data-casino-tile-howto={game.id}>
          {game.howTo}
        </span>
        <span className="casino-tile-meta">{meta}</span>
      </span>
      <button
        type="button"
        className={`casino-tile-fav${favorite ? " is-on" : ""}`}
        aria-label={favorite ? "Убрать из избранного" : "В избранное"}
        aria-pressed={favorite}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          onFavorite(game.id);
        }}
      >
        <Star size={16} fill={favorite ? "currentColor" : "none"} />
      </button>
    </Link>
  );
}
