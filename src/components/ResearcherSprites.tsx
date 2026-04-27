import { useRef, useMemo, useCallback } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { latLngToVector3 } from "../utils/geoUtils";
import type { Researcher } from "../data/researchers";
import { getFieldColor } from "../data/researchers";

const GLOBE_RADIUS = 2;
const SURFACE_OFFSET = 0.008; // 구체 표면 바로 위

function logScale(v: number, max: number) {
  return max > 0 ? Math.log1p(v) / Math.log1p(max) : 0;
}

// 방사형 그라디언트 캔버스 텍스처 생성 (한 번만)
function makeGlowTexture(hexColor: string): THREE.Texture {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const c = size / 2;
  const grad = ctx.createRadialGradient(c, c, 0, c, c, c);
  grad.addColorStop(0.0, "rgba(255,255,255,1)");
  grad.addColorStop(0.15, hexColor.replace(")", ",0.95)").replace("rgb", "rgba") || hexColor);
  grad.addColorStop(0.4, hexColor + "cc");
  grad.addColorStop(0.7, hexColor + "44");
  grad.addColorStop(1.0, "rgba(0,0,0,0)");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  return tex;
}

// 단순 밝은 흰 코어 텍스처
function makeCoreTexture(): THREE.Texture {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const c = size / 2;
  const grad = ctx.createRadialGradient(c, c, 0, c, c, c);
  grad.addColorStop(0.0, "rgba(255,255,255,1)");
  grad.addColorStop(0.3, "rgba(255,255,255,0.8)");
  grad.addColorStop(1.0, "rgba(255,255,255,0)");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(canvas);
}

interface ResearcherSpritesProps {
  researchers: Researcher[];
  selected: Researcher | null;
  onSelect: (r: Researcher) => void;
  activeField: string | null;
}

// 연구자 한 명의 글로우 스프라이트 (외부 글로우 + 밝은 코어)
function ResearcherDot({
  researcher,
  maxCitations,
  isSelected,
  isFiltered,
  onClick,
  glowTex,
  coreTex,
}: {
  researcher: Researcher;
  maxCitations: number;
  isSelected: boolean;
  isFiltered: boolean;
  onClick: (r: Researcher) => void;
  glowTex: THREE.Texture;
  coreTex: THREE.Texture;
}) {
  const outerRef = useRef<THREE.Sprite>(null!);
  const innerRef = useRef<THREE.Sprite>(null!);

  const n = logScale(researcher.citations, maxCitations);
  const baseSize = 0.04 + n * 0.22; // 0.04 ~ 0.26
  const pos = useMemo(() => {
    const v = latLngToVector3(researcher.lat ?? 0, researcher.lng ?? 0, GLOBE_RADIUS + SURFACE_OFFSET);
    return v;
  }, [researcher.lat, researcher.lng]);

  const opacity = isFiltered ? 0.12 : 1.0;

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    const seed = (researcher.h_index % 17) * 0.4;
    // 느리고 자연스러운 펄스 (도시 불빛처럼)
    const pulse = 0.92 + Math.sin(t * 0.8 + seed) * 0.08;
    const selBoost = isSelected ? 1.4 : 1.0;

    if (outerRef.current) {
      const s = baseSize * 2.2 * pulse * selBoost;
      outerRef.current.scale.setScalar(s);
      (outerRef.current.material as THREE.SpriteMaterial).opacity =
        Math.min(1, (isSelected ? 0.9 : 0.55) * opacity * pulse);
    }
    if (innerRef.current) {
      const s = baseSize * 0.55 * selBoost;
      innerRef.current.scale.setScalar(s);
      (innerRef.current.material as THREE.SpriteMaterial).opacity =
        Math.min(1, (isSelected ? 1.0 : 0.85) * opacity);
    }
  });

  const handleClick = useCallback(
    (e: THREE.Event) => { (e as any).stopPropagation?.(); onClick(researcher); },
    [researcher, onClick]
  );

  return (
    <>
      {/* 바깥 글로우 */}
      <sprite
        ref={outerRef}
        position={pos.toArray()}
        onClick={handleClick}
      >
        <spriteMaterial
          map={glowTex}
          transparent
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </sprite>
      {/* 밝은 코어 */}
      <sprite
        ref={innerRef}
        position={pos.toArray()}
      >
        <spriteMaterial
          map={coreTex}
          transparent
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </sprite>
    </>
  );
}

export function ResearcherSprites({
  researchers,
  selected,
  onSelect,
  activeField,
}: ResearcherSpritesProps) {
  // 분야별 텍스처 (한 번만 생성)
  const textures = useMemo(() => {
    const map = new Map<string, THREE.Texture>();
    researchers.forEach((r) => {
      const hex = getFieldColor(r.field);
      if (!map.has(hex)) map.set(hex, makeGlowTexture(hex));
    });
    return map;
  }, []);

  const coreTex = useMemo(() => makeCoreTexture(), []);
  const maxCitations = useMemo(
    () => Math.max(...researchers.map((r) => r.citations), 1),
    [researchers]
  );

  return (
    <>
      {researchers.map((r) => {
        if (r.lat == null || r.lng == null) return null;
        const hex = getFieldColor(r.field);
        const glowTex = textures.get(hex) ?? coreTex;
        const isFiltered = activeField != null && r.field !== activeField;
        return (
          <ResearcherDot
            key={r.id}
            researcher={r}
            maxCitations={maxCitations}
            isSelected={selected?.id === r.id}
            isFiltered={isFiltered}
            onClick={onSelect}
            glowTex={glowTex}
            coreTex={coreTex}
          />
        );
      })}
    </>
  );
}
