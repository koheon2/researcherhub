import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

const API_BASE = "http://localhost:8000/api";
const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT = "'Share Tech Mono', monospace";

interface PaperAuthor {
  author_id: string;
  name: string | null;
  institution: string | null;
  country?: string | null;
  position: number;
}

interface PaperFacet {
  facet_type: string;
  facet_value: string;
  source: string;
  confidence: number;
  rank: number;
}

interface QualityFlag {
  flag_type: string;
  severity: string;
  reason: string;
  source: string;
}

interface Affiliation {
  author_id: string;
  author_name: string | null;
  institution_name: string;
  canonical_institution_name: string;
  institution_ror_id: string | null;
  institution_match_confidence: number | null;
  country_code: string;
  position: number;
  confidence: number;
}

interface PaperDetail {
  id: string;
  title: string | null;
  year: number | null;
  citations: number;
  fwci: number | null;
  doi: string | null;
  doi_url: string | null;
  openalex_url: string | null;
  abstract: string | null;
  abstract_available: boolean;
  open_access: boolean;
  type: string | null;
  subfield: string | null;
  topic: string | null;
  authors: PaperAuthor[];
  facets: PaperFacet[];
  quality_flags: QualityFlag[];
  affiliations: Affiliation[];
  quality_filtered: boolean;
  quality_policy: string;
}

interface PaperReferenceSummary {
  paper_id: string;
  total_references: number;
  internal_references: number;
  external_references: number;
  references: Array<Partial<PaperDetail> & {
    target_openalex_id: string;
    internal: boolean;
    authors?: PaperAuthor[];
  }>;
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return n.toString();
}

function axisLabel(axis: string): string {
  if (axis === "aboutness") return "Field";
  if (axis === "method") return "Method";
  if (axis === "task") return "Task";
  if (axis === "application") return "Application";
  return axis;
}

