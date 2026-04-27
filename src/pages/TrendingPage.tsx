import { useState, useEffect, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

const API_BASE = "http://localhost:8000/api";
const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT  = "'Share Tech Mono', monospace";

interface TrendingTopic {
  rank: number;
  topic_id: string;
  topic_name: string;
  paper_count: number;
  contributions: number;
  researcher_count: number;
  total_citations: number;
  dominant_axis: string;
  growth_pct: number;
  emoji: string;
}

type TrendingAxis = "aboutness" | "method" | "task" | "application";

const AXIS_OPTIONS: { key: TrendingAxis; label: string }[] = [
  { key: "aboutness", label: "FIELDS" },
  { key: "method", label: "METHODS" },
  { key: "task", label: "TASKS" },
  { key: "application", label: "APPS" },
];

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return n.toString();
}

function growthColor(pct: number): string {
  if (pct >= 25) return "#34d399";
  if (pct >= 15) return "#fbbf24";
  return "#94a3b8";
}

export function TrendingPage() {
  const [searchParams] = useSearchParams();
  const [topics, setTopics] = useState<TrendingTopic[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(Date.now());
  const [axis, setAxis] = useState<TrendingAxis>("aboutness");
  const navigate = useNavigate();

  const fetchTrending = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/trending?axis=${axis}&limit=20`);
      const data = await res.json();
      setTopics(data);
      setLastRefresh(Date.now());
    } catch (e) {
      console.error("Failed to fetch trending:", e);
    } finally {
      setLoading(false);
    }
  }, [axis]);

  useEffect(() => {
    fetchTrending();
    const interval = setInterval(fetchTrending, 30_000);
    return () => clearInterval(interval);
  }, [fetchTrending]);

  useEffect(() => {
    const axisParam = searchParams.get("axis");
    if (
      axisParam === "aboutness" ||
      axisParam === "method" ||
      axisParam === "task" ||
      axisParam === "application"
    ) {
      setAxis(axisParam);
    }
  }, [searchParams]);

  const maxPapers = Math.max(...topics.map(t => t.paper_count), 1);

  return (
    <div style={{
      position: "absolute", top: 52, left: 0, right: 0, bottom: 0,
      background: "#06080f",
      overflowY: "auto",
      padding: "32px 40px",
    }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 16,
        marginBottom: 32,
      }}>
        <span style={{ fontSize: 28 }}>🔥</span>
        <h1 style={{
          fontFamily: PIXEL_FONT, fontSize: 16,
          color: "#f8fafc", margin: 0,
          letterSpacing: "0.04em",
        }}>
          TRENDING NOW
        </h1>
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "4px 10px",
          border: "1px solid #ef444466",
          background: "#ef444410",
        }}>
          <div style={{
            width: 6, height: 6, borderRadius: "50%",
            background: "#ef4444",
            animation: "livePulse 1.5s ease-in-out infinite",
          }} />
          <span style={{
            fontFamily: PIXEL_FONT, fontSize: 7,
            color: "#ef4444", letterSpacing: "0.08em",
          }}>LIVE</span>
        </div>
        <span style={{
          fontFamily: MONO_FONT, fontSize: 11,
          color: "#334155", marginLeft: "auto",
        }}>
          Refreshes every 30s
        </span>
      </div>

      <div style={{
        display: "flex",
        gap: 4,
        marginBottom: 20,
        borderBottom: "1px solid #1e293b",
      }}>
        {AXIS_OPTIONS.map(option => (
          <button
            key={option.key}
            onClick={() => {
              setLoading(true);
              setAxis(option.key);
            }}
            style={{
              background: axis === option.key ? "#00d4ff14" : "transparent",
              border: "none",
              borderBottom: axis === option.key ? "2px solid #00d4ff" : "2px solid transparent",
              color: axis === option.key ? "#00d4ff" : "#475569",
              fontFamily: PIXEL_FONT,
              fontSize: 7,
              padding: "8px 12px",
              cursor: "pointer",
            }}
          >
            {option.label}
          </button>
        ))}
      </div>

      {/* Column headers */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "50px 32px 1fr 120px 140px 200px",
        gap: 12,
        padding: "8px 16px",
        borderBottom: "1px solid #1e293b",
        marginBottom: 4,
      }}>
        <span style={headerStyle}>RANK</span>
        <span />
        <span style={headerStyle}>TOPIC</span>
        <span style={{ ...headerStyle, textAlign: "right" }}>PAPERS</span>
        <span style={{ ...headerStyle, textAlign: "right" }}>CITATIONS</span>
        <span style={headerStyle}>GROWTH</span>
      </div>

      {/* Loading */}
      {loading && (
        <div style={{
          fontFamily: MONO_FONT, fontSize: 14,
          color: "#475569", padding: "40px 16px",
          textAlign: "center",
        }}>
          Loading trending topics...
        </div>
      )}

      {/* Rows */}
      {topics.map((t) => {
        const barWidth = (t.paper_count / maxPapers) * 100;
        const gc = growthColor(t.growth_pct);

        return (
          <div
            key={t.topic_id}
            onClick={() => navigate(`/map?q=${encodeURIComponent(t.topic_name)}`)}
            style={{
              display: "grid",
              gridTemplateColumns: "50px 32px 1fr 120px 140px 200px",
              gap: 12,
              padding: "12px 16px",
              borderBottom: "1px solid #0d1421",
              cursor: "pointer",
              transition: "background 0.1s",
            }}
            onMouseEnter={e => e.currentTarget.style.background = "#0a0f1a"}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
          >
            {/* Rank */}
            <div style={{
              fontFamily: PIXEL_FONT,
              fontSize: t.rank <= 3 ? 14 : 10,
              color: t.rank === 1 ? "#fbbf24" : t.rank === 2 ? "#94a3b8" : t.rank === 3 ? "#d97706" : "#475569",
              display: "flex", alignItems: "center",
              textShadow: t.rank <= 3 ? `0 0 8px ${t.rank === 1 ? "#fbbf2444" : "transparent"}` : "none",
            }}>
              #{t.rank}
            </div>

            {/* Emoji */}
            <div style={{ display: "flex", alignItems: "center", fontSize: 18 }}>
              {t.emoji}
            </div>

            {/* Topic name + axis */}
            <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: 4 }}>
              <span style={{
                fontFamily: MONO_FONT, fontSize: 14, color: "#e2e8f0",
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {t.topic_name}
              </span>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{
                  flex: 1, height: 3, background: "#0f172a", maxWidth: 160,
                }}>
                  <div style={{
                    height: "100%",
                    width: `${barWidth}%`,
                    background: `linear-gradient(90deg, #00d4ff44, #00d4ff)`,
                    transition: "width 0.5s ease",
                  }} />
                </div>
                <span style={{
                  fontFamily: PIXEL_FONT, fontSize: 6, color: "#334155",
                }}>
                  {t.dominant_axis}
                </span>
              </div>
            </div>

            {/* Paper count */}
            <div style={{
              fontFamily: MONO_FONT, fontSize: 14, color: "#00d4ff",
              display: "flex", alignItems: "center", justifyContent: "flex-end",
            }}>
              {fmtNum(t.paper_count)}
            </div>

            {/* Citations */}
            <div style={{
              fontFamily: MONO_FONT, fontSize: 14, color: "#a78bfa",
              display: "flex", alignItems: "center", justifyContent: "flex-end",
            }}>
              {fmtNum(t.total_citations)}
            </div>

            {/* Growth */}
            <div style={{
              display: "flex", alignItems: "center", gap: 8,
            }}>
              <div style={{
                flex: 1, height: 8, background: "#0f172a",
                position: "relative", overflow: "hidden",
              }}>
                <div style={{
                  position: "absolute", left: 0, top: 0, bottom: 0,
                  width: `${Math.min(100, t.growth_pct * 2.5)}%`,
                  background: `linear-gradient(90deg, ${gc}44, ${gc})`,
                  transition: "width 0.5s ease",
                }} />
              </div>
              <span style={{
                fontFamily: MONO_FONT, fontSize: 12, color: gc,
                minWidth: 50, textAlign: "right",
              }}>
                +{t.growth_pct}%
              </span>
            </div>
          </div>
        );
      })}

      {/* Refresh indicator */}
      <div style={{
        fontFamily: MONO_FONT, fontSize: 10,
        color: "#1e293b", textAlign: "center",
        padding: "20px 0",
      }}>
        Last updated: {new Date(lastRefresh).toLocaleTimeString()}
      </div>

      <style>{`
        @keyframes livePulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}

const headerStyle: React.CSSProperties = {
  fontFamily: "'Press Start 2P', monospace",
  fontSize: 6,
  color: "#334155",
  letterSpacing: "0.08em",
};
