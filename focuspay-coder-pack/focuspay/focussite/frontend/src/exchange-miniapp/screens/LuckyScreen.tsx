import { CasinoRaffle } from "@/casino/CasinoRaffle";
import "@/casino/casino.css";
import "@/casino/casino-skin.css";

export function LuckyScreen() {
  return (
    <div className="ex-lucky casino-root">
      <CasinoRaffle embedded />
    </div>
  );
}
