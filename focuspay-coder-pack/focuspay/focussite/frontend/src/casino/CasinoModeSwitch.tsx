export type CasinoPlayMode = "house" | "players";

export function CasinoModeSwitch({
  mode,
  onChange,
  houseDisabled,
  playersDisabled,
}: {
  mode: CasinoPlayMode;
  onChange: (mode: CasinoPlayMode) => void;
  houseDisabled?: boolean;
  playersDisabled?: boolean;
}) {
  return (
    <div className="casino-mode-switch" role="tablist" aria-label="Режим игры" data-casino-mode={mode}>
      <button
        type="button"
        role="tab"
        aria-selected={mode === "house"}
        className={mode === "house" ? "is-on" : ""}
        disabled={houseDisabled}
        onClick={() => onChange("house")}
      >
        Против FocusBet
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={mode === "players"}
        className={mode === "players" ? "is-on" : ""}
        disabled={playersDisabled}
        onClick={() => onChange("players")}
      >
        С игроками
      </button>
    </div>
  );
}
