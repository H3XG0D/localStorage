import { useEffect, useState } from "react";
import {
  getCasinoRoom,
  getCasinoV2Table,
  type CasinoInboxSession,
  type CasinoRoomSnapshot,
  type CasinoV2TableView,
} from "@/lib/public";
import { CasinoRoomLiveCanvas, roomStatusLabel } from "./CasinoRoomLiveCanvas";
import { CasinoTableTile } from "./CasinoTableTile";
import { CasinoV2CompactPlay, v2StatusLabel } from "./CasinoV2CompactPlay";

function formatRub(value: number | string): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value) || 0)} ₽`;
}

function sessionMeta(row: CasinoInboxSession): string {
  return row.stake_rub ? formatRub(row.stake_rub) : row.body || row.status;
}

export function CasinoLiveDock({
  sessions,
  onOpen,
  onDrop,
}: {
  sessions: CasinoInboxSession[];
  onOpen: (row: CasinoInboxSession) => void;
  onDrop: (row: CasinoInboxSession) => void;
}) {
  const live = sessions.slice(0, 10);
  if (!live.length) return null;
  return (
    <div className="casino-live-dock" data-casino-live-dock="" data-casino-now-playing="">
      <div className="casino-live-dock-head">
        <strong>Мои столы</strong>
        <span>{live.length}/10</span>
      </div>
      <div className="casino-live-dock-grid">
        {live.map((row) => (
          <DockTile key={`${row.kind}-${row.game_id}`} row={row} onOpen={() => onOpen(row)} onDrop={() => onDrop(row)} />
        ))}
      </div>
    </div>
  );
}

function DockTile({
  row,
  onOpen,
  onDrop,
}: {
  row: CasinoInboxSession;
  onOpen: () => void;
  onDrop: () => void;
}) {
  const canDrop = Boolean(row.can_cancel || row.can_leave);
  if (row.kind === "room") {
    return <RoomDockTile row={row} onOpen={onOpen} onDrop={onDrop} canDrop={canDrop} />;
  }
  if (row.kind === "v2") {
    return <V2DockTile row={row} onOpen={onOpen} onDrop={onDrop} canDrop={canDrop} />;
  }
  return (
    <CasinoTableTile
      id={`${row.kind}-${row.game_id}`}
      title={row.title}
      meta={sessionMeta(row)}
      status={row.status}
      seated
      onOpen={onOpen}
      actions={
        canDrop ? (
          <button type="button" className="casino-btn casino-btn-ghost" onClick={onDrop}>
            {row.can_leave ? "Встать" : "Отменить"}
          </button>
        ) : null
      }
    >
      <p className="casino-muted">{row.body || "Открытый стол"}</p>
    </CasinoTableTile>
  );
}

function RoomDockTile({
  row,
  onOpen,
  onDrop,
  canDrop,
}: {
  row: CasinoInboxSession;
  onOpen: () => void;
  onDrop: () => void;
  canDrop: boolean;
}) {
  const [room, setRoom] = useState<CasinoRoomSnapshot | null>(null);
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const next = await getCasinoRoom(row.game_id);
        if (!cancelled) setRoom(next);
      } catch {
        /* keep */
      }
    }
    void load();
    const poll = window.setInterval(() => void load(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(poll);
    };
  }, [row.game_id]);
  return (
    <CasinoTableTile
      id={row.game_id}
      title={room ? formatRub(room.stake_rub) : row.title}
      meta={room ? `${room.filled}/${room.seat_count}` : sessionMeta(row)}
      status={room ? roomStatusLabel(room) : row.status}
      seated
      countdownEndsAt={room?.status === "countdown" ? room.countdown_ends_at : null}
      onOpen={onOpen}
      actions={
        canDrop ? (
          <button type="button" className="casino-btn casino-btn-ghost" onClick={onDrop}>
            {row.can_cancel ? "Отменить" : "Выйти"}
          </button>
        ) : null
      }
    >
      {room ? <CasinoRoomLiveCanvas room={room} compact /> : <p className="casino-muted">Загрузка…</p>}
    </CasinoTableTile>
  );
}

function V2DockTile({
  row,
  onOpen,
  onDrop,
  canDrop,
}: {
  row: CasinoInboxSession;
  onOpen: () => void;
  onDrop: () => void;
  canDrop: boolean;
}) {
  const [table, setTable] = useState<CasinoV2TableView | null>(null);
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const next = await getCasinoV2Table(row.game_id);
        if (!cancelled) setTable(next);
      } catch {
        /* keep */
      }
    }
    void load();
    const poll = window.setInterval(() => void load(), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(poll);
    };
  }, [row.game_id]);
  return (
    <CasinoTableTile
      id={row.game_id}
      title={table ? formatRub(table.stake_rub) : row.title}
      meta={table ? `${table.roster.length}/${table.max_seats}` : sessionMeta(row)}
      status={table ? v2StatusLabel(table) : row.status}
      seated
      countdownEndsAt={table?.countdown_ends_at}
      onOpen={onOpen}
      actions={
        canDrop ? (
          <button type="button" className="casino-btn casino-btn-ghost" onClick={onDrop}>
            {row.can_cancel ? "Отменить" : "Встать"}
          </button>
        ) : null
      }
    >
      {table ? <CasinoV2CompactPlay table={table} /> : <p className="casino-muted">Загрузка…</p>}
    </CasinoTableTile>
  );
}
