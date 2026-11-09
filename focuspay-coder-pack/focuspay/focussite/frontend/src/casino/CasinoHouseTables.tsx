import { asDiePips, CasinoDiceTable } from "./CasinoDice";
import type { CasinoHouseTableSnapshot } from "@/lib/public";

function houseSeatLabel(raw: string | undefined, index: number, botCount: number): string {
  const fallback = botCount === 1 ? "FocusBet" : `FocusBet ${index + 1}`;
  const text = (raw || "").trim();
  if (!text || /^казино(\s+\d+)?$/i.test(text)) return fallback;
  return text;
}

export function CasinoHouseTables({
  snap,
  rolling,
  botCount,
  resolving,
  onTake,
  onReroll,
}: {
  snap: CasinoHouseTableSnapshot | null;
  rolling?: boolean;
  botCount: number;
  resolving?: boolean;
  onTake?: () => void;
  onReroll?: () => void;
}) {
  const players = snap
    ? (snap.dice?.players || []).map((row) => ({
        label: row.label,
        value: asDiePips(row.pips),
      }))
    : [{ label: "Вы", value: null }];
  const house = snap
    ? (snap.dice?.house || []).map((row, index) => ({
        label: houseSeatLabel(row.label, index, snap.dice?.house.length || botCount),
        value: asDiePips(row.pips),
      }))
    : Array.from({ length: botCount }, (_, index) => ({
        label: houseSeatLabel(undefined, index, botCount),
        value: null,
      }));
  const choice = snap?.choice;
  const lastKind = snap?.last_round?.kind;

  return (
    <div className="casino-house-table casino-cub-stage" data-casino-house-tables="solo">
      <p className="casino-house-howto">
        Ставка одна. Грань против каждой грани дома: проигрыш любому боту — вся ставка. Ничья — забрать
        выигрыши или один переброс ×2.
      </p>
      <CasinoDiceTable players={players} house={house} rolling={Boolean(rolling)} />
      {choice ? (
        <div className="casino-house-choice" data-casino-house-choice="1">
          <p className="casino-hmac-note">
            Ничья с {choice.ties} {choice.ties === 1 ? "ботом" : "ботами"}. Можно забрать ×{choice.take_multiplier}{" "}
            ({choice.take_payout_rub} ₽) или один раз перебросить ничейных.
          </p>
          <div className="casino-house-choice-actions">
            <button type="button" className="casino-btn" disabled={resolving} onClick={onTake}>
              Забрать {choice.take_payout_rub} ₽
            </button>
            {choice.can_reroll ? (
              <button type="button" className="casino-btn casino-btn-ghost" disabled={resolving} onClick={onReroll}>
                Переброс ×{choice.reroll_multiplier}
              </button>
            ) : null}
          </div>
        </div>
      ) : snap?.last_round && !rolling ? (
        <p className="casino-hmac-note">
          {lastKind === "push"
            ? "Ничья по всем — ставка вернулась."
            : lastKind === "loss"
              ? "Проигрыш любому боту забирает всю ставку."
              : "Исход по граням HMAC, не по порогу 1×1."}
        </p>
      ) : (
        <p className="casino-muted">Слева ставка и число ботов. «Ставка» сразу кидает раунд.</p>
      )}
    </div>
  );
}
