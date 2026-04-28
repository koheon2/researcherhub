import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { InfoCard } from "../components/InfoCard";
import type { Researcher } from "../data/researchers";

const API_BASE   = "http://localhost:8000/api";
const MONO_FONT  = "'Share Tech Mono', monospace";
const PIXEL_FONT = "'Press Start 2P', monospace";
const BAR_COLOR  = "#60a5fa";
const BG         = "#050810";

/* ── Types ── */
interface ConceptHit {
  id: string;
  name: string;
  works_count: number;
  cited_by_count: number;
}

interface YearlyEntry {
  year: number;
  paper_count: number;
}

interface PaperAuthor {
  id: string;
  name: string;
}

interface TopPaper {
  id: string;
  title: string;
  year: number | null;
  citations: number;
  authors: PaperAuthor[];
}

interface TimelineData {
  concept: { id: string; name: string; works_count: number };
  yearly: YearlyEntry[];
  top_papers: TopPaper[];
}

/* ── Helpers ── */
function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

/* ── Main component ── */
export function BenchmarkPage() {
  const [query, setQuery]             = useState("");
  const [concepts, setConcepts]       = useState<ConceptHit[]>([]);
  const [selectedConcept, setSelected] = useState<ConceptHit | null>(null);
  const [timeline, setTimeline]       = useState<TimelineData | null>(null);
  const [loading, setLoading]         = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const [linkedAuthors, setLinkedAuthors] = useState<Record<string, boolean>>({});
  const [matchedIds, setMatchedIds]   = useState<string[]>([]);

  const [selectedResearcher, setSelectedResearcher] = useState<Researcher | null>(null);

  const debounceRef    = useRef<ReturnType<typeof setTimeout> | null>(null);
  const canvasRef      = useRef<HTMLCanvasElement>(null);
  const navigate       = useNavigate();
  const [searchParams] = useSearchParams();

  /* ── Auto-search from URL ?query= param ── */
  const lastAutoQuery = useRef<string | null>(null);
  useEffect(() => {
    const q = searchParams.get("query");
    if (!q || q === lastAutoQuery.current) return;
    lastAutoQuery.current = q;
    setQuery(q);
    fetch(`${API_BASE}/benchmarks/search?q=${encodeURIComponent(q)}`)
      .then(r => r.json())
      .then((hits: ConceptHit[]) => { if (hits.length > 0) selectConcept(hits[0]); })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const clickAuthor = useCallback(async (authorId: string) => {
    if (!authorId) return;
    const shortId = authorId.includes("/") ? authorId.split("/").pop()! : authorId;
    try {
      const res = await fetch(`${API_BASE}/researchers/${shortId}`);
      if (res.ok) setSelectedResearcher(await res.json());
    } catch { /* ignore */ }
  }, []);

  /* ── Search concepts ── */
  const doSearch = useCallback(async (q: string) => {
    if (q.length < 2) { setConcepts([]); return; }
    setSearchLoading(true);
    try {
      const res = await fetch(`${API_BASE}/benchmarks/search?q=${encodeURIComponent(q)}`);
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

  /* ── Select concept -> fetch timeline ── */
  const selectConcept = useCallback(async (c: ConceptHit) => {
    setSelected(c);
    setTimeline(null);
    setLinkedAuthors({});
    setLoading(true);
    try {
      const res = await fetch(
        `${API_BASE}/benchmarks/timeline?concept_id=${encodeURIComponent(c.id)}&years=10`
      );
      if (res.ok) {
        const data: TimelineData = await res.json();
        data.concept.name = c.name; // use the known name
        setTimeline(data);
        // Check author links in background
        checkAuthorLinks(data.top_papers);
      }
    } catch { /* keep empty */ }
    setLoading(false);
  }, []);

  /* ── Check if authors exist in our DB (batch by OpenAlex ID) ── */
  const checkAuthorLinks = async (papers: TopPaper[]) => {
    // Collect all unique OpenAlex author IDs
    const authorMap = new Map<string, string>(); // id -> name
    for (const p of papers) {
      for (const a of p.authors) {
        if (a.id) {
          // OpenAlex author IDs come as URLs like "https://openalex.org/A5031152245"
          // Extract short form
          const shortId = a.id.includes("/") ? a.id.split("/").pop()! : a.id;
          authorMap.set(shortId, a.name);
        }
      }
    }

    if (authorMap.size === 0) {
      setLinkedAuthors({});
      setMatchedIds([]);
      return;
    }

    const idList = [...authorMap.keys()].slice(0, 200);
    try {
      const res = await fetch(
        `${API_BASE}/researchers/by-openalex-ids?ids=${idList.join(",")}`
      );
      if (!res.ok) { setLinkedAuthors({}); setMatchedIds([]); return; }
      const results: { id: string; name: string }[] = await res.json();
      const foundIds = new Set(results.map(r => r.id));

      // Build linked map by name for display
      const linked: Record<string, boolean> = {};
      for (const [shortId, name] of authorMap) {
        if (foundIds.has(shortId)) {
          linked[name] = true;
        }
      }
      setLinkedAuthors(linked);
      setMatchedIds([...foundIds]);
    } catch {
      setLinkedAuthors({});
      setMatchedIds([]);
    }
  };

  /* ── Canvas bar chart ── */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !timeline || timeline.yearly.length === 0) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Size canvas to container
    const parent = canvas.parentElement;
    if (parent) {
      canvas.width = parent.clientWidth;
      canvas.height = parent.clientHeight;
    }
    const W = canvas.width;
    const H = canvas.height;

    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, W, H);

    const years = timeline.yearly;
    const maxCount = Math.max(1, ...years.map(y => y.paper_count));

    const padL = 60;
    const padR = 20;
    const padT = 30;
    const padB = 40;
    const chartW = W - padL - padR;
    const chartH = H - padT - padB;
    const barW = Math.max(8, Math.min(48, (chartW / years.length) * 0.7));
    const gap = chartW / years.length;

    // Y-axis grid lines
    ctx.strokeStyle = "#1e293b";
    ctx.lineWidth = 0.5;
    const ySteps = 5;
    for (let i = 0; i <= ySteps; i++) {
      const y = padT + (chartH / ySteps) * i;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(W - padR, y);
      ctx.stroke();
      // Y label
      const val = maxCount - (maxCount / ySteps) * i;
      ctx.fillStyle = "#334155";
      ctx.font = `10px ${MONO_FONT}`;
      ctx.textAlign = "right";
      ctx.fillText(fmtNum(Math.round(val)), padL - 8, y + 3);
    }

    // Bars
    for (let i = 0; i < years.length; i++) {
      const entry = years[i];
      const ratio = entry.paper_count / maxCount;
      const barH = ratio * chartH;
      const x = padL + gap * i + (gap - barW) / 2;
      const y = padT + chartH - barH;

      // Bar gradient
      const grad = ctx.createLinearGradient(x, y, x, y + barH);
      grad.addColorStop(0, BAR_COLOR);
      grad.addColorStop(1, BAR_COLOR + "66");
      ctx.fillStyle = grad;
      ctx.fillRect(x, y, barW, barH);

      // Glow on top
      ctx.fillStyle = BAR_COLOR + "33";
      ctx.fillRect(x - 2, y - 2, barW + 4, 4);

      // Count label on top of bar
      ctx.fillStyle = "#e2e8f0";
      ctx.font = `9px ${MONO_FONT}`;
      ctx.textAlign = "center";
      if (barH > 20) {
        ctx.fillText(fmtNum(entry.paper_count), x + barW / 2, y - 6);
      }

      // Year label
      ctx.fillStyle = "#475569";
      ctx.font = `9px ${MONO_FONT}`;
      ctx.textAlign = "center";
      ctx.fillText(String(entry.year), x + barW / 2, padT + chartH + 18);
    }

    // X axis line
    ctx.strokeStyle = "#334155";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padL, padT + chartH);
    ctx.lineTo(W - padR, padT + chartH);
    ctx.stroke();

    // Title
    ctx.fillStyle = "#475569";
    ctx.font = `7px ${PIXEL_FONT}`;
    ctx.textAlign = "left";
    ctx.fillText("PAPERS PER YEAR", padL, padT - 12);
  }, [timeline]);

  /* ── Resize observer ── */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const parent = canvas.parentElement;
    if (!parent) return;
    const obs = new ResizeObserver(() => {
      // trigger re-render of chart
      setTimeline(prev => prev ? { ...prev } : prev);
    });
    obs.observe(parent);
    return () => obs.disconnect();
  }, []);


  return (
    <div style={{
      position: "absolute", top: 52, left: 0, right: 0, bottom: 0,
      background: BG, display: "flex", flexDirection: "column",
      fontFamily: MONO_FONT,
    }}>

      {selectedResearcher && (
        <InfoCard
          researcher={selectedResearcher}
          related={[]}
          onClose={() => setSelectedResearcher(null)}
          onSelect={(r) => setSelectedResearcher(r)}
        />
      )}

      {/* Search bar */}
      <div style={{
        padding: "16px 24px",
        borderBottom: "1px solid #1e293b",
        flexShrink: 0,
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
            placeholder="Search benchmarks, datasets, methods..."
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
              onClick={() => { setQuery(""); setConcepts([]); }}
              style={{
                background: "transparent", border: "none",
                color: "#334155", cursor: "pointer",
                padding: "0 14px", fontFamily: MONO_FONT, fontSize: 16,
              }}
            >x</button>
          )}
        </div>
      </div>

      {/* Main content */}
      <div style={{
        flex: 1, display: "flex", overflow: "hidden",
      }}>

        {/* Left panel: search results */}
        <div style={{
          width: 320, flexShrink: 0,
          borderRight: "1px solid #1e293b",
          overflowY: "auto",
          padding: "8px 0",
        }}>
          {concepts.length === 0 && !searchLoading && (
            <div style={{
              padding: "40px 24px",
              fontFamily: PIXEL_FONT, fontSize: 7,
              color: "#1e293b", textAlign: "center",
              lineHeight: 2.2, letterSpacing: ".06em",
            }}>
              {query.length >= 2
                ? "NO RESULTS FOUND"
                : "SEARCH FOR A CONCEPT\nTO VIEW ITS TIMELINE"}
            </div>
          )}
          {concepts.map((c) => {
            const isActive = selectedConcept?.id === c.id;
            return (
              <div
                key={c.id}
                onClick={() => selectConcept(c)}
                style={{
                  padding: "12px 20px",
                  cursor: "pointer",
                  background: isActive ? "#0d1117" : "transparent",
                  borderLeft: isActive ? `2px solid ${BAR_COLOR}` : "2px solid transparent",
                  borderBottom: "1px solid #0a0f1a",
                  transition: "background 0.1s",
                }}
                onMouseEnter={(e) => {
                  if (!isActive) e.currentTarget.style.background = "#0a0d14";
                }}
                onMouseLeave={(e) => {
                  if (!isActive) e.currentTarget.style.background = "transparent";
                }}
              >
                <div style={{
                  fontSize: 13, color: isActive ? BAR_COLOR : "#e2e8f0",
                  marginBottom: 4,
                }}>
                  {c.name}
                </div>
                <div style={{ fontSize: 10, color: "#475569" }}>
                  {fmtNum(c.works_count)} works &middot; {fmtNum(c.cited_by_count)} citations
                </div>
              </div>
            );
          })}
        </div>

        {/* Right panel: timeline + papers */}
        <div style={{
          flex: 1, overflowY: "auto",
          display: "flex", flexDirection: "column",
        }}>
          {!selectedConcept && (
            <div style={{
              flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
              fontFamily: PIXEL_FONT, fontSize: 8, color: "#1e293b",
              letterSpacing: ".08em",
            }}>
              SELECT A CONCEPT FROM THE LEFT
            </div>
          )}

          {selectedConcept && loading && (
            <div style={{
              flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
              fontFamily: PIXEL_FONT, fontSize: 9, color: BAR_COLOR,
              letterSpacing: ".1em",
            }}>
              LOADING TIMELINE...
            </div>
          )}

          {selectedConcept && !loading && timeline && (
            <>
              {/* Concept header */}
              <div style={{
                padding: "20px 28px 12px",
                borderBottom: "1px solid #1e293b",
                flexShrink: 0,
              }}>
                <div style={{
                  fontFamily: PIXEL_FONT, fontSize: 10, color: BAR_COLOR,
                  marginBottom: 6, letterSpacing: ".04em",
                }}>
                  {selectedConcept.name.toUpperCase()}
                </div>
                <div style={{
                  display: "flex", gap: 24, fontSize: 11, color: "#475569",
                }}>
                  <span>{fmtNum(selectedConcept.works_count)} total works</span>
                  <span>{fmtNum(selectedConcept.cited_by_count)} total citations</span>
                  <span>{timeline.yearly.length} years</span>
                </div>
              </div>

              {/* Navigation buttons */}
              <div style={{
                padding: "0 28px 8px",
                display: "flex", gap: 10,
                flexShrink: 0,
              }}>
                <button
                  disabled={matchedIds.length === 0}
                  onClick={() => {
                    if (matchedIds.length > 0) {
                      navigate(`/?highlight=${matchedIds.join(",")}`);
                    }
                  }}
                  style={{
                    padding: "8px 16px",
                    fontFamily: PIXEL_FONT, fontSize: 8,
                    letterSpacing: ".04em",
                    background: matchedIds.length > 0 ? "#0d1117" : "#080b12",
                    border: `1px solid ${matchedIds.length > 0 ? "#1e4976" : "#0f1520"}`,
                    color: matchedIds.length > 0 ? "#60a5fa" : "#1e293b",
                    cursor: matchedIds.length > 0 ? "pointer" : "default",
                    opacity: matchedIds.length > 0 ? 1 : 0.5,
                    transition: "all 0.15s",
                  }}
                >
                  GLOBE ({matchedIds.length})
                </button>
                {matchedIds.length > 0 && (
                  <span style={{
                    fontFamily: MONO_FONT, fontSize: 10, color: "#334155",
                    alignSelf: "center",
                  }}>
                    {matchedIds.length} author{matchedIds.length !== 1 ? "s" : ""} in DB
                  </span>
                )}
              </div>

              {/* Chart */}
              <div style={{
                height: 260, flexShrink: 0,
                padding: "12px 20px",
              }}>
                <div style={{ width: "100%", height: "100%", position: "relative" }}>
                  <canvas
                    ref={canvasRef}
                    style={{ width: "100%", height: "100%", display: "block" }}
                  />
                </div>
              </div>

              {/* Top papers header */}
              <div style={{
                padding: "12px 28px 8px",
                borderTop: "1px solid #1e293b",
                flexShrink: 0,
              }}>
                <div style={{
                  fontFamily: PIXEL_FONT, fontSize: 7, color: "#334155",
                  letterSpacing: ".08em",
                }}>
                  TOP PAPERS ({timeline.top_papers.length})
                </div>
              </div>

              {/* Papers list */}
              <div style={{
                flex: 1, overflowY: "auto",
                padding: "0 20px 20px",
              }}>
                {timeline.top_papers.map((paper, idx) => (
                  <div key={paper.id || idx} style={{
                    padding: "12px 14px",
                    marginBottom: 4,
                    background: "#0a0f1a",
                    border: "1px solid #1e293b",
                  }}>
                    <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                      <span style={{
                        fontFamily: MONO_FONT, fontSize: 9, color: "#334155",
                        width: 22, flexShrink: 0, paddingTop: 2,
                      }}>
                        {idx + 1}.
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{
                          fontSize: 12, color: "#e2e8f0",
                          marginBottom: 4, lineHeight: 1.4,
                        }}>
                          {paper.title}
                        </div>
                        <div style={{
                          display: "flex", gap: 12, fontSize: 10, color: "#475569",
                          marginBottom: 4, flexWrap: "wrap",
                        }}>
                          {paper.year && <span>{paper.year}</span>}
                          <span style={{ color: BAR_COLOR }}>
                            {fmtNum(paper.citations)} citations
                          </span>
                        </div>
                        <div style={{
                          fontSize: 10, color: "#475569",
                          display: "flex", gap: 4, flexWrap: "wrap",
                        }}>
                          {paper.authors.map((a, ai) => (
                            <span
                              key={a.id || ai}
                              onClick={() => linkedAuthors[a.name] && clickAuthor(a.id)}
                              style={{
                                color: linkedAuthors[a.name] ? BAR_COLOR : "#475569",
                                cursor: linkedAuthors[a.name] ? "pointer" : "default",
                                textDecoration: linkedAuthors[a.name] ? "underline" : "none",
                              }}
                            >
                              {a.name}
                              {linkedAuthors[a.name] && (
                                <span style={{ marginLeft: 2, fontSize: 9 }}>🔗</span>
                              )}
                              {ai < paper.authors.length - 1 && ",\u00A0"}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
                {timeline.top_papers.length === 0 && (
                  <div style={{
                    padding: "30px", textAlign: "center",
                    fontFamily: PIXEL_FONT, fontSize: 7,
                    color: "#1e293b", letterSpacing: ".06em",
                  }}>
                    NO PAPERS FOUND
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
