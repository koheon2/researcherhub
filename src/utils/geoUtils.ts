import * as THREE from "three";

export function latLngToVector3(lat: number, lng: number, radius: number): THREE.Vector3 {
  const phi = (90 - lat) * (Math.PI / 180);
  const theta = (lng + 180) * (Math.PI / 180);
  return new THREE.Vector3(
    -radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta)
  );
}

// Normalize citation count to pillar height
export function citationsToHeight(citations: number, maxCitations: number): number {
  const minHeight = 0.05;
  const maxHeight = 1.8;
  const normalized = Math.sqrt(citations) / Math.sqrt(maxCitations);
  return minHeight + normalized * (maxHeight - minHeight);
}

// Normalize for glow intensity
export function citationsToGlow(citations: number, maxCitations: number): number {
  return 0.3 + (Math.sqrt(citations) / Math.sqrt(maxCitations)) * 0.7;
}
