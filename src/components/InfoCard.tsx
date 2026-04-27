import { useNavigate } from "react-router-dom";
import type { Researcher } from "../data/researchers";
import { getFieldColor } from "../data/researchers";

const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT  = "'Share Tech Mono', monospace";

interface InfoCardProps {
  researcher: Researcher | null;
  related:    Researcher[];
  onClose:    () => void;
  onSelect:   (r: Researcher) => void;
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return n.toString();
}

export function InfoCard({ researcher, related, onClose, onSelect }: InfoCardProps) {
  const navigate = useNavigate();
  if (!researcher) return null;
  const color     = getFieldColor(researcher.field);
  const impactPct = Math.min(100, (researcher.h_index / 200) * 100);

  return (
    <div style={{
      position: "absolute",
      bottom: 24, left: 24,
      width: 400,
      background: "#06080f",
      border: `1px solid ${color}44`,
      boxShadow: `0 0 0 1px #06080f, 0 8px 32px rgba(0,0,0,0.7), inset 0 0 60px ${color}06`,
      color: "#e2e8f0",
      fontFamily: MONO_FONT,
      userSelect: "none",
    }}>

      {/* Header: gradient + name */}
      <div style={{
        background: `linear-gradient(135deg, ${color}20 0%, transparent 70%)`,
        borderBottom: `1px solid ${color}22`,
        padding: "14px 16px",
        position: "relative",
      }}>
        {/* Field badge */}
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          marginBottom: 10,
        }}>
          <div style={{ width: 6, height: 6, background: color, boxShadow: `0 0 6px ${color}` }} />
          <span style={{
            fontFamily: PIXEL_FONT, fontSize: 7, color,
            letterSpacing: "0.08em",
          }}>
            {(researcher.field ?? "UNKNOWN").toUpperCase()}
          </span>
        </div>

        {/* Name */}
        <div style={{
          fontFamily: PIXEL_FONT, fontSize: 10,
          color: "#f1f5f9",
          lineHeight: 1.8, letterSpacing: "0.02em",
          paddingRight: 36,
        }}>
          {researcher.name.toUpperCase()}
        </div>

        {/* Institution · Country */}
        <div style={{
          marginTop: 7, fontSize: 12, color: "#4b6080",
          letterSpacing: "0.02em",
        }}>
          {researcher.institution ?? "—"}
          {researcher.country && (
            <span style={{ color: "#334155" }}>&nbsp;·&nbsp;{researcher.country}</span>
          )}
        </div>

        {/* Close */}
        <button
          onClick={onClose}
          style={{
            position: "absolute", top: 12, right: 12,
            background: "transparent",
            border: `1px solid #1e293b`,
            color: "#334155", cursor: "pointer",
            fontFamily: MONO_FONT, fontSize: 16, lineHeight: 1,
            padding: "2px 7px",
            transition: "all 0.12s",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = color;
            e.currentTarget.style.color = color;
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = "#1e293b";
            e.currentTarget.style.color = "#334155";
          }}
        >×</button>
      </div>

      {/* Stats: 3 columns */}
      <div style={{
        display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
        borderBottom: `1px solid #0d1421`,
      }}>
        {[
          { label: "CITATIONS",  value: fmtNum(researcher.citations) },
          { label: "H-INDEX",    value: researcher.h_index.toString() },
          { label: "2YR PAPERS", value: researcher.recent_papers.toString() },
        ].map(({ label, value }, i) => (
          <div key={label} style={{
            padding: "11px 14px",
            borderRight: i < 2 ? "1px solid #0d1421" : "none",
          }}>
            <div style={{
              fontSize: 7, fontFamily: PIXEL_FONT,
              color: "#334155", marginBottom: 7, letterSpacing: "0.05em",
            }}>
              {label}
            </div>
            <div style={{ fontSize: 16, color, fontFamily: MONO_FONT }}>
              {value}
            </div>
          </div>
        ))}
      </div>

      {/* Impact bar */}
      <div style={{
        padding: "10px 16px",
        borderBottom: "1px solid #0d1421",
        display: "flex", alignItems: "center", gap: 10,
      }}>
        <span style={{
          fontFamily: PIXEL_FONT, fontSize: 7,
          color: "#334155", flexShrink: 0, letterSpacing: "0.05em",
        }}>IMPACT</span>
        <div style={{ flex: 1, height: 3, background: "#0f172a", position: "relative" }}>
          <div style={{
            position: "absolute", left: 0, top: 0, bottom: 0,
            width: `${impactPct}%`,
            background: `linear-gradient(90deg, ${color}66, ${color})`,
            boxShadow: `0 0 8px ${color}66`,
            transition: "width 0.5s ease",
          }} />
        </div>
        <span style={{
          fontFamily: MONO_FONT, fontSize: 10, color: "#475569",
          flexShrink: 0, minWidth: 28, textAlign: "right",
        }}>
          {impactPct.toFixed(0)}%
        </span>
      </div>

      {/* Related */}
      {related.length > 0 && (
        <div style={{ borderBottom: "1px solid #0d1421" }}>
          <div style={{
            padding: "8px 16px 4px",
            fontFamily: PIXEL_FONT, fontSize: 7,
            color: "#334155", letterSpacing: "0.06em",
          }}>
            RELATED
          </div>
          {related.slice(0, 4).map((r) => {
            const rc = getFieldColor(r.field);
            return (
              <div
                key={r.id}
                onClick={() => onSelect(r)}
                style={{
                  display: "flex", alignItems: "center", gap: 9,
                  padding: "8px 16px", cursor: "pointer",
                  borderTop: "1px solid #060a12",
                  transition: "background 0.08s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "#0a0f1a")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <div style={{
                  width: 6, height: 6, background: rc, flexShrink: 0,
                  boxShadow: `0 0 4px ${rc}88`,
                }} />
                <span style={{
                  flex: 1, fontSize: 12, color: "#94a3b8",
                  fontFamily: MONO_FONT,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>{r.name}</span>
                <span style={{
                  fontSize: 10, color: "#334155",
                  fontFamily: MONO_FONT, flexShrink: 0,
                }}>{fmtNum(r.citations)}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Navigation links */}
      <div style={{
        display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
        borderBottom: "1px solid #0d1421",
      }}>
        <button
          onClick={() => navigate(`/universe?researcher=${researcher.id}`)}
          style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: "9px 16px", gap: 6,
            background: "transparent",
            border: "none",
            borderRight: "1px solid #0d1421",
            color: "#334155", fontFamily: PIXEL_FONT, fontSize: 7,
            cursor: "pointer", letterSpacing: "0.05em",
            transition: "color 0.12s, background 0.12s",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = "#00d4ff";
            e.currentTarget.style.background = "#00d4ff08";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = "#334155";
            e.currentTarget.style.background = "transparent";
          }}
        >
          UNIVERSE
        </button>
        <button
          onClick={() => navigate(`/graph?researcher=${researcher.id}`)}
          style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: "9px 16px", gap: 6,
            background: "transparent",
            border: "none",
            borderRight: "1px solid #0d1421",
            color: "#334155", fontFamily: PIXEL_FONT, fontSize: 7,
            cursor: "pointer", letterSpacing: "0.05em",
            transition: "color 0.12s, background 0.12s",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = "#a855f7";
            e.currentTarget.style.background = "#a855f708";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = "#334155";
            e.currentTarget.style.background = "transparent";
          }}
        >
          GRAPH
        </button>
        <button
          onClick={() => navigate(`/researcher/${researcher.id}`)}
          style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: "9px 16px", gap: 6,
            background: "transparent",
            border: "none",
            color: "#334155", fontFamily: PIXEL_FONT, fontSize: 7,
            cursor: "pointer", letterSpacing: "0.05em",
            transition: "color 0.12s, background 0.12s",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = "#34d399";
            e.currentTarget.style.background = "#34d39908";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = "#334155";
            e.currentTarget.style.background = "transparent";
          }}
        >
          DNA
        </button>
      </div>

      {/* OpenAlex link */}
      {researcher.openalex_url && (
        <a
          href={researcher.openalex_url}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: "9px 16px", gap: 6,
            color: "#334155", fontFamily: PIXEL_FONT, fontSize: 7,
            textDecoration: "none", letterSpacing: "0.05em",
            transition: "color 0.12s",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "#00d4ff")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "#334155")}
        >
          OPENALEX ↗
        </a>
      )}
    </div>
  );
}
