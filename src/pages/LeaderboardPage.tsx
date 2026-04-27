import { useState, useEffect, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { FIELD_COLORS, getFieldColor } from "../data/researchers";

const API_BASE = "http://localhost:8000/api";
const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT  = "'Share Tech Mono', monospace";

type LeaderboardType = "country" | "institution" | "researcher";

interface LeaderboardEntry {
  rank: number;
  key: string;
  name: string;
  researcher_count?: number;
  contributions?: number;
  papers?: number;
  total_citations?: number;
  avg_h_index?: number;
  institution?: string;
  country?: string;
  field?: string;
  citations?: number;
  h_index?: number;
  works_count?: number;
}

interface LeaderboardData {
  type: string;
  field: string | null;
  entries: LeaderboardEntry[];
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return n.toString();
}

function getMedal(rank: number): string {
  if (rank === 1) return "🥇";
  if (rank === 2) return "🥈";
  if (rank === 3) return "🥉";
  return "";
}

function getRankColor(rank: number): string {
  if (rank === 1) return "#fbbf24";
  if (rank === 2) return "#94a3b8";
  if (rank === 3) return "#d97706";
  return "#475569";
}

const FIELD_OPTIONS = ["", ...Object.keys(FIELD_COLORS)];

export function LeaderboardPage() {
  const [searchParams] = useSearchParams();
  const [type, setType] = useState<LeaderboardType>("country");
  const [field, setField] = useState("");
  const [data, setData] = useState<LeaderboardData | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ type, limit: "20" });
      if (field) params.set("field", field);
      const res = await fetch(`${API_BASE}/leaderboard?${params}`);
      setData(await res.json());
    } catch (e) {
      console.error("Failed to fetch leaderboard:", e);
    } finally {
      setLoading(false);
    }
  }, [type, field]);

  useEffect(() => { fetchData(); }, [fetchData]);

  useEffect(() => {
    const typeParam = searchParams.get("type");
    const fieldParam = searchParams.get("field");
    if (typeParam === "country" || typeParam === "institution" || typeParam === "researcher") {
      setType(typeParam);
    }
    setField(fieldParam ?? "");
  }, [searchParams]);

  const entries = data?.entries ?? [];
  const maxScore = type === "researcher"
    ? Math.max(...entries.map(e => e.citations ?? 0), 1)
    : Math.max(...entries.map(e => e.total_citations ?? 0), 1);

  const handleRowClick = (entry: LeaderboardEntry) => {
    if (type === "researcher") {
      navigate(`/researcher/${entry.key}`);
    } else if (type === "country") {
      // Compare top 2 countries (this + next)
      const idx = entries.findIndex(e => e.key === entry.key);
      const other = entries[idx === 0 ? 1 : 0];
      if (other) {
        navigate(`/?compare=true`);
        // Use the AI search compare flow
      }
    }
  };

  return (
    <div style={{
      position: "absolute", top: 52, left: 0, right: 0, bottom: 0,
      background: "#06080f",
      overflowY: "auto",
      padding: "32px 40px",
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
        <span style={{ fontSize: 24 }}>🏆</span>
        <h1 style={{
          fontFamily: PIXEL_FONT, fontSize: 14,
          color: "#f8fafc", margin: 0, letterSpacing: "0.04em",
        }}>
          RESEARCH LEADERBOARD
        </h1>
      </div>

      {/* Controls */}
      <div style={{
        display: "flex", alignItems: "center", gap: 16,
        marginBottom: 24,
      }}>
        {/* Type tabs */}
        <div style={{ display: "flex", gap: 2 }}>
          {(["country", "institution", "researcher"] as const).map(t => (
            <button
              key={t}
              onClick={() => setType(t)}
              style={{
                background: type === t ? "#00d4ff14" : "transparent",
                border: "none",
                borderBottom: type === t ? "2px solid #00d4ff" : "2px solid transparent",
                color: type === t ? "#00d4ff" : "#334155",
                fontFamily: PIXEL_FONT, fontSize: 7,
                padding: "8px 14px", cursor: "pointer",
                letterSpacing: "0.06em",
              }}
            >
              {t.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Field filter */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontFamily: PIXEL_FONT, fontSize: 6, color: "#334155" }}>FIELD:</span>
          <select
            value={field}
            onChange={e => setField(e.target.value)}
            style={{
              background: "#0a0f1a",
              border: "1px solid #1e293b",
              color: "#e2e8f0",
              fontFamily: MONO_FONT, fontSize: 12,
              padding: "6px 10px",
              outline: "none",
            }}
          >
            <option value="">ALL</option>
            {FIELD_OPTIONS.filter(f => f).map(f => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Column headers */}
      {type !== "researcher" ? (
        <div style={{
          display: "grid",
          gridTemplateColumns: "60px 1fr 120px 160px 100px 200px",
          gap: 12,
          padding: "8px 16px",
          borderBottom: "1px solid #1e293b",
          marginBottom: 4,
        }}>
          <span style={headerStyle}>RANK</span>
          <span style={headerStyle}>NAME</span>
          <span style={{ ...headerStyle, textAlign: "right" }}>CONTRIBUTIONS</span>
          <span style={{ ...headerStyle, textAlign: "right" }}>TOTAL CITATIONS</span>
          <span style={{ ...headerStyle, textAlign: "right" }}>PAPERS</span>
          <span style={headerStyle}>SCORE</span>
        </div>
      ) : (
        <div style={{
          display: "grid",
          gridTemplateColumns: "60px 1fr 160px 100px 100px 200px",
          gap: 12,
          padding: "8px 16px",
          borderBottom: "1px solid #1e293b",
          marginBottom: 4,
        }}>
          <span style={headerStyle}>RANK</span>
          <span style={headerStyle}>NAME</span>
          <span style={headerStyle}>INSTITUTION</span>
          <span style={{ ...headerStyle, textAlign: "right" }}>CITATIONS</span>
          <span style={{ ...headerStyle, textAlign: "right" }}>H-INDEX</span>
          <span style={headerStyle}>SCORE</span>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div style={{
          fontFamily: MONO_FONT, fontSize: 14,
          color: "#475569", padding: "40px 16px",
          textAlign: "center",
        }}>
          Loading leaderboard...
        </div>
      )}

      {/* Rows */}
      {!loading && entries.map((entry) => {
        const medal = getMedal(entry.rank);
        const rankColor = getRankColor(entry.rank);
        const score = type === "researcher" ? (entry.citations ?? 0) : (entry.total_citations ?? 0);
        const barPct = (score / maxScore) * 100;
        const isTop3 = entry.rank <= 3;

        if (type !== "researcher") {
          return (
            <div
              key={entry.key}
              onClick={() => handleRowClick(entry)}
              style={{
                display: "grid",
                gridTemplateColumns: "60px 1fr 120px 160px 100px 200px",
                gap: 12,
                padding: isTop3 ? "14px 16px" : "10px 16px",
                borderBottom: "1px solid #0d1421",
                cursor: "pointer",
                background: isTop3 ? `${rankColor}06` : "transparent",
                transition: "background 0.1s",
              }}
              onMouseEnter={e => e.currentTarget.style.background = "#0a0f1a"}
              onMouseLeave={e => e.currentTarget.style.background = isTop3 ? `${rankColor}06` : "transparent"}
            >
              {/* Rank */}
              <div style={{
                fontFamily: PIXEL_FONT,
                fontSize: isTop3 ? 14 : 10,
                color: rankColor,
                display: "flex", alignItems: "center", gap: 4,
              }}>
                {medal || `#${entry.rank}`}
                {!medal && ""}
              </div>

              {/* Name */}
              <div style={{
                fontFamily: isTop3 ? PIXEL_FONT : MONO_FONT,
                fontSize: isTop3 ? 10 : 13,
                color: isTop3 ? "#f1f5f9" : "#94a3b8",
                display: "flex", alignItems: "center",
              }}>
                {entry.name}
              </div>

              {/* Researcher count */}
              <div style={{
                fontFamily: MONO_FONT, fontSize: 13, color: "#00d4ff",
                display: "flex", alignItems: "center", justifyContent: "flex-end",
              }}>
                {fmtNum(entry.contributions ?? entry.researcher_count ?? 0)}
              </div>

              {/* Total citations */}
              <div style={{
                fontFamily: MONO_FONT, fontSize: 13, color: "#a78bfa",
                display: "flex", alignItems: "center", justifyContent: "flex-end",
              }}>
                {fmtNum(entry.total_citations ?? 0)}
              </div>

              {/* Distinct papers */}
              <div style={{
                fontFamily: MONO_FONT, fontSize: 13, color: "#34d399",
                display: "flex", alignItems: "center", justifyContent: "flex-end",
              }}>
                {fmtNum(entry.papers ?? 0)}
              </div>

              {/* Score bar */}
              <div style={{
                display: "flex", alignItems: "center",
              }}>
                <div style={{
                  flex: 1, height: isTop3 ? 10 : 6, background: "#0f172a",
                  position: "relative", overflow: "hidden",
                }}>
                  <div style={{
                    position: "absolute", left: 0, top: 0, bottom: 0,
                    width: `${barPct}%`,
                    background: `linear-gradient(90deg, ${rankColor}44, ${rankColor})`,
                    boxShadow: isTop3 ? `0 0 8px ${rankColor}33` : "none",
                    transition: "width 0.5s ease",
                  }} />
                </div>
              </div>
            </div>
          );
        } else {
          // Researcher type
          const fc = getFieldColor(entry.field ?? null);
          return (
            <div
              key={entry.key}
              onClick={() => handleRowClick(entry)}
              style={{
                display: "grid",
                gridTemplateColumns: "60px 1fr 160px 100px 100px 200px",
                gap: 12,
                padding: isTop3 ? "14px 16px" : "10px 16px",
                borderBottom: "1px solid #0d1421",
                cursor: "pointer",
                background: isTop3 ? `${rankColor}06` : "transparent",
                transition: "background 0.1s",
              }}
              onMouseEnter={e => e.currentTarget.style.background = "#0a0f1a"}
              onMouseLeave={e => e.currentTarget.style.background = isTop3 ? `${rankColor}06` : "transparent"}
            >
              {/* Rank */}
              <div style={{
                fontFamily: PIXEL_FONT,
                fontSize: isTop3 ? 14 : 10,
                color: rankColor,
                display: "flex", alignItems: "center",
              }}>
                {medal || `#${entry.rank}`}
              </div>

              {/* Name + field badge */}
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ width: 6, height: 6, background: fc, boxShadow: `0 0 4px ${fc}88` }} />
                <span style={{
                  fontFamily: isTop3 ? PIXEL_FONT : MONO_FONT,
                  fontSize: isTop3 ? 10 : 13,
                  color: isTop3 ? "#f1f5f9" : "#94a3b8",
                }}>
                  {entry.name}
                </span>
              </div>

              {/* Institution */}
              <div style={{
                fontFamily: MONO_FONT, fontSize: 11, color: "#475569",
                display: "flex", alignItems: "center",
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {entry.institution ?? "---"}
              </div>

              {/* Citations */}
              <div style={{
                fontFamily: MONO_FONT, fontSize: 13, color: "#a78bfa",
                display: "flex", alignItems: "center", justifyContent: "flex-end",
              }}>
                {fmtNum(entry.citations ?? 0)}
              </div>

              {/* H-index */}
              <div style={{
                fontFamily: MONO_FONT, fontSize: 13, color: "#34d399",
                display: "flex", alignItems: "center", justifyContent: "flex-end",
              }}>
                {entry.h_index ?? "---"}
              </div>

              {/* Score bar */}
              <div style={{ display: "flex", alignItems: "center" }}>
                <div style={{
                  flex: 1, height: isTop3 ? 10 : 6, background: "#0f172a",
                  position: "relative", overflow: "hidden",
                }}>
                  <div style={{
                    position: "absolute", left: 0, top: 0, bottom: 0,
                    width: `${barPct}%`,
                    background: `linear-gradient(90deg, ${rankColor}44, ${rankColor})`,
                    boxShadow: isTop3 ? `0 0 8px ${rankColor}33` : "none",
                    transition: "width 0.5s ease",
                  }} />
                </div>
              </div>
            </div>
          );
        }
      })}
    </div>
  );
}

const headerStyle: React.CSSProperties = {
  fontFamily: "'Press Start 2P', monospace",
  fontSize: 6,
  color: "#334155",
  letterSpacing: "0.08em",
};
