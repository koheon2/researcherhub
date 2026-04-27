import { useEffect, useState, useRef } from "react";

const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT  = "'Share Tech Mono', monospace";

const ENTITY_COLORS = ["#60a5fa", "#f87171", "#34d399"];
const BG = "#020408";

/* ── Types ── */
interface Metric { [key: string]: number | string }

interface CompEntity {
  key: string;
  name: string;
  emoji: string;
  metrics: Metric;
  top_researcher?: { name: string; citations: number; institution?: string } | null;
  top_cluster?: string;
  matched_axis?: string;
  field?: string | null;
  institution?: string | null;
  id?: string | null;
}

interface ComparisonData {
  comparison_type: "country" | "topic" | "institution" | "researcher";
  entities: CompEntity[];
}

interface Props {
  data: ComparisonData;
  onClose: () => void;
}

/* ── Metric display config ── */
const METRIC_CONFIG: Record<string, { label: string; format: (v: number) => string; higherBetter: boolean }> = {
  researchers:     { label: "RESEARCHERS",      format: fmtBig,   higherBetter: true },
  contributions:   { label: "CONTRIBUTIONS",    format: fmtBig,   higherBetter: true },
  papers:          { label: "PAPERS",           format: fmtBig,   higherBetter: true },
  total_citations: { label: "TOTAL CITATIONS",  format: fmtBig,   higherBetter: true },
  avg_citations:   { label: "AVG CITATIONS",    format: fmtBig,   higherBetter: true },
  avg_paper_citations: { label: "AVG PAPER CIT.", format: fmtBig, higherBetter: true },
  avg_h_index:     { label: "AVG H-INDEX",      format: v => v.toFixed(1), higherBetter: true },
  citations:       { label: "CITATIONS",        format: fmtBig,   higherBetter: true },
  h_index:         { label: "H-INDEX",          format: v => String(v), higherBetter: true },
  works_count:     { label: "PUBLICATIONS",     format: fmtBig,   higherBetter: true },
  clusters:        { label: "TOPIC CLUSTERS",   format: v => String(v), higherBetter: true },
};

function fmtBig(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return Math.round(n).toLocaleString();
}

function typeLabel(t: string) {
  return { country: "COUNTRY BATTLE", topic: "TOPIC BATTLE",
           institution: "INSTITUTION BATTLE", researcher: "RESEARCHER BATTLE" }[t] ?? "BATTLE";
}

/* ── Animated stat bar ── */
function StatBar({ value, max, color, winner }: { value: number; max: number; color: string; winner: boolean }) {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setWidth(max > 0 ? (value / max) * 100 : 0), 80);
    return () => clearTimeout(t);
  }, [value, max]);

  return (
    <div style={{ position: "relative", height: 6, background: "#0d1117", borderRadius: 0, overflow: "hidden" }}>
      <div style={{
        position: "absolute", left: 0, top: 0, bottom: 0,
        width: `${width}%`,
        background: winner ? color : color + "88",
        transition: "width 1.2s cubic-bezier(0.22, 1, 0.36, 1)",
        boxShadow: winner ? `0 0 8px ${color}88` : "none",
      }} />
    </div>
  );
}

