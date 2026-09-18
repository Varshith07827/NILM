/**
 * Appliance geometry.
 *
 * Every appliance is built from primitives (boxes, cylinders, cones) rather than
 * loaded from a GLTF file. That keeps the project self-contained — no binary
 * assets to ship, no licence questions, no loading states — and a low-poly
 * stylised look actually reads *better* at this scale than a detailed model
 * would.
 *
 * Each model receives its live state and is expected to show it physically:
 * fan blades spin at a speed proportional to draw, the induction hob glows,
 * the washing machine drum turns, the TV screen flickers. The visual is driven
 * by the same numbers as the dashboard, so the two can never disagree.
 */

import { useFrame } from "@react-three/fiber";
import { useRef, type ReactNode } from "react";
import * as THREE from "three";

export interface ModelProps {
  /** True when the detector says this appliance is drawing power. */
  active: boolean;
  /** Estimated draw in watts. */
  power: number;
  /** Nameplate rating, used to normalise animation speed and glow. */
  ratedPower: number;
  /** The appliance's dashboard colour. */
  colour: string;
}

/** Normalised 0..1 load, used for glow and animation speed. */
function loadRatio({ active, power, ratedPower }: ModelProps): number {
  if (!active || ratedPower <= 0) return 0;
  return Math.min(1, Math.max(0.15, power / ratedPower));
}

const OFF_COLOUR = "#38445a";

/** Shared body material: neutral when off, tinted and lit when running. */
function Body({
  active,
  colour,
  emissive = 0.35,
  metalness = 0.25,
  roughness = 0.55,
  children,
}: {
  active: boolean;
  colour: string;
  emissive?: number;
  metalness?: number;
  roughness?: number;
  children?: ReactNode;
}) {
  return (
    <meshStandardMaterial
      color={active ? colour : OFF_COLOUR}
      emissive={active ? colour : "#000000"}
      emissiveIntensity={active ? emissive : 0}
      metalness={metalness}
      roughness={roughness}
    >
      {children}
    </meshStandardMaterial>
  );
}

// --------------------------------------------------------------------------- //
// Individual appliances
// --------------------------------------------------------------------------- //

function CeilingFan(props: ModelProps) {
  const blades = useRef<THREE.Group>(null);
  const ratio = loadRatio(props);

  useFrame((_, delta) => {
    if (blades.current) {
      // A ceiling fan at full tilt is roughly 300 rpm; scale with draw so a
      // regulator set low visibly spins slower.
      blades.current.rotation.y += delta * (2 + ratio * 22);
    }
  });

  return (
    <group>
      {/* drop rod up to the ceiling */}
      <mesh position={[0, 0.3, 0]}>
        <cylinderGeometry args={[0.025, 0.025, 0.6, 8]} />
        <meshStandardMaterial color="#4b5769" metalness={0.6} roughness={0.4} />
      </mesh>
      {/* motor housing */}
      <mesh castShadow>
        <cylinderGeometry args={[0.17, 0.2, 0.14, 20]} />
        <Body {...props} emissive={0.25} metalness={0.5} />
      </mesh>
      <group ref={blades}>
        {[0, 1, 2].map((index) => (
          <mesh
            key={index}
            position={[
              Math.cos((index * Math.PI * 2) / 3) * 0.52,
              -0.03,
              Math.sin((index * Math.PI * 2) / 3) * 0.52,
            ]}
            rotation={[0, -(index * Math.PI * 2) / 3, 0.04]}
            castShadow
          >
            <boxGeometry args={[0.92, 0.022, 0.2]} />
            <meshStandardMaterial
              color={props.active ? props.colour : OFF_COLOUR}
              metalness={0.2}
              roughness={0.6}
              transparent
              opacity={ratio > 0.4 ? 0.75 : 1}
            />
          </mesh>
        ))}
      </group>
    </group>
  );
}

function LedLight(props: ModelProps) {
  const ratio = loadRatio(props);
  return (
    <group>
      <mesh position={[0, 0.16, 0]}>
        <cylinderGeometry args={[0.02, 0.02, 0.32, 6]} />
        <meshStandardMaterial color="#4b5769" />
      </mesh>
      <mesh castShadow>
        <cylinderGeometry args={[0.2, 0.26, 0.1, 20]} />
        <meshStandardMaterial color="#8894a8" metalness={0.4} roughness={0.5} />
      </mesh>
      {/* the emitting face */}
      <mesh position={[0, -0.055, 0]}>
        <cylinderGeometry args={[0.21, 0.21, 0.02, 20]} />
        <meshStandardMaterial
          color={props.active ? "#fff6d8" : "#39435a"}
          emissive={props.active ? "#ffe9a8" : "#000000"}
          emissiveIntensity={props.active ? 1.6 : 0}
        />
      </mesh>
      {props.active ? (
        <pointLight
          position={[0, -0.3, 0]}
          color="#ffe7ae"
          intensity={14 * ratio}
          distance={5}
          decay={2}
        />
      ) : null}
    </group>
  );
}

