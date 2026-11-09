import type { ReactElement } from "react";
import { Navigate, Route, useParams } from "react-router-dom";
import { CasinoClanWars } from "./CasinoClanWars";
import { CasinoClans } from "./CasinoClans";
import { CasinoDuelRoom } from "./CasinoDuelRoom";
import { CasinoFixedRooms } from "./CasinoFixedRooms";
import { CasinoLobby } from "./CasinoLobby";
import { CasinoPlay } from "./CasinoPlay";
import { CasinoPlayerSettings } from "./CasinoPlayerSettings";
import { CasinoPokerTable } from "./CasinoPokerTable";
import { CasinoNardyTable } from "./CasinoNardyTable";
import { CasinoDraughtsTable } from "./CasinoDraughtsTable";
import { CasinoProfile } from "./CasinoProfile";
import { CasinoTournaments } from "./CasinoTournaments";
import { CasinoWallet } from "./CasinoWallet";
import { CasinoV2Table } from "./CasinoV2Table";
import { casinoTo, RedirectToCasinoPlay } from "./casinoPaths";
import { CASINO_CLANS_PAGE_HIDDEN, canonicalGameId, isShelvedCasinoGame } from "./gameCatalog";
import { CasinoFairness } from "@/pages/CasinoFairness";

function LobbyIfShelved({ id, children }: { id: string; children: ReactElement }) {
  if (isShelvedCasinoGame(id)) return <Navigate to={casinoTo("/casino")} replace />;
  return children;
}

function LobbyIfClansHidden({ children }: { children: ReactElement }) {
  if (CASINO_CLANS_PAGE_HIDDEN) return <Navigate to={casinoTo("/casino")} replace />;
  return children;
}

function PlayRoute() {
  const { gameId } = useParams();
  return (
    <LobbyIfShelved id={canonicalGameId(gameId || "")}>
      <CasinoPlay />
    </LobbyIfShelved>
  );
}

/** Parked games stay in the repo. Hidden ones bounce to the lobby. /casino/duels → rooms. */
export const casinoChildRoutes = (
  <>
    <Route index element={<CasinoLobby />} />
    <Route path="duels" element={<RedirectToCasinoPlay gameId="fixed_room" mode="players" />} />
    <Route path="duels/:duelId" element={<CasinoDuelRoom />} />
    <Route path="tables/:tableId" element={<CasinoV2Table />} />
    <Route path="u/:userId" element={<CasinoProfile />} />
    <Route path="me" element={<CasinoProfile />} />
    <Route path="wallet" element={<CasinoWallet />} />
    <Route path="settings" element={<CasinoPlayerSettings />} />
    <Route path="tournaments" element={<CasinoTournaments />} />
    <Route path="tournaments/:tournamentId" element={<CasinoTournaments />} />
    <Route path="fairness" element={<CasinoFairness />} />
    <Route
      path="poker"
      element={
        <LobbyIfShelved id="holdem">
          <RedirectToCasinoPlay gameId="holdem" mode="players" />
        </LobbyIfShelved>
      }
    />
    <Route
      path="poker/:tableId"
      element={
        <LobbyIfShelved id="holdem">
          <CasinoPokerTable />
        </LobbyIfShelved>
      }
    />
    <Route
      path="nardy/:tableId"
      element={
        <LobbyIfShelved id="nardy">
          <CasinoNardyTable />
        </LobbyIfShelved>
      }
    />
    <Route
      path="draughts/:tableId"
      element={
        <LobbyIfShelved id="russian_draughts">
          <CasinoDraughtsTable />
        </LobbyIfShelved>
      }
    />
    <Route path="jackpot" element={<RedirectToCasinoPlay gameId="jackpot" mode="players" />} />
    <Route path="rooms" element={<RedirectToCasinoPlay gameId="fixed_room" mode="players" />} />
    <Route path="rooms/:roomId" element={<CasinoFixedRooms />} />
    <Route path="wars" element={<RedirectToCasinoPlay gameId="clan_war" mode="players" />} />
    <Route
      path="wars/:warId"
      element={
        <LobbyIfShelved id="clan_war">
          <CasinoClanWars />
        </LobbyIfShelved>
      }
    />
    <Route
      path="clans"
      element={
        <LobbyIfClansHidden>
          <CasinoClans />
        </LobbyIfClansHidden>
      }
    />
    <Route
      path="clans/:tag"
      element={
        <LobbyIfClansHidden>
          <CasinoClans />
        </LobbyIfClansHidden>
      }
    />
    <Route path="play/:gameId" element={<PlayRoute />} />
  </>
);
