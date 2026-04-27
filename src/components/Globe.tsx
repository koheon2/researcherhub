import { useRef, useMemo } from "react";
import { useFrame, useLoader } from "@react-three/fiber";
import * as THREE from "three";
import { TextureLoader } from "three";

const GLOBE_RADIUS = 2;

export function Globe() {
  const globeRef = useRef<THREE.Mesh>(null!);
  const atmoRef = useRef<THREE.Mesh>(null!);

  const [nightMap] = useLoader(TextureLoader, [
    "https://unpkg.com/three-globe/example/img/earth-night.jpg",
  ]);

  useFrame((_, delta) => {
    globeRef.current.rotation.y += delta * 0.025;
    atmoRef.current.rotation.y += delta * 0.025;
  });

  const atmoMat = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: `
      varying vec3 vNormal;
      void main() {
        vNormal = normalize(normalMatrix * normal);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      varying vec3 vNormal;
      void main() {
        float i = pow(0.7 - dot(vNormal, vec3(0,0,1)), 3.0);
        gl_FragColor = vec4(0.15, 0.45, 1.0, 1.0) * i;
      }
    `,
    blending: THREE.AdditiveBlending,
    side: THREE.BackSide,
    transparent: true,
  }), []);

  return (
    <group>
      <mesh ref={globeRef}>
        <sphereGeometry args={[GLOBE_RADIUS, 64, 64]} />
        <meshBasicMaterial map={nightMap} />
      </mesh>
      <mesh ref={atmoRef} scale={1.12}>
        <sphereGeometry args={[GLOBE_RADIUS, 64, 64]} />
        <primitive object={atmoMat} />
      </mesh>
    </group>
  );
}
