import axios from "axios";

const LAB_USER_KEY = "focuspay_lab_user";

export function getLabUser(): string {
  return localStorage.getItem(LAB_USER_KEY) || "alice";
}

export function setLabUser(userId: string): void {
  localStorage.setItem(LAB_USER_KEY, userId);
}

const api = axios.create({ baseURL: "" });

api.interceptors.request.use((config) => {
  config.headers["X-Lab-User"] = getLabUser();
  return config;
});

export default api;

export interface CurrentRound {
  round_id: number;
  seconds_left: number;
  red_total: number;
  blue_total: number;
  red_pct: number;
  blue_pct: number;
  bank: number;
  status: "open" | "locked" | "resolved" | "cancelled";
  my_bet: { side: "red" | "blue"; amount: number } | null;
  balance_available: number;
}

export interface HistoryItem {
  round_id: number;
  winner: "red" | "blue" | null;
  red_total: number;
  blue_total: number;
  ended_at: string;
}

export async function fetchCurrent(): Promise<CurrentRound> {
  const { data } = await api.get<CurrentRound>("/api/battle/current");
  return data;
}

export async function placeBet(side: "red" | "blue", amountRub: number): Promise<CurrentRound> {
  const { data } = await api.post<CurrentRound>("/api/battle/bet", {
    side,
    amount_rub: amountRub,
  });
  return data;
}

export async function fetchHistory(limit = 20): Promise<HistoryItem[]> {
  const { data } = await api.get<HistoryItem[]>("/api/battle/history", { params: { limit } });
  return data;
}
