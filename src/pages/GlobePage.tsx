import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { CesiumGlobe } from "../components/CesiumGlobe";
import { InfoCard }    from "../components/InfoCard";
import { SidePanel }   from "../components/SidePanel";
import type { Researcher } from "../data/researchers";

const API_BASE = "http://localhost:8000/api";
const PIXEL_FONT = "'Press Start 2P', monospace";
const MONO_FONT  = "'Share Tech Mono', monospace";

type TileStyle = "dark" | "light" | "voyager";

interface Props {
  selected:    Researcher | null;
  onSelect:    (r: Researcher | null) => void;
  visibleCount: number;
  onCountChange: (n: number) => void;
}

export function GlobePage({ selected, onSelect, visibleCount: _visibleCount, onCountChange }: Props) {
  const [activeField, setActiveField]   = useState<string | null>(null);
  const [tileStyle, setTileStyle]       = useState<TileStyle>("dark");
  const [related, setRelated]           = useState<Researcher[]>([]);
  const [filterCountry, setFilterCountry] = useState<string | null>(null);
  const [focusCity, setFocusCity]       = useState<string | null>(null);
  const [filterLabel, setFilterLabel]   = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const [highlightIds, setHighlightIds] = useState<string[]>([]);
  const [highlightedResearchers, setHighlightedResearchers] = useState<Researcher[]>([]);

  // Parse URL params: highlight, field, country, city
  useEffect(() => {
    const hlParam  = searchParams.get("highlight");
    const field    = searchParams.get("field");
    const country  = searchParams.get("country");
    const city     = searchParams.get("city");

    if (hlParam) {
      setHighlightIds(hlParam.split(",").filter(Boolean));
    } else {
      setHighlightIds([]);
      setHighlightedResearchers([]);
    }

    if (field)   setActiveField(field);
    if (country) setFilterCountry(country.toUpperCase());
    if (city)    setFocusCity(city);

    // Build human-readable filter label
    const parts = [];
    if (field)   parts.push(field);
    if (city)    parts.push(city);
    else if (country) parts.push(country.toUpperCase());
    setFilterLabel(parts.length > 0 ? parts.join(" · ") : null);
  }, [searchParams]);

  // Fetch highlighted researchers from backend
  useEffect(() => {
    if (highlightIds.length === 0) {
      setHighlightedResearchers([]);
      return;
    }
    fetch(`${API_BASE}/researchers/by-openalex-ids?ids=${highlightIds.join(",")}`)
      .then(r => r.json())
      .then((data: Researcher[]) => setHighlightedResearchers(data))
      .catch(() => setHighlightedResearchers([]));
  }, [highlightIds]);

  // Clear all filters
  const clearAll = useCallback(() => {
    setHighlightIds([]);
    setHighlightedResearchers([]);
    setActiveField(null);
    setFilterCountry(null);
    setFocusCity(null);
    setFilterLabel(null);
    setSearchParams({});
  }, [setSearchParams]);

  useEffect(() => {
    if (!selected) { setRelated([]); return; }
    fetch(`${API_BASE}/researchers/${selected.id}/related`)
      .then((r) => r.json())
      .then(setRelated)
      .catch(() => setRelated([]));
  }, [selected?.id]);

  return (
    <>
      <CesiumGlobe
        selected={selected}
        related={related}
        onSelect={onSelect}
        activeField={activeField}
        filterCountry={filterCountry}
        focusCity={focusCity}
        tileStyle={tileStyle}
        onCountChange={onCountChange}
        highlightIds={highlightIds}
        highlightedResearchers={highlightedResearchers}
      />

      <SidePanel
        activeField={activeField}
        onFieldChange={setActiveField}
        tileStyle={tileStyle}
        onTileChange={setTileStyle}
        selected={selected}
        onSelect={onSelect}
      />

      <InfoCard
        researcher={selected}
        related={related}
        onClose={() => onSelect(null)}
        onSelect={onSelect}
      />

      {/* Filter / highlight banner */}
      {(filterLabel || highlightedResearchers.length > 0) && (
        <div style={{
          position: "absolute", top: 60, left: "50%", transform: "translateX(-50%)",
          background: "#0d1117ee", border: "1px solid #1e4976",
          padding: "8px 18px",
          display: "flex", alignItems: "center", gap: 14,
          zIndex: 20,
        }}>
          <span style={{ fontFamily: PIXEL_FONT, fontSize: 8, color: "#60a5fa", letterSpacing: ".06em" }}>
            {filterLabel && `FILTER: ${filterLabel}`}
            {filterLabel && highlightedResearchers.length > 0 && "  ·  "}
            {highlightedResearchers.length > 0 &&
              `${highlightedResearchers.length} HIGHLIGHTED`}
          </span>
          <button
            onClick={clearAll}
            style={{
              background: "none", border: "1px solid #334155",
              color: "#475569", cursor: "pointer",
              fontFamily: MONO_FONT, fontSize: 12, padding: "2px 8px",
            }}
          >×</button>
        </div>
      )}

      {!selected && highlightedResearchers.length === 0 && (
        <div style={{
          position: "absolute", bottom: 20, left: "50%", transform: "translateX(-50%)",
          fontFamily: PIXEL_FONT, fontSize: 8, color: "#1a2540",
          letterSpacing: "0.08em", pointerEvents: "none", whiteSpace: "nowrap", zIndex: 10,
        }}>
          [CLICK] SELECT &nbsp;·&nbsp; [DRAG] ROTATE &nbsp;·&nbsp; [SCROLL] ZOOM
        </div>
      )}
    </>
  );
}
