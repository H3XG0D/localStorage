import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { createCasinoPokerTable, getCasinoPokerLobby, type CasinoPokerLobby } from "@/lib/public";
import { useSession } from "@/lib/session";
import { casinoTo, goCasinoLogin } from "./casinoPaths";

function formatRub(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value)} ₽`;
}

export function CasinoPoker({ embedded = false }: { embedded?: boolean }) {
  const { isAuthed } = useSession();
  const navigate = useNavigate();
  const [data, setData] = useState<CasinoPokerLobby | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setError("");
    try {
      setData(await getCasinoPokerLobby());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить столы");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function createTable() {
    if (!isAuthed) {
      goCasinoLogin(navigate, "/casino/play/holdem?mode=players");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const table = await createCasinoPokerTable(6);
      navigate(casinoTo(`/casino/poker/${table.table_id}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось открыть стол");
    } finally {
      setBusy(false);
    }
  }

  const tables = data?.tables ?? [];
  return (
    <div className="casino-poker-lobby casino-table-lobby" data-casino-poker="1">
      {embedded ? null : (
        <p className="casino-muted">
          <Link to={casinoTo("/casino")}>← В лобби</Link>
        </p>
      )}
      <section className="casino-create-card">
        <div className="casino-create-card-head">
          <div>
            <p className="casino-create-eyebrow">Техасский холдем</p>
            <h2>Новый стол</h2>
            <p className="casino-muted">
              Кэш-стол 2–6 мест. Бай-ин {data ? `${formatRub(data.min_buyin_rub)}–${formatRub(data.max_buyin_rub)}` : "…"},
              блайнды {data ? `${formatRub(data.small_blind_rub)}/${formatRub(data.big_blind_rub)}` : "…"}. Рейк{" "}
              {data ? `${data.rake_percent}%` : "…"}.
            </p>
          </div>
          <button type="button" className="casino-icon-btn" onClick={() => void load()} aria-label="Обновить">
            <RefreshCw size={16} />
          </button>
        </div>
        {data && !data.enabled ? <p className="casino-muted">Покер выключен в настройках.</p> : null}
        <button type="button" className="casino-btn casino-btn-primary" disabled={busy || data?.enabled === false} onClick={() => void createTable()}>
          <Plus size={16} /> {isAuthed ? "Открыть стол" : "Войти и открыть стол"}
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
            <p>Блайнды и бай-ин общие. За стол садятся от двух до шести человек.</p>
          </div>
        ) : (
          <ul className="casino-poker-list">
            {tables.map((table) => (
              <li key={table.table_id}>
                <Link to={casinoTo(`/casino/poker/${table.table_id}`)} className="casino-poker-row">
                  <strong>
                    {formatRub(table.small_blind_rub)}/{formatRub(table.big_blind_rub)}
                  </strong>
                  <span>
                    {table.seated}/{table.max_seats} мест
                  </span>
                  <span>бай-ин от {formatRub(table.min_buyin_rub)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
