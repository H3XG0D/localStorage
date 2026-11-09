import { useState } from "react";
import "./casino.css";
import "./casino-skin.css";

const SURFACES = [
  { token: "--surface-0", hex: "#0c0c0c", label: "0 · глубокая" },
  { token: "--surface-1", hex: "#111111", label: "1" },
  { token: "--surface-2", hex: "#121212", label: "2" },
  { token: "--surface-3", hex: "#191919", label: "3" },
  { token: "--surface-4", hex: "#1f1f1f", label: "4 · приподнятая" },
] as const;

const STATUS = [
  { id: "accent", title: "Акцент (белый)", softClass: "casino-badge-accent", btnClass: "casino-btn" },
  { id: "win", title: "Выигрыш", softClass: "casino-badge-win", btnClass: "casino-btn casino-btn-win" },
  { id: "lose", title: "Проигрыш", softClass: "casino-badge-lose", btnClass: "casino-btn casino-btn-lose" },
  { id: "vip", title: "VIP / награда", softClass: "casino-badge-vip", btnClass: "casino-btn casino-btn-vip" },
] as const;

export function CasinoTokensPreview() {
  const [railOpen, setRailOpen] = useState(false);
  return (
    <div className="casino-root" data-casino-tokens="1">
      <header
        data-casino-header=""
        style={{
          height: "var(--casino-header-h)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 16px",
          background: "var(--surface-2)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <strong>FocusBet · токены</strong>
        <button type="button" className="casino-btn casino-btn-ghost" onClick={() => setRailOpen((open) => !open)}>
          Рельс {railOpen ? "240" : "60"}
        </button>
      </header>

      <div style={{ display: "flex", minHeight: "calc(100dvh - var(--casino-header-h))" }}>
        <aside
          data-casino-rail={railOpen ? "expanded" : "collapsed"}
          style={{
            width: railOpen ? "var(--casino-rail-expanded)" : "var(--casino-rail-collapsed)",
            background: "var(--surface-1)",
            borderRight: "1px solid var(--border)",
            transition: "width var(--casino-rail-duration)",
          }}
        />
        <main
          data-casino-content=""
          style={{
            flex: 1,
            maxWidth: "var(--casino-content-max)",
            padding: 20,
            display: "grid",
            gap: 20,
          }}
        >
          <p style={{ margin: 0, color: "var(--text-muted)", maxWidth: 720 }}>
            FocusBet: поверхности почти чёрные, сетка как на главной. Акцент — белый{" "}
            <code data-casino-accent="#f4f4f4">#f4f4f4</code>, не зелёный Stake. Запрещены navy{" "}
            <code data-forbidden-stake-navy="#0f212e">#0f212e</code> и neon{" "}
            <code data-forbidden-stake-green="#00e701">#00e701</code>. Зелёный и красный только у выигрыша и проигрыша.
            Золото только VIP. Премиум через spacing и тип, не через glow.
          </p>

          <section>
            <h2 style={{ fontSize: 14, margin: "0 0 10px" }}>Пять ступеней поверхности</h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: 8 }}>
              {SURFACES.map((surface) => (
                <div
                  key={surface.token}
                  data-casino-surface={surface.token}
                  style={{
                    background: `var(${surface.token})`,
                    border: "1px solid var(--border-strong)",
                    borderRadius: "var(--casino-radius)",
                    padding: 12,
                    minHeight: 88,
                  }}
                >
                  <div style={{ fontFamily: "var(--casino-font-mono)", fontSize: 11 }}>{surface.token}</div>
                  <div style={{ color: "var(--text-muted)", fontSize: 12 }}>{surface.label}</div>
                  <div style={{ fontFamily: "var(--casino-font-mono)", fontSize: 11 }}>{surface.hex}</div>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h2 style={{ fontSize: 14, margin: "0 0 10px" }}>Статусы: заливка / наведение / нажатие / 16%</h2>
            <div style={{ display: "grid", gap: 12 }}>
              {STATUS.map((row) => (
                <div
                  key={row.id}
                  data-casino-status={row.id}
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    alignItems: "center",
                    gap: 10,
                    background: "var(--surface-1)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--casino-radius-lg)",
                    padding: 12,
                  }}
                >
                  <div style={{ width: 140 }}>{row.title}</div>
                  <span className={`casino-badge ${row.softClass}`}>бейдж 16%</span>
                  <button type="button" className={row.btnClass}>
                    Нажми · scale .97
                  </button>
                  <span style={{ color: "var(--text-faint)", fontSize: 12 }}>
                    на яркой заливке текст почти чёрный
                  </span>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h2 style={{ fontSize: 14, margin: "0 0 10px" }}>Шрифты и геометрия</h2>
            <p style={{ margin: "0 0 8px" }}>Manrope 14px · кнопки не круглые, пилюля только у бейджа.</p>
            <p style={{ margin: 0, fontFamily: "var(--casino-font-mono)", color: "var(--text-muted)" }}>
              DM Mono · шапка 60 · рельс 60/240 @ 300ms · низ 68 · контент 1280
            </p>
          </section>
        </main>
      </div>

      <nav
        data-casino-nav-mobile=""
        style={{
          position: "sticky",
          bottom: 0,
          height: "var(--casino-nav-mobile-h)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--surface-2)",
          borderTop: "1px solid var(--border)",
        }}
      >
        нижняя навигация 68px
      </nav>
    </div>
  );
}
