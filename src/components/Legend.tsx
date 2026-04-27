import { FIELD_COLORS } from "../data/researchers";

const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT = "'Share Tech Mono', monospace";

interface LegendProps {
  activeField: string | null;
  onFieldClick: (field: string | null) => void;
  tileStyle: "dark" | "light" | "voyager";
  onTileChange: (s: "dark" | "light" | "voyager") => void;
}

export function Legend({ activeField, onFieldClick, tileStyle, onTileChange }: LegendProps) {
  return (
    <div style={{
      position: "absolute",
      top: 24,
      right: 24,
      background: "#06080f",
      border: "2px solid #1e293b",
      boxShadow: "4px 4px 0 #0f172a",
      fontFamily: MONO_FONT,
      minWidth: 260,
    }}>
      {/* Titlebar */}
      <div style={{
        background: "#1e293b",
        padding: "8px 12px",
        fontFamily: PIXEL_FONT,
        fontSize: 9,
        color: "#94a3b8",
        letterSpacing: "0.05em",
      }}>
        FIELD_FILTER.EXE
      </div>

      {/* Tile style toggle */}
      <div style={{ padding: "10px 12px 0", borderBottom: "1px solid #0f172a" }}>
        <div style={{ fontFamily: PIXEL_FONT, fontSize: 8, color: "#334155", marginBottom: 8, letterSpacing: "0.05em" }}>
          MAP_STYLE
        </div>
        <div style={{ display: "flex", gap: 3, marginBottom: 10 }}>
          {(["dark", "voyager", "light"] as const).map((s, i) => {
            const labels = ["DARK", "MAP", "LIGHT"];
            const active = tileStyle === s;
            return (
              <button key={s} onClick={() => onTileChange(s)} style={{
                flex: 1,
                background: active ? "#00d4ff" : "#0f172a",
                color: active ? "#000005" : "#475569",
                border: `1px solid ${active ? "#00d4ff" : "#1e293b"}`,
                padding: "6px 0",
                cursor: "pointer",
                fontFamily: PIXEL_FONT,
                fontSize: 7,
                letterSpacing: "0.03em",
              }}>{labels[i]}</button>
            );
          })}
        </div>
      </div>

      {/* Field filters */}
      <div style={{ padding: "12px 12px 8px" }}>
        {Object.entries(FIELD_COLORS).map(([field, color]) => (
          <div
            key={field}
            onClick={() => onFieldClick(activeField === field ? null : field)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "6px 8px",
              cursor: "pointer",
              opacity: activeField && activeField !== field ? 0.2 : 1,
              transition: "opacity 0.15s",
              background: activeField === field ? `${color}18` : "transparent",
              border: activeField === field ? `1px solid ${color}44` : "1px solid transparent",
              marginBottom: 3,
            }}
          >
            {/* Pixel dot */}
            <div style={{
              width: 10,
              height: 10,
              background: color,
              flexShrink: 0,
              boxShadow: `2px 2px 0 ${color}55`,
              imageRendering: "pixelated",
            }} />
            <span style={{
              fontSize: 12,
              color: activeField === field ? color : "#64748b",
              fontFamily: MONO_FONT,
            }}>
              {field}
            </span>
          </div>
        ))}

        <div style={{
          marginTop: 12,
          borderTop: "1px solid #1e293b",
          paddingTop: 12,
        }}>
          <div style={{ fontFamily: PIXEL_FONT, fontSize: 8, color: "#334155", marginBottom: 8 }}>
            LEGEND
          </div>
          <div style={{ fontSize: 12, color: "#475569", lineHeight: 2 }}>
            &#x25B2; size = citations<br />
            &#x2605; glow = h-index
          </div>
        </div>
      </div>
    </div>
  );
}
