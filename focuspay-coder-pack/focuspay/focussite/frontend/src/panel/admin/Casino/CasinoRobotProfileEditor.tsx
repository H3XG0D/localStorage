import { useState } from "react";
import { toast } from "sonner";
import { CASINO_HOUSE_LIMIT_PRESETS } from "@/panel/admin/Casino/casinoHousePresets";
import {
  ADMIN_CASINO_GAME_TYPES,
  patchCasinoHouseProfile,
  type AdminCasinoGameType,
  type AdminCasinoHouseProfile,
} from "@/panel/lib/adminApi";
import { PanelApiError } from "@/panel/lib/panelApi";
import { Button, Field, Input, Modal, Select } from "@/panel/ui/primitives";

const PVP_GAMES = ADMIN_CASINO_GAME_TYPES.filter((game) => game.startsWith("pvp_"));
const LIVE_GAMES = new Set<string>(ADMIN_CASINO_GAME_TYPES.filter((game) => game !== "holdem" && game !== "jackpot" && game !== "clan_war" && game !== "russian_draughts"));

function liveAllowedGames(games: readonly string[]): AdminCasinoGameType[] {
  return games.filter((game): game is AdminCasinoGameType => LIVE_GAMES.has(game));
}

function message(error: unknown, fallback: string): string {
  return error instanceof PanelApiError ? error.message : fallback;
}

