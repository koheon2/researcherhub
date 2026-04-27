import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import type { Researcher } from "../data/researchers";
import { getFieldColor } from "../data/researchers";

const API_BASE = "http://localhost:8000/api";

// ── LOD 레벨 정의 ─────────────────────────────────────────────────────────────
const LOD_LEVELS = [
  { minAlt: 5_000_000, limit: 500,   minCitations: 5000, useBbox: false },
  { minAlt: 1_500_000, limit: 2000,  minCitations: 500,  useBbox: true  },
  { minAlt: 300_000,   limit: 5000,  minCitations: 0,    useBbox: true  },
  { minAlt: 0,         limit: 10000, minCitations: 0,    useBbox: true  },
] as const;

function getTileUrl(style: "dark" | "light" | "voyager") {
  const base = "https://{s}.basemaps.cartocdn.com";
  if (style === "dark")    return `${base}/dark_all/{z}/{x}/{y}.png`;
  if (style === "light")   return `${base}/light_all/{z}/{x}/{y}.png`;
  return `${base}/rastertiles/voyager/{z}/{x}/{y}.png`;
}

function emphasisScale(v: number, max: number): number {
  if (max <= 0) return 0;
  const log = Math.log1p(v) / Math.log1p(max);
  return log * log;
}

// ── Deterministic jitter: spreads co-located researchers ~9km apart ───────────
function idHash(id: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

function computeJitter(id: string): [number, number] {
  const h = idHash(id);
  const angle = ((h & 0xffff) / 0xffff) * Math.PI * 2;
  const radius = ((h >> 16) & 0xff) / 255 * 0.08; // max 0.08° ≈ ~9km
  return [Math.sin(angle) * radius, Math.cos(angle) * radius];
}

// ── PulseMeta ─────────────────────────────────────────────────────────────────
interface PulseMeta {
  idx: number;
  baseAlpha: number;
  phase: number;
  cr: number; cg: number; cb: number;
}

// ── Arc positions (great circle via EllipsoidGeodesic) ────────────────────────
function makeArcPositions(
  lng1: number, lat1: number,
  lng2: number, lat2: number,
  n = 80,
): Cesium.Cartesian3[] {
  const start    = Cesium.Cartographic.fromDegrees(lng1, lat1);
  const end      = Cesium.Cartographic.fromDegrees(lng2, lat2);
  const geodesic = new Cesium.EllipsoidGeodesic(start, end);
  const distDeg  = Math.hypot(lat2 - lat1, lng2 - lng1);
  const peakH    = Math.min(800_000, Math.max(80_000, distDeg * 80_000));

  const pts: Cesium.Cartesian3[] = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    const c = geodesic.interpolateUsingFraction(t);
    const h = peakH * 4 * t * (1 - t);
    pts.push(Cesium.Cartesian3.fromRadians(c.longitude, c.latitude, h));
  }
  return pts;
}

