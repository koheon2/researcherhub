import { useState, useRef, useCallback, useEffect } from "react";
import { useSearchParams } from "react-router-dom";

const API_BASE   = "http://localhost:8000/api";
const MONO_FONT  = "'Share Tech Mono', monospace";
const PIXEL_FONT = "'Press Start 2P', monospace";
const BG         = "#050810";
const CARD_BG    = "#0d1117";

const CAMP_COLORS = [
  "#60a5fa", "#a78bfa", "#34d399", "#fbbf24",
  "#f87171", "#fb923c", "#e879f9", "#94a3b8",
];

const ROLE_COLORS: Record<string, string> = {
  foundational: "#fbbf24",
  milestone:    "#a78bfa",
  current:      "#34d399",
  notable:      "#475569",
};

/* ── Types ── */
interface ConceptHit {
  id: string;
  name: string;
  works_count: number;
}

interface TimelineEntry {
  year: number;
  paper_count: number;
  avg_citations: number;
  dominant_camp: string | null;
}

interface CampTopPaper {
  id: string;
  title: string;
  year: number;
  citations: number;
}

interface Camp {
  id: string;
  name: string;
  paper_count: number;
  total_citations: number;
  top_papers: CampTopPaper[];
}

interface KeyPaper {
  id: string;
  title: string;
  year: number;
  citations: number;
  role: "foundational" | "milestone" | "current" | "notable";
  camp: string;
  authors: string[];
}

interface MapAnalysis {
  concept: { id: string; name: string; total_works: number };
  timeline: TimelineEntry[];
  camps: Camp[];
  key_papers: KeyPaper[];
  narrative: string;
  sample_size: number;
}

/* ── Helpers ── */
function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

function getCampColor(camps: Camp[], campName: string): string {
  const idx = camps.findIndex((c) => c.name === campName);
  return idx >= 0 ? CAMP_COLORS[idx % CAMP_COLORS.length] : "#475569";
}

