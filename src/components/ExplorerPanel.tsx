import { useState, useEffect, useCallback } from "react";
import type { Researcher } from "../data/researchers";
import { FIELD_COLORS, getFieldColor } from "../data/researchers";

const API_BASE = "http://localhost:8000/api";
const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT = "'Share Tech Mono', monospace";

interface Props {
  activeField: string | null;
  onFieldChange: (f: string | null) => void;
  onSelect: (r: Researcher) => void;
  selected: Researcher | null;
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return n.toString();
}

interface FieldStat {
  field: string;
  count: number;
}

export function ExplorerPanel({ activeField, onFieldChange, onSelect, selected }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [fieldStats, setFieldStats] = useState<FieldStat[]>([]);
  const [researchers, setResearchers] = useState<Researcher[]>([]);
  const [loading, setLoading] = useState(false);

  // Fetch field stats once on mount
  useEffect(() => {
    fetch(`${API_BASE}/researchers/stats/fields`)
      .then((r) => r.json())
      .then((data: FieldStat[]) => setFieldStats(data))
      .catch(() => setFieldStats([]));
  }, []);

  // Fetch researcher list when expanded or activeField changes
  const fetchList = useCallback(async () => {
    if (!expanded) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "30", min_citations: "1000" });
      if (activeField) params.set("field", activeField);
      const res = await fetch(`${API_BASE}/researchers/?${params}`);
      const data: Researcher[] = await res.json();
      setResearchers(data);
    } catch {
      setResearchers([]);
    } finally {
      setLoading(false);
    }
  }, [expanded, activeField]);

  useEffect(() => { fetchList(); }, [fetchList]);

  const fieldKeys = Object.keys(FIELD_COLORS);

  return (
    <div style={{
      position: "absolute",
      left: 0,
      top: "50%",
      transform: "translateY(-50%)",
      zIndex: 15,
      display: "flex",
      alignItems: "stretch",
      pointerEvents: "none",
    }}>
      {/* Panel body */}
      <div style={{
        width: expanded ? 320 : 0,
        overflow: "hidden",
        transition: "width 0.25s ease",
        background: "#06080f",
        borderRight: expanded ? "2px solid #1e293b" : "none",
        borderTop: expanded ? "2px solid #1e293b" : "none",
        borderBottom: expanded ? "2px solid #1e293b" : "none",
        boxShadow: expanded ? "4px 4px 0 #0f172a" : "none",
        pointerEvents: "auto",
        display: "flex",
        flexDirection: "column",
        maxHeight: "70vh",
      }}>
        {/* Titlebar */}
        <div style={{
          background: "#1e293b",
          padding: "8px 12px",
          fontFamily: PIXEL_FONT,
          fontSize: 9,
          color: "#94a3b8",
          letterSpacing: "0.05em",
          flexShrink: 0,
        }}>
          EXPLORER.EXE
        </div>

        {/* Field tabs */}
        <div style={{
          padding: "10px 10px 6px",
          borderBottom: "1px solid #0f172a",
          flexShrink: 0,
        }}>
          <div style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 4,
          }}>
            <button
              onClick={() => onFieldChange(null)}
              style={{
                background: activeField === null ? "#00d4ff" : "#0f172a",
                color: activeField === null ? "#000005" : "#475569",
                border: `1px solid ${activeField === null ? "#00d4ff" : "#1e293b"}`,
                padding: "4px 8px",
                cursor: "pointer",
                fontFamily: PIXEL_FONT,
                fontSize: 7,
                letterSpacing: "0.03em",
              }}
            >ALL</button>
            {fieldKeys.map((f) => {
              const c = FIELD_COLORS[f];
              const active = activeField === f;
              return (
                <button
                  key={f}
                  onClick={() => onFieldChange(active ? null : f)}
                  style={{
                    background: active ? c : "#0f172a",
                    color: active ? "#000005" : "#475569",
                    border: `1px solid ${active ? c : "#1e293b"}`,
                    padding: "4px 8px",
                    cursor: "pointer",
                    fontFamily: PIXEL_FONT,
                    fontSize: 7,
                    letterSpacing: "0.03em",
                    whiteSpace: "nowrap",
                  }}
                >{f}</button>
              );
            })}
          </div>
          {/* Field stat hint */}
          {fieldStats.length > 0 && activeField && (
            <div style={{
              marginTop: 6,
              fontSize: 11,
              color: "#334155",
              fontFamily: MONO_FONT,
            }}>
              {fieldStats.find((s) => s.field === activeField)?.count ?? 0} researchers
            </div>
          )}
        </div>

        {/* Researcher list */}
        <div style={{
          flex: 1,
          overflowY: "auto",
          padding: "4px 0",
        }}>
          {loading && (
            <div style={{
              padding: "16px",
              fontSize: 9,
              color: "#334155",
              fontFamily: MONO_FONT,
              textAlign: "center",
            }}>LOADING...</div>
          )}
          {!loading && researchers.map((r, i) => {
            const rc = getFieldColor(r.field);
            const isSel = selected?.id === r.id;
            return (
              <div
                key={r.id}
                onClick={() => onSelect(r)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "8px 10px",
                  cursor: "pointer",
                  borderLeft: isSel ? `3px solid ${rc}` : "3px solid transparent",
                  background: isSel ? `${rc}15` : "transparent",
                  borderBottom: "1px solid #060a12",
                  transition: "background 0.1s",
                }}
                onMouseEnter={(e) => {
                  if (!isSel) e.currentTarget.style.background = "#0f172a";
                }}
                onMouseLeave={(e) => {
                  if (!isSel) e.currentTarget.style.background = "transparent";
                }}
              >
                {/* Rank */}
                <span style={{
                  fontFamily: MONO_FONT,
                  fontSize: 10,
                  color: "#334155",
                  width: 22,
                  textAlign: "right",
                  flexShrink: 0,
                }}>{i + 1}</span>

                {/* Name */}
                <span style={{
                  flex: 1,
                  fontFamily: MONO_FONT,
                  fontSize: 12,
                  color: isSel ? rc : "#cbd5e1",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  minWidth: 0,
                }}>{r.name}</span>

                {/* Citations */}
                <span style={{
                  fontFamily: MONO_FONT,
                  fontSize: 10,
                  color: "#475569",
                  flexShrink: 0,
                }}>{fmtNum(r.citations)}</span>

                {/* Field color dot */}
                <div style={{
                  width: 7,
                  height: 7,
                  background: rc,
                  flexShrink: 0,
                  boxShadow: `0 0 5px ${rc}88`,
                }} />
              </div>
            );
          })}
        </div>
      </div>

      {/* Toggle button */}
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          pointerEvents: "auto",
          background: "#06080f",
          border: "2px solid #1e293b",
          borderLeft: expanded ? "none" : "2px solid #1e293b",
          color: "#475569",
          cursor: "pointer",
          fontFamily: PIXEL_FONT,
          fontSize: 8,
          letterSpacing: "0.05em",
          padding: "10px 6px",
          writingMode: "vertical-rl",
          textOrientation: "mixed",
          boxShadow: "4px 4px 0 #0f172a",
          whiteSpace: "nowrap",
          lineHeight: 1.6,
        }}
        onMouseEnter={(e) => (e.currentTarget.style.color = "#00d4ff")}
        onMouseLeave={(e) => (e.currentTarget.style.color = "#475569")}
      >
        {expanded ? "\u25C0 CLOSE" : "\u25B6 EXPLORE"}
      </button>
    </div>
  );
}