// ── buildPoints ───────────────────────────────────────────────────────────────
// Size budget (px, before NearFarScalar):
//   normal  core≤7  mid≤14  outer≤28
//   selected core≤15 mid≤30  outer≤60
// NearFarScalar: ×1.2 at 30km alt, ×0.35 at 20M alt
//   → at closest zoom: outer_normal=34px, outer_selected=72px  ✓
function buildPoints(
  viewer: Cesium.Viewer,
  researchers: Researcher[],
  selected: Researcher | null,
  related: Researcher[],
  activeField: string | null,
  colRef: React.MutableRefObject<Cesium.PointPrimitiveCollection | null>,
  jitterMap: Map<string, [number, number]>,
): PulseMeta[] {
  if (colRef.current && !colRef.current.isDestroyed()) {
    viewer.scene.primitives.remove(colRef.current);
  }
  colRef.current = null;

  const filtered = activeField
    ? researchers.filter((r) => r.field === activeField)
    : researchers;
  if (filtered.length === 0) return [];

  const maxCitations = Math.max(...filtered.map((r) => r.citations), 1);
  const col = new Cesium.PointPrimitiveCollection();
  viewer.scene.primitives.add(col);
  colRef.current = col;

  const relatedIds  = new Set(related.map((r) => r.id));
  const hasSelection = selected !== null;
  const pulseMeta: PulseMeta[] = [];
  let pointIdx = 0;

  // Scale: conservative near-far so close zoom doesn't balloon
  const scale = new Cesium.NearFarScalar(3e4, 1.2, 2e7, 0.35);

  filtered.forEach((r) => {
    if (r.lat == null || r.lng == null) return;

    const [djlat, djlng] = jitterMap.get(r.id) ?? [0, 0];
    const hex   = getFieldColor(r.field);
    const color = Cesium.Color.fromCssColorString(hex);
    const n     = emphasisScale(r.citations, maxCitations);
    const isSel     = selected?.id === r.id;
    const isRelated = relatedIds.has(r.id);
    const dimFactor = hasSelection && !isSel && !isRelated ? 0.18 : 1.0;

    const pos = Cesium.Cartesian3.fromDegrees(
      r.lng + djlng,
      r.lat + djlat,
      100,
    );

    // Core size: normal 2–7px, selected 5–15px
    const coreSize = isSel ? 5 + n * 10 : 2 + n * 5;
    const midSize  = coreSize * 2.2;
    const outerSize = coreSize * 4.5;

    const outerAlpha = isSel ? 0.18 : (0.015 + n * 0.10) * dimFactor;
    const midAlpha   = isSel ? 0.50 : (0.05  + n * 0.22) * dimFactor;

    // Outer halo
    col.add({
      position: pos,
      color: color.withAlpha(outerAlpha),
      pixelSize: outerSize,
      scaleByDistance: scale,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    });
    // Mid glow
    col.add({
      position: pos,
      color: color.withAlpha(midAlpha),
      pixelSize: midSize,
      scaleByDistance: scale,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    });
    // Core
    col.add({
      position: pos,
      color: isSel
        ? Cesium.Color.WHITE
        : new Cesium.Color(
            color.red   * 0.4 + 0.6,
            color.green * 0.4 + 0.6,
            color.blue  * 0.4 + 0.6,
            (0.35 + n * 0.60) * dimFactor,
          ),
      pixelSize: coreSize,
      scaleByDistance: scale,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    });

    if (n > 0.25 && (!hasSelection || isSel || isRelated)) {
      pulseMeta.push({
        idx: pointIdx * 3,
        baseAlpha: (0.015 + n * 0.10) * dimFactor,
        phase: ((r.lat ?? 0) * 73 + (r.lng ?? 0) * 37) % (Math.PI * 2),
        cr: color.red,
        cg: color.green,
        cb: color.blue,
      });
    }

    pointIdx++;
  });

  return pulseMeta;
}

// ── Props ─────────────────────────────────────────────────────────────────────
/* ── City / country lookup for camera focus ── */
const CITY_COORDS: Record<string, [number, number]> = {
  seoul: [37.5665, 126.9780], busan: [35.1796, 129.0756],
  tokyo: [35.6762, 139.6503], osaka: [34.6937, 135.5023],
  beijing: [39.9042, 116.4074], shanghai: [31.2304, 121.4737],
  "new york": [40.7128, -74.0060], "san francisco": [37.7749, -122.4194],
  boston: [42.3601, -71.0589], chicago: [41.8781, -87.6298],
  london: [51.5074, -0.1278], paris: [48.8566, 2.3522],
  berlin: [52.5200, 13.4050], amsterdam: [52.3676, 4.9041],
  toronto: [43.6532, -79.3832], montreal: [45.5017, -73.5673],
  singapore: [1.3521, 103.8198], sydney: [-33.8688, 151.2093],
  zurich: [47.3769, 8.5417], cambridge: [52.2053, 0.1218],
  stanford: [37.4275, -122.1697],
};
const COUNTRY_COORDS: Record<string, [number, number, number]> = {
  // [lat, lng, altitude_km]
  kr: [36.5, 127.9, 800], us: [38.0, -97.0, 4000], jp: [36.2, 138.2, 1200],
  cn: [35.9, 104.2, 4000], de: [51.2, 10.5, 1000], gb: [55.4, -3.4, 900],
  fr: [46.2, 2.2, 1000], ca: [60.0, -96.8, 4000], au: [-27.0, 133.8, 3500],
  in: [20.6, 78.9, 3000], sg: [1.35, 103.82, 200], ch: [46.8, 8.2, 400],
  nl: [52.1, 5.3, 400], se: [62.2, 17.6, 800], il: [31.5, 34.8, 400],
  br: [-14.2, -51.9, 4000], it: [41.9, 12.6, 1000], es: [40.5, -3.7, 1000],
};

