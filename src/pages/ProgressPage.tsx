import { useState, useCallback, useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";

const API_BASE = "http://localhost:8000/api";
const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT  = "'Share Tech Mono', monospace";

const LINE_COLORS = ["#00d4ff", "#a78bfa", "#34d399", "#f87171", "#fbbf24"];

const COUNTRY_FLAGS: Record<string, string> = {
  US: "🇺🇸", KR: "🇰🇷", CN: "🇨🇳", JP: "🇯🇵", DE: "🇩🇪", GB: "🇬🇧",
  FR: "🇫🇷", CA: "🇨🇦", AU: "🇦🇺", IN: "🇮🇳", SG: "🇸🇬", CH: "🇨🇭",
  NL: "🇳🇱", SE: "🇸🇪", IL: "🇮🇱", BR: "🇧🇷", IT: "🇮🇹", TW: "🇹🇼",
};

interface TrendPoint {
  year: number;
  researcher_count: number;
  contributions?: number;
  avg_citations: number;
}

interface ProgressData {
  type: string;
  entity: string;
  topic?: string;
  matched_axis?: string | null;
  trend: TrendPoint[];
  current: { researcher_count: number; contributions?: number; avg_citations: number };
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return n.toString();
}

export function ProgressPage() {
  const [searchParams] = useSearchParams();
  const [input, setInput] = useState("");
  const [type, setType] = useState<"country" | "field">("country");
  const [series, setSeries] = useState<ProgressData[]>([]);
  const [loading, setLoading] = useState(false);
  const [metric, setMetric] = useState<"researcher_count" | "avg_citations">("researcher_count");
  const [topicFilter, setTopicFilter] = useState("");
  const lastAutoQuery = useRef<string | null>(null);

  const fetchProgressData = useCallback(async (
    rawEntity: string,
    rawType: "country" | "field",
    rawTopic = "",
  ): Promise<ProgressData | null> => {
    if (!rawEntity.trim()) return null;
    const entity = rawType === "country" ? rawEntity.trim().toUpperCase() : rawEntity.trim();
    const params = new URLSearchParams({
      type: rawType,
      entity,
      years: "10",
    });
    if (rawType === "country" && rawTopic.trim()) {
      params.set("topic", rawTopic.trim());
    }
    const res = await fetch(`${API_BASE}/progress?${params}`);
    const data: ProgressData = await res.json();
    return data.trend.length > 0 ? data : null;
  }, []);

  const fetchEntity = useCallback(async (
    rawEntity: string,
    rawType: "country" | "field",
    replace = false,
  ) => {
    if (!rawEntity.trim()) return;
    setLoading(true);
    try {
      const data = await fetchProgressData(rawEntity, rawType, topicFilter);
      if (data) {
        setSeries(prev => {
          const next = replace ? [] : prev;
          if (next.some(s => s.type === data.type && s.entity.toLowerCase() === data.entity.toLowerCase())) {
            return next;
          }
          return [...next, data].slice(0, 3);
        });
      }
    } catch (e) {
      console.error("Failed to fetch progress:", e);
    } finally {
      setLoading(false);
      setInput("");
    }
  }, [fetchProgressData, topicFilter]);

  const fetchEntities = useCallback(async (
    rawEntities: string[],
    rawType: "country" | "field",
    rawTopic = "",
  ) => {
    const entities = rawEntities.map(e => e.trim()).filter(Boolean).slice(0, 3);
    if (!entities.length) return;
    setLoading(true);
    try {
      const results = await Promise.all(
        entities.map(entity => fetchProgressData(entity, rawType, rawTopic))
      );
      setSeries(results.filter((item): item is ProgressData => item !== null));
    } catch (e) {
      console.error("Failed to fetch progress:", e);
    } finally {
      setLoading(false);
      setInput("");
    }
  }, [fetchProgressData]);

  const addEntity = useCallback(async () => {
    if (!input.trim()) return;
    if (series.length >= 3) return; // max 3
    await fetchEntity(input, type);
  }, [fetchEntity, input, type, series.length]);

  useEffect(() => {
    const typeParam = searchParams.get("type");
    const entityParam = searchParams.get("entity");
    const entitiesParam = searchParams.get("entities");
    const topicParam = searchParams.get("topic") ?? "";
    const nextType = typeParam === "field" ? "field" : "country";
    if (typeParam === "field" || typeParam === "country") {
      setType(nextType);
    }
    setTopicFilter(nextType === "country" ? topicParam : "");

    const rawEntities = entitiesParam
      ? entitiesParam.split(",")
      : entityParam
        ? [entityParam]
        : [];
    if (!rawEntities.length) return;

    const autoKey = `${nextType}:${rawEntities.join(",")}:${topicParam}`;
    if (autoKey === lastAutoQuery.current) return;
    lastAutoQuery.current = autoKey;
    fetchEntities(rawEntities, nextType, topicParam);
  }, [searchParams, fetchEntities]);

  const removeEntity = (idx: number) => {
    setSeries(prev => prev.filter((_, i) => i !== idx));
  };

  // Compute chart bounds
  const allPoints = series.flatMap(s => s.trend);
  const allVals = allPoints.map(p => p[metric]);
  const maxVal = Math.max(...allVals, 1);
  const minYear = allPoints.length > 0 ? Math.min(...allPoints.map(p => p.year)) : 2016;
  const maxYear = allPoints.length > 0 ? Math.max(...allPoints.map(p => p.year)) : 2025;
  const yearSpan = Math.max(maxYear - minYear, 1);

  const chartW = 700;
  const chartH = 320;
  const pad = { top: 24, right: 24, bottom: 40, left: 60 };
  const innerW = chartW - pad.left - pad.right;
  const innerH = chartH - pad.top - pad.bottom;

  const toX = (year: number) => pad.left + ((year - minYear) / yearSpan) * innerW;
  const toY = (val: number) => pad.top + innerH - (val / maxVal) * innerH;

  return (
    <div style={{
      position: "absolute", top: 52, left: 0, right: 0, bottom: 0,
      background: "#06080f",
      overflowY: "auto",
      padding: "32px 40px",
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
        <span style={{ fontSize: 24 }}>📈</span>
        <h1 style={{
          fontFamily: PIXEL_FONT, fontSize: 14,
          color: "#f8fafc", margin: 0,
        }}>
          RESEARCH PROGRESS
        </h1>
      </div>

      {/* Controls */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        marginBottom: 24, flexWrap: "wrap",
      }}>
        {/* Type toggle */}
        <div style={{ display: "flex", gap: 2 }}>
          {(["country", "field"] as const).map(t => (
            <button
              key={t}
              onClick={() => setType(t)}
              style={{
                background: type === t ? "#00d4ff14" : "transparent",
                border: "none",
                borderBottom: type === t ? "2px solid #00d4ff" : "2px solid transparent",
                color: type === t ? "#00d4ff" : "#334155",
                fontFamily: PIXEL_FONT, fontSize: 7,
                padding: "6px 12px", cursor: "pointer",
              }}
            >
              {t.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Input */}
        <div style={{
          display: "flex", alignItems: "center",
          background: "#0a0f1a",
          border: "1px solid #1e293b",
        }}>
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") addEntity(); }}
            placeholder={type === "country" ? "e.g. KR, US, CN" : "e.g. AI, NLP, Computer Vision"}
            style={{
              padding: "8px 12px",
              background: "transparent", border: "none", outline: "none",
              color: "#e2e8f0", fontFamily: MONO_FONT, fontSize: 13,
              width: 220,
            }}
          />
          <button
            onClick={addEntity}
            disabled={loading || series.length >= 3}
            style={{
              background: "#00d4ff14",
              border: "none", borderLeft: "1px solid #1e293b",
              color: loading ? "#334155" : "#00d4ff",
              fontFamily: PIXEL_FONT, fontSize: 7,
              padding: "8px 14px", cursor: loading ? "wait" : "pointer",
            }}
          >
            {loading ? "..." : "ADD"}
          </button>
        </div>

        {/* Active tags */}
        {series.map((s, i) => (
          <div key={i} style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "4px 10px",
            border: `1px solid ${LINE_COLORS[i]}44`,
            background: `${LINE_COLORS[i]}10`,
          }}>
            {s.type === "country" && COUNTRY_FLAGS[s.entity] && (
              <span>{COUNTRY_FLAGS[s.entity]}</span>
            )}
            {s.type === "field" && (
              <div style={{ width: 6, height: 6, background: LINE_COLORS[i] }} />
            )}
            <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: LINE_COLORS[i] }}>
              {s.entity}
            </span>
            <button
              onClick={() => removeEntity(i)}
              style={{
                background: "transparent", border: "none",
                color: "#475569", cursor: "pointer",
                fontFamily: MONO_FONT, fontSize: 14, lineHeight: 1,
                padding: "0 2px",
              }}
            >x</button>
          </div>
        ))}

        {/* Metric toggle */}
        <div style={{ marginLeft: "auto", display: "flex", gap: 2 }}>
          {([
            { key: "researcher_count" as const, label: type === "country" ? "CONTRIBUTIONS" : "PAPERS" },
            { key: "avg_citations" as const, label: "AVG CITATIONS" },
          ]).map(m => (
            <button
              key={m.key}
              onClick={() => setMetric(m.key)}
              style={{
                background: metric === m.key ? "#a78bfa14" : "transparent",
                border: "none",
                borderBottom: metric === m.key ? "2px solid #a78bfa" : "2px solid transparent",
                color: metric === m.key ? "#a78bfa" : "#334155",
                fontFamily: PIXEL_FONT, fontSize: 6,
                padding: "6px 10px", cursor: "pointer",
              }}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {type === "country" && (
        <div style={{
          fontFamily: MONO_FONT,
          fontSize: 11,
          color: "#475569",
          marginBottom: 12,
        }}>
          Country trends use publication-year author affiliation contributions.
          {topicFilter && (
            <span style={{ color: "#00d4ff" }}>
              {" "}Filtered to {topicFilter} facet papers.
            </span>
          )}
        </div>
      )}
      {type === "field" && (
        <div style={{
          fontFamily: MONO_FONT,
          fontSize: 11,
          color: "#475569",
          marginBottom: 12,
        }}>
          Field trends use publication-year paper counts from weak paper facets.
        </div>
      )}

      {/* Chart */}
      {series.length === 0 ? (
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "center",
          height: 320,
          border: "1px solid #1e293b",
          background: "#0a0f1a",
          fontFamily: MONO_FONT, fontSize: 13, color: "#334155",
        }}>
          Add a country or field to see progress trends
        </div>
      ) : (
        <div style={{
          background: "#0a0f1a",
          border: "1px solid #1e293b",
          padding: 20,
        }}>
          <svg width={chartW} height={chartH} style={{ display: "block", margin: "0 auto" }}>
            {/* Grid */}
            {[0, 0.25, 0.5, 0.75, 1].map(frac => {
              const y = toY(maxVal * frac);
              return (
                <g key={frac}>
                  <line x1={pad.left} y1={y} x2={pad.left + innerW} y2={y}
                    stroke="#1e293b" strokeWidth={0.5} />
                  <text x={pad.left - 8} y={y + 4} textAnchor="end"
                    fill="#334155" fontFamily={MONO_FONT} fontSize={9}>
                    {fmtNum(Math.round(maxVal * frac))}
                  </text>
                </g>
              );
            })}

            {/* Year labels */}
            {Array.from({ length: yearSpan + 1 }, (_, i) => minYear + i).map(year => (
              <text key={year} x={toX(year)} y={chartH - 10} textAnchor="middle"
                fill="#475569" fontFamily={MONO_FONT} fontSize={9}>
                {year}
              </text>
            ))}

            {/* Lines */}
            {series.map((s, si) => {
              const c = LINE_COLORS[si];
              const pts = s.trend.map(t => ({ x: toX(t.year), y: toY(t[metric]) }));
              const path = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
              const areaPath = `${path} L${pts[pts.length - 1]?.x ?? 0},${pad.top + innerH} L${pts[0]?.x ?? 0},${pad.top + innerH} Z`;

              return (
                <g key={si}>
                  <path d={areaPath} fill={c} opacity={0.05} />
                  <path d={path} fill="none" stroke={c} strokeWidth={2} />
                  <path d={path} fill="none" stroke={c} strokeWidth={4} opacity={0.15} />
                  {pts.map((p, i) => (
                    <g key={i}>
                      <circle cx={p.x} cy={p.y} r={3} fill={c} />
                      <circle cx={p.x} cy={p.y} r={6} fill={c} opacity={0.12} />
                    </g>
                  ))}
                </g>
              );
            })}
          </svg>
        </div>
      )}

      {/* Summary cards */}
      {series.length > 0 && (
        <div style={{
          display: "grid",
          gridTemplateColumns: `repeat(${series.length}, 1fr)`,
          gap: 16,
          marginTop: 20,
        }}>
          {series.map((s, i) => (
            <div key={i} style={{
              background: "#0a0f1a",
              border: `1px solid ${LINE_COLORS[i]}33`,
              padding: 16,
            }}>
              <div style={{
                fontFamily: PIXEL_FONT, fontSize: 8, color: LINE_COLORS[i],
                marginBottom: 12, display: "flex", alignItems: "center", gap: 6,
              }}>
                {s.type === "country" && COUNTRY_FLAGS[s.entity] && (
                  <span style={{ fontSize: 14 }}>{COUNTRY_FLAGS[s.entity]}</span>
                )}
                {s.entity}
              </div>
              <div style={{ display: "flex", gap: 16 }}>
                <div>
                  <div style={{ fontFamily: PIXEL_FONT, fontSize: 6, color: "#334155", marginBottom: 4 }}>
                    {s.type === "country" ? "CONTRIBUTIONS" : "PAPERS"}
                  </div>
                  <div style={{ fontFamily: MONO_FONT, fontSize: 18, color: "#e2e8f0" }}>
                    {fmtNum(s.current.researcher_count)}
                  </div>
                </div>
                <div>
                  <div style={{ fontFamily: PIXEL_FONT, fontSize: 6, color: "#334155", marginBottom: 4 }}>
                    AVG CIT
                  </div>
                  <div style={{ fontFamily: MONO_FONT, fontSize: 18, color: "#e2e8f0" }}>
                    {fmtNum(s.current.avg_citations)}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
