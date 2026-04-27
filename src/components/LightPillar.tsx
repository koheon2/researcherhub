import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { latLngToVector3 } from "../utils/geoUtils";
import type { Researcher } from "../data/researchers";
import { getFieldColor } from "../data/researchers";

const GLOBE_RADIUS = 2;

interface LightPillarProps {
  researcher: Researcher;
  maxCitations: number;
  onClick: (r: Researcher) => void;
  isSelected: boolean;
  isHighlighted: boolean;
}

function logScale(value: number, max: number): number {
  if (value <= 0 || max <= 0) return 0;
  return Math.log(value + 1) / Math.log(max + 1);
}

export function LightPillar({
  researcher,
  maxCitations,
  onClick,
  isSelected,
  isHighlighted,
}: LightPillarProps) {
  const coreRef = useRef<THREE.Mesh>(null!);
  const glowRef = useRef<THREE.Mesh>(null!);
  const topRef = useRef<THREE.Mesh>(null!);

  const normalized = logScale(researcher.citations, maxCitations);
  const height = 0.04 + normalized * 0.55;        // 픽셀 블록 높이
  const width = 0.008 + (researcher.h_index / 200) * 0.016; // 폭 = h-index 반영
  const glowIntensity = 0.25 + normalized * 0.75;
  const highlightBoost = isHighlighted ? 1.4 : 1.0;
  const color = new THREE.Color(getFieldColor(researcher.field));

  const basePos = useMemo(
    () => latLngToVector3(researcher.lat ?? 0, researcher.lng ?? 0, GLOBE_RADIUS),
    [researcher.lat, researcher.lng]
  );

  const quaternion = useMemo(() => {
    const up = new THREE.Vector3(0, 1, 0);
    const dir = basePos.clone().normalize();
    return new THREE.Quaternion().setFromUnitVectors(up, dir);
  }, [basePos]);

  const pillarPos = useMemo(
    () => basePos.clone().add(basePos.clone().normalize().multiplyScalar(height / 2)),
    [basePos, height]
  );

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    const seed = researcher.h_index * 0.1;

    if (coreRef.current) {
      // 픽셀 아트 feel: 스텝 pulse (부드럽지 않고 끊기는 느낌)
      const raw = Math.sin(t * 2 + seed);
      const stepped = Math.round(raw * 4) / 4; // 0.25 단위로 양자화
      const pulse = (isSelected ? 1.3 + stepped * 0.2 : 1.0 + stepped * 0.04) * highlightBoost;
      coreRef.current.scale.setScalar(pulse);
    }

    if (glowRef.current) {
      const mat = glowRef.current.material as THREE.MeshBasicMaterial;
      const flicker = isSelected
        ? 0.4 + Math.sin(t * 6 + seed) * 0.1
        : glowIntensity * 0.15 * highlightBoost;
      mat.opacity = flicker;
    }

    if (topRef.current) {
      // 선택된 연구자의 top 큐브는 회전
      if (isSelected) {
        topRef.current.rotation.y += 0.05;
        topRef.current.rotation.x += 0.03;
      }
    }
  });

  return (
    <group
      position={pillarPos.toArray()}
      quaternion={quaternion}
      onClick={(e) => {
        e.stopPropagation();
        onClick(researcher);
      }}
    >
      {/* 픽셀 블록 기둥 (BoxGeometry) */}
      <mesh ref={coreRef}>
        <boxGeometry args={[width, height, width]} />
        <meshBasicMaterial
          color={isSelected ? "#ffffff" : color}
          transparent
          opacity={isSelected || isHighlighted ? 1.0 : 0.85}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>

      {/* 외곽 글로우 박스 (살짝 더 큰 반투명) */}
      <mesh ref={glowRef}>
        <boxGeometry args={[width * 3, height * 1.05, width * 3]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={glowIntensity * 0.15}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>

      {/* 꼭대기 픽셀 큐브 */}
      <mesh ref={topRef} position={[0, height / 2 + width, 0]}>
        <boxGeometry args={[width * 2.5, width * 2.5, width * 2.5]} />
        <meshBasicMaterial
          color={isSelected ? "#ffffff" : color}
          transparent
          opacity={isSelected ? 1.0 : 0.9}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>

      {/* 베이스 픽셀 헤일로 (얇은 박스 링) */}
      <mesh position={[0, -height / 2, 0]}>
        <boxGeometry args={[width * 6, width * 0.5, width * 6]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={0.25 * glowIntensity}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
    </group>
  );
}
