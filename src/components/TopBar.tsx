import { useState, useRef, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import type { Researcher } from "../data/researchers";
import { ComparisonPanel } from "./ComparisonPanel";

interface UniversalResult {
  intent: "researcher_search" | "topic_map" | "benchmark" | "stats" | "comparison" | "trending" | "progress" | "leaderboard" | "researcher_dna";
  params: Record<string, string>;
  explanation: string;
  redirect: string | null;
  answer: number | null;
  answer_label: string | null;
}

const API_BASE = "http://localhost:8000/api";
const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT  = "'Share Tech Mono', monospace";

interface Props {
  onSelect: (r: Researcher) => void;
  visibleCount: number;
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return n.toString();
}

export function TopBar({ onSelect, visibleCount }: Props) {
  const [query, setQuery]     = useState("");
  const [results, setResults] = useState<Researcher[]>([]);
  const [open, setOpen]       = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [aiQuery, setAiQuery]         = useState("");
  const [aiLoading, setAiLoading]     = useState(false);
  const [aiResult, setAiResult]       = useState<UniversalResult | null>(null);
  const [comparisonData, setComparisonData] = useState<any | null>(null);
  const aiTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const navigate = useNavigate();
  const location = useLocation();

  const NAV_TABS = [
    { label: "GLOBE",      path: "/" },
    { label: "UNIVERSE",   path: "/universe" },
    { label: "GRAPH",      path: "/graph" },
    { label: "BENCHMARKS", path: "/benchmarks" },
    { label: "MAP",        path: "/map" },
    { label: "TRENDING",   path: "/trending" },
    { label: "LEADERBOARD", path: "/leaderboard" },
  ] as const;

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

  const handleAiSearch = useCallback(async (q: string) => {
    if (!q.trim()) return;
    setAiLoading(true);
    setAiResult(null);
    try {
      const res = await fetch(`${API_BASE}/search/universal?q=${encodeURIComponent(q)}`);
      const data: UniversalResult = await res.json();
      setAiResult(data);
      if (aiTimeoutRef.current) clearTimeout(aiTimeoutRef.current);

      if (data.intent === "comparison") {
        // Fetch comparison data then show panel
        const { comparison_type, entities } = data.params;
        fetch(`${API_BASE}/compare?type=${comparison_type}&entities=${encodeURIComponent(entities)}`)
          .then(r => r.json())
          .then(cd => { setComparisonData(cd); setAiResult(null); setAiQuery(""); })
          .catch(() => {});
      } else if (data.intent === "stats") {
        // Stats: show answer inline, dismiss after 6 seconds
        aiTimeoutRef.current = setTimeout(() => {
          setAiQuery("");
          setAiResult(null);
        }, 6000);
      } else if (data.redirect) {
        // Navigate after showing explanation briefly
        aiTimeoutRef.current = setTimeout(() => {
          const params = new URLSearchParams(data.params).toString();
          navigate(data.redirect + (params ? `?${params}` : ""));
          setAiQuery("");
          setAiResult(null);
        }, 1800);
      }
    } catch {
      setAiLoading(false);
    } finally {
      setAiLoading(false);
    }
  }, [navigate]);

  return (
    <>
    {comparisonData && (
      <ComparisonPanel
        data={comparisonData}
        onClose={() => setComparisonData(null)}
      />
    )}
    <div style={{
      position: "absolute", top: 0, left: 0, right: 0,
      height: 52, zIndex: 20,
      background: "rgba(6, 8, 15, 0.97)",
      borderBottom: "1px solid #1e293b",
      display: "flex", alignItems: "center",
      padding: "0 20px",
      gap: 20,
    }}>

      {/* Logo */}
      <div style={{
        fontFamily: PIXEL_FONT, fontSize: 10,
        color: "#f8fafc", letterSpacing: "0.04em",
        flexShrink: 0, whiteSpace: "nowrap",
        textShadow: "2px 2px 0 #00d4ff55",
      }}>
        RESEARCHER<span style={{ color: "#00d4ff" }}>WORLD</span>
      </div>

      {/* Divider */}
      <div style={{ width: 1, height: 20, background: "#1e293b", flexShrink: 0 }} />

      {/* Nav tabs */}
      <div style={{ display: "flex", gap: 2, flexShrink: 0 }}>
        {NAV_TABS.map((tab) => {
          const isActive = location.pathname === tab.path;
          return (
            <button
              key={tab.path}
              onClick={() => navigate(tab.path)}
              style={{
                background: isActive ? "#00d4ff14" : "transparent",
                border: "none",
                borderBottom: isActive ? "2px solid #00d4ff" : "2px solid transparent",
                color: isActive ? "#00d4ff" : "#334155",
                fontFamily: PIXEL_FONT, fontSize: 7,
                padding: "6px 12px",
                cursor: "pointer",
                letterSpacing: "0.06em",
                transition: "color 0.12s, border-color 0.12s, background 0.12s",
              }}
              onMouseEnter={(e) => {
                if (!isActive) e.currentTarget.style.color = "#64748b";
              }}
              onMouseLeave={(e) => {
                if (!isActive) e.currentTarget.style.color = "#334155";
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Divider */}
      <div style={{ width: 1, height: 20, background: "#1e293b", flexShrink: 0 }} />

      {/* Search */}
      <div style={{ flex: 1, maxWidth: 460, position: "relative" }}>
        <div style={{
          display: "flex", alignItems: "center",
          background: "#0a0f1a",
          border: `1px solid ${open ? "#00d4ff33" : "#1e293b"}`,
          transition: "border-color 0.15s",
        }}>
          <span style={{
            padding: "0 8px 0 12px",
            fontFamily: PIXEL_FONT, fontSize: 9,
            color: open ? "#00d4ff88" : "#334155",
            flexShrink: 0, transition: "color 0.15s",
          }}>›</span>
          <input
            value={query}
            onChange={handleChange}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            placeholder="SEARCH RESEARCHER..."
            style={{
              flex: 1, padding: "8px 8px 8px 0",
              background: "transparent", border: "none", outline: "none",
              color: "#e2e8f0", fontFamily: MONO_FONT, fontSize: 13,
              letterSpacing: "0.03em",
            }}
          />
          {query && (
            <button
              onClick={() => { setQuery(""); setResults([]); }}
              style={{
                background: "transparent", border: "none",
                color: "#334155", cursor: "pointer",
                padding: "0 12px",
                fontFamily: MONO_FONT, fontSize: 14, lineHeight: 1,
              }}
            >×</button>
          )}
        </div>

        {open && results.length > 0 && (
          <div style={{
            position: "absolute", top: "calc(100% + 3px)", left: 0, right: 0,
            background: "#06080f",
            border: "1px solid #1e293b",
            boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
            maxHeight: 260, overflowY: "auto", zIndex: 30,
          }}>
            {results.map((r) => (
              <div key={r.id} onMouseDown={() => handleSelect(r)}
                style={{
                  padding: "10px 14px", cursor: "pointer",
                  borderBottom: "1px solid #060a12",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "#0a0f1a")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <div style={{ fontFamily: MONO_FONT, fontSize: 13, color: "#e2e8f0" }}>
                  {r.name}
                </div>
                <div style={{ fontFamily: MONO_FONT, fontSize: 11, color: "#475569", marginTop: 2 }}>
                  {r.institution ?? "—"}&nbsp;·&nbsp;{fmtNum(r.citations)} cit
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* AI Universal Search */}
      <div style={{ flex: 1, position: "relative", maxWidth: 500 }}>
        <div style={{
          display: "flex", alignItems: "center",
          background: "#06030d",
          border: `1px solid ${aiLoading ? "#a78bfa88" : aiResult ? "#34d39966" : "#2d1b6b55"}`,
          transition: "border-color 0.2s",
        }}>
          <span style={{
            padding: "0 6px 0 10px",
            fontFamily: PIXEL_FONT, fontSize: 7,
            color: aiLoading ? "#a78bfa" : "#4c2fa0",
            flexShrink: 0,
          }}>AI</span>
          <input
            value={aiQuery}
            onChange={e => setAiQuery(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") handleAiSearch(aiQuery); }}
            placeholder={aiLoading ? "ANALYZING..." : "Ask anything... (↵ to search)"}
            disabled={aiLoading}
            style={{
              flex: 1, padding: "7px 8px 7px 0",
              background: "transparent", border: "none", outline: "none",
              color: aiLoading ? "#a78bfa" : "#c4b5fd",
              fontFamily: MONO_FONT, fontSize: 12,
              letterSpacing: "0.02em",
            }}
          />
          {aiLoading && (
            <span style={{
              padding: "0 10px", fontFamily: PIXEL_FONT, fontSize: 6,
              color: "#a78bfa", animation: "pulse 1s infinite",
            }}>···</span>
          )}
        </div>

        {/* Result bubble */}
        {aiResult && (
          <div style={{
            position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0,
            background: "#0a0520",
            border: `1px solid ${aiResult.intent === "stats" ? "#34d39955" : "#4c2fa055"}`,
            padding: "12px 14px",
            zIndex: 40,
          }}>
            {aiResult.intent === "stats" ? (
              /* Stats answer */
              <>
                <div style={{ fontFamily: PIXEL_FONT, fontSize: 6, color: "#34d399", marginBottom: 8 }}>
                  ANSWER
                </div>
                {aiResult.answer != null ? (
                  <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                    <span style={{ fontFamily: MONO_FONT, fontSize: 22, color: "#f0fdf4", fontWeight: "bold" }}>
                      {aiResult.answer.toLocaleString()}
                    </span>
                    <span style={{ fontFamily: MONO_FONT, fontSize: 11, color: "#6ee7b7" }}>
                      {aiResult.answer_label}
                    </span>
                  </div>
                ) : (
                  <div style={{ fontFamily: MONO_FONT, fontSize: 11, color: "#475569" }}>조회 실패</div>
                )}
                <div style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#475569", marginTop: 6 }}>
                  {aiResult.explanation}
                </div>
              </>
            ) : (
              /* Navigation intent */
              <>
                <div style={{ fontFamily: PIXEL_FONT, fontSize: 6, color: "#a78bfa", marginBottom: 6 }}>
                  {aiResult.intent.replace("_", " ").toUpperCase()} →{" "}
                  {(aiResult.redirect ?? "").replace("/", "") || "GLOBE"}
                </div>
                <div style={{ fontFamily: MONO_FONT, fontSize: 11, color: "#94a3b8" }}>
                  {aiResult.explanation}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Node count */}
      <div style={{
        fontFamily: MONO_FONT, fontSize: 11,
        color: visibleCount > 0 ? "#475569" : "#334155",
        flexShrink: 0, letterSpacing: "0.06em",
        whiteSpace: "nowrap",
      }}>
        {visibleCount > 0 ? `${visibleCount} NODES` : "LOADING..."}
      </div>
    </div>
    </>
  );
}