/* ── Main Component ── */
export function ResearchMap() {
  const [query, setQuery]         = useState("");
  const [concepts, setConcepts]   = useState<ConceptHit[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [analysis, setAnalysis]   = useState<MapAnalysis | null>(null);
  const [loading, setLoading]     = useState(false);
  const [expandedCamp, setExpandedCamp] = useState<string | null>(null);
  const [hoveredBar, setHoveredBar]     = useState<number | null>(null);

  const debounceRef    = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [searchParams] = useSearchParams();

  /* ── Auto-search from URL ?query= param ── */
  const lastAutoQuery = useRef<string | null>(null);
  useEffect(() => {
    const q = searchParams.get("query");
    if (!q || q === lastAutoQuery.current) return;
    lastAutoQuery.current = q;
    setQuery(q);
    fetch(`${API_BASE}/map/search?q=${encodeURIComponent(q)}`)
      .then(r => r.json())
      .then((hits: ConceptHit[]) => { if (hits.length > 0) selectConcept(hits[0]); })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  /* ── Search concepts ── */
  const doSearch = useCallback(async (q: string) => {
    if (q.length < 2) { setConcepts([]); return; }
    setSearchLoading(true);
    try {
      const res = await fetch(`${API_BASE}/map/search?q=${encodeURIComponent(q)}`);
      if (res.ok) setConcepts(await res.json());
      else setConcepts([]);
    } catch { setConcepts([]); }
    setSearchLoading(false);
  }, []);

  const handleInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value;
    setQuery(q);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(q), 350);
  };

  const selectConcept = useCallback(async (c: ConceptHit) => {
    setQuery(c.name);
    setConcepts([]);
    setAnalysis(null);
    setLoading(true);
    setExpandedCamp(null);
    try {
      const res = await fetch(
        `${API_BASE}/map/analyze?concept_id=${encodeURIComponent(c.id)}&years=15`
      );
      if (res.ok) {
        const data: MapAnalysis = await res.json();
        setAnalysis(data);
      }
    } catch {
      console.error("Failed to fetch map analysis");
    }
    setLoading(false);
  }, []);

  /* ── Timeline SVG ── */
  const renderTimeline = (timeline: TimelineEntry[], camps: Camp[]) => {
    if (timeline.length === 0) return null;
    const maxCount = Math.max(1, ...timeline.map((t) => t.paper_count));
    const padL = 10;
    const padR = 10;
    const padT = 10;
    const padB = 28;
    const chartW = 100 - padL - padR;
    const chartH = 100 - padT - padB;
    const barW = Math.max(1, (chartW / timeline.length) * 0.7);
    const gap = chartW / timeline.length;

    return (
      <svg
        viewBox={`0 0 100 100`}
        preserveAspectRatio="none"
        style={{ width: "100%", height: "100%", display: "block" }}
      >
        {/* bars */}
        {timeline.map((entry, i) => {
          const ratio = entry.paper_count / maxCount;
          const barH = Math.max(0.5, ratio * chartH);
          const x = padL + gap * i + (gap - barW) / 2;
          const y = padT + chartH - barH;
          const color = entry.dominant_camp
            ? getCampColor(camps, entry.dominant_camp)
            : "#60a5fa";
          const isHovered = hoveredBar === i;

          return (
            <g key={entry.year}>
              <rect
                x={x}
                y={y}
                width={barW}
                height={barH}
                fill={color}
                opacity={isHovered ? 1 : 0.75}
                onMouseEnter={() => setHoveredBar(i)}
                onMouseLeave={() => setHoveredBar(null)}
                style={{ cursor: "pointer" }}
              />
              {/* glow on hover */}
              {isHovered && (
                <rect
                  x={x - 0.3}
                  y={y - 0.3}
                  width={barW + 0.6}
                  height={barH + 0.6}
                  fill="none"
                  stroke={color}
                  strokeWidth={0.4}
                  opacity={0.6}
                />
              )}
            </g>
          );
        })}

        {/* x-axis labels (every 5 years) */}
        {timeline.map((entry, i) => {
          if (entry.year % 5 !== 0 && i !== 0 && i !== timeline.length - 1) return null;
          const x = padL + gap * i + gap / 2;
          return (
            <text
              key={`lbl-${entry.year}`}
              x={x}
              y={padT + chartH + 6}
              textAnchor="middle"
              fill="#475569"
              fontSize="3"
              fontFamily={MONO_FONT}
            >
              {entry.year}
            </text>
          );
        })}

        {/* x-axis line */}
        <line
          x1={padL} y1={padT + chartH}
          x2={100 - padR} y2={padT + chartH}
          stroke="#1e293b" strokeWidth={0.3}
        />
      </svg>
    );
  };

  /* ── Tooltip for hovered bar ── */
  const renderTooltip = (timeline: TimelineEntry[]) => {
    if (hoveredBar === null || !timeline[hoveredBar]) return null;
    const entry = timeline[hoveredBar];
    return (
      <div style={{
        position: "absolute", top: 8, right: 12,
        background: "#0a0f1aee", border: "1px solid #1e293b",
        padding: "6px 10px",
        fontFamily: MONO_FONT, fontSize: 11, color: "#e2e8f0",
        pointerEvents: "none",
      }}>
        <span style={{ color: "#60a5fa" }}>{entry.year}</span>
        {" "}&middot; {fmtNum(entry.paper_count)} papers
        {" "}&middot; avg {entry.avg_citations.toFixed(1)} cit
      </div>
    );
  };

  return (
    <div style={{
      position: "absolute", top: 52, left: 0, right: 0, bottom: 0,
      background: BG, display: "flex", flexDirection: "column",
      fontFamily: MONO_FONT,
    }}>

      {/* Search bar */}
      <div style={{
        padding: "16px 24px",
        borderBottom: "1px solid #1e293b",
        flexShrink: 0, position: "relative",
      }}>
        <div style={{
          display: "flex", alignItems: "center",
          background: "#0a0f1a",
          border: "1px solid #1e293b",
          maxWidth: 600,
        }}>
          <span style={{
            padding: "0 8px 0 14px",
            fontFamily: PIXEL_FONT, fontSize: 9,
            color: "#334155", flexShrink: 0,
          }}>&gt;</span>
          <input
            value={query}
            onChange={handleInput}
            placeholder="Search research topics..."
            style={{
              flex: 1, padding: "10px 10px 10px 4px",
              background: "transparent", border: "none", outline: "none",
              color: "#e2e8f0", fontFamily: MONO_FONT, fontSize: 14,
              letterSpacing: "0.03em",
            }}
          />
          {searchLoading && (
            <span style={{
              padding: "0 14px", fontSize: 10, color: "#334155",
              fontFamily: MONO_FONT,
            }}>...</span>
          )}
          {query && !searchLoading && (
            <button
              onClick={() => { setQuery(""); setConcepts([]); setAnalysis(null); }}
              style={{
                background: "transparent", border: "none",
                color: "#334155", cursor: "pointer",
                padding: "0 14px", fontFamily: MONO_FONT, fontSize: 16,
              }}
            >x</button>
          )}
        </div>

        {/* Autocomplete dropdown */}
        {concepts.length > 0 && (
          <div style={{
            position: "absolute", top: "100%", left: 24, right: 24,
            maxWidth: 600, zIndex: 30,
            background: "#06080f",
            border: "1px solid #1e293b",
            boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
            maxHeight: 260, overflowY: "auto",
          }}>
            {concepts.map((c) => (
              <div
                key={c.id}
                onClick={() => selectConcept(c)}
                style={{
                  padding: "10px 14px", cursor: "pointer",
                  borderBottom: "1px solid #060a12",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "#0a0f1a")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <div style={{ fontSize: 13, color: "#e2e8f0" }}>{c.name}</div>
                <div style={{ fontSize: 10, color: "#475569", marginTop: 2 }}>
                  {fmtNum(c.works_count)} works
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Main content area */}
      <div style={{ flex: 1, overflowY: "auto" }}>

        {/* Initial state */}
        {!loading && !analysis && (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            height: "100%",
            fontFamily: PIXEL_FONT, fontSize: 8, color: "#1e293b",
            letterSpacing: ".08em", lineHeight: 2.2,
            textAlign: "center", padding: 40,
          }}>
            SEARCH FOR A TOPIC{"\n"}TO MAP ITS RESEARCH LANDSCAPE
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            height: "100%",
            fontFamily: PIXEL_FONT, fontSize: 9, color: "#60a5fa",
            letterSpacing: ".1em",
          }}>
            ANALYZING RESEARCH LANDSCAPE...
          </div>
        )}

        {/* Results */}
        {!loading && analysis && (
          <div style={{ padding: "0 24px 24px" }}>

            {/* Concept header */}
            <div style={{
              padding: "20px 0 16px",
              borderBottom: "1px solid #1e293b",
              marginBottom: 20,
            }}>
              <div style={{
                fontFamily: PIXEL_FONT, fontSize: 11, color: "#60a5fa",
                letterSpacing: ".04em", marginBottom: 8,
              }}>
                {analysis.concept.name.toUpperCase()}
              </div>
              <div style={{
                display: "flex", gap: 24, fontSize: 11, color: "#475569",
                marginBottom: 10,
              }}>
                <span>{fmtNum(analysis.concept.total_works)} total works</span>
                <span>sample: {fmtNum(analysis.sample_size)} analyzed</span>
              </div>
              {analysis.narrative && (
                <div style={{
                  fontSize: 12, color: "#94a3b8", lineHeight: 1.6,
                  maxWidth: 800,
                }}>
                  {analysis.narrative}
                </div>
              )}
            </div>

            {/* Timeline */}
            <div style={{
              background: CARD_BG, border: "1px solid #1e293b",
              marginBottom: 20, position: "relative",
            }}>
              <div style={{
                padding: "12px 16px 4px",
                fontFamily: PIXEL_FONT, fontSize: 7, color: "#334155",
                letterSpacing: ".08em",
              }}>
                TIMELINE
              </div>
              <div style={{ height: 200, padding: "0 8px 8px", position: "relative" }}>
                {renderTimeline(analysis.timeline, analysis.camps)}
                {renderTooltip(analysis.timeline)}
              </div>
            </div>

            {/* Bottom panels: Camps + Key Papers */}
            <div style={{
              display: "flex", gap: 20,
              flexWrap: "wrap",
            }}>

              {/* Research Camps */}
              <div style={{
                flex: "1 1 320px", minWidth: 280,
                background: CARD_BG, border: "1px solid #1e293b",
              }}>
                <div style={{
                  padding: "12px 16px",
                  fontFamily: PIXEL_FONT, fontSize: 7, color: "#334155",
                  letterSpacing: ".08em",
                  borderBottom: "1px solid #1e293b",
                }}>
                  RESEARCH CAMPS ({Math.min(8, analysis.camps.length)})
                </div>
                <div style={{ padding: "8px 0" }}>
                  {analysis.camps.slice(0, 8).map((camp, idx) => {
                    const maxPapers = Math.max(1, ...analysis.camps.slice(0, 8).map((c) => c.paper_count));
                    const ratio = camp.paper_count / maxPapers;
                    const color = CAMP_COLORS[idx % CAMP_COLORS.length];
                    const isExpanded = expandedCamp === camp.id;

                    return (
                      <div key={camp.id}>
                        <div
                          onClick={() => setExpandedCamp(isExpanded ? null : camp.id)}
                          style={{
                            padding: "8px 16px", cursor: "pointer",
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = "#0a0f1a")}
                          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                        >
                          <div style={{
                            display: "flex", justifyContent: "space-between",
                            alignItems: "center", marginBottom: 4,
                          }}>
                            <span style={{
                              fontSize: 11, color: "#e2e8f0",
                              maxWidth: "70%",
                              overflow: "hidden", textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}>
                              <span style={{
                                display: "inline-block", width: 8, height: 8,
                                background: color, marginRight: 8,
                                flexShrink: 0,
                              }} />
                              {camp.name}
                            </span>
                            <span style={{ fontSize: 10, color: "#475569" }}>
                              {fmtNum(camp.paper_count)}
                            </span>
                          </div>
                          <div style={{
                            height: 4, background: "#1e293b",
                            width: "100%",
                          }}>
                            <div style={{
                              height: "100%",
                              width: `${ratio * 100}%`,
                              background: color,
                              opacity: 0.7,
                              transition: "width 0.3s ease",
                            }} />
                          </div>
                        </div>

                        {/* Expanded top papers */}
                        {isExpanded && camp.top_papers.length > 0 && (
                          <div style={{
                            padding: "4px 16px 8px 32px",
                            borderBottom: "1px solid #0a0f1a",
                          }}>
                            {camp.top_papers.slice(0, 3).map((p) => (
                              <a
                                key={p.id}
                                href={`https://openalex.org/W${p.id}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                style={{
                                  display: "block",
                                  padding: "4px 0",
                                  fontSize: 10, color: "#94a3b8",
                                  textDecoration: "none",
                                  lineHeight: 1.4,
                                }}
                                onMouseEnter={(e) => (e.currentTarget.style.color = color)}
                                onMouseLeave={(e) => (e.currentTarget.style.color = "#94a3b8")}
                              >
                                {p.title.length > 80 ? p.title.slice(0, 80) + "..." : p.title}
                                <span style={{ color: "#475569", marginLeft: 6 }}>
                                  {p.year} &middot; {fmtNum(p.citations)} cit
                                </span>
                              </a>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Key Papers */}
              <div style={{
                flex: "2 1 400px", minWidth: 320,
                background: CARD_BG, border: "1px solid #1e293b",
                maxHeight: 600, display: "flex", flexDirection: "column",
              }}>
                <div style={{
                  padding: "12px 16px",
                  fontFamily: PIXEL_FONT, fontSize: 7, color: "#334155",
                  letterSpacing: ".08em",
                  borderBottom: "1px solid #1e293b",
                  flexShrink: 0,
                }}>
                  KEY PAPERS ({Math.min(30, analysis.key_papers.length)})
                </div>
                <div style={{ overflowY: "auto", flex: 1 }}>
                  {analysis.key_papers.slice(0, 30).map((paper) => {
                    const roleColor = ROLE_COLORS[paper.role] ?? "#475569";
                    const campColor = getCampColor(analysis.camps, paper.camp);
                    const isFoundational = paper.role === "foundational";

                    return (
                      <a
                        key={paper.id}
                        href={`https://openalex.org/W${paper.id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          display: "block",
                          padding: "10px 16px",
                          borderBottom: "1px solid #0a0f1a",
                          textDecoration: "none",
                          borderLeft: isFoundational ? `3px solid ${ROLE_COLORS.foundational}` : "3px solid transparent",
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = "#0a0f1a")}
                        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                      >
                        {/* top row: role badge + year + citations */}
                        <div style={{
                          display: "flex", alignItems: "center", gap: 8,
                          marginBottom: 4,
                        }}>
                          <span style={{
                            fontFamily: PIXEL_FONT, fontSize: 6,
                            color: roleColor,
                            padding: "2px 6px",
                            border: `1px solid ${roleColor}44`,
                            background: `${roleColor}11`,
                            letterSpacing: ".04em",
                            textTransform: "uppercase",
                          }}>
                            {isFoundational && "\u2B50 "}{paper.role}
                          </span>
                          <span style={{ fontSize: 10, color: "#475569" }}>
                            {paper.year}
                          </span>
                          <span style={{ fontSize: 10, color: "#60a5fa" }}>
                            {fmtNum(paper.citations)} cit
                          </span>
                          <span style={{
                            fontSize: 9, color: campColor,
                            marginLeft: "auto",
                            maxWidth: 120,
                            overflow: "hidden", textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}>
                            {paper.camp}
                          </span>
                        </div>

                        {/* title */}
                        <div style={{
                          fontSize: 12, color: "#e2e8f0",
                          lineHeight: 1.4,
                          display: "-webkit-box",
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: "vertical",
                          overflow: "hidden",
                          marginBottom: 3,
                        }}>
                          {paper.title}
                        </div>

                        {/* authors */}
                        {paper.authors.length > 0 && (
                          <div style={{
                            fontSize: 10, color: "#475569",
                            overflow: "hidden", textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}>
                            {paper.authors.slice(0, 4).join(", ")}
                            {paper.authors.length > 4 && ` +${paper.authors.length - 4}`}
                          </div>
                        )}
                      </a>
                    );
                  })}
                  {analysis.key_papers.length === 0 && (
                    <div style={{
                      padding: 30, textAlign: "center",
                      fontFamily: PIXEL_FONT, fontSize: 7,
                      color: "#1e293b", letterSpacing: ".06em",
                    }}>
                      NO KEY PAPERS FOUND
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
