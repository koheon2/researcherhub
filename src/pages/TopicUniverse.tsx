import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useSearchParams } from "react-router-dom";

const API_BASE   = "http://localhost:8000/api";
const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT  = "'Share Tech Mono', monospace";

/* ── Field colour palette (same as Globe) ── */
const FIELD_COLORS: Record<string, string> = {
  "AI":                  "#60a5fa",
  "Computer Vision":     "#a78bfa",
  "Networks":            "#34d399",
  "Theory & Math":       "#fbbf24",
  "Information Systems": "#f87171",
  "HCI":                 "#fb923c",
  "Signal Processing":   "#e879f9",
  "Hardware":            "#94a3b8",
  "other":               "#475569",
};
function fieldColor(f: string) { return FIELD_COLORS[f] ?? FIELD_COLORS.other; }

/* ── Types ── */
interface TopicCluster {
  topic_id:        string;
  topic_name:      string;
  researcher_count: number;
  centroid_x:      number;  // UMAP -50..50
  centroid_y:      number;
  dominant_field:  string;
  total_citations: number;
  top_researchers: { id: string; name: string; citations: number }[];
}

/* ── UMAP → canvas 변환: 데이터 범위를 동적으로 계산 ── */
interface UmapBounds { minX: number; maxX: number; minY: number; maxY: number; }

function computeBounds(clusters: TopicCluster[]): UmapBounds {
  if (!clusters.length) return { minX: -10, maxX: 10, minY: -10, maxY: 10 };
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const c of clusters) {
    if (c.centroid_x < minX) minX = c.centroid_x;
    if (c.centroid_x > maxX) maxX = c.centroid_x;
    if (c.centroid_y < minY) minY = c.centroid_y;
    if (c.centroid_y > maxY) maxY = c.centroid_y;
  }
  const px = (maxX - minX) * 0.07;
  const py = (maxY - minY) * 0.07;
  return { minX: minX - px, maxX: maxX + px, minY: minY - py, maxY: maxY + py };
}

function umapToCanvas(
  ux: number, uy: number,
  w: number, h: number,
  vp: Viewport,
  bounds: UmapBounds,
): [number, number] {
  const pad = 48;
  const aw = w - pad * 2;
  const ah = h - pad * 2;
  const nx = (ux - bounds.minX) / (bounds.maxX - bounds.minX);
  const ny = (uy - bounds.minY) / (bounds.maxY - bounds.minY);
  const sx = pad + nx * aw;
  const sy = pad + (1 - ny) * ah;  // flip Y
  return [
    (sx - w / 2 - vp.panX) * vp.zoom + w / 2,
    (sy - h / 2 - vp.panY) * vp.zoom + h / 2,
  ];
}

interface Viewport {
  zoom: number;
  panX: number;   // world-space pan offset (before zoom)
  panY: number;
}

interface HighlightResearcher {
  id: string; umap_x: number | null; umap_y: number | null;
  name: string; institution: string | null; field: string | null; citations: number;
}

