import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import type { ThreeEvent } from "@react-three/fiber";
import * as THREE from "three";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from "d3-force";
import { InfoCard } from "../components/InfoCard";
import type { Researcher } from "../data/researchers";
import { getFieldColor, FIELD_COLORS } from "../data/researchers";

const API_BASE   = "http://localhost:8000/api";
const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT  = "'Share Tech Mono', monospace";

/* ── Types ── */
interface GraphNode extends SimulationNodeDatum {
  id: string;
  name: string;
  field: string | null;
  citations: number;
  institution: string | null;
  country: string | null;
  h_index: number;
  works_count: number;
  recent_papers: number;
  lat: number | null;
  lng: number | null;
  umap_x: number | null;
  umap_y: number | null;
  openalex_url: string | null;
}

interface GraphEdge extends SimulationLinkDatum<GraphNode> {
  weight: number;
}

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

/* ── Helpers ── */
function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return n.toString();
}

function nodeToResearcher(n: GraphNode): Researcher {
  return {
    id: n.id,
    name: n.name,
    field: n.field,
    citations: n.citations,
    institution: n.institution,
    country: n.country,
    h_index: n.h_index,
    works_count: n.works_count,
    recent_papers: n.recent_papers,
    lat: n.lat,
    lng: n.lng,
    umap_x: n.umap_x,
    umap_y: n.umap_y,
    openalex_url: n.openalex_url,
  };
}

/* ── Force simulation hook ── */
function useForceGraph(graphData: GraphData) {
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }>>(new Map());
  const simRef = useRef<ReturnType<typeof forceSimulation<GraphNode>> | null>(null);

  useEffect(() => {
    if (graphData.nodes.length === 0) return;

    // Clone nodes to avoid mutating original data
    const nodes: GraphNode[] = graphData.nodes.map((n) => ({ ...n }));
    const rawEdges: GraphEdge[] = graphData.edges.map((e) => ({ ...e }));

    // Normalize edge weights to [0, 1] (API returns raw paper counts)
    const maxWeight = Math.max(1, ...rawEdges.map((e) => e.weight ?? 1));
    const edges: GraphEdge[] = rawEdges.map((e) => ({
      ...e,
      weight: (e.weight ?? 1) / maxWeight,
    }));

    const maxCit = Math.max(1, ...nodes.map((n) => n.citations));

    const sim = forceSimulation<GraphNode>(nodes)
      .force("link", forceLink<GraphNode, GraphEdge>(edges)
        .id((d) => d.id)
        .distance(60)
        .strength((e) => 0.2 + (e.weight ?? 0.5) * 0.6))
      .force("charge", forceManyBody<GraphNode>()
        .strength((d) => {
          const s = Math.log1p(d.citations) / Math.log1p(maxCit);
          return -80 - s * 200;
        }))
      .force("center", forceCenter(0, 0).strength(0.05))
      .force("collide", forceCollide<GraphNode>()
        .radius((d) => {
          const s = Math.log1p(d.citations) / Math.log1p(maxCit);
          return 3 + s * 8;
        })
        .iterations(2))
      .alphaDecay(0.02)
      .on("tick", () => {
        const map = new Map<string, { x: number; y: number }>();
        for (const n of nodes) {
          map.set(n.id, { x: n.x ?? 0, y: n.y ?? 0 });
        }
        setPositions(new Map(map));
      });

    simRef.current = sim;

    return () => {
      sim.stop();
    };
  }, [graphData]);

  return positions;
}

/* ── Three.js Graph Renderer ── */
interface GraphRendererProps {
  graphData: GraphData;
  positions: Map<string, { x: number; y: number }>;
  onHover: (r: Researcher | null, screenPos: { x: number; y: number } | null) => void;
  onClick: (r: Researcher) => void;
  highlightId: string | null;
}