function TubeLight(props: ModelProps) {
  const ratio = loadRatio(props);
  return (
    <group>
      <mesh position={[0, 0.12, 0]}>
        <boxGeometry args={[1.3, 0.07, 0.14]} />
        <meshStandardMaterial color="#8894a8" metalness={0.4} roughness={0.5} />
      </mesh>
      <mesh castShadow rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.055, 0.055, 1.25, 12]} />
        <meshStandardMaterial
          color={props.active ? "#f2fbff" : "#39435a"}
          emissive={props.active ? "#cfeeff" : "#000000"}
          emissiveIntensity={props.active ? 1.5 : 0}
        />
      </mesh>
      {props.active ? (
        <pointLight
          position={[0, -0.35, 0]}
          color="#d8f2ff"
          intensity={16 * ratio}
          distance={6}
          decay={2}
        />
      ) : null}
    </group>
  );
}

function Television(props: ModelProps) {
  const screen = useRef<THREE.MeshStandardMaterial>(null);
  const ratio = loadRatio(props);

  useFrame((state) => {
    if (!screen.current) return;
    if (!props.active) {
      screen.current.emissiveIntensity = 0;
      return;
    }
    // Backlight flicker: a slow scene-change wobble, not a strobe.
    const t = state.clock.elapsedTime;
    screen.current.emissiveIntensity =
      0.85 + Math.sin(t * 1.7) * 0.16 + Math.sin(t * 4.3) * 0.06;
  });

  return (
    <group>
      {/* bezel */}
      <mesh castShadow>
        <boxGeometry args={[0.07, 0.66, 1.15]} />
        <meshStandardMaterial color="#1b2130" metalness={0.5} roughness={0.4} />
      </mesh>
      {/* screen */}
      <mesh position={[0.042, 0, 0]}>
        <boxGeometry args={[0.012, 0.58, 1.06]} />
        <meshStandardMaterial
          ref={screen}
          color={props.active ? "#8fd8ff" : "#222b3b"}
          emissive={props.active ? props.colour : "#000000"}
          emissiveIntensity={props.active ? 0.9 : 0}
        />
      </mesh>
      {/* stand */}
      <mesh position={[0, -0.38, 0]}>
        <boxGeometry args={[0.24, 0.1, 0.5]} />
        <meshStandardMaterial color="#1b2130" />
      </mesh>
      {props.active ? (
        <pointLight
          position={[0.5, 0, 0]}
          color={props.colour}
          intensity={10 * ratio}
          distance={4.5}
          decay={2}
        />
      ) : null}
    </group>
  );
}

function Refrigerator(props: ModelProps) {
  return (
    <group position={[0, 0.85, 0]}>
      <mesh castShadow receiveShadow>
        <boxGeometry args={[0.7, 1.7, 0.68]} />
        <Body {...props} emissive={0.22} metalness={0.45} roughness={0.4} />
      </mesh>
      {/* door split line */}
      <mesh position={[0, 0.32, 0.345]}>
        <boxGeometry args={[0.71, 0.012, 0.012]} />
        <meshStandardMaterial color="#0f141d" />
      </mesh>
      {/* handles */}
      {[0.62, -0.25].map((y) => (
        <mesh key={y} position={[0.26, y, 0.36]}>
          <boxGeometry args={[0.035, 0.4, 0.035]} />
          <meshStandardMaterial color="#9fb0c6" metalness={0.8} roughness={0.25} />
        </mesh>
      ))}
    </group>
  );
}

function MixerGrinder(props: ModelProps) {
  const jar = useRef<THREE.Group>(null);
  const ratio = loadRatio(props);

  useFrame((_, delta) => {
    if (jar.current && props.active) {
      // A universal motor mixer runs fast and shakes; the wobble sells it.
      jar.current.rotation.y += delta * (6 + ratio * 30);
      jar.current.position.x = Math.sin(performance.now() * 0.03) * 0.006 * ratio;
    }
  });

  return (
    <group position={[0, 0.16, 0]}>
      {/* base */}
      <mesh castShadow>
        <boxGeometry args={[0.3, 0.22, 0.3]} />
        <Body {...props} emissive={0.3} />
      </mesh>
      <group ref={jar} position={[0, 0.28, 0]}>
        <mesh castShadow>
          <cylinderGeometry args={[0.11, 0.13, 0.32, 14]} />
          <meshStandardMaterial
            color="#9fb0c6"
            metalness={0.7}
            roughness={0.3}
            transparent
            opacity={0.85}
          />
        </mesh>
        <mesh position={[0, 0.18, 0]}>
          <cylinderGeometry args={[0.115, 0.115, 0.05, 14]} />
          <meshStandardMaterial color="#27303f" />
        </mesh>
      </group>
    </group>
  );
}