/* ── Main page ── */
export function TopicUniverse({ selected: _selected, onSelect: _onSelect }: { selected: any; onSelect: (r: any) => void }) {
  const [searchParams] = useSearchParams();
  const [clusters, setClusters]   = useState<TopicCluster[]>([]);
  const [loading, setLoading]     = useState(true);
  const [hovered, setHovered]     = useState<TopicCluster | null>(null);
  const [focusedTopic, setFocusedTopic] = useState<TopicCluster | null>(null);
  const [mousePos, setMousePos]   = useState({ x: 0, y: 0 });
  const [highlighted, setHighlighted] = useState<HighlightResearcher[]>([]);

  const canvasRef  = useRef<HTMLCanvasElement>(null);
  const vpRef      = useRef<Viewport>({ zoom: 1, panX: 0, panY: 0 });
  const dragging   = useRef<{ sx: number; sy: number; px: number; py: number } | null>(null);
  const rafRef     = useRef<number>(0);
  const hoveredRef = useRef<TopicCluster | null>(null);

  /* Load clusters */
  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/researchers/topics/clusters?limit=500&min_researchers=3`)
      .then(r => r.json())
      .then(d => { setClusters(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  /* Fetch highlighted researchers from ?highlight= URL param */
  useEffect(() => {
    const hlParam = searchParams.get("highlight");
    if (!hlParam) { setHighlighted([]); return; }
    const ids = hlParam.split(",").filter(Boolean);
    fetch(`${API_BASE}/researchers/by-openalex-ids?ids=${ids.join(",")}`)
      .then(r => r.json())
      .then(setHighlighted)
      .catch(() => setHighlighted([]));
  }, [searchParams]);

  /* UMAP 데이터 범위 */
  const bounds = useMemo(() => computeBounds(clusters), [clusters]);

  /* 버블 반경: 훨씬 작게 — 최대 18px */
  const maxCount = useMemo(() => Math.max(1, ...clusters.map(c => c.researcher_count)), [clusters]);

  const bubbleRadius = useCallback((c: TopicCluster, zoom: number) => {
    const base = 3 + Math.sqrt(c.researcher_count / maxCount) * 15;
    return Math.max(2.5, base * Math.max(0.6, Math.min(3, zoom)));
  }, [maxCount]);

  /* 라벨 표시 기준: 상위 N개만 줌 레벨에 따라 */
  const labelRankMap = useMemo(() => {
    const ranked = [...clusters].sort((a, b) => b.researcher_count - a.researcher_count);
    return new Map(ranked.map((c, i) => [c.topic_id, i]));
  }, [clusters]);

  /* Precompute: sorted clusters + connection pairs (constant after load) */
  const sortedClusters = useMemo(
    () => [...clusters].sort((a, b) => b.researcher_count - a.researcher_count),
    [clusters],
  );

  const connectionPairs = useMemo(() => {
    const pairs: [number, number][] = [];
    const n = Math.min(clusters.length, 150);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = clusters[i], b = clusters[j];
        if (a.dominant_field !== b.dominant_field) continue;
        const dx = a.centroid_x - b.centroid_x;
        const dy = a.centroid_y - b.centroid_y;
        if (dx * dx + dy * dy < 80) pairs.push([i, j]);
      }
    }
    return pairs;
  }, [clusters]);

  /* ── Canvas render ── */
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    if (w === 0 || h === 0) return;
    const vp = vpRef.current;

    ctx.fillStyle = "#050810";
    ctx.fillRect(0, 0, w, h);

    // Stars (고정, 얇게)
    ctx.fillStyle = "#ffffff10";
    const rng = mulberry32(42);
    for (let i = 0; i < 250; i++) {
      const sx = rng() * w;
      const sy = rng() * h;
      const sr = rng() * 0.9;
      ctx.beginPath();
      ctx.arc(sx, sy, Math.max(0.2, sr), 0, Math.PI * 2);
      ctx.fill();
    }

    if (!sortedClusters.length) return;

    // 줌 레벨에 따라 라벨 표시 개수 결정
    const labelLimit = vp.zoom < 0.8 ? 15 : vp.zoom < 1.5 ? 30 : vp.zoom < 3 ? 60 : 120;

    // Connection lines (hover 근처만, 매우 얇게)
    const hov = hoveredRef.current;
    if (hov) {
      ctx.lineWidth = 0.5;
      for (const [i, j] of connectionPairs) {
        const a = clusters[i], b = clusters[j];
        if (a.topic_id !== hov.topic_id && b.topic_id !== hov.topic_id) continue;
        const [ax, ay] = umapToCanvas(a.centroid_x, a.centroid_y, w, h, vp, bounds);
        const [bx, by] = umapToCanvas(b.centroid_x, b.centroid_y, w, h, vp, bounds);
        if (!isFinite(ax) || !isFinite(ay) || !isFinite(bx) || !isFinite(by)) continue;
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx, by);
        ctx.strokeStyle = fieldColor(a.dominant_field) + "33";
        ctx.stroke();
      }
    }

    // Bubbles (큰 것부터 — 작은 게 위에 렌더)
    for (const c of sortedClusters) {
      const [cx, cy] = umapToCanvas(c.centroid_x, c.centroid_y, w, h, vp, bounds);
      if (!isFinite(cx) || !isFinite(cy)) continue;
      if (cx < -80 || cx > w + 80 || cy < -80 || cy > h + 80) continue;

      const r   = bubbleRadius(c, vp.zoom);
      const col = fieldColor(c.dominant_field);
      const isH = hov?.topic_id === c.topic_id;
      const isF = focusedTopic?.topic_id === c.topic_id;
      const rank = labelRankMap.get(c.topic_id) ?? 9999;

      // 버블 fill — 간단하고 선명하게
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = col + (isH ? "e0" : isF ? "cc" : "90");
      ctx.fill();

      // hover/focus 테두리
      if (isH || isF) {
        ctx.beginPath();
        ctx.arc(cx, cy, r + 1.5, 0, Math.PI * 2);
        ctx.strokeStyle = col + "ff";
        ctx.lineWidth = isH ? 2 : 1.2;
        ctx.stroke();
        // 작은 글로우
        ctx.beginPath();
        ctx.arc(cx, cy, r + 5, 0, Math.PI * 2);
        ctx.strokeStyle = col + "28";
        ctx.lineWidth = 6;
        ctx.stroke();
      }

      // 라벨: 순위 내 + 화면에 충분히 큰 경우만
      const showLabel = isH || (rank < labelLimit && r > 5);
      if (showLabel) {
        const fontSize = isH ? 11 : Math.max(8, Math.min(11, r * 0.9));
        ctx.font = `${fontSize}px ${MONO_FONT}`;
        ctx.textAlign = "center";
        // 텍스트 배경 (가독성)
        const label = c.topic_name.length > 28 ? c.topic_name.slice(0, 26) + "…" : c.topic_name;
        const tw = ctx.measureText(label).width;
        if (!isH) {
          ctx.fillStyle = "#05081088";
          ctx.fillRect(cx - tw / 2 - 2, cy + r + 2, tw + 4, fontSize + 3);
        }
        ctx.fillStyle = isH ? "#ffffff" : col + "dd";
        ctx.fillText(label, cx, cy + r + fontSize + 2);
        if (isH) {
          ctx.font = `9px ${MONO_FONT}`;
          ctx.fillStyle = "#94a3b8";
          ctx.fillText(`${c.researcher_count.toLocaleString()} researchers`, cx, cy + r + fontSize + 15);
        }
      }
    }
    // Highlighted researchers (from Benchmark page)
    for (const hl of highlighted) {
      if (hl.umap_x == null || hl.umap_y == null) continue;
      const [hx, hy] = umapToCanvas(hl.umap_x, hl.umap_y, w, h, vp, bounds);
      if (!isFinite(hx) || !isFinite(hy)) continue;

      // Pulsing glow ring
      ctx.beginPath();
      ctx.arc(hx, hy, 12, 0, Math.PI * 2);
      ctx.strokeStyle = "#fbbf2466";
      ctx.lineWidth = 6;
      ctx.stroke();

      // Outer ring
      ctx.beginPath();
      ctx.arc(hx, hy, 7, 0, Math.PI * 2);
      ctx.strokeStyle = "#fbbf24cc";
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Bright center dot
      ctx.beginPath();
      ctx.arc(hx, hy, 4, 0, Math.PI * 2);
      ctx.fillStyle = "#fbbf24";
      ctx.fill();

      // Name label above dot
      ctx.font = `bold 11px ${MONO_FONT}`;
      ctx.textAlign = "center";
      const lw = ctx.measureText(hl.name).width;
      ctx.fillStyle = "#05081099";
      ctx.fillRect(hx - lw / 2 - 3, hy - 28, lw + 6, 14);
      ctx.fillStyle = "#fbbf24";
      ctx.fillText(hl.name, hx, hy - 17);
    }
  }, [clusters, sortedClusters, connectionPairs, bubbleRadius, labelRankMap, focusedTopic, bounds, highlighted]);

  /* Always keep drawRef current — loop reads from ref so it never needs restart */
  const drawRef = useRef(draw);
  useEffect(() => { drawRef.current = draw; }, [draw]);

  /* Single persistent animation loop (never cancelled) */
  useEffect(() => {
    let alive = true;
    const loop = () => {
      if (!alive) return;
      drawRef.current();
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);
    return () => { alive = false; cancelAnimationFrame(rafRef.current); };
  }, []); // empty deps — runs once

  /* Canvas resize — only update dimensions when they actually change */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const setSize = () => {
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width  = w;
        canvas.height = h;
      }
    };
    const obs = new ResizeObserver(setSize);
    obs.observe(canvas);
    setSize();
    return () => obs.disconnect();
  }, []);

  /* Hit test */
  const hitTest = useCallback((mx: number, my: number): TopicCluster | null => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const w = canvas.width, h = canvas.height;
    const vp = vpRef.current;
    let best: TopicCluster | null = null;
    let bestD = Infinity;
    for (const c of clusters) {
      const [cx, cy] = umapToCanvas(c.centroid_x, c.centroid_y, w, h, vp, bounds);
      const r = bubbleRadius(c, vp.zoom);
      const d = Math.hypot(mx - cx, my - cy);
      if (d < r + 10 && d < bestD) { bestD = d; best = c; }
    }
    return best;
  }, [clusters, bubbleRadius, bounds]);

  /* Mouse events */
  const onMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    setMousePos({ x: e.clientX, y: e.clientY });

    if (dragging.current) {
      const dx = mx - dragging.current.sx;
      const dy = my - dragging.current.sy;
      vpRef.current.panX = dragging.current.px - dx / vpRef.current.zoom;
      vpRef.current.panY = dragging.current.py - dy / vpRef.current.zoom;
      return;
    }

    const hit = hitTest(mx, my);
    hoveredRef.current = hit;
    setHovered(hit);
    canvasRef.current!.style.cursor = hit ? "pointer" : "default";
  }, [hitTest]);

  const onMouseDown = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    dragging.current = {
      sx: e.clientX - rect.left,
      sy: e.clientY - rect.top,
      px: vpRef.current.panX,
      py: vpRef.current.panY,
    };
  }, []);

  const onMouseUp = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (dragging.current) {
      const rect = canvasRef.current!.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const dx = Math.abs(mx - dragging.current.sx);
      const dy = Math.abs(my - dragging.current.sy);
      if (dx < 4 && dy < 4) {
        // click
        const hit = hitTest(mx, my);
        setFocusedTopic(hit ?? null);
      }
      dragging.current = null;
    }
  }, [hitTest]);

  const onWheel = useCallback((e: React.WheelEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.85 : 1.18;
    vpRef.current.zoom = Math.max(0.3, Math.min(8, vpRef.current.zoom * factor));
  }, []);

  /* ── Legend ── */
  const fields = useMemo(() => {
    const seen = new Set<string>();
    clusters.forEach(c => seen.add(c.dominant_field));
    return Array.from(seen).sort();
  }, [clusters]);


  return (
    <div style={{ position: "absolute", top: 52, left: 0, right: 0, bottom: 0, background: "#020408", overflow: "hidden" }}>
      {loading && (
        <div style={{
          position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
          fontFamily: PIXEL_FONT, fontSize: 10, color: "#60a5fa", letterSpacing: ".12em", zIndex: 30,
          background: "#020408",
        }}>
          MAPPING TOPIC UNIVERSE...
        </div>
      )}

      <canvas
        ref={canvasRef}
        style={{ width: "100%", height: "100%", display: "block" }}
        onMouseMove={onMouseMove}
        onMouseDown={onMouseDown}
        onMouseUp={onMouseUp}
        onMouseLeave={() => { hoveredRef.current = null; setHovered(null); dragging.current = null; }}
        onWheel={onWheel}
      />

      {/* Field legend */}
      {!loading && (
        <div style={{
          position: "absolute", top: 16, left: 16,
          background: "#06080fee", border: "1px solid #1e293b",
          padding: "12px 16px", minWidth: 160,
        }}>
          <div style={{ fontFamily: PIXEL_FONT, fontSize: 7, color: "#475569", marginBottom: 10, letterSpacing: ".08em" }}>
            RESEARCH FIELDS
          </div>
          {fields.map(f => (
            <div key={f} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: fieldColor(f), flexShrink: 0 }} />
              <span style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#94a3b8" }}>{f}</span>
            </div>
          ))}
          <div style={{ borderTop: "1px solid #1e293b", marginTop: 10, paddingTop: 10 }}>
            <div style={{ fontFamily: PIXEL_FONT, fontSize: 7, color: "#475569", marginBottom: 6, letterSpacing: ".08em" }}>
              BUBBLE SIZE
            </div>
            <div style={{ fontFamily: MONO_FONT, fontSize: 9, color: "#475569" }}>
              = researcher count
            </div>
          </div>
        </div>
      )}

      {/* Hover tooltip */}
      {hovered && (
        <div style={{
          position: "fixed",
          left: mousePos.x + 16,
          top: mousePos.y - 60,
          background: "#06080fee",
          border: `1px solid ${fieldColor(hovered.dominant_field)}44`,
          padding: "10px 14px",
          pointerEvents: "none",
          zIndex: 50,
          maxWidth: 260,
          minWidth: 200,
        }}>
          <div style={{ fontFamily: PIXEL_FONT, fontSize: 8, color: fieldColor(hovered.dominant_field), marginBottom: 6 }}>
            {hovered.topic_name}
          </div>
          <div style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#94a3b8", marginBottom: 4 }}>
            {hovered.dominant_field}
          </div>
          <div style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#64748b" }}>
            {hovered.researcher_count.toLocaleString()} researchers
          </div>
          <div style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#64748b" }}>
            {formatCitations(hovered.total_citations)} total citations
          </div>
          {hovered.top_researchers.length > 0 && (
            <div style={{ marginTop: 8, borderTop: "1px solid #1e293b", paddingTop: 8 }}>
              <div style={{ fontFamily: PIXEL_FONT, fontSize: 6, color: "#334155", marginBottom: 5 }}>TOP RESEARCHERS</div>
              {hovered.top_researchers.map(r => (
                <div key={r.id} style={{ fontFamily: MONO_FONT, fontSize: 9, color: "#475569", marginBottom: 2 }}>
                  {r.name} · {formatCitations(r.citations)}
                </div>
              ))}
            </div>
          )}
          <div style={{ marginTop: 8, fontFamily: MONO_FONT, fontSize: 8, color: "#1e293b" }}>
            [CLICK] to focus
          </div>
        </div>
      )}

      {/* Focused topic panel */}
      {focusedTopic && (
        <div style={{
          position: "absolute", top: 16, right: 16, bottom: 16,
          width: 280,
          background: "#06080fee",
          border: `1px solid ${fieldColor(focusedTopic.dominant_field)}55`,
          padding: "16px",
          overflowY: "auto",
          zIndex: 40,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
            <div style={{ fontFamily: PIXEL_FONT, fontSize: 8, color: fieldColor(focusedTopic.dominant_field), lineHeight: 1.6 }}>
              {focusedTopic.topic_name}
            </div>
            <button
              onClick={() => setFocusedTopic(null)}
              style={{ background: "none", border: "none", color: "#475569", cursor: "pointer", fontSize: 16, padding: 0, lineHeight: 1 }}
            >×</button>
          </div>

          <div style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#60a5fa", marginBottom: 12 }}>
            {focusedTopic.dominant_field}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 16 }}>
            <Stat label="RESEARCHERS" value={focusedTopic.researcher_count.toLocaleString()} />
            <Stat label="TOTAL CITS" value={formatCitations(focusedTopic.total_citations)} />
          </div>

          <div style={{ borderTop: "1px solid #1e293b", paddingTop: 12, marginBottom: 8 }}>
            <div style={{ fontFamily: PIXEL_FONT, fontSize: 6, color: "#334155", marginBottom: 8, letterSpacing: ".08em" }}>
              TOP RESEARCHERS
            </div>
            {focusedTopic.top_researchers.map((r, i) => (
              <div key={r.id} style={{
                display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
                padding: "6px 8px", background: "#0d1117", border: "1px solid #1e293b",
              }}>
                <span style={{ fontFamily: MONO_FONT, fontSize: 9, color: "#334155", width: 14 }}>{i+1}.</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#e2e8f0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {r.name}
                  </div>
                  <div style={{ fontFamily: MONO_FONT, fontSize: 9, color: "#475569" }}>
                    {formatCitations(r.citations)} cit
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div style={{
            marginTop: 16, padding: "10px", background: "#0d1117", border: "1px solid #1e293b",
            fontFamily: MONO_FONT, fontSize: 9, color: "#334155", lineHeight: 1.6,
          }}>
            TIME EXPANSION<br />
            <span style={{ color: "#1e293b" }}>— available after paper<br />  topic collection —</span>
          </div>
        </div>
      )}

      {/* Bottom stats */}
      {!loading && (
        <div style={{
          position: "absolute", bottom: 16, left: "50%", transform: "translateX(-50%)",
          display: "flex", gap: 24, alignItems: "center",
        }}>
          <span style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#1e293b" }}>
            {clusters.length} TOPICS
          </span>
          <span style={{ fontFamily: PIXEL_FONT, fontSize: 7, color: "#1a2540", letterSpacing: ".06em" }}>
            [DRAG] PAN · [SCROLL] ZOOM · [CLICK] FOCUS
          </span>
          <span style={{ fontFamily: MONO_FONT, fontSize: 10, color: "#1e293b" }}>
            UMAP SPACE
          </span>
        </div>
      )}
    </div>
  );
}

/* ── Helpers ── */

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ padding: "8px", background: "#0d1117", border: "1px solid #1e293b" }}>
      <div style={{ fontFamily: PIXEL_FONT, fontSize: 6, color: "#334155", marginBottom: 4, letterSpacing: ".06em" }}>{label}</div>
      <div style={{ fontFamily: MONO_FONT, fontSize: 13, color: "#e2e8f0" }}>{value}</div>
    </div>
  );
}

function formatCitations(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

/* Simple seedable RNG for deterministic stars */
function mulberry32(seed: number) {
  return function() {
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
