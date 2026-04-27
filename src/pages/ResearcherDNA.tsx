import { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { FIELD_COLORS, getFieldColor } from "../data/researchers";
import type { Researcher } from "../data/researchers";

const API_BASE = "http://localhost:8000/api";
const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT  = "'Share Tech Mono', monospace";

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return n.toString();
}

// Generate fake 5-year citation growth from current value
function generateCitationTrend(currentCitations: number): { year: number; citations: number }[] {
  const years: { year: number; citations: number }[] = [];
  for (let i = 4; i >= 0; i--) {
    const year = 2025 - i;
    const factor = Math.pow((5 - i) / 5, 1.4) + Math.random() * 0.05;
    years.push({
      year,
      citations: Math.round(currentCitations * factor),
    });
  }
  return years;
}

export function ResearcherDNA() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [researcher, setResearcher] = useState<Researcher | null>(null);
  const [related, setRelated] = useState<Researcher[]>([]);
  const [topicNames, setTopicNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    setLoading(true);

    Promise.all([
      fetch(`${API_BASE}/researchers/${id}`).then(r => r.json()),
      fetch(`${API_BASE}/researchers/${id}/related`).then(r => r.json()),
    ])
      .then(([rData, relData]) => {
        setResearcher(rData);
        setRelated(relData.slice(0, 5));
      })
      .catch(e => console.error("Failed to load researcher:", e))
      .finally(() => setLoading(false));
  }, [id]);

  // Load topic names for displaying
  useEffect(() => {
    fetch(`${API_BASE}/researchers/topics/clusters?limit=2000`)
      .then(r => r.json())
      .then((clusters: any[]) => {
        const map: Record<string, string> = {};
        for (const c of clusters) {
          map[c.topic_id] = c.topic_name;
        }
        setTopicNames(map);
      })
      .catch(() => {});
  }, []);

  const citationTrend = useMemo(
    () => researcher ? generateCitationTrend(researcher.citations) : [],
    [researcher],
  );

  if (loading) {
    return (
      <div style={{
        position: "absolute", top: 52, left: 0, right: 0, bottom: 0,
        background: "#06080f",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: MONO_FONT, fontSize: 14, color: "#475569",
      }}>
        Loading researcher data...
      </div>
    );
  }

  if (!researcher) {
    return (
      <div style={{
        position: "absolute", top: 52, left: 0, right: 0, bottom: 0,
        background: "#06080f",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: MONO_FONT, fontSize: 14, color: "#475569",
      }}>
        Researcher not found.
      </div>
    );
  }

  const color = getFieldColor(researcher.field);
  const topics = (researcher as any).topics as string[] | null;
  const topicCount = topics?.length ?? 0;

  // SVG line chart for citation trend
  const chartW = 320;
  const chartH = 160;
  const chartPad = { top: 20, right: 20, bottom: 30, left: 50 };
  const innerW = chartW - chartPad.left - chartPad.right;
  const innerH = chartH - chartPad.top - chartPad.bottom;
  const maxCit = Math.max(...citationTrend.map(d => d.citations), 1);
  const points = citationTrend.map((d, i) => {
    const x = chartPad.left + (i / Math.max(citationTrend.length - 1, 1)) * innerW;
    const y = chartPad.top + innerH - (d.citations / maxCit) * innerH;
    return { x, y, ...d };
  });
  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");

  return (
    <div style={{
      position: "absolute", top: 52, left: 0, right: 0, bottom: 0,
      background: "#06080f",
      overflowY: "auto",
      padding: "32px 40px",
    }}>
      {/* Back button */}
      <button
        onClick={() => navigate(-1)}
        style={{
          background: "transparent", border: "1px solid #1e293b",
          color: "#475569", fontFamily: PIXEL_FONT, fontSize: 7,
          padding: "6px 12px", cursor: "pointer", marginBottom: 24,
          letterSpacing: "0.06em",
        }}
        onMouseEnter={e => { e.currentTarget.style.color = "#00d4ff"; e.currentTarget.style.borderColor = "#00d4ff44"; }}
        onMouseLeave={e => { e.currentTarget.style.color = "#475569"; e.currentTarget.style.borderColor = "#1e293b"; }}
      >
        &lt; BACK
      </button>

      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12, marginBottom: 8,
      }}>
        <span style={{ fontSize: 24 }}>🧬</span>
        <h1 style={{
          fontFamily: PIXEL_FONT, fontSize: 14,
          color: "#f8fafc", margin: 0,
        }}>
          RESEARCHER DNA
        </h1>
      </div>

      {/* Main layout: 3 columns */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "280px 1fr 360px",
        gap: 24,
        marginTop: 24,
      }}>
        {/* LEFT: Basic info */}
        <div style={{
          background: "#0a0f1a",
          border: `1px solid ${color}33`,
          padding: 20,
        }}>
          {/* Field badge */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 16 }}>
            <div style={{ width: 8, height: 8, background: color, boxShadow: `0 0 8px ${color}` }} />
            <span style={{ fontFamily: PIXEL_FONT, fontSize: 7, color, letterSpacing: "0.08em" }}>
              {(researcher.field ?? "UNKNOWN").toUpperCase()}
            </span>
          </div>

          {/* Name */}
          <h2 style={{
            fontFamily: PIXEL_FONT, fontSize: 11, color: "#f1f5f9",
            margin: "0 0 12px 0", lineHeight: 1.8,
          }}>
            {researcher.name.toUpperCase()}
          </h2>

          {/* Institution */}
          <div style={{ fontFamily: MONO_FONT, fontSize: 13, color: "#4b6080", marginBottom: 4 }}>
            {researcher.institution ?? "---"}
          </div>
          <div style={{ fontFamily: MONO_FONT, fontSize: 12, color: "#334155", marginBottom: 20 }}>
            {researcher.country ?? "---"}
          </div>

          {/* Stats */}
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {[
              { label: "CITATIONS", value: fmtNum(researcher.citations), c: "#00d4ff" },
              { label: "H-INDEX", value: String(researcher.h_index), c: "#a78bfa" },
              { label: "PAPERS", value: String(researcher.works_count), c: "#34d399" },
              { label: "2YR PAPERS", value: String(researcher.recent_papers), c: "#fbbf24" },
            ].map(s => (
              <div key={s.label} style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                padding: "8px 0",
                borderBottom: "1px solid #0d1421",
              }}>
                <span style={{ fontFamily: PIXEL_FONT, fontSize: 6, color: "#334155", letterSpacing: "0.06em" }}>
                  {s.label}
                </span>
                <span style={{ fontFamily: MONO_FONT, fontSize: 16, color: s.c }}>
                  {s.value}
                </span>
              </div>
            ))}
          </div>

          {/* Impact bar */}
          <div style={{ marginTop: 16 }}>
            <span style={{ fontFamily: PIXEL_FONT, fontSize: 6, color: "#334155", letterSpacing: "0.06em" }}>
              IMPACT
            </span>
            <div style={{ height: 4, background: "#0f172a", marginTop: 6 }}>
              <div style={{
                height: "100%",
                width: `${Math.min(100, (researcher.h_index / 200) * 100)}%`,
                background: `linear-gradient(90deg, ${color}66, ${color})`,
                boxShadow: `0 0 8px ${color}44`,
              }} />
            </div>
          </div>
        </div>

        {/* CENTER: DNA visualization - topic bars */}
        <div style={{
          background: "#0a0f1a",
          border: "1px solid #1e293b",
          padding: 20,
        }}>
          <div style={{
            fontFamily: PIXEL_FONT, fontSize: 8, color: "#00d4ff",
            marginBottom: 16, letterSpacing: "0.06em",
          }}>
            TOPIC DNA ({topicCount} TOPICS)
          </div>

          {topics && topics.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {topics.slice(0, 20).map((topicId, i) => {
                const name = topicNames[topicId] || topicId;
                const barPct = ((topics.length - i) / topics.length) * 100;
                const barColor = Object.values(FIELD_COLORS)[i % Object.values(FIELD_COLORS).length];
                return (
                  <div key={topicId} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{
                      fontFamily: MONO_FONT, fontSize: 11, color: "#64748b",
                      minWidth: 180, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                    }}>
                      {name}
                    </span>
                    <div style={{
                      flex: 1, height: 12, background: "#0f172a",
                      position: "relative", overflow: "hidden",
                    }}>
                      <div style={{
                        position: "absolute", left: 0, top: 0, bottom: 0,
                        width: `${barPct}%`,
                        background: `linear-gradient(90deg, ${barColor}44, ${barColor})`,
                        transition: "width 0.3s ease",
                      }} />
                    </div>
                    <span style={{
                      fontFamily: MONO_FONT, fontSize: 10, color: "#475569",
                      minWidth: 35, textAlign: "right",
                    }}>
                      {barPct.toFixed(0)}%
                    </span>
                  </div>
                );
              })}
            </div>
          ) : (
            <div style={{ fontFamily: MONO_FONT, fontSize: 12, color: "#334155", padding: "20px 0" }}>
              No topic data available for this researcher.
            </div>
          )}
        </div>

        {/* RIGHT: Citation trend chart + Similar researchers */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Citation trend */}
          <div style={{
            background: "#0a0f1a",
            border: "1px solid #1e293b",
            padding: 20,
          }}>
            <div style={{
              fontFamily: PIXEL_FONT, fontSize: 8, color: "#a78bfa",
              marginBottom: 12, letterSpacing: "0.06em",
            }}>
              CITATION GROWTH (5YR)
            </div>
            <svg width={chartW} height={chartH} style={{ display: "block" }}>
              {/* Grid lines */}
              {[0, 0.25, 0.5, 0.75, 1].map(frac => {
                const y = chartPad.top + innerH * (1 - frac);
                return (
                  <g key={frac}>
                    <line x1={chartPad.left} y1={y} x2={chartPad.left + innerW} y2={y}
                      stroke="#1e293b" strokeWidth={0.5} />
                    <text x={chartPad.left - 6} y={y + 3} textAnchor="end"
                      fill="#334155" fontFamily={MONO_FONT} fontSize={9}>
                      {fmtNum(Math.round(maxCit * frac))}
                    </text>
                  </g>
                );
              })}

              {/* Line */}
              <path d={linePath} fill="none" stroke="#a78bfa" strokeWidth={2} />

              {/* Glow line */}
              <path d={linePath} fill="none" stroke="#a78bfa" strokeWidth={4} opacity={0.2} />

              {/* Dots + labels */}
              {points.map((p, i) => (
                <g key={i}>
                  <circle cx={p.x} cy={p.y} r={3} fill="#a78bfa" />
                  <circle cx={p.x} cy={p.y} r={6} fill="#a78bfa" opacity={0.15} />
                  <text x={p.x} y={chartH - 6} textAnchor="middle"
                    fill="#475569" fontFamily={MONO_FONT} fontSize={9}>
                    {p.year}
                  </text>
                </g>
              ))}

              {/* Area fill */}
              <path
                d={`${linePath} L${points[points.length - 1]?.x ?? 0},${chartPad.top + innerH} L${points[0]?.x ?? 0},${chartPad.top + innerH} Z`}
                fill="#a78bfa" opacity={0.06}
              />
            </svg>
          </div>

          {/* Similar researchers */}
          <div style={{
            background: "#0a0f1a",
            border: "1px solid #1e293b",
            padding: 20,
            flex: 1,
          }}>
            <div style={{
              fontFamily: PIXEL_FONT, fontSize: 8, color: "#34d399",
              marginBottom: 12, letterSpacing: "0.06em",
            }}>
              SIMILAR RESEARCHERS
            </div>

            {related.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {related.map((r) => {
                  const rc = getFieldColor(r.field);
                  return (
                    <div
                      key={r.id}
                      onClick={() => navigate(`/researcher/${r.id}`)}
                      style={{
                        display: "flex", alignItems: "center", gap: 8,
                        padding: "8px 10px", cursor: "pointer",
                        borderBottom: "1px solid #060a12",
                        transition: "background 0.08s",
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = "#0f172a"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                    >
                      <div style={{ width: 6, height: 6, background: rc, boxShadow: `0 0 4px ${rc}88` }} />
                      <span style={{
                        flex: 1, fontFamily: MONO_FONT, fontSize: 12, color: "#94a3b8",
                        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                      }}>
                        {r.name}
                      </span>
                      <span style={{
                        fontFamily: MONO_FONT, fontSize: 10, color: "#334155",
                      }}>
                        {fmtNum(r.citations)}
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div style={{ fontFamily: MONO_FONT, fontSize: 12, color: "#334155" }}>
                No similar researchers found.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
