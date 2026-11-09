export interface CasinoHouseLimitPreset {
  id: string;
  label: string;
  description: string;
  max_exposure_rub: number;
  max_concurrent_games: number;
}

export const CASINO_HOUSE_LIMIT_PRESETS: CasinoHouseLimitPreset[] = [
  {
    id: "conservative",
    label: "Консервативно",
    description: "Малый риск: до 5 столов, exposure 5 000 ₽",
    max_exposure_rub: 5000,
    max_concurrent_games: 5,
  },
  {
    id: "standard",
    label: "Стандарт",
    description: "Баланс риска: до 20 столов, exposure 50 000 ₽",
    max_exposure_rub: 50000,
    max_concurrent_games: 20,
  },
  {
    id: "aggressive",
    label: "Агрессивно",
    description: "Высокая нагрузка: до 50 столов, exposure 200 000 ₽",
    max_exposure_rub: 200000,
    max_concurrent_games: 50,
  },
];

export const DEFAULT_TEST_STAKE_RUB = 100;