/* ── Single metric row ── */
function MetricRow({
  metricKey, entities, colors, comparisonType,
}: {
  metricKey: string;
  entities: CompEntity[];
  colors: string[];
  comparisonType: ComparisonData["comparison_type"];
}) {
  const cfg = METRIC_CONFIG[metricKey];
  if (!cfg) return null;
  const label = metricKey === "researchers" && (comparisonType === "country" || comparisonType === "institution")
    ? "CONTRIBUTIONS"
    : cfg.label;

  const numericValues = entities.map(e => {
    const v = e.metrics[metricKey];
    return typeof v === "number" ? v : 0;
  });

  const max = Math.max(...numericValues, 1);
  const winnerIdx = numericValues.indexOf(Math.max(...numericValues));

  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: 6,
      }}>
        <span style={{ fontFamily: PIXEL_FONT, fontSize: 6, color: "#334155", letterSpacing: ".06em" }}>
          {label}
        </span>
        <span style={{ fontFamily: PIXEL_FONT, fontSize: 6, color: colors[winnerIdx] + "cc" }}>
          🏆 {entities[winnerIdx]?.name}
        </span>
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        {entities.map((e, i) => {
          const v = numericValues[i];
          const isWinner = i === winnerIdx;
          return (
            <div key={e.key} style={{ flex: 1 }}>
              <div style={{
                fontFamily: MONO_FONT, fontSize: 13,
                color: isWinner ? colors[i] : colors[i] + "99",
                marginBottom: 4, textAlign: "center",
                fontWeight: isWinner ? "bold" : "normal",
              }}>
                {cfg.format(v)}
                {isWinner && <span style={{ marginLeft: 4, fontSize: 10 }}>▲</span>}
              </div>
              <StatBar value={v} max={max} color={colors[i]} winner={isWinner} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Main panel ── */
export function ComparisonPanel({ data, onClose }: Props) {
  const { comparison_type, entities } = data;
  const colors = entities.map((_, i) => ENTITY_COLORS[i] ?? "#94a3b8");
  const [appeared, setAppeared] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setAppeared(true), 30);
    return () => clearTimeout(t);
  }, []);

  // Keyboard close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  // Figure out metric keys (numeric only)
  const hasContributions = entities.some(e => typeof e.metrics.contributions === "number");
  const hasAvgPaperCitations = entities.some(e => typeof e.metrics.avg_paper_citations === "number");
  const metricKeys = Object.keys(entities[0]?.metrics ?? {}).filter(k => {
    if ((comparison_type === "country" || comparison_type === "institution" || comparison_type === "topic") && k === "researchers" && hasContributions) return false;
    if ((comparison_type === "country" || comparison_type === "institution" || comparison_type === "topic") && k === "avg_citations" && hasAvgPaperCitations) return false;
    const v = entities[0]?.metrics[k];
    return typeof v === "number" && k in METRIC_CONFIG;
  });

  // Overall winner: most metric wins
  const wins = entities.map(() => 0);
  metricKeys.forEach(k => {
    const vals = entities.map(e => typeof e.metrics[k] === "number" ? e.metrics[k] as number : 0);
    const maxV = Math.max(...vals);
    vals.forEach((v, i) => { if (v === maxV) wins[i]++; });
  });
  const overallWinnerIdx = wins.indexOf(Math.max(...wins));

  // Fun insight
  const insights: string[] = [];
  if (comparison_type === "country" || comparison_type === "institution") {
    const rcIdx = entities.map(e => (e.metrics.avg_citations as number) ?? 0).indexOf(
      Math.max(...entities.map(e => (e.metrics.avg_citations as number) ?? 0))
    );
    const scIdx = entities.map(e => (e.metrics.researchers as number) ?? 0).indexOf(
      Math.max(...entities.map(e => (e.metrics.researchers as number) ?? 0))
    );
    if (rcIdx !== scIdx) {
      insights.push(`${entities[rcIdx].emoji} ${entities[rcIdx].name} leads in research efficiency`);
      insights.push(`${entities[scIdx].emoji} ${entities[scIdx].name} leads in total scale`);
    }
  }

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 200,
        background: `${BG}f0`,
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        opacity: appeared ? 1 : 0,
        transition: "opacity 0.25s ease",
        backdropFilter: "blur(4px)",
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        ref={panelRef}
        style={{
          width: "min(95vw, 960px)",
          maxHeight: "90vh",
          overflowY: "auto",
          background: "#06080f",
          border: "1px solid #1e293b",
          boxShadow: "0 0 60px #000a",
          transform: appeared ? "translateY(0)" : "translateY(24px)",
          transition: "transform 0.35s cubic-bezier(0.22, 1, 0.36, 1)",
        }}
      >
        {/* Header */}
        <div style={{
          padding: "20px 28px 16px",
          borderBottom: "1px solid #1e293b",
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <div>
            <div style={{
              fontFamily: PIXEL_FONT, fontSize: 7, color: "#fbbf24",
              letterSpacing: ".12em", marginBottom: 6,
            }}>
              ⚡ {typeLabel(comparison_type)} ⚡
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              {entities.map((e, i) => (
                <span key={e.key} style={{
                  fontFamily: MONO_FONT, fontSize: 11,
                  color: colors[i], padding: "2px 8px",
                  border: `1px solid ${colors[i]}44`,
                }}>
                  {e.emoji} {e.name}
                </span>
              ))}
            </div>
          </div>
          <button onClick={onClose} style={{
            background: "none", border: "1px solid #1e293b",
            color: "#475569", cursor: "pointer",
            fontFamily: MONO_FONT, fontSize: 18, padding: "4px 12px",
            lineHeight: 1,
          }}>×</button>
        </div>

        {/* Entity name headers */}
        <div style={{
          display: "grid",
          gridTemplateColumns: `repeat(${entities.length}, 1fr)`,
          gap: 0,
          borderBottom: "1px solid #0d1117",
        }}>
          {entities.map((e, i) => (
            <div key={e.key} style={{
              padding: "20px 24px 16px",
              borderRight: i < entities.length - 1 ? "1px solid #0d1117" : "none",
              background: i % 2 === 0 ? "#06080f" : "#07090f",
            }}>
              <div style={{
                fontFamily: PIXEL_FONT, fontSize: 14,
                color: colors[i], marginBottom: 4, lineHeight: 1.4,
              }}>{e.emoji}</div>
              <div style={{
                fontFamily: MONO_FONT, fontSize: 17,
                color: "#e2e8f0", marginBottom: 2,
              }}>{e.name}</div>
              {comparison_type === "researcher" && (
                <div style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#475569" }}>
                  {e.field ?? "—"} · {e.institution ?? "—"}
                </div>
              )}
              {comparison_type === "topic" && e.top_cluster && (
                <div style={{ fontFamily: MONO_FONT, fontSize: 9, color: "#475569" }}>
                  axis: {e.matched_axis ?? "—"} · {e.top_cluster.length > 28 ? e.top_cluster.slice(0, 26) + "…" : e.top_cluster}
                </div>
              )}
              {(comparison_type === "country" || comparison_type === "institution") && (
                <div style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#475569" }}>
                  top field: {(e.metrics.top_field as string) ?? "—"}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Stats */}
        <div style={{ padding: "24px 28px" }}>
          {metricKeys.map(k => (
            <MetricRow key={k} metricKey={k} entities={entities} colors={colors} comparisonType={comparison_type} />
          ))}
        </div>

        {/* Top researchers (country/institution only) */}
        {(comparison_type === "country" || comparison_type === "institution") &&
          entities.some(e => e.top_researcher) && (
          <div style={{
            padding: "0 28px 20px",
            display: "grid",
            gridTemplateColumns: `repeat(${entities.length}, 1fr)`,
            gap: 12,
          }}>
            {entities.map((e, i) => e.top_researcher && (
              <div key={e.key} style={{
                padding: "10px 14px",
                background: "#0d1117",
                border: `1px solid ${colors[i]}22`,
              }}>
                <div style={{ fontFamily: PIXEL_FONT, fontSize: 6, color: "#334155", marginBottom: 6 }}>
                  TOP CONTRIBUTOR
                </div>
                <div style={{ fontFamily: MONO_FONT, fontSize: 12, color: colors[i] }}>
                  {e.top_researcher.name}
                </div>
                <div style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#475569", marginTop: 2 }}>
                  {fmtBig(e.top_researcher.citations)} citations
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Overall winner */}
        <div style={{
          margin: "0 28px 24px",
          padding: "16px 20px",
          background: `${colors[overallWinnerIdx]}11`,
          border: `1px solid ${colors[overallWinnerIdx]}44`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <div style={{ fontFamily: PIXEL_FONT, fontSize: 7, color: colors[overallWinnerIdx], marginBottom: 6 }}>
              🏆 OVERALL WINNER
            </div>
            <div style={{ fontFamily: MONO_FONT, fontSize: 18, color: "#f8fafc" }}>
              {entities[overallWinnerIdx].emoji} {entities[overallWinnerIdx].name}
            </div>
            <div style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#64748b", marginTop: 4 }}>
              wins {wins[overallWinnerIdx]}/{metricKeys.length} metrics
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            {insights.map((ins, i) => (
              <div key={i} style={{
                fontFamily: MONO_FONT, fontSize: 10, color: "#475569",
                marginBottom: 3,
              }}>· {ins}</div>
            ))}
          </div>
        </div>

        {/* Footer hint */}
        <div style={{
          padding: "10px 28px 16px",
          fontFamily: PIXEL_FONT, fontSize: 6,
          color: "#1e293b", letterSpacing: ".06em",
        }}>
          [ESC] OR CLICK OUTSIDE TO CLOSE
        </div>
      </div>
    </div>
  );
}