function WashingMachine(props: ModelProps) {
  const drum = useRef<THREE.Mesh>(null);
  const ratio = loadRatio(props);

  useFrame((_, delta) => {
    if (drum.current && props.active) {
      drum.current.rotation.z += delta * (1.5 + ratio * 9);
    }
  });

  return (
    <group position={[0, 0.43, 0]}>
      <mesh castShadow receiveShadow>
        <boxGeometry args={[0.62, 0.86, 0.62]} />
        <Body {...props} emissive={0.2} metalness={0.4} roughness={0.45} />
      </mesh>
      {/* porthole */}
      <mesh position={[0, 0.02, 0.315]} rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.21, 0.21, 0.03, 24]} />
        <meshStandardMaterial color="#111722" metalness={0.4} roughness={0.3} />
      </mesh>
      <mesh ref={drum} position={[0, 0.02, 0.333]} rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.165, 0.165, 0.02, 6]} />
        <meshStandardMaterial
          color={props.active ? "#7fd4ff" : "#2a3346"}
          emissive={props.active ? props.colour : "#000000"}
          emissiveIntensity={props.active ? 0.5 : 0}
          transparent
          opacity={0.8}
        />
      </mesh>
      {/* control panel */}
      <mesh position={[0, 0.36, 0.315]}>
        <boxGeometry args={[0.5, 0.08, 0.02]} />
        <meshStandardMaterial
          color={props.active ? props.colour : "#2a3346"}
          emissive={props.active ? props.colour : "#000000"}
          emissiveIntensity={props.active ? 0.9 : 0}
        />
      </mesh>
    </group>
  );
}

function AirConditioner(props: ModelProps) {
  const ratio = loadRatio(props);
  const louvre = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    if (louvre.current) {
      louvre.current.rotation.x = props.active
        ? -0.35 + Math.sin(state.clock.elapsedTime * 0.9) * 0.22
        : 0;
    }
  });

  return (
    <group>
      <mesh castShadow>
        <boxGeometry args={[1.1, 0.34, 0.26]} />
        <Body {...props} emissive={0.18} metalness={0.3} roughness={0.5} />
      </mesh>
      {/* louvre that swings while running */}
      <mesh ref={louvre} position={[0, -0.15, 0.1]}>
        <boxGeometry args={[0.95, 0.06, 0.16]} />
        <meshStandardMaterial color="#d5deea" metalness={0.3} roughness={0.5} />
      </mesh>
      {/* status LED */}
      <mesh position={[0.45, 0.04, 0.135]}>
        <sphereGeometry args={[0.022, 8, 8]} />
        <meshStandardMaterial
          color={props.active ? "#7dffc4" : "#374357"}
          emissive={props.active ? "#4dffb0" : "#000000"}
          emissiveIntensity={props.active ? 2.5 : 0}
        />
      </mesh>
      {props.active ? (
        <pointLight
          position={[0, -0.5, 0.6]}
          color={props.colour}
          intensity={7 * ratio}
          distance={4}
          decay={2}
        />
      ) : null}
    </group>
  );
}

function Laptop(props: ModelProps) {
  const screen = useRef<THREE.MeshStandardMaterial>(null);

  useFrame((state) => {
    if (!screen.current) return;
    screen.current.emissiveIntensity = props.active
      ? 0.7 + Math.sin(state.clock.elapsedTime * 2.2) * 0.12
      : 0;
  });

  return (
    <group>
      {/* base */}
      <mesh castShadow>
        <boxGeometry args={[0.42, 0.022, 0.3]} />
        <meshStandardMaterial color="#3d4759" metalness={0.6} roughness={0.35} />
      </mesh>
      {/* lid */}
      <group position={[0, 0.01, -0.14]} rotation={[-1.15, 0, 0]}>
        <mesh position={[0, 0.14, 0]} castShadow>
          <boxGeometry args={[0.42, 0.28, 0.016]} />
          <meshStandardMaterial color="#3d4759" metalness={0.6} roughness={0.35} />
        </mesh>
        <mesh position={[0, 0.14, 0.01]}>
          <boxGeometry args={[0.385, 0.245, 0.004]} />
          <meshStandardMaterial
            ref={screen}
            color={props.active ? "#bcd8ff" : "#1d2534"}
            emissive={props.active ? props.colour : "#000000"}
            emissiveIntensity={props.active ? 0.7 : 0}
          />
        </mesh>
      </group>
    </group>
  );
}