export function PaperDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [paper, setPaper] = useState<PaperDetail | null>(null);
  const [references, setReferences] = useState<PaperReferenceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setReferences(null);

    Promise.all([
      fetch(`${API_BASE}/papers/${encodeURIComponent(id)}`),
      fetch(`${API_BASE}/papers/${encodeURIComponent(id)}/references?limit=20`),
    ])
      .then(([paperRes, refsRes]) => {
        if (!paperRes.ok) throw new Error(`Paper fetch failed: ${paperRes.status}`);
        if (!refsRes.ok) throw new Error(`References fetch failed: ${refsRes.status}`);
        return Promise.all([paperRes.json(), refsRes.json()]);
      })
      .then(([paperJson, refsJson]: [PaperDetail, PaperReferenceSummary]) => {
        if (!cancelled) {
          setPaper(paperJson);
          setReferences(refsJson);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  const facetsByType = (paper?.facets ?? []).reduce<Record<string, PaperFacet[]>>((acc, facet) => {
    if (!acc[facet.facet_type]) acc[facet.facet_type] = [];
    acc[facet.facet_type].push(facet);
    return acc;
  }, {});

  return (
    <div
      style={{
        position: "absolute",
        top: 52,
        left: 0,
        right: 0,
        bottom: 0,
        overflowY: "auto",
        background: "#000005",
        padding: "28px 48px 80px",
      }}
    >
      <div style={{ maxWidth: 1060, margin: "0 auto" }}>
        <button
          onClick={() => navigate(-1)}
          style={{
            background: "transparent",
            border: "1px solid #1e293b",
            color: "#64748b",
            padding: "7px 11px",
            fontFamily: PIXEL_FONT,
            fontSize: 7,
            cursor: "pointer",
            marginBottom: 20,
          }}
        >
          BACK
        </button>

        {loading && (
          <div style={{ fontFamily: PIXEL_FONT, fontSize: 9, color: "#00d4ff", padding: "40px 0" }}>
            LOADING PAPER...
          </div>
        )}

        {!loading && error && (
          <div style={{ fontFamily: MONO_FONT, color: "#f87171", fontSize: 13 }}>
            {error}
          </div>
        )}

        {!loading && paper && (
          <>
            <div style={{ borderBottom: "1px solid #1e293b", paddingBottom: 22, marginBottom: 22 }}>
              <div
                style={{
                  fontFamily: MONO_FONT,
                  color: "#e2e8f0",
                  fontSize: 24,
                  lineHeight: 1.35,
                  marginBottom: 12,
                }}
              >
                {paper.title || "(untitled)"}
              </div>

              <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontFamily: MONO_FONT, fontSize: 12 }}>
                {paper.year && <span style={{ color: "#94a3b8" }}>{paper.year}</span>}
                <span style={{ color: "#fbbf24" }}>{fmtNum(paper.citations)} citations</span>
                {paper.fwci != null && <span style={{ color: "#34d399" }}>FWCI {paper.fwci.toFixed(2)}</span>}
                {paper.type && <span style={{ color: "#64748b" }}>{paper.type}</span>}
                {paper.open_access && <span style={{ color: "#34d399" }}>open access</span>}
                {!paper.abstract_available && <span style={{ color: "#f59e0b" }}>no abstract</span>}
              </div>

              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
                {paper.doi_url && (
                  <a
                    href={paper.doi_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      color: "#00d4ff",
                      border: "1px solid #1e293b",
                      padding: "6px 9px",
                      fontFamily: MONO_FONT,
                      fontSize: 12,
                      textDecoration: "none",
                    }}
                  >
                    DOI
                  </a>
                )}
                {paper.openalex_url && (
                  <a
                    href={paper.openalex_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      color: "#94a3b8",
                      border: "1px solid #1e293b",
                      padding: "6px 9px",
                      fontFamily: MONO_FONT,
                      fontSize: 12,
                      textDecoration: "none",
                    }}
                  >
                    OpenAlex
                  </a>
                )}
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 320px", gap: 24 }}>
              <main>
                <section style={{ marginBottom: 26 }}>
                  <div style={{ fontFamily: PIXEL_FONT, fontSize: 8, color: "#64748b", marginBottom: 10 }}>
                    ABSTRACT
                  </div>
                  <div style={{ fontFamily: MONO_FONT, fontSize: 14, lineHeight: 1.7, color: "#cbd5e1" }}>
                    {paper.abstract || "No abstract is available in the local dataset."}
                  </div>
                </section>

                <section style={{ marginBottom: 26 }}>
                  <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
                    <div style={{ fontFamily: PIXEL_FONT, fontSize: 8, color: "#64748b" }}>
                      REFERENCED PAPERS
                    </div>
                    {references && (
                      <div style={{ fontFamily: MONO_FONT, fontSize: 11, color: "#64748b" }}>
                        {references.internal_references} local · {references.external_references} external
                      </div>
                    )}
                  </div>
                  <div style={{ border: "1px solid #1e293b" }}>
                    {!references || references.references.length === 0 ? (
                      <div style={{ padding: 12, fontFamily: MONO_FONT, color: "#475569", fontSize: 12 }}>
                        No OpenAlex references have been enriched for this paper yet.
                      </div>
                    ) : (
                      references.references.map((ref, idx) => (
                        ref.internal && ref.id ? (
                          <Link
                            key={`${ref.target_openalex_id}:${idx}`}
                            to={`/papers/${encodeURIComponent(ref.id)}`}
                            style={{
                              display: "grid",
                              gridTemplateColumns: "minmax(0, 1fr) 64px 82px",
                              gap: 12,
                              padding: "10px 12px",
                              borderBottom: "1px solid #0f172a",
                              color: "inherit",
                              textDecoration: "none",
                              fontFamily: MONO_FONT,
                              fontSize: 12,
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.background = "#06080f")}
                            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                          >
                            <div style={{ minWidth: 0 }}>
                              <div style={{ color: "#e2e8f0", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                {ref.title || ref.id}
                              </div>
                              {ref.authors && ref.authors.length > 0 && (
                                <div style={{ color: "#64748b", marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                  {ref.authors.map((a) => a.name).filter(Boolean).join(" · ")}
                                </div>
                              )}
                            </div>
                            <div style={{ color: "#94a3b8", textAlign: "right" }}>{ref.year || ""}</div>
                            <div style={{ color: "#fbbf24", textAlign: "right" }}>
                              {typeof ref.citations === "number" ? `${fmtNum(ref.citations)} cit` : ""}
                            </div>
                          </Link>
                        ) : (
                          <a
                            key={`${ref.target_openalex_id}:${idx}`}
                            href={`https://openalex.org/${ref.target_openalex_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                              display: "block",
                              padding: "10px 12px",
                              borderBottom: "1px solid #0f172a",
                              color: "#64748b",
                              textDecoration: "none",
                              fontFamily: MONO_FONT,
                              fontSize: 12,
                            }}
                          >
                            {ref.target_openalex_id} · external OpenAlex work
                          </a>
                        )
                      ))
                    )}
                  </div>
                </section>

                <section style={{ marginBottom: 26 }}>
                  <div style={{ fontFamily: PIXEL_FONT, fontSize: 8, color: "#64748b", marginBottom: 10 }}>
                    AUTHORS
                  </div>
                  <div style={{ border: "1px solid #1e293b" }}>
                    {paper.authors.length === 0 ? (
                      <div style={{ padding: 12, fontFamily: MONO_FONT, color: "#475569", fontSize: 12 }}>
                        No authors available.
                      </div>
                    ) : (
                      paper.authors.map((author) => (
                        <div
                          key={`${author.author_id}:${author.position}`}
                          style={{
                            display: "grid",
                            gridTemplateColumns: "44px minmax(0, 1fr) 60px",
                            gap: 12,
                            padding: "10px 12px",
                            borderBottom: "1px solid #0f172a",
                            fontFamily: MONO_FONT,
                            fontSize: 12,
                          }}
                        >
                          <span style={{ color: "#475569" }}>#{author.position + 1}</span>
                          <span style={{ color: "#e2e8f0" }}>
                            {author.name || author.author_id}
                            {author.institution && (
                              <span style={{ color: "#64748b" }}> · {author.institution}</span>
                            )}
                          </span>
                          <span style={{ color: "#64748b", textAlign: "right" }}>{author.country || ""}</span>
                        </div>
                      ))
                    )}
                  </div>
                </section>

                <section>
                  <div style={{ fontFamily: PIXEL_FONT, fontSize: 8, color: "#64748b", marginBottom: 10 }}>
                    PUBLICATION-TIME AFFILIATIONS
                  </div>
                  <div style={{ border: "1px solid #1e293b" }}>
                    {paper.affiliations.length === 0 ? (
                      <div style={{ padding: 12, fontFamily: MONO_FONT, color: "#475569", fontSize: 12 }}>
                        No affiliation rows available.
                      </div>
                    ) : (
                      paper.affiliations.map((aff, idx) => (
                        <div
                          key={`${aff.author_id}:${aff.institution_name}:${idx}`}
                          style={{
                            padding: "10px 12px",
                            borderBottom: "1px solid #0f172a",
                            fontFamily: MONO_FONT,
                            fontSize: 12,
                          }}
                        >
                          <div style={{ color: "#e2e8f0" }}>
                            {aff.author_name || aff.author_id}
                            <span style={{ color: "#64748b" }}> · {aff.country_code}</span>
                          </div>
                          <div style={{ color: "#94a3b8", marginTop: 3 }}>
                            {aff.canonical_institution_name || aff.institution_name}
                          </div>
                          {aff.institution_ror_id && (
                            <div style={{ color: "#475569", marginTop: 3 }}>
                              ROR {aff.institution_ror_id}
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </section>
              </main>

              <aside>
                <section style={{ border: "1px solid #1e293b", padding: 14, marginBottom: 14 }}>
                  <div style={{ fontFamily: PIXEL_FONT, fontSize: 8, color: "#64748b", marginBottom: 10 }}>
                    CLASSIFICATION
                  </div>
                  {Object.keys(facetsByType).length === 0 ? (
                    <div style={{ fontFamily: MONO_FONT, color: "#475569", fontSize: 12 }}>No facets.</div>
                  ) : (
                    Object.entries(facetsByType).map(([type, facets]) => (
                      <div key={type} style={{ marginBottom: 12 }}>
                        <div style={{ fontFamily: MONO_FONT, fontSize: 11, color: "#64748b", marginBottom: 5 }}>
                          {axisLabel(type)}
                        </div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                          {facets.map((facet) => (
                            <Link
                              key={`${facet.facet_type}:${facet.facet_value}:${facet.source}`}
                              to={`/timeline?topic=${encodeURIComponent(facet.facet_value)}&axis=${encodeURIComponent(facet.facet_type)}`}
                              style={{
                                color: "#e2e8f0",
                                border: "1px solid #1e293b",
                                padding: "4px 6px",
                                fontFamily: MONO_FONT,
                                fontSize: 11,
                                textDecoration: "none",
                              }}
                            >
                              {facet.facet_value}
                            </Link>
                          ))}
                        </div>
                      </div>
                    ))
                  )}
                </section>

                <section style={{ border: "1px solid #1e293b", padding: 14 }}>
                  <div style={{ fontFamily: PIXEL_FONT, fontSize: 8, color: "#64748b", marginBottom: 10 }}>
                    QUALITY
                  </div>
                  <div style={{ fontFamily: MONO_FONT, fontSize: 12, color: "#94a3b8", marginBottom: 8 }}>
                    {paper.quality_filtered ? paper.quality_policy : "unfiltered"}
                  </div>
                  {paper.quality_flags.length === 0 ? (
                    <div style={{ fontFamily: MONO_FONT, color: "#34d399", fontSize: 12 }}>No local flags.</div>
                  ) : (
                    paper.quality_flags.map((flag) => (
                      <div
                        key={`${flag.flag_type}:${flag.source}`}
                        style={{
                          borderTop: "1px solid #0f172a",
                          paddingTop: 8,
                          marginTop: 8,
                          fontFamily: MONO_FONT,
                          fontSize: 11,
                        }}
                      >
                        <div style={{ color: flag.severity === "exclude" ? "#f87171" : "#f59e0b" }}>
                          {flag.severity} · {flag.flag_type}
                        </div>
                        <div style={{ color: "#64748b", marginTop: 3 }}>{flag.reason}</div>
                      </div>
                    ))
                  )}
                </section>
              </aside>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