interface Props {
  selected: Researcher | null;
  related: Researcher[];
  onSelect: (r: Researcher) => void;
  activeField: string | null;
  filterCountry: string | null;
  focusCity: string | null;
  tileStyle: "dark" | "light" | "voyager";
  onCountChange?: (count: number) => void;
  highlightIds?: string[];
  highlightedResearchers?: Researcher[];
}

export function CesiumGlobe({ selected, related, onSelect, activeField, filterCountry, focusCity, tileStyle, onCountChange }: Props) {
  const containerRef   = useRef<HTMLDivElement>(null);
  const viewerRef      = useRef<Cesium.Viewer | null>(null);
  const pointColRef    = useRef<Cesium.PointPrimitiveCollection | null>(null);
  const arcColRef      = useRef<Cesium.PolylineCollection | null>(null);
  const researchersRef = useRef<Researcher[]>([]);
  const activeFieldRef    = useRef<string | null>(activeField);
  const filterCountryRef  = useRef<string | null>(filterCountry);
  const selectedRef    = useRef<Researcher | null>(selected);
  const relatedRef     = useRef<Researcher[]>([]);
  const pulseMetaRef   = useRef<PulseMeta[]>([]);
  const debounceRef    = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastLodRef     = useRef<string>("");
  // Jitter map: researcher id → [dlat, dlng], computed once per researcher
  const jitterMapRef   = useRef<Map<string, [number, number]>>(new Map());

  useEffect(() => { activeFieldRef.current = activeField; }, [activeField]);
  useEffect(() => { filterCountryRef.current = filterCountry; }, [filterCountry]);
  useEffect(() => { selectedRef.current = selected; }, [selected]);

  // ── LOD fetch ──────────────────────────────────────────────────────────────
  const fetchResearchers = useCallback(async (viewer: Cesium.Viewer) => {
    const alt = viewer.camera.positionCartographic.height;
    const lod = LOD_LEVELS.find((l) => alt >= l.minAlt) ?? LOD_LEVELS[LOD_LEVELS.length - 1];

    const params = new URLSearchParams({
      limit: String(lod.limit),
      min_citations: String(lod.minCitations),
    });

    if (lod.useBbox) {
      const rect = viewer.camera.computeViewRectangle(
        viewer.scene.globe.ellipsoid,
        new Cesium.Rectangle(),
      );
      if (rect) {
        params.set("lat_min", String(Cesium.Math.toDegrees(rect.south).toFixed(4)));
        params.set("lat_max", String(Cesium.Math.toDegrees(rect.north).toFixed(4)));
        params.set("lng_min", String(Cesium.Math.toDegrees(rect.west).toFixed(4)));
        params.set("lng_max", String(Cesium.Math.toDegrees(rect.east).toFixed(4)));
      }
    }

    if (activeFieldRef.current) {
      params.set("field", activeFieldRef.current);
    }
    if (filterCountryRef.current) {
      params.set("country", filterCountryRef.current);
    }

    const key = params.toString();
    if (key === lastLodRef.current) return;
    lastLodRef.current = key;

    try {
      const res  = await fetch(`${API_BASE}/researchers/?${key}`);
      const data: Researcher[] = await res.json();
      const withCoords = data.filter((r) => r.lat != null && r.lng != null);
      researchersRef.current = withCoords;
      onCountChange?.(withCoords.length);

      // Build jitter map for new researcher set (deterministic, stable)
      const jm = jitterMapRef.current;
      for (const r of withCoords) {
        if (!jm.has(r.id)) jm.set(r.id, computeJitter(r.id));
      }

      const v = viewerRef.current;
      if (v && !v.isDestroyed()) {
        const pm = buildPoints(v, withCoords, selectedRef.current, relatedRef.current, activeFieldRef.current, pointColRef, jm);
        pulseMetaRef.current = pm;
      }
    } catch (e) {
      console.error("Fetch failed:", e);
    }
  }, [onCountChange]);

  const scheduleFetch = useCallback((viewer: Cesium.Viewer) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchResearchers(viewer), 500);
  }, [fetchResearchers]);

  // ── Viewer init ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;
    let destroyed = false;

    const initialProvider = new Cesium.UrlTemplateImageryProvider({
      url: getTileUrl("dark"),
      subdomains: "abcd",
      minimumLevel: 0,
      maximumLevel: 19,
      credit: new Cesium.Credit("\u00A9 OpenStreetMap contributors \u00A9 CartoDB"),
    });

    const viewer = new Cesium.Viewer(containerRef.current, {
      baseLayer: new Cesium.ImageryLayer(initialProvider),
      terrainProvider: new Cesium.EllipsoidTerrainProvider(),
      timeline: false,
      animation: false,
      homeButton: false,
      sceneModePicker: false,
      baseLayerPicker: false,
      geocoder: false,
      navigationHelpButton: false,
      infoBox: false,
      selectionIndicator: false,
      skyBox: false,
      skyAtmosphere: new Cesium.SkyAtmosphere(),
    });

    if (destroyed) { viewer.destroy(); return; }
    viewerRef.current = viewer;

    viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#000005");
    viewer.scene.globe.enableLighting = false;
    viewer.scene.globe.showGroundAtmosphere = true;
    viewer.scene.globe.atmosphereLightIntensity = 8.0;

    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(20, 15, 18_000_000),
    });

    viewer.camera.changed.addEventListener(() => scheduleFetch(viewer));
    viewer.camera.moveEnd.addEventListener(() => fetchResearchers(viewer));

    fetchResearchers(viewer);

    // ── postRender: cull + pulse ─────────────────────────────────────────────
    const _camDir = new Cesium.Cartesian3();
    const _ptNorm = new Cesium.Cartesian3();
    const cullListener = viewer.scene.postRender.addEventListener(() => {
      const col = pointColRef.current;
      if (!col || col.isDestroyed()) return;
      Cesium.Cartesian3.normalize(viewer.camera.position, _camDir);

      // 1. Back-face culling
      for (let i = 0; i < col.length; i++) {
        const pt = col.get(i);
        Cesium.Cartesian3.normalize(pt.position, _ptNorm);
        pt.show = Cesium.Cartesian3.dot(_ptNorm, _camDir) > 0;
      }

      // 2. Pulsing (outer halo only)
      const t = Date.now() / 1000;
      for (const meta of pulseMetaRef.current) {
        if (meta.idx >= col.length) continue;
        const pt = col.get(meta.idx);
        if (!pt || !pt.show) continue;
        const pulse = 0.5 + 0.5 * Math.sin(t * 1.3 + meta.phase);
        pt.color = new Cesium.Color(meta.cr, meta.cg, meta.cb, meta.baseAlpha * (0.55 + 0.45 * pulse));
      }
    });

    // ── Click handler ────────────────────────────────────────────────────────
    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((e: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
      const ray  = viewer.camera.getPickRay(e.position);
      if (!ray) return;
      const globe = viewer.scene.globe.pick(ray, viewer.scene);
      if (!globe) return;
      const carto    = Cesium.Cartographic.fromCartesian(globe);
      const clickLat = Cesium.Math.toDegrees(carto.latitude);
      const clickLng = Cesium.Math.toDegrees(carto.longitude);

      let closest: Researcher | null = null;
      let minDist = Infinity;
      const curField = activeFieldRef.current;
      const visible  = curField
        ? researchersRef.current.filter((r) => r.field === curField)
        : researchersRef.current;

      const jm = jitterMapRef.current;
      visible.forEach((r) => {
        if (r.lat == null || r.lng == null) return;
        const [djlat, djlng] = jm.get(r.id) ?? [0, 0];
        const dist = Math.hypot((r.lat + djlat) - clickLat, (r.lng + djlng) - clickLng);
        if (dist < minDist) { minDist = dist; closest = r; }
      });
      if (closest && minDist < 5) onSelect(closest);
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    return () => {
      destroyed = true;
      if (debounceRef.current) clearTimeout(debounceRef.current);
      cullListener();
      handler.destroy();
      viewer.destroy();
      viewerRef.current = null;
    };
  }, []);

  // ── Tile style ─────────────────────────────────────────────────────────────
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;
    const provider = new Cesium.UrlTemplateImageryProvider({
      url: getTileUrl(tileStyle),
      subdomains: "abcd",
      minimumLevel: 0,
      maximumLevel: 19,
      credit: new Cesium.Credit("\u00A9 OpenStreetMap contributors \u00A9 CartoDB"),
    });
    viewer.imageryLayers.removeAll();
    viewer.imageryLayers.addImageryProvider(provider);
  }, [tileStyle]);

  // ── activeField / filterCountry change → refetch ──────────────────────────
  useEffect(() => {
    lastLodRef.current = "";
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;
    fetchResearchers(viewer);
  }, [activeField, filterCountry, fetchResearchers]);

  // ── focusCity / filterCountry → fly camera ────────────────────────────────
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;

    if (focusCity) {
      const key = focusCity.toLowerCase();
      const coords = CITY_COORDS[key];
      if (coords) {
        viewer.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(coords[1], coords[0], 300_000),
          duration: 2.0,
          orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
        });
        return;
      }
    }
    if (filterCountry) {
      const entry = COUNTRY_COORDS[filterCountry.toLowerCase()];
      if (entry) {
        viewer.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(entry[1], entry[0], entry[2] * 1000),
          duration: 2.0,
          orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
        });
      }
    }
  }, [focusCity, filterCountry]);

  // ── selected/related change: rebuild points ────────────────────────────────
  useEffect(() => {
    relatedRef.current = related;
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;
    const pm = buildPoints(viewer, researchersRef.current, selected, related, activeFieldRef.current, pointColRef, jitterMapRef.current);
    pulseMetaRef.current = pm;
  }, [selected, related]);

  // ── Arc effect ─────────────────────────────────────────────────────────────
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;

    if (arcColRef.current && !arcColRef.current.isDestroyed()) {
      viewer.scene.primitives.remove(arcColRef.current);
      arcColRef.current = null;
    }

    if (!selected?.lat || !selected?.lng || related.length === 0) return;

    const arcCol = new Cesium.PolylineCollection();
    viewer.scene.primitives.add(arcCol);
    arcColRef.current = arcCol;

    const fieldColor = Cesium.Color.fromCssColorString(getFieldColor(selected.field));

    // Use jittered coords so arcs originate from the rendered dot position
    const jm = jitterMapRef.current;
    const [sdjlat, sdjlng] = jm.get(selected.id) ?? [0, 0];
    const selLat = selected.lat + sdjlat;
    const selLng = selected.lng + sdjlng;

    related
      .filter((r) => r.lat != null && r.lng != null)
      .slice(0, 6)
      .forEach((r, i) => {
        const [rdjlat, rdjlng] = jm.get(r.id) ?? [0, 0];
        const alpha     = Math.max(0.12, 0.60 - i * 0.08);
        const positions = makeArcPositions(selLng, selLat, r.lng! + rdjlng, r.lat! + rdjlat);
        const line      = arcCol.add({ positions, width: 1.5 });
        line.material   = Cesium.Material.fromType("PolylineDash", {
          color: fieldColor.withAlpha(alpha),
          gapColor: Cesium.Color.TRANSPARENT,
          dashLength: 20.0,
          dashPattern: 255,
        });
      });
  }, [selected?.id, related]);

  // ── Fly-to ─────────────────────────────────────────────────────────────────
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed() || !selected) return;
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(
        selected.lng ?? 0,
        selected.lat ?? 0,
        related.length > 0 ? 1_500_000 : 80_000,
      ),
      duration: 1.8,
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
    });
  }, [selected?.id, related.length]);

  return <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />;
}
