import { useState, useEffect, useCallback, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";

const API_BASE = "http://localhost:8000/api";
const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT  = "'Share Tech Mono', monospace";

interface TopicOption {
  facet_type: string;
  topic: string;
  paper_count: number;
  total_citations: number;
  min_year: number | null;
  max_year: number | null;
}

interface Author {
  author_id: string;
  name: string | null;
  institution: string | null;
  position: number;
}

interface Paper {
  id: string;
  title: string | null;
  year: number;
  citations: number;
  fwci: number | null;
  doi: string | null;
  abstract: string | null;
  open_access: boolean;
  type: string | null;
  authors: Author[];
}

interface YearGroup {
  year: number;
  papers: Paper[];
}

interface TimelineResponse {
  topic: string;
  query?: string;
  matched_axes?: string[];
  per_year: number;
  min_fwci: number;
  papers: Paper[];
  by_year: YearGroup[];
}

interface RepresentativeResponse {
  topic: string | null;
  query: string | null;
  matched_axes: string[];
  match_kind: string;
  sort: string;
  limit: number;
  papers: Paper[];
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return n.toString();
}

function axisLabel(axis?: string): string {
  if (axis === "aboutness") return "TOPIC";
  if (axis === "method") return "METHOD";
  if (axis === "task") return "TASK";
  if (axis === "application") return "APP";
  if (axis === "specific") return "SPECIFIC";
  return "TOPIC";
}

function axisColor(axis?: string): string {
  if (axis === "method") return "#fbbf24";
  if (axis === "application") return "#34d399";
  if (axis === "specific") return "#00d4ff";
  return "#64748b";
}

export function PaperTimelinePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTopic = searchParams.get("topic") || "";
  const initialAxis = searchParams.get("axis") || "";

  const [topicQuery, setTopicQuery] = useState(initialTopic);
  const [topicSuggestions, setTopicSuggestions] = useState<TopicOption[]>([]);
  const [selectedTopic, setSelectedTopic] = useState<string>(initialTopic);
  const [selectedAxis, setSelectedAxis] = useState<string>(initialAxis);
  const [perYear, setPerYear] = useState(3);
  const [minFwci, setMinFwci] = useState(2.0);
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [representative, setRepresentative] = useState<RepresentativeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [representativeLoading, setRepresentativeLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const topicCacheRef = useRef<Map<string, TopicOption[]>>(new Map());
  const topicAbortRef = useRef<AbortController | null>(null);
  const topicRequestRef = useRef(0);

  const fetchTopics = useCallback(async (q: string) => {
    const query = q.trim();
    const cacheKey = query.toLowerCase();
    const cached = topicCacheRef.current.get(cacheKey);
    if (cached) {
      setTopicSuggestions(cached);
      return;
    }

    topicAbortRef.current?.abort();
    const controller = new AbortController();
    topicAbortRef.current = controller;
    const requestId = ++topicRequestRef.current;

    try {
      const url = query
        ? `${API_BASE}/papers/topics?q=${encodeURIComponent(query)}&limit=30`
        : `${API_BASE}/papers/topics?limit=30`;
      const res = await fetch(url, { signal: controller.signal });
      if (!res.ok) throw new Error(`Topic search failed: ${res.status}`);
      const json: TopicOption[] = await res.json();
      topicCacheRef.current.set(cacheKey, json);
      if (requestId === topicRequestRef.current) {
        setTopicSuggestions(json);
      }
    } catch (e) {
      const error = e as Error;
      if (error.name === "AbortError") return;
      if (requestId === topicRequestRef.current) {
        setTopicSuggestions([]);
      }
    }
  }, []);

  useEffect(() => {
    fetchTopics("");
  }, [fetchTopics]);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      topicAbortRef.current?.abort();
    };
  }, []);

  const handleTopicInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setTopicQuery(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchTopics(v), 150);
  };

  const fetchTimeline = useCallback(async (topic: string, axis: string) => {
    if (!topic) return;
    setLoading(true);
    try {
      const axisParam = axis ? `&axis=${encodeURIComponent(axis)}` : "";
      const url = `${API_BASE}/papers/timeline?topic=${encodeURIComponent(topic)}${axisParam}&per_year=${perYear}&min_fwci=${minFwci}&year_from=2017`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`Timeline fetch failed: ${res.status}`);
      const json: TimelineResponse = await res.json();
      setData(json);
    } catch (e) {
      console.error("Failed to fetch timeline:", e);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [perYear, minFwci]);

  const fetchRepresentative = useCallback(async (topic: string, axis: string) => {
    setRepresentativeLoading(true);
    try {
      const params = new URLSearchParams({
        limit: "16",
        sort: "impact",
        year_from: "2017",
      });
      if (topic) params.set("topic", topic);
      if (axis) params.set("axis", axis);
      const res = await fetch(`${API_BASE}/papers/representative?${params}`);
      if (!res.ok) throw new Error(`Representative papers failed: ${res.status}`);
      const json: RepresentativeResponse = await res.json();
      setRepresentative(json);
    } catch (e) {
      console.error("Failed to fetch representative papers:", e);
      setRepresentative(null);
    } finally {
      setRepresentativeLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedTopic) {
      fetchTimeline(selectedTopic, selectedAxis);
      fetchRepresentative(selectedTopic, selectedAxis);
    } else {
      setData(null);
      fetchRepresentative("", "");
    }
  }, [selectedTopic, selectedAxis, fetchTimeline, fetchRepresentative]);

  const handlePickTopic = (option: TopicOption) => {
    setSelectedTopic(option.topic);
    setSelectedAxis(option.facet_type);
    setTopicQuery(option.topic);
    setSearchParams({ topic: option.topic, axis: option.facet_type });
  };

  const handleClearTopic = () => {
    setSelectedTopic("");
    setSelectedAxis("");
    setTopicQuery("");
    setData(null);
    setSearchParams({});
    fetchTopics("");
    fetchRepresentative("", "");
  };

  return (
    <div style={{
      position: "absolute", top: 52, left: 0, right: 0, bottom: 0,
      overflowY: "auto", background: "#000005",
      padding: "32px 48px 80px",
    }}>
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>

        {/* Header */}
        <div style={{
          fontFamily: PIXEL_FONT, fontSize: 14, color: "#f8fafc",
          letterSpacing: "0.06em", marginBottom: 6,
          textShadow: "2px 2px 0 #00d4ff55",
        }}>
          PAPERS <span style={{ color: "#00d4ff" }}>EXPLORER</span>
        </div>
        <div style={{
          fontFamily: MONO_FONT, fontSize: 12, color: "#475569",
          marginBottom: 28, letterSpacing: "0.04em",
        }}>
          Representative papers, topic timelines, and citation-backed paper details.
        </div>

        {/* Controls */}
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 28 }}>
          {/* Topic selector */}
          <div style={{ position: "relative", minWidth: 360, flex: 1 }}>
            <label style={{
              display: "block", fontFamily: PIXEL_FONT, fontSize: 7,
              color: "#64748b", marginBottom: 6, letterSpacing: "0.08em",
            }}>TOPIC</label>
            <input
              value={topicQuery}
              onChange={handleTopicInput}
              placeholder="Search topic..."
              style={{
                width: "100%",
                background: "#0a0f1a",
                border: "1px solid #1e293b",
                padding: "10px 12px",
                color: "#e2e8f0",
                fontFamily: MONO_FONT, fontSize: 13,
                outline: "none",
                letterSpacing: "0.02em",
              }}
            />
          </div>

          {/* Per-year */}
          <div>
            <label style={{
              display: "block", fontFamily: PIXEL_FONT, fontSize: 7,
              color: "#64748b", marginBottom: 6, letterSpacing: "0.08em",
            }}>PER YEAR</label>
            <select
              value={perYear}
              onChange={(e) => setPerYear(Number(e.target.value))}
              style={{
                background: "#0a0f1a", border: "1px solid #1e293b",
                padding: "10px 12px", color: "#e2e8f0",
                fontFamily: MONO_FONT, fontSize: 13, outline: "none",
              }}
            >
              {[1, 2, 3, 5, 10].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>

          {/* Min FWCI */}
          <div>
            <label style={{
              display: "block", fontFamily: PIXEL_FONT, fontSize: 7,
              color: "#64748b", marginBottom: 6, letterSpacing: "0.08em",
            }}>MIN FWCI</label>
            <select
              value={minFwci}
              onChange={(e) => setMinFwci(Number(e.target.value))}
              style={{
                background: "#0a0f1a", border: "1px solid #1e293b",
                padding: "10px 12px", color: "#e2e8f0",
                fontFamily: MONO_FONT, fontSize: 13, outline: "none",
              }}
            >
              {[0, 1, 2, 3, 5, 10].map(n => <option key={n} value={n}>≥ {n}</option>)}
            </select>
          </div>
        </div>

        {/* Topic picker — always visible when no topic chosen */}
        {!selectedTopic && (
          <div>
            <div style={{
              fontFamily: PIXEL_FONT, fontSize: 7, color: "#64748b",
              marginBottom: 12, letterSpacing: "0.08em",
            }}>
              {topicQuery ? "MATCHING TOPICS" : "TOP TOPICS BY PAPER COUNT"}
            </div>
            {topicSuggestions.length === 0 ? (
              <div style={{ fontFamily: MONO_FONT, fontSize: 12, color: "#475569" }}>
                No topics match.
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 8 }}>
                {topicSuggestions.map((t) => (
                  <div
                    key={`${t.facet_type}:${t.topic}`}
                    onClick={() => handlePickTopic(t)}
                    style={{
                      textAlign: "left",
                      background: "#06080f",
                      border: "1px solid #1e293b",
                      padding: "12px 14px",
                      color: "#e2e8f0",
                      cursor: "pointer",
                      transition: "border-color 0.12s, background 0.12s",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.borderColor = "#00d4ff44";
                      e.currentTarget.style.background = "#0a0f1a";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.borderColor = "#1e293b";
                      e.currentTarget.style.background = "#06080f";
                    }}
                  >
                    <div style={{ fontFamily: MONO_FONT, fontSize: 13, color: "#e2e8f0", marginBottom: 4 }}>
                      {t.topic}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontFamily: MONO_FONT, fontSize: 10, color: "#475569" }}>
                      <span style={{
                        color: axisColor(t.facet_type),
                        border: "1px solid #1e293b",
                        padding: "1px 5px",
                      }}>
                        {axisLabel(t.facet_type)}
                      </span>
                      <span>
                        {fmtNum(t.paper_count)} papers
                        {t.min_year && t.max_year && ` · ${t.min_year}-${t.max_year}`}
                      </span>
                    </div>
                    <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handlePickTopic(t);
                        }}
                        style={smallActionStyle}
                      >
                        TIMELINE
                      </button>
                      <Link
                        onClick={(e) => e.stopPropagation()}
                        to={`/lineage?topic=${encodeURIComponent(t.topic)}&axis=${encodeURIComponent(t.facet_type)}`}
                        style={{
                          ...smallActionStyle,
                          color: "#34d399",
                          display: "inline-flex",
                          alignItems: "center",
                          textDecoration: "none",
                        }}
                      >
                        LINEAGE
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {selectedTopic && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 20 }}>
            <button
              onClick={handleClearTopic}
              style={{
                background: "transparent",
                border: "1px solid #1e293b",
                color: "#64748b",
                padding: "6px 12px",
                fontFamily: PIXEL_FONT, fontSize: 7,
                cursor: "pointer",
                letterSpacing: "0.08em",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.color = "#00d4ff")}
              onMouseLeave={(e) => (e.currentTarget.style.color = "#64748b")}
            >
              ← CHANGE TOPIC
            </button>
            <span style={{
              fontFamily: PIXEL_FONT,
              fontSize: 7,
              color: axisColor(data?.matched_axes?.[0] || selectedAxis),
              border: "1px solid #1e293b",
              padding: "6px 8px",
              letterSpacing: "0.08em",
            }}>
              {axisLabel(data?.matched_axes?.[0] || selectedAxis)}
            </span>
            <span style={{ fontFamily: MONO_FONT, fontSize: 13, color: "#94a3b8" }}>
              {data?.topic || selectedTopic}
            </span>
            <Link
              to={`/lineage?topic=${encodeURIComponent(selectedTopic)}${selectedAxis ? `&axis=${encodeURIComponent(selectedAxis)}` : ""}`}
              style={{
                color: "#34d399",
                border: "1px solid #1e293b",
                padding: "6px 10px",
                fontFamily: PIXEL_FONT,
                fontSize: 7,
                textDecoration: "none",
                letterSpacing: "0.08em",
              }}
            >
              TOPIC LINEAGE
            </Link>
          </div>
        )}

        {loading && (
          <div style={{
            fontFamily: PIXEL_FONT, fontSize: 9, color: "#00d4ff",
            padding: "40px 0", textAlign: "center", letterSpacing: "0.1em",
          }}>
            LOADING···
          </div>
        )}

        {!loading && (
          <section style={{ marginBottom: 28 }}>
            <div style={{
              display: "flex", alignItems: "baseline", justifyContent: "space-between",
              gap: 16, marginBottom: 10,
            }}>
              <div style={{ fontFamily: PIXEL_FONT, fontSize: 8, color: "#64748b", letterSpacing: "0.08em" }}>
                {selectedTopic ? "REPRESENTATIVE PAPERS" : "GLOBAL REPRESENTATIVE PAPERS"}
              </div>
              {representative && (
                <div style={{ fontFamily: MONO_FONT, fontSize: 11, color: "#475569" }}>
                  {representative.match_kind} · {representative.sort}
                </div>
              )}
            </div>

            {representativeLoading && (
              <div style={{ fontFamily: MONO_FONT, fontSize: 12, color: "#475569", padding: "12px 0" }}>
                Loading representative papers...
              </div>
            )}

            {!representativeLoading && representative && representative.papers.length > 0 && (
              <div style={{ border: "1px solid #1e293b" }}>
                {representative.papers.map((paper, idx) => (
                  <Link
                    key={paper.id}
                    to={`/papers/${encodeURIComponent(paper.id)}`}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "36px minmax(0, 1fr) 74px 88px 72px",
                      gap: 12,
                      alignItems: "center",
                      padding: "10px 12px",
                      borderBottom: idx === representative.papers.length - 1 ? "none" : "1px solid #0f172a",
                      color: "inherit",
                      textDecoration: "none",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "#06080f")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                  >
                    <div style={{ fontFamily: MONO_FONT, fontSize: 12, color: "#475569" }}>
                      {idx + 1}
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div style={{
                        fontFamily: MONO_FONT,
                        fontSize: 13,
                        lineHeight: 1.35,
                        color: "#e2e8f0",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}>
                        {paper.title || "(untitled)"}
                      </div>
                      {paper.authors.length > 0 && (
                        <div style={{
                          fontFamily: MONO_FONT,
                          fontSize: 10,
                          color: "#64748b",
                          marginTop: 3,
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}>
                          {paper.authors.map(a => a.name).filter(Boolean).join(" · ")}
                        </div>
                      )}
                    </div>
                    <div style={{ fontFamily: MONO_FONT, fontSize: 12, color: "#94a3b8", textAlign: "right" }}>
                      {paper.year}
                    </div>
                    <div style={{ fontFamily: MONO_FONT, fontSize: 12, color: "#fbbf24", textAlign: "right" }}>
                      {fmtNum(paper.citations)} cit
                    </div>
                    <div style={{ fontFamily: MONO_FONT, fontSize: 12, color: "#34d399", textAlign: "right" }}>
                      {paper.fwci != null ? paper.fwci.toFixed(1) : "—"}
                    </div>
                  </Link>
                ))}
              </div>
            )}

            {!representativeLoading && representative && representative.papers.length === 0 && (
              <div style={{ fontFamily: MONO_FONT, fontSize: 12, color: "#475569" }}>
                No representative papers found.
              </div>
            )}
          </section>
        )}

        {/* Timeline */}
        {!loading && data && data.by_year.length === 0 && (
          <div style={{
            fontFamily: MONO_FONT, fontSize: 13, color: "#475569",
            padding: "40px 0", textAlign: "center",
          }}>
            No papers found for this topic with the current filters.
          </div>
        )}

        {!loading && data && data.by_year.length > 0 && (
          <div style={{ position: "relative", paddingLeft: 32 }}>
            {/* Vertical line */}
            <div style={{
              position: "absolute", left: 8, top: 8, bottom: 8,
              width: 2, background: "linear-gradient(to bottom, #00d4ff44, #1e293b)",
            }} />

            {data.by_year.map((group) => (
              <div key={group.year} style={{ position: "relative", marginBottom: 32 }}>
                {/* Dot */}
                <div style={{
                  position: "absolute", left: -28, top: 4,
                  width: 14, height: 14,
                  background: "#00d4ff",
                  border: "2px solid #06080f",
                  boxShadow: "0 0 10px #00d4ff88",
                }} />

                {/* Year label */}
                <div style={{
                  fontFamily: PIXEL_FONT, fontSize: 14, color: "#00d4ff",
                  marginBottom: 12, letterSpacing: "0.06em",
                }}>
                  {group.year}
                </div>

                {/* Papers */}
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {group.papers.map((p) => (
                    <div key={p.id} style={{
                      background: "#06080f",
                      border: "1px solid #1e293b",
                      padding: "14px 16px",
                    }}>
                      <div style={{
                        fontFamily: MONO_FONT, fontSize: 14, color: "#e2e8f0",
                        lineHeight: 1.5, marginBottom: 8,
                      }}>
                        <Link
                          to={`/papers/${encodeURIComponent(p.id)}`}
                          style={{ color: "#e2e8f0", textDecoration: "none" }}
                          onMouseEnter={(e) => (e.currentTarget.style.color = "#00d4ff")}
                          onMouseLeave={(e) => (e.currentTarget.style.color = "#e2e8f0")}
                        >
                          {p.title || "(untitled)"}
                        </Link>
                      </div>

                      {/* Authors */}
                      {p.authors.length > 0 && (
                        <div style={{
                          fontFamily: MONO_FONT, fontSize: 11, color: "#64748b",
                          marginBottom: 8,
                        }}>
                          {p.authors.map(a => a.name).filter(Boolean).join(" · ")}
                          {p.authors[0]?.institution && (
                            <span style={{ color: "#475569" }}> — {p.authors[0].institution}</span>
                          )}
                        </div>
                      )}

                      {/* Metrics */}
                      <div style={{ display: "flex", gap: 16, fontFamily: MONO_FONT, fontSize: 11 }}>
                        <span style={{ color: "#fbbf24" }}>
                          {fmtNum(p.citations)} cit
                        </span>
                        {p.fwci != null && (
                          <span style={{ color: p.fwci >= 5 ? "#34d399" : "#94a3b8" }}>
                            FWCI {p.fwci.toFixed(2)}
                          </span>
                        )}
                        {p.open_access && (
                          <span style={{ color: "#34d399" }}>OA</span>
                        )}
                        {p.type && (
                          <span style={{ color: "#475569" }}>{p.type}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const smallActionStyle: React.CSSProperties = {
  background: "transparent",
  border: "1px solid #1e293b",
  color: "#00d4ff",
  padding: "5px 8px",
  fontFamily: "'Press Start 2P', monospace",
  fontSize: 6,
  cursor: "pointer",
  letterSpacing: "0.06em",
};