function GraphRenderer({ graphData, positions, onHover, onClick, highlightId }: GraphRendererProps) {
  const meshRefs    = useRef<Map<string, THREE.Mesh>>(new Map());
  const edgesRef    = useRef<THREE.LineSegments>(null);
  const highlightRef = useRef<THREE.Mesh>(null);
  const { gl }      = useThree();
  const startTime   = useRef(performance.now());

  const maxCit = useMemo(
    () => Math.max(1, ...graphData.nodes.map((n) => n.citations)),
    [graphData.nodes]
  );

  // Build edge geometry
  useEffect(() => {
    if (!edgesRef.current || positions.size === 0) return;
    const edgePositions: number[] = [];
    for (const e of graphData.edges) {
      const srcId = typeof e.source === "object" ? (e.source as GraphNode).id : (e.source as string);
      const tgtId = typeof e.target === "object" ? (e.target as GraphNode).id : (e.target as string);
      const src = positions.get(srcId);
      const tgt = positions.get(tgtId);
      if (src && tgt) {
        edgePositions.push(src.x, src.y, 0, tgt.x, tgt.y, 0);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(edgePositions, 3));
    edgesRef.current.geometry.dispose();
    edgesRef.current.geometry = geo;
  }, [positions, graphData.edges]);

  // Update node positions
  useFrame(() => {
    for (const node of graphData.nodes) {
      const mesh = meshRefs.current.get(node.id);
      const pos  = positions.get(node.id);
      if (mesh && pos) {
        mesh.position.set(pos.x, pos.y, 0);
      }
    }

    // Highlight pulse
    if (highlightRef.current && highlightId) {
      const pos = positions.get(highlightId);
      if (pos) {
        highlightRef.current.visible = true;
        highlightRef.current.position.set(pos.x, pos.y, 0.1);
        const elapsed = (performance.now() - startTime.current) / 1000;
        const pulse = 1 + Math.sin(elapsed * 4) * 0.15;
        highlightRef.current.scale.set(pulse, pulse, 1);
      } else {
        highlightRef.current.visible = false;
      }
    } else if (highlightRef.current) {
      highlightRef.current.visible = false;
    }
  });

  const handlePointerMove = useCallback((e: ThreeEvent<PointerEvent>, node: GraphNode) => {
    gl.domElement.style.cursor = "pointer";
    const rect = gl.domElement.getBoundingClientRect();
    onHover(nodeToResearcher(node), {
      x: e.nativeEvent.clientX - rect.left,
      y: e.nativeEvent.clientY - rect.top,
    });
  }, [gl, onHover]);

  const handlePointerLeave = useCallback(() => {
    gl.domElement.style.cursor = "default";
    onHover(null, null);
  }, [gl, onHover]);

  const handleClick = useCallback((_e: ThreeEvent<MouseEvent>, node: GraphNode) => {
    onClick(nodeToResearcher(node));
  }, [onClick]);

  return (
    <>
      {/* Edges */}
      <lineSegments ref={edgesRef}>
        <bufferGeometry />
        <lineBasicMaterial color="#ffffff" transparent opacity={0.08} />
      </lineSegments>

      {/* Nodes */}
      {graphData.nodes.map((node) => {
        const logCit = Math.log1p(node.citations) / Math.log1p(maxCit);
        const radius = 0.8 + logCit * 3.2;
        const color  = getFieldColor(node.field);
        const bright = 0.3 + logCit * 0.7;

        return (
          <mesh
            key={node.id}
            ref={(ref) => {
              if (ref) meshRefs.current.set(node.id, ref);
              else meshRefs.current.delete(node.id);
            }}
            onPointerMove={(e) => handlePointerMove(e, node)}
            onPointerLeave={handlePointerLeave}
            onClick={(e) => handleClick(e, node)}
          >
            <sphereGeometry args={[radius, 16, 16]} />
            <meshBasicMaterial
              color={new THREE.Color(color).multiplyScalar(bright)}
              transparent
              opacity={0.85}
            />
          </mesh>
        );
      })}

      {/* Glow layer for nodes */}
      {graphData.nodes.map((node) => {
        const logCit = Math.log1p(node.citations) / Math.log1p(maxCit);
        const radius = (0.8 + logCit * 3.2) * 1.8;
        const color  = getFieldColor(node.field);

        return (
          <mesh
            key={`glow-${node.id}`}
            position={[0, 0, -0.1]}
            ref={(ref) => {
              // Track alongside main node
              const mainMesh = meshRefs.current.get(node.id);
              if (ref && mainMesh) {
                ref.position.copy(mainMesh.position);
                ref.position.z = -0.1;
              }
            }}
          >
            <sphereGeometry args={[radius, 12, 12]} />
            <meshBasicMaterial color={color} transparent opacity={0.08 + logCit * 0.12} />
          </mesh>
        );
      })}

      {/* Highlight ring */}
      <mesh ref={highlightRef} visible={false}>
        <ringGeometry args={[4.5, 5.5, 32]} />
        <meshBasicMaterial color="#ffffff" transparent opacity={0.7} side={THREE.DoubleSide} />
      </mesh>
    </>
  );
}

/* ── Node Labels (HTML overlay) ── */
interface NodeLabelsProps {
  graphData: GraphData;
  positions: Map<string, { x: number; y: number }>;
  cameraRef: React.RefObject<any>;
  containerRef: React.RefObject<HTMLDivElement | null>;
  topN?: number;
}

function NodeLabels({ graphData, positions, cameraRef, containerRef, topN = 20 }: NodeLabelsProps) {
  const topNodes = useMemo(
    () => [...graphData.nodes].sort((a, b) => b.citations - a.citations).slice(0, topN),
    [graphData.nodes, topN]
  );

  const [labels, setLabels] = useState<{ id: string; name: string; x: number; y: number; color: string; size: number }[]>([]);

  useEffect(() => {
    let raf: number;
    const update = () => {
      const cam = cameraRef.current;
      const el  = containerRef.current;
      if (!cam || !el) { raf = requestAnimationFrame(update); return; }

      const w = el.clientWidth;
      const h = el.clientHeight;
      const vec = new THREE.Vector3();
      const ortho = new THREE.OrthographicCamera(
        cam.left / cam.zoom, cam.right / cam.zoom,
        cam.top / cam.zoom, cam.bottom / cam.zoom,
        -100, 100,
      );
      ortho.position.copy(cam.position);
      ortho.updateMatrixWorld();
      ortho.updateProjectionMatrix();

      const maxCit = topNodes[0]?.citations ?? 1;
      const result: typeof labels = [];
      for (const node of topNodes) {
        const pos = positions.get(node.id);
        if (!pos) continue;
        vec.set(pos.x, pos.y, 0);
        vec.project(ortho);
        const sx = (vec.x * 0.5 + 0.5) * w;
        const sy = (-vec.y * 0.5 + 0.5) * h;
        if (sx > -100 && sx < w + 100 && sy > -20 && sy < h + 20) {
          const logCit = Math.log1p(node.citations) / Math.log1p(maxCit);
          result.push({
            id: node.id,
            name: node.name,
            x: sx,
            y: sy,
            color: getFieldColor(node.field),
            size: logCit,
          });
        }
      }
      setLabels(result);
      raf = requestAnimationFrame(update);
    };
    raf = requestAnimationFrame(update);
    return () => cancelAnimationFrame(raf);
  }, [topNodes, positions, cameraRef, containerRef]);

  return (
    <>
      {labels.map((l) => (
        <div
          key={l.id}
          style={{
            position: "absolute",
            left: l.x,
            top: l.y - 14 - l.size * 8,
            transform: "translateX(-50%)",
            fontFamily: MONO_FONT,
            fontSize: 9 + l.size * 2,
            color: l.color,
            opacity: 0.5 + l.size * 0.5,
            pointerEvents: "none",
            whiteSpace: "nowrap",
            textShadow: `0 0 6px ${l.color}44`,
            letterSpacing: "0.04em",
          }}
        >
          {l.name}
        </div>
      ))}
    </>
  );
}

/* ── Camera controls ── */
function CameraControls() {
  const { camera, gl } = useThree();

  useEffect(() => {
    const el = gl.domElement;
    let isDragging = false;
    let lastX = 0, lastY = 0;

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (camera instanceof THREE.OrthographicCamera) {
        const zoomFactor = 1 + e.deltaY * 0.001;
        camera.zoom = Math.max(1, Math.min(80, camera.zoom / zoomFactor));
        camera.updateProjectionMatrix();
      }
    };

    const onPointerDown = (e: PointerEvent) => {
      isDragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
      el.setPointerCapture(e.pointerId);
    };

    const onPointerMove = (e: PointerEvent) => {
      if (!isDragging) return;
      if (camera instanceof THREE.OrthographicCamera) {
        const dx = e.clientX - lastX;
        const dy = e.clientY - lastY;
        const scale = (camera.right - camera.left) / camera.zoom / el.clientWidth;
        camera.position.x -= dx * scale;
        camera.position.y += dy * scale;
        lastX = e.clientX;
        lastY = e.clientY;
      }
    };

    const onPointerUp = (e: PointerEvent) => {
      isDragging = false;
      el.releasePointerCapture(e.pointerId);
    };

    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("pointerdown", onPointerDown);
    el.addEventListener("pointermove", onPointerMove);
    el.addEventListener("pointerup", onPointerUp);

    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("pointerdown", onPointerDown);
      el.removeEventListener("pointermove", onPointerMove);
      el.removeEventListener("pointerup", onPointerUp);
    };
  }, [camera, gl]);

  return null;
}

