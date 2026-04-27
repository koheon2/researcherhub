import { useState, useRef, useCallback } from "react";
import type { Researcher } from "../data/researchers";

const API_BASE = "http://localhost:8000/api";
const MONO_FONT = "'Share Tech Mono', monospace";
const PIXEL_FONT = "'Press Start 2P', monospace";

interface Props {
  onSelect: (r: Researcher) => void;
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return n.toString();
}

export function SearchBar({ onSelect }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Researcher[]>([]);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const search = useCallback(async (q: string) => {
    if (q.length < 2) { setResults([]); return; }
    try {
      const res = await fetch(`${API_BASE}/researchers/search?q=${encodeURIComponent(q)}`);
      setResults(await res.json());
    } catch { setResults([]); }
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value;
    setQuery(q);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(q), 300);
  };

  const handleSelect = (r: Researcher) => {
    onSelect(r);
    setQuery(r.name);
    setResults([]);
    setOpen(false);
  };

  return (
    <div style={{
      position: "absolute", top: 28, left: "50%", transform: "translateX(-50%)",
      zIndex: 20, width: 400,
    }}>
      <div style={{
        background: "#06080f",
        border: `2px solid ${open ? "#00d4ff66" : "#1e293b"}`,
        boxShadow: "4px 4px 0 #0f172a",
        display: "flex", alignItems: "center",
        transition: "border-color 0.15s",
      }}>
        <span style={{
          padding: "0 8px 0 10px",
          fontFamily: PIXEL_FONT, fontSize: 10, color: "#00d4ff",
          flexShrink: 0,
        }}>&rsaquo;</span>
        <input
          value={query}
          onChange={handleChange}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="SEARCH RESEARCHER..."
          style={{
            flex: 1, padding: "11px 10px 11px 0",
            background: "transparent", border: "none", outline: "none",
            color: "#e2e8f0", fontFamily: MONO_FONT, fontSize: 14,
            letterSpacing: "0.04em",
          }}
        />
        {query && (
          <button onClick={() => { setQuery(""); setResults([]); }}
            style={{
              background: "transparent", border: "none", color: "#334155",
              cursor: "pointer", padding: "0 12px", fontFamily: PIXEL_FONT, fontSize: 9,
            }}>&#x2715;</button>
        )}
      </div>

      {open && results.length > 0 && (
        <div style={{
          position: "absolute", top: "calc(100% + 2px)", left: 0, right: 0,
          background: "#06080f", border: "2px solid #1e293b",
          boxShadow: "4px 4px 0 #0f172a",
          maxHeight: 260, overflowY: "auto", zIndex: 30,
        }}>
          {results.map((r) => (
            <div key={r.id} onMouseDown={() => handleSelect(r)}
              style={{
                padding: "11px 14px", cursor: "pointer",
                borderBottom: "1px solid #060a12",
              }}
              onMouseEnter={e => (e.currentTarget.style.background = "#0f172a")}
              onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
            >
              <div style={{ fontFamily: MONO_FONT, fontSize: 13, color: "#e2e8f0" }}>{r.name}</div>
              <div style={{ fontFamily: MONO_FONT, fontSize: 11, color: "#475569", marginTop: 3 }}>
                {r.institution ?? "\u2014"}  &middot;  {fmtNum(r.citations)} cit
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
