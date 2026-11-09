import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { ApiError } from "@/lib/api";
import { createNardyTable, getNardyLobby, joinNardyTable, type NardyLobby } from "@/lib/public";
import { useSession } from "@/lib/session";
import { casinoTo, goCasinoLogin } from "./casinoPaths";

const STAKES = [100, 500, 1000, 5000];

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value)} ₽`;
}

export function CasinoNardy({ embedded = false }: { embedded?: boolean }) {
  const { isAuthed } = useSession();
  const navigate = useNavigate();
  const [data, setData] = useState<NardyLobby | null>(null);
  const [stake, setStake] = useState(100);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setError("");
    try {
      setData(await getNardyLobby());
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
      goCasinoLogin(navigate, "/casino/play/nardy");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const table = await createNardyTable(stake);
      navigate(casinoTo(`/casino/nardy/${table.table_id}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось открыть стол");
    } finally {
      setBusy(false);
    }
  }

  async function sit(tableId: string) {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/play/nardy");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const table = await joinNardyTable(tableId);
      navigate(casinoTo(`/casino/nardy/${table.table_id}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сесть");
    } finally {
      setBusy(false);
    }
  }

  const tables = data?.tables ?? [];
  return (
    <div className="casino-table-lobby" data-casino-nardy="lobby">
      {embedded ? null : (
        <p className="casino-muted">
          <Link to={casinoTo("/casino")}>← В лобби</Link>
        </p>
      )}
      <section className="casino-create-card">
        <div className="casino-create-card-head">
          <div>
            <p className="casino-create-eyebrow">Нарды</p>
            <h2>Новый стол</h2>
            <p className="casino-muted">Двое за доской. Рейк {data ? `${data.rake_percent}%` : "5%"} с проигрыша.</p>
          </div>
          <button type="button" className="casino-icon-btn" onClick={() => void load()} aria-label="Обновить">
            <RefreshCw size={16} />
          </button>
        </div>
        <div className="casino-create-field">
          <span>Ставка</span>
          <div className="casino-choice-row">
            {STAKES.map((amount) => (
              <button key={amount} type="button" className={amount === stake ? "is-on" : ""} onClick={() => setStake(amount)}>
                {formatRub(amount)}
              </button>
            ))}
          </div>
        </div>
        <div className="casino-create-summary">
          <div><span>Ставка</span><strong>{formatRub(stake)}</strong></div>
          <div><span>Места</span><strong>2</strong></div>
        </div>
        <button type="button" className="casino-btn casino-btn-primary" disabled={busy} onClick={() => void createTable()}>
          <Plus size={16} /> {isAuthed ? `Открыть стол · ${formatRub(stake)}` : "Войти и открыть стол"}
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
            <p>Белые сверху справа, чёрные снизу слева. С головы за ход одна шашка, боя нет.</p>
          </div>
        ) : (
          <ul className="casino-poker-list">
            {tables.map((table) => {
              const openSeat = table.status === "waiting" && table.seated < 2;
              return (
                <li key={table.table_id} className="casino-poker-row nardy-table-row">
                  <strong>{formatRub(table.stake_rub)}</strong>
                  <span>
                    {table.seated}/2 · {table.status === "waiting" ? "ждут соперника" : "партия"}
                  </span>
                  <span className="nardy-table-actions">
                    <Link to={casinoTo(`/casino/nardy/${table.table_id}`)} className="casino-btn casino-btn-ghost">
                      Смотреть
                    </Link>
                    {openSeat ? (
                      <button type="button" className="casino-btn casino-btn-primary" disabled={busy} onClick={() => void sit(table.table_id)}>
                        Сесть
                      </button>
                    ) : null}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