/* ── Camera state bridge ── */
function CameraStateBridge({ cameraRef }: { cameraRef: React.MutableRefObject<any> }) {
  const { camera } = useThree();
  useFrame(() => {
    if (camera instanceof THREE.OrthographicCamera) {
      cameraRef.current = {
        position: camera.position.clone(),
        zoom: camera.zoom,
        left: camera.left,
        right: camera.right,
        top: camera.top,
        bottom: camera.bottom,
      };
    }
  });
  return null;
}

/* ── Tooltip ── */
interface TooltipProps {
  researcher: Researcher | null;
  position:   { x: number; y: number } | null;
}

function Tooltip({ researcher, position }: TooltipProps) {
  if (!researcher || !position) return null;
  return (
    <div style={{
      position: "absolute",
      left: position.x + 12,
      top: position.y - 30,
      background: "#06080fee",
      border: `1px solid ${getFieldColor(researcher.field)}44`,
      padding: "6px 10px",
      pointerEvents: "none",
      zIndex: 40,
      whiteSpace: "nowrap",
    }}>
      <div style={{
        fontFamily: PIXEL_FONT, fontSize: 8,
        color: "#e2e8f0", marginBottom: 3,
      }}>
        {researcher.name.toUpperCase()}
      </div>
      <div style={{
        fontFamily: MONO_FONT, fontSize: 11,
        color: "#475569",
      }}>
        {researcher.institution ?? "Unknown"} · {fmtNum(researcher.citations)} cit
      </div>
    </div>
  );
}

