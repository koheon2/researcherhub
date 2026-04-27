import { useState, useEffect, useCallback } from "react";
import type { Researcher } from "../data/researchers";
import { FIELD_COLORS, getFieldColor } from "../data/researchers";

const API_BASE   = "http://localhost:8000/api";
const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT  = "'Share Tech Mono', monospace";

interface FieldStat { field: string; count: number; }

interface Props {
  activeField:   string | null;
  onFieldChange: (f: string | null) => void;
  tileStyle:     "dark" | "light" | "voyager";
  onTileChange:  (s: "dark" | "light" | "voyager") => void;
  selected:      Researcher | null;
  onSelect:      (r: Researcher) => void;
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return n.toString();
}

export function SidePanel({
  activeField, onFieldChange,
  tileStyle, onTileChange,
  selected, onSelect,
}: Props) {
  const [expanded, setExpanded]     = useState(true);
  const [tab, setTab]               = useState<"fields" | "top">("fields");
  const [fieldStats, setFieldStats] = useState<FieldStat[]>([]);
  const [researchers, setResearchers] = useState<Researcher[]>([]);
  const [loading, setLoading]       = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/researchers/stats/fields`)
      .then((r) => r.json())
      .then(setFieldStats)
      .catch(() => setFieldStats([]));
  }, []);

  const fetchTop = useCallback(async () => {
    if (tab !== "top") return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "30", min_citations: "1000" });
      if (activeField) params.set("field", activeField);
      const res = await fetch(`${API_BASE}/researchers/?${params}`);
      setResearchers(await res.json());
    } catch {
      setResearchers([]);
    } finally {
      setLoading(false);
    }
  }, [tab, activeField]);

  useEffect(() => { fetchTop(); }, [fetchTop]);

  const fieldKeys  = Object.keys(FIELD_COLORS);
  const totalCount = fieldStats.reduce((a, s) => a + s.count, 0);

  return (
    <div style={{
      position: "absolute",
      top: 52,           // flush below TopBar
      right: 0,
      bottom: 0,
      zIndex: 15,
      display: "flex",
      alignItems: "stretch",
      pointerEvents: "none",
    }}>
      {/* Panel body */}
      <div style={{
        width: expanded ? 272 : 0,
        overflow: "hidden",
        transition: "width 0.22s ease",
        background: "rgba(6, 8, 15, 0.97)",
        borderLeft: "1px solid #1e293b",
        pointerEvents: expanded ? "auto" : "none",
        display: "flex",
        flexDirection: "column",
      }}>

        {/* Tab bar */}
        <div style={{
          display: "flex",
          borderBottom: "1px solid #1e293b",
          flexShrink: 0,
        }}>
          {(["fields", "top"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                flex: 1, padding: "11px 0",
                background: "transparent",
                border: "none",
                borderBottom: tab === t ? "2px solid #00d4ff" : "2px solid transparent",
                color: tab === t ? "#94a3b8" : "#334155",
                fontFamily: PIXEL_FONT, fontSize: 7,
                cursor: "pointer", letterSpacing: "0.06em",
                transition: "color 0.12s, border-color 0.12s",
              }}
              onMouseEnter={(e) => { if (tab !== t) e.currentTarget.style.color = "#64748b"; }}
              onMouseLeave={(e) => { if (tab !== t) e.currentTarget.style.color = "#334155"; }}
            >
              {t === "fields" ? "FIELDS" : "TOP"}
            </button>
          ))}
        </div>

        {/* ── FIELDS tab ── */}
        {tab === "fields" && (
          <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column" }}>

            {/* ALL row */}
            <div
              onClick={() => onFieldChange(null)}
              style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "9px 16px", cursor: "pointer",
                background: activeField === null ? "rgba(0,212,255,0.06)" : "transparent",
                borderLeft: activeField === null ? "2px solid #00d4ff" : "2px solid transparent",
              }}
              onMouseEnter={(e) => { if (activeField !== null) e.currentTarget.style.background = "#0a0f1a"; }}
              onMouseLeave={(e) => { if (activeField !== null) e.currentTarget.style.background = "transparent"; }}
            >
              <div style={{ width: 7, height: 7, background: "#00d4ff", flexShrink: 0 }} />
              <span style={{
                flex: 1, fontFamily: MONO_FONT, fontSize: 12,
                color: activeField === null ? "#00d4ff" : "#64748b",
              }}>ALL FIELDS</span>
              {totalCount > 0 && (
                <span style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#334155" }}>
                  {fmtNum(totalCount)}
                </span>
              )}
            </div>

            <div style={{ height: 1, background: "#0f172a", margin: "2px 0" }} />

            {/* Field rows */}
            {fieldKeys.map((f) => {
              const c      = FIELD_COLORS[f];
              const active = activeField === f;
              const count  = fieldStats.find((s) => s.field === f)?.count ?? 0;
              return (
                <div
                  key={f}
                  onClick={() => onFieldChange(active ? null : f)}
                  style={{
                    display: "flex", alignItems: "center", gap: 10,
                    padding: "8px 16px", cursor: "pointer",
                    background: active ? `${c}10` : "transparent",
                    borderLeft: active ? `2px solid ${c}` : "2px solid transparent",
                    opacity: activeField && !active ? 0.3 : 1,
                    transition: "opacity 0.12s, background 0.1s",
                  }}
                  onMouseEnter={(e) => { if (!active && (!activeField || activeField === f)) e.currentTarget.style.background = "#0a0f1a"; }}
                  onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = "transparent"; }}
                >
                  <div style={{
                    width: 7, height: 7, background: c, flexShrink: 0,
                    boxShadow: active ? `0 0 5px ${c}` : "none",
                  }} />
                  <span style={{
                    flex: 1, fontFamily: MONO_FONT, fontSize: 12,
                    color: active ? c : "#64748b",
                  }}>{f}</span>
                  {count > 0 && (
                    <span style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#334155" }}>
                      {fmtNum(count)}
                    </span>
                  )}
                </div>
              );
            })}

            {/* Map style */}
            <div style={{ marginTop: "auto", padding: "12px 16px", borderTop: "1px solid #1e293b" }}>
              <div style={{
                fontFamily: PIXEL_FONT, fontSize: 7,
                color: "#334155", marginBottom: 8, letterSpacing: "0.06em",
              }}>
                MAP STYLE
              </div>
              <div style={{ display: "flex", gap: 4 }}>
                {(["dark", "voyager", "light"] as const).map((s, i) => {
                  const labels  = ["DARK", "MAP", "LIGHT"];
                  const isActive = tileStyle === s;
                  return (
                    <button key={s} onClick={() => onTileChange(s)} style={{
                      flex: 1,
                      background: isActive ? "#00d4ff" : "#0a0f1a",
                      color:      isActive ? "#000" : "#475569",
                      border:     `1px solid ${isActive ? "#00d4ff" : "#1e293b"}`,
                      padding: "6px 0",
                      cursor: "pointer",
                      fontFamily: PIXEL_FONT, fontSize: 7,
                      letterSpacing: "0.03em",
                      transition: "all 0.1s",
                    }}>{labels[i]}</button>
                  );
                })}
              </div>

              <div style={{ marginTop: 10, fontFamily: MONO_FONT, fontSize: 11, color: "#1e293b", lineHeight: 2 }}>
                ▲ size = citations &nbsp;·&nbsp; ★ glow = h-index
              </div>
            </div>
          </div>
        )}

        {/* ── TOP tab ── */}
        {tab === "top" && (
          <div style={{ flex: 1, overflowY: "auto" }}>
            {loading && (
              <div style={{
                padding: 16, textAlign: "center",
                fontFamily: MONO_FONT, fontSize: 11, color: "#334155",
              }}>
                LOADING...
              </div>
            )}
            {!loading && researchers.map((r, i) => {
              const rc    = getFieldColor(r.field);
              const isSel = selected?.id === r.id;
              return (
                <div
                  key={r.id}
                  onClick={() => onSelect(r)}
                  style={{
                    display: "flex", alignItems: "center", gap: 8,
                    padding: "8px 14px", cursor: "pointer",
                    borderLeft: isSel ? `2px solid ${rc}` : "2px solid transparent",
                    background: isSel ? `${rc}10` : "transparent",
                    borderBottom: "1px solid #060a12",
                    transition: "background 0.08s",
                  }}
                  onMouseEnter={(e) => { if (!isSel) e.currentTarget.style.background = "#0a0f1a"; }}
                  onMouseLeave={(e) => { if (!isSel) e.currentTarget.style.background = "transparent"; }}
                >
                  <span style={{
                    fontFamily: MONO_FONT, fontSize: 9, color: "#334155",
                    width: 18, textAlign: "right", flexShrink: 0,
                  }}>{i + 1}</span>
                  <div style={{ width: 6, height: 6, background: rc, flexShrink: 0 }} />
                  <span style={{
                    flex: 1, fontFamily: MONO_FONT, fontSize: 12,
                    color: isSel ? rc : "#94a3b8",
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }}>{r.name}</span>
                  <span style={{
                    fontFamily: MONO_FONT, fontSize: 10, color: "#475569", flexShrink: 0,
                  }}>{fmtNum(r.citations)}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Toggle strip */}
      <div style={{
        width: 28,
        background: "rgba(6, 8, 15, 0.97)",
        borderLeft: "1px solid #1e293b",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        pointerEvents: "auto",
        cursor: "pointer",
        flexShrink: 0,
      }}
        onClick={() => setExpanded(!expanded)}
        onMouseEnter={(e) => (e.currentTarget.style.background = "#0a0f1a")}
        onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(6, 8, 15, 0.97)")}
      >
        <span style={{
          fontFamily: PIXEL_FONT, fontSize: 8,
          color: "#334155",
          writingMode: "vertical-rl",
          textOrientation: "mixed",
          letterSpacing: "0.1em",
          userSelect: "none",
          transition: "color 0.15s",
        }}>
          {expanded ? "▶" : "◀"}
        </span>
      </div>
    </div>
  );
}