export function CasinoRobotProfileEditor({
  profile,
  onClose,
  onSaved,
}: {
  profile: AdminCasinoHouseProfile;
  onClose: () => void;
  onSaved: (profile: AdminCasinoHouseProfile) => void;
}) {
  const [active, setActive] = useState(profile.is_active);
  const [displayName, setDisplayName] = useState(profile.display_name);
  const [mode, setMode] = useState<AdminCasinoHouseProfile["mode"]>(profile.mode);
  const [allowedGames, setAllowedGames] = useState<AdminCasinoGameType[]>(() => liveAllowedGames(profile.allowed_games));
  const [minBet, setMinBet] = useState(String(profile.min_bet_rub));
  const [maxBet, setMaxBet] = useState(String(profile.max_bet_rub));
  const [exposure, setExposure] = useState(String(profile.max_exposure_rub));
  const [concurrent, setConcurrent] = useState(String(profile.max_concurrent_games));
  const [saving, setSaving] = useState(false);

  const toggleGame = (game: AdminCasinoGameType) => {
    setAllowedGames((items) =>
      items.includes(game) ? items.filter((item) => item !== game) : [...items, game],
    );
  };

  const applyPreset = (presetId: string) => {
    const preset = CASINO_HOUSE_LIMIT_PRESETS.find((item) => item.id === presetId);
    if (!preset) return;
    setExposure(String(preset.max_exposure_rub));
    setConcurrent(String(preset.max_concurrent_games));
  };

  const submit = async () => {
    const values = [Number(minBet), Number(maxBet), Number(exposure), Number(concurrent)];
    if (!displayName.trim()) {
      toast.error("Укажите название робота");
      return;
    }
    if (!allowedGames.length) {
      toast.error("Выберите хотя бы одну игру");
      return;
    }
    if (
      !values.every(Number.isFinite) ||
      values[0] <= 0 ||
      values[1] < values[0] ||
      values[2] < 0 ||
      !Number.isInteger(values[3]) ||
      values[3] <= 0
    ) {
      toast.error("Проверьте лимиты профиля");
      return;
    }
    setSaving(true);
    try {
      const saved = await patchCasinoHouseProfile(profile.id, {
        is_active: active,
        display_name: displayName.trim(),
        mode,
        allowed_games: allowedGames,
        min_bet_rub: values[0],
        max_bet_rub: values[1],
        max_exposure_rub: values[2],
        max_concurrent_games: values[3],
      });
      toast.success("Профиль робота сохранён");
      onSaved(saved);
    } catch (error) {
      toast.error(message(error, "Не удалось сохранить профиль"));
    } finally {
      setSaving(false);
    }
  };

  const gameOptions = mode === "pvp_robot" ? PVP_GAMES : (["cub"] as AdminCasinoGameType[]);

  return (
    <Modal
      open
      title={`Робот: ${profile.display_name}`}
      onClose={onClose}
      size="lg"
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={saving}>
            Отмена
          </Button>
          <Button type="button" variant="primary" onClick={() => void submit()} disabled={saving}>
            {saving ? "Сохранение…" : "Сохранить"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="flex items-center gap-2 text-[13px] sm:col-span-2">
          <input
            type="checkbox"
            checked={active}
            onChange={(event) => setActive(event.target.checked)}
            className="h-4 w-4 accent-[var(--accent)]"
          />
          Бот включён
        </label>

        <Field label="Название">
          <Input value={displayName} onChange={(event) => setDisplayName(event.target.value)} disabled={saving} />
        </Field>

        <Field label="Тип робота">
          <Select
            value={mode}
            onChange={(event) => {
              const nextMode = event.target.value as AdminCasinoHouseProfile["mode"];
              setMode(nextMode);
              if (nextMode === "house_robot") setAllowedGames(["cub"]);
              else if (!allowedGames.some((game) => game.startsWith("pvp_"))) setAllowedGames(["pvp_dice"]);
            }}
            disabled={saving}
          >
            <option value="pvp_robot">PvP-бот (столы V2)</option>
            <option value="house_robot">House-бот (cub vs казино)</option>
          </Select>
        </Field>

        <div className="sm:col-span-2 space-y-2">
          <div className="text-[12px] text-[var(--text-muted)]">Разрешённые игры</div>
          <div className="flex flex-wrap gap-2">
            {gameOptions.map((game) => (
              <label
                key={game}
                className="flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-strong)] px-2 py-1 text-[12px]"
              >
                <input
                  type="checkbox"
                  checked={allowedGames.includes(game)}
                  onChange={() => toggleGame(game)}
                  className="h-3.5 w-3.5 accent-[var(--accent)]"
                />
                <span className="font-mono">{game}</span>
              </label>
            ))}
          </div>
        </div>

        <Field label="Мин. ставка (₽)">
          <Input type="number" value={minBet} onChange={(event) => setMinBet(event.target.value)} disabled={saving} />
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">Ниже этой суммы бот не сядет за стол</p>
        </Field>
        <Field label="Макс. ставка (₽)">
          <Input type="number" value={maxBet} onChange={(event) => setMaxBet(event.target.value)} disabled={saving} />
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">Выше этой суммы бот не сядет за стол</p>
        </Field>
        <Field label="Макс. проигрыш банка (₽)">
          <Input type="number" value={exposure} onChange={(event) => setExposure(event.target.value)} disabled={saving} />
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">Суммарный резерв по активным столам; 0 = без лимита</p>
        </Field>
        <Field label="Параллельных столов">
          <Input type="number" step="1" value={concurrent} onChange={(event) => setConcurrent(event.target.value)} disabled={saving} />
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">Сколько игр бот может вести одновременно</p>
        </Field>

        <div className="sm:col-span-2 space-y-2">
          <div className="text-[12px] text-[var(--text-muted)]">Быстрые пресеты лимитов</div>
          <div className="flex flex-wrap gap-2">
            {CASINO_HOUSE_LIMIT_PRESETS.map((preset) => (
              <Button key={preset.id} type="button" size="sm" variant="secondary" onClick={() => applyPreset(preset.id)} disabled={saving}>
                {preset.label}
              </Button>
            ))}
          </div>
          <p className="text-[11px] text-[var(--text-muted)]">
            Пресет меняет только exposure и параллельность. Ставки настраиваются отдельно.
          </p>
        </div>
      </div>
    </Modal>
  );
}