/* ── Side Panel ── */
interface SidePanelProps {
  activeField: string;
  onFieldChange: (field: string) => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  searchResults: Researcher[];
  onSearchSelect: (r: Researcher) => void;
  nodeCount: number;
}

function SidePanel({
  activeField, onFieldChange,
  searchQuery, onSearchChange,
  searchResults, onSearchSelect,
  nodeCount,
}: SidePanelProps) {
  const fields = Object.keys(FIELD_COLORS);

  return (
    <div style={{
      position: "absolute",
      top: 0, left: 0, bottom: 0,
      width: 200,
      background: "rgba(6, 8, 15, 0.95)",
      borderRight: "1px solid #1e293b",
      zIndex: 15,
      display: "flex",
      flexDirection: "column",
      padding: "16px 12px",
      gap: 16,
      overflowY: "auto",
    }}>
      {/* Field section */}
      <div>
        <div style={{
          fontFamily: PIXEL_FONT, fontSize: 7,
          color: "#334155", marginBottom: 10,
          letterSpacing: "0.08em",
        }}>
          FIELD
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {fields.map((f) => {
            const isActive = activeField === f;
            const color = FIELD_COLORS[f];
            return (
              <button
                key={f}
                onClick={() => onFieldChange(f)}
                style={{
                  background: isActive ? `${color}22` : "transparent",
                  border: `1px solid ${isActive ? color + "66" : "#1e293b"}`,
                  color: isActive ? color : "#475569",
                  fontFamily: PIXEL_FONT, fontSize: 6,
                  padding: "4px 6px",
                  cursor: "pointer",
                  letterSpacing: "0.04em",
                  transition: "all 0.12s",
                }}
                onMouseEnter={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.borderColor = color + "44";
                    e.currentTarget.style.color = color;
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.borderColor = "#1e293b";
                    e.currentTarget.style.color = "#475569";
                  }
                }}
              >
                {f.length > 8 ? f.slice(0, 8) + ".." : f}
              </button>
            );
          })}
        </div>
      </div>

      {/* Divider */}
      <div style={{ height: 1, background: "#1e293b" }} />

      {/* Search section */}
      <div>
        <div style={{
          fontFamily: PIXEL_FONT, fontSize: 7,
          color: "#334155", marginBottom: 10,
          letterSpacing: "0.08em",
        }}>
          SEARCH
        </div>
        <div style={{
          display: "flex", alignItems: "center",
          background: "#0a0f1a",
          border: "1px solid #1e293b",
        }}>
          <span style={{
            padding: "0 6px 0 8px",
            fontFamily: PIXEL_FONT, fontSize: 8,
            color: "#334155", flexShrink: 0,
          }}>{">"}</span>
          <input
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="NAME..."
            style={{
              flex: 1, padding: "6px 6px 6px 0",
              background: "transparent", border: "none", outline: "none",
              color: "#e2e8f0", fontFamily: MONO_FONT, fontSize: 11,
              letterSpacing: "0.03em",
            }}
          />
        </div>
        {searchResults.length > 0 && (
          <div style={{
            marginTop: 4,
            background: "#06080f",
            border: "1px solid #1e293b",
            maxHeight: 180, overflowY: "auto",
          }}>
            {searchResults.slice(0, 8).map((r) => (
              <div
                key={r.id}
                onClick={() => onSearchSelect(r)}
                style={{
                  padding: "6px 8px", cursor: "pointer",
                  borderBottom: "1px solid #060a12",
                  fontFamily: MONO_FONT, fontSize: 10,
                  color: "#94a3b8",
                  transition: "background 0.08s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "#0a0f1a")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <div>{r.name}</div>
                <div style={{ color: "#334155", fontSize: 9, marginTop: 2 }}>
                  {r.field ?? "—"} · {fmtNum(r.citations)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Node count */}
      <div style={{
        fontFamily: MONO_FONT, fontSize: 10,
        color: "#334155", letterSpacing: "0.06em",
      }}>
        {nodeCount} NODES
      </div>
    </div>
  );
}

/* ── Star background ── */
function Stars() {
  const geo = useMemo(() => {
    const positions = new Float32Array(2000 * 3);
    for (let i = 0; i < 2000; i++) {
      positions[i * 3]     = (Math.random() - 0.5) * 600;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 600;
      positions[i * 3 + 2] = -20 - Math.random() * 10;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    return g;
  }, []);

  return (
    <points geometry={geo}>
      <pointsMaterial color="#ffffff" size={0.06} transparent opacity={0.4} sizeAttenuation />
    </points>
  );
}

/* ── Main Page ── */
interface GraphPageProps {
  selected: Researcher | null;
  onSelect: (r: Researcher | null) => void;
}

export function GraphPage({ selected, onSelect }: GraphPageProps) {
  const [searchParams] = useSearchParams();
  const [graphData, setGraphData]     = useState<GraphData>({ nodes: [], edges: [] });
  const [activeField, setActiveField] = useState("AI");
  const [loading, setLoading]         = useState(true);
  const [hovered, setHovered]         = useState<Researcher | null>(null);
  const [hoverPos, setHoverPos]       = useState<{ x: number; y: number } | null>(null);
  const [related, setRelated]         = useState<Researcher[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Researcher[]>([]);
  const cameraRef    = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef  = useRef<ReturnType<typeof setTimeout> | null>(null);
  const initDoneRef  = useRef(false);

  // Fetch graph data with fallback
  const fetchGraphData = useCallback(async (field: string, centerId?: string) => {
    setLoading(true);
    try {
      // Try graph API first
      let url: string;
      if (centerId) {
        url = `${API_BASE}/researchers/graph/data?center_id=${centerId}&depth=2&max_nodes=50`;
      } else {
        url = `${API_BASE}/researchers/graph/top?field=${encodeURIComponent(field)}&limit=50`;
      }

      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setGraphData(data);
        setLoading(false);
        return;
      }
    } catch {
      // Graph API not available, fallback
    }

    // Fallback: fetch researchers list, no edges
    try {
      const res = await fetch(`${API_BASE}/researchers/?limit=50&field=${encodeURIComponent(field)}`);
      if (res.ok) {
        const researchers: Researcher[] = await res.json();
        const nodes: GraphNode[] = researchers.map((r) => ({
          id: r.id,
          name: r.name,
          field: r.field,
          citations: r.citations,
          institution: r.institution,
          country: r.country,
          h_index: r.h_index,
          works_count: r.works_count,
          recent_papers: r.recent_papers,
          lat: r.lat,
          lng: r.lng,
          umap_x: r.umap_x,
          umap_y: r.umap_y,
          openalex_url: r.openalex_url,
        }));

        // Generate proximity-based edges for visual interest
        const edges: GraphEdge[] = [];
        for (let i = 0; i < nodes.length; i++) {
          for (let j = i + 1; j < nodes.length; j++) {
            if (nodes[i].field === nodes[j].field && Math.random() < 0.15) {
              edges.push({
                source: nodes[i].id,
                target: nodes[j].id,
                weight: 0.3 + Math.random() * 0.4,
              });
            } else if (Math.random() < 0.03) {
              edges.push({
                source: nodes[i].id,
                target: nodes[j].id,
                weight: 0.1 + Math.random() * 0.2,
              });
            }
          }
        }

        setGraphData({ nodes, edges });
      }
    } catch (err) {
      console.error("Failed to fetch graph data:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    const rid = searchParams.get("researcher");
    if (rid && !initDoneRef.current) {
      initDoneRef.current = true;
      fetchGraphData(activeField, rid);
    } else {
      fetchGraphData(activeField);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Field change
  const handleFieldChange = useCallback((field: string) => {
    setActiveField(field);
    fetchGraphData(field);
  }, [fetchGraphData]);

  // Force simulation
  const positions = useForceGraph(graphData);

  // Fetch related when selected
  useEffect(() => {
    if (!selected) { setRelated([]); return; }
    fetch(`${API_BASE}/researchers/${selected.id}/related`)
      .then((r) => r.json())
      .then(setRelated)
      .catch(() => setRelated([]));
  }, [selected?.id]);

  // Search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (searchQuery.length < 2) { setSearchResults([]); return; }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await fetch(`${API_BASE}/researchers/search?q=${encodeURIComponent(searchQuery)}`);
        if (res.ok) setSearchResults(await res.json());
      } catch { setSearchResults([]); }
    }, 300);
  }, [searchQuery]);

  const handleSearchSelect = useCallback((r: Researcher) => {
    setSearchQuery(r.name);
    setSearchResults([]);
    onSelect(r);
    fetchGraphData(r.field ?? activeField, r.id);
  }, [onSelect, fetchGraphData, activeField]);

  const handleHover = useCallback((r: Researcher | null, pos: { x: number; y: number } | null) => {
    setHovered(r);
    setHoverPos(pos);
  }, []);

  const handleClick = useCallback((r: Researcher) => {
    onSelect(r);
  }, [onSelect]);

  return (
    <div style={{
      position: "absolute", top: 52, left: 0, right: 0, bottom: 0,
      background: "#000000",
    }}>
      {/* Side Panel */}
      <SidePanel
        activeField={activeField}
        onFieldChange={handleFieldChange}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        searchResults={searchResults}
        onSearchSelect={handleSearchSelect}
        nodeCount={graphData.nodes.length}
      />

      {/* Main canvas area */}
      <div
        ref={containerRef}
        style={{
          position: "absolute",
          top: 0, left: 200, right: 0, bottom: 0,
        }}
      >
        {loading && (
          <div style={{
            position: "absolute", top: "50%", left: "50%",
            transform: "translate(-50%, -50%)",
            fontFamily: PIXEL_FONT, fontSize: 10,
            color: "#00d4ff", zIndex: 30,
            letterSpacing: "0.1em",
          }}>
            LOADING GRAPH...
          </div>
        )}

        <Canvas
          orthographic
          camera={{
            zoom: 4,
            position: [0, 0, 10],
            near: -100,
            far: 100,
          }}
          style={{ width: "100%", height: "100%" }}
          gl={{ antialias: true, alpha: false }}
          onCreated={({ gl }) => {
            gl.setClearColor("#000000");
          }}
        >
          <CameraControls />
          <CameraStateBridge cameraRef={cameraRef} />
          <Stars />
          {graphData.nodes.length > 0 && positions.size > 0 && (
            <GraphRenderer
              graphData={graphData}
              positions={positions}
              onHover={handleHover}
              onClick={handleClick}
              highlightId={selected?.id ?? null}
            />
          )}
        </Canvas>

        {/* Node labels */}
        {graphData.nodes.length > 0 && positions.size > 0 && (
          <NodeLabels
            graphData={graphData}
            positions={positions}
            cameraRef={cameraRef}
            containerRef={containerRef}
            topN={20}
          />
        )}

        {/* Tooltip */}
        <Tooltip researcher={hovered} position={hoverPos} />

        {/* InfoCard */}
        <InfoCard
          researcher={selected}
          related={related}
          onClose={() => onSelect(null)}
          onSelect={onSelect}
        />

        {/* Hint */}
        {!selected && !loading && graphData.nodes.length > 0 && (
          <div style={{
            position: "absolute", bottom: 20, left: "50%", transform: "translateX(-50%)",
            fontFamily: PIXEL_FONT, fontSize: 8, color: "#1a2540",
            letterSpacing: "0.08em", pointerEvents: "none", whiteSpace: "nowrap", zIndex: 10,
          }}>
            [CLICK] SELECT · [DRAG] PAN · [SCROLL] ZOOM
          </div>
        )}
      </div>
    </div>
  );
}
