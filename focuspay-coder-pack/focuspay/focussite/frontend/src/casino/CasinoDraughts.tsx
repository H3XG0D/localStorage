import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { ApiError } from "@/lib/api";
import { createDraughtsTable, getDraughtsLobby, type DraughtsLobby } from "@/lib/public";
import { useSession } from "@/lib/session";
import { casinoTo, goCasinoLogin } from "./casinoPaths";
import { DraughtsBoard } from "./CasinoDraughtsTable";

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value)} ₽`;
}

export function CasinoDraughts({ embedded = false }: { embedded?: boolean }) {
  const { isAuthed } = useSession();
  const navigate = useNavigate();
  const [data, setData] = useState<DraughtsLobby | null>(null);
  const [stake, setStake] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setError("");
    try {
      const next = await getDraughtsLobby();
      setData(next);
      setStake((current) => current || String(next.min_stake_rub));
    } catch (err) {
      const missing = err instanceof ApiError && err.status === 404;
      setError(missing ? "Список столов на сервере ещё не включён" : err instanceof Error ? err.message : "Не удалось загрузить столы");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function createTable() {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/play/russian_draughts");
      return;
    }
    const amount = Number(stake);
    if (!Number.isFinite(amount) || amount <= 0) {
      setError("Укажите ставку");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const table = await createDraughtsTable(amount);
      navigate(casinoTo(`/casino/draughts/${table.table_id}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось открыть стол");
    } finally {
      setBusy(false);
    }
  }

  const rakeCap = data && data.rake_cap_rub > 0 ? `, не больше ${formatRub(data.rake_cap_rub)}` : "";
  const tables = data?.tables ?? [];
  const stakeNumber = Number(stake);

  return (
    <div className="casino-table-lobby" data-casino-draughts="lobby">
      {embedded ? null : (
        <p className="casino-muted">
          <Link to={casinoTo("/casino")}>← В лобби</Link>
        </p>
      )}
      <section className="casino-create-card">
        <div className="casino-create-card-head">
          <div>
            <p className="casino-create-eyebrow">Русские шашки</p>
            <h2>Новый стол</h2>
            <p className="casino-muted">
              8×8, по 12 шашек. Победа — банк минус рейк {data ? `${data.rake_percent}%${rakeCap}` : "как у холдема"}. Бота нет.
            </p>
          </div>
          <button type="button" className="casino-icon-btn" onClick={() => void load()} aria-label="Обновить">
            <RefreshCw size={16} />
          </button>
        </div>
        {data && !data.enabled ? <p className="casino-muted">Шашки выключены в настройках.</p> : null}
        <div className="casino-create-field">
          <span>Ставка за место</span>
          <div className="casino-amount-control">
            <input inputMode="decimal" value={stake} onChange={(event) => setStake(event.target.value)} aria-label="Сумма ставки" />
            <strong>₽</strong>
          </div>
        </div>
        {data ? (
          <p className="casino-lobby-info">
            От {formatRub(data.min_stake_rub)} до {formatRub(data.max_stake_rub)}. На ход {data.timeout_seconds} с, потом сдача.
          </p>
        ) : null}
        <button
          type="button"
          className="casino-btn casino-btn-primary"
          disabled={busy || data?.enabled === false}
          onClick={() => void createTable()}
        >
          <Plus size={16} /> {isAuthed ? `Открыть стол${Number.isFinite(stakeNumber) && stakeNumber > 0 ? ` · ${formatRub(stakeNumber)}` : ""}` : "Войти и открыть стол"}
        </button>
      </section>
      <div className="casino-lobby-tables">
        <div className="casino-table-toolbar">
          <h2>Открытые столы <span>{tables.length}</span></h2>
        </div>
        {error ? <p className="casino-duel-error">{error}</p> : null}
        {tables.length === 0 ? (
          <div className="casino-lobby-empty">
            <h3>Первый стол — ваш</h3>
            <p>Ход появится у белых, когда сядут чёрные. Ничья возвращает обе ставки.</p>
          </div>
        ) : (
          <ul className="casino-poker-list">
            {tables.map((table) => (
              <li key={table.table_id}>
                <Link to={casinoTo(`/casino/draughts/${table.table_id}`)} className="casino-poker-row">
                  <strong>{formatRub(table.stake_rub)}</strong>
                  <span>
                    {table.seated}/2 · {table.status === "waiting" ? "ждут соперника" : "партия"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        <DraughtsBoard
          pieces={[
            ..."a1,c1,e1,g1,b2,d2,f2,h2,a3,c3,e3,g3".split(",").map((square) => ({ square, side: "white" as const, kind: "man" as const })),
            ..."a7,c7,e7,g7,b6,d6,f6,h6,b8,d8,f8,h8".split(",").map((square) => ({ square, side: "black" as const, kind: "man" as const })),
          ]}
          side="white"
          origins={new Set()}
          targets={new Set()}
          selected=""
          interactive={false}
          onSquare={() => undefined}
        />
      </div>
    </div>
  );
}