function MobileCharger(props: ModelProps) {
  const ratio = loadRatio(props);
  return (
    <group>
      {/* phone lying on the bedside table */}
      <mesh rotation={[0, 0.35, 0]} castShadow>
        <boxGeometry args={[0.075, 0.012, 0.15]} />
        <meshStandardMaterial color="#232b3a" metalness={0.5} roughness={0.4} />
      </mesh>
      <mesh position={[0, 0.008, 0]} rotation={[0, 0.35, 0]}>
        <boxGeometry args={[0.066, 0.002, 0.138]} />
        <meshStandardMaterial
          color={props.active ? "#ffd6ec" : "#1a2130"}
          emissive={props.active ? props.colour : "#000000"}
          emissiveIntensity={props.active ? 1.4 : 0}
        />
      </mesh>
      {/* charging LED */}
      {props.active ? (
        <pointLight
          position={[0, 0.12, 0]}
          color={props.colour}
          intensity={3 * ratio}
          distance={1.6}
          decay={2}
        />
      ) : null}
    </group>
  );
}

function Microwave(props: ModelProps) {
  const ratio = loadRatio(props);
  return (
    <group position={[0, 0.15, 0]}>
      <mesh castShadow>
        <boxGeometry args={[0.55, 0.3, 0.4]} />
        <Body {...props} emissive={0.18} metalness={0.4} roughness={0.45} />
      </mesh>
      {/* door window — lit from inside while cooking */}
      <mesh position={[-0.07, 0, 0.203]}>
        <boxGeometry args={[0.34, 0.2, 0.012]} />
        <meshStandardMaterial
          color={props.active ? "#ffcf7a" : "#161d29"}
          emissive={props.active ? "#ffb347" : "#000000"}
          emissiveIntensity={props.active ? 1.3 : 0}
          transparent
          opacity={0.9}
        />
      </mesh>
      {/* keypad */}
      <mesh position={[0.2, 0, 0.203]}>
        <boxGeometry args={[0.1, 0.22, 0.01]} />
        <meshStandardMaterial color="#1b2230" />
      </mesh>
      {props.active ? (
        <pointLight
          position={[0, 0, 0.5]}
          color="#ffb347"
          intensity={6 * ratio}
          distance={2.4}
          decay={2}
        />
      ) : null}
    </group>
  );
}

function InductionStove(props: ModelProps) {
  const ring = useRef<THREE.MeshStandardMaterial>(null);
  const ratio = loadRatio(props);

  useFrame((state) => {
    if (!ring.current) return;
    // Induction hobs pulse as the inverter modulates power.
    ring.current.emissiveIntensity = props.active
      ? 1.4 + Math.sin(state.clock.elapsedTime * 3.1) * 0.5 * ratio
      : 0;
  });

  return (
    <group>
      {/* glass top */}
      <mesh castShadow receiveShadow>
        <boxGeometry args={[0.62, 0.06, 0.46]} />
        <meshStandardMaterial color="#12161f" metalness={0.5} roughness={0.25} />
      </mesh>
      {/* heating ring */}
      <mesh position={[0, 0.033, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.1, 0.17, 32]} />
        <meshStandardMaterial
          ref={ring}
          color={props.active ? "#ff6b4a" : "#232a38"}
          emissive={props.active ? "#ff4d2e" : "#000000"}
          emissiveIntensity={props.active ? 1.4 : 0}
          side={THREE.DoubleSide}
        />
      </mesh>
      {props.active ? (
        <pointLight
          position={[0, 0.25, 0]}
          color="#ff6a3c"
          intensity={12 * ratio}
          distance={2.6}
          decay={2}
        />
      ) : null}
    </group>
  );
}

/** Anything not in the registry falls back to a labelled box. */
function GenericAppliance(props: ModelProps) {
  return (
    <mesh castShadow position={[0, 0.25, 0]}>
      <boxGeometry args={[0.4, 0.5, 0.4]} />
      <Body {...props} />
    </mesh>
  );
}

export const APPLIANCE_MODELS: Record<
  string,
  (props: ModelProps) => ReactNode
> = {
  fan: CeilingFan,
  led_light: LedLight,
  tube_light: TubeLight,
  tv: Television,
  refrigerator: Refrigerator,
  mixer: MixerGrinder,
  washing_machine: WashingMachine,
  air_conditioner: AirConditioner,
  laptop: Laptop,
  mobile_charger: MobileCharger,
  microwave: Microwave,
  induction_stove: InductionStove,
};

export function applianceModel(id: string) {
  return APPLIANCE_MODELS[id] ?? GenericAppliance;
}

/** Approximate visual height, used to place the floating label above a model. */
export const MODEL_HEIGHT: Record<string, number> = {
  fan: 0.35,
  led_light: 0.25,
  tube_light: 0.25,
  tv: 0.45,
  refrigerator: 1.75,
  mixer: 0.65,
  washing_machine: 0.95,
  air_conditioner: 0.3,
  laptop: 0.35,
  mobile_charger: 0.2,
  microwave: 0.35,
  induction_stove: 0.18,
};
