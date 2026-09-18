/**
 * The 3-D house.
 *
 * An isometric cutaway of the simulated household, driven entirely by the live
 * pipeline frame. Appliances are clickable — that replaces the old toggle
 * switches — and they *show* their state physically rather than through a
 * label: fan blades spin faster under load, the induction hob glows and pulses,
 * the tube light actually lights the kitchen.
 *
 * Scene lighting follows the simulated clock. Running the Night scenario
 * genuinely darkens the house, so the only illumination left comes from
 * appliances that are really drawing power. That is the clearest way to show a
 * viewer what the detector is working with.
 */

import { Html, OrbitControls, RoundedBox } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { Suspense, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import {
  MODEL_HEIGHT,
  applianceModel,
  type ModelProps,
} from "@/components/house/ApplianceModels";
import {
  CEILING_HEIGHT,
  FURNITURE,
  PLACEMENTS,
  ROOMS,
  ROOM_OF_APPLIANCE,
  WALL_HEIGHT,
  WALL_THICKNESS,
  daylight,
  type FurnitureSpec,
  type RoomSpec,
} from "@/components/house/layout";
import { formatPower } from "@/lib/utils";
import type { ApplianceFrame } from "@/types";

// --------------------------------------------------------------------------- //
// Rooms
// --------------------------------------------------------------------------- //

function Room({ room, highlight }: { room: RoomSpec; highlight: boolean }) {
  const width = room.x[1] - room.x[0];
  const depth = room.z[1] - room.z[0];
  const cx = (room.x[0] + room.x[1]) / 2;
  const cz = (room.z[0] + room.z[1]) / 2;

  // Walls are drawn as four thin slabs around the perimeter of the room. They
  // are deliberately low (1.45 m) so the interior stays visible from any camera
  // angle — an architectural cutaway rather than a closed box.
  const walls = useMemo(
    () => [
      { position: [cx, WALL_HEIGHT / 2, room.z[0]], size: [width, WALL_HEIGHT, WALL_THICKNESS] },
      { position: [cx, WALL_HEIGHT / 2, room.z[1]], size: [width, WALL_HEIGHT, WALL_THICKNESS] },
      { position: [room.x[0], WALL_HEIGHT / 2, cz], size: [WALL_THICKNESS, WALL_HEIGHT, depth] },
      { position: [room.x[1], WALL_HEIGHT / 2, cz], size: [WALL_THICKNESS, WALL_HEIGHT, depth] },
    ],
    [cx, cz, width, depth, room.x, room.z],
  );

  return (
    <group>
      {/* floor */}
      <mesh position={[cx, 0, cz]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[width, depth]} />
        <meshStandardMaterial
          color={highlight ? "#2b4152" : room.colour}
          roughness={0.95}
          metalness={0.05}
        />
      </mesh>

      {walls.map((wall, index) => (
        <mesh
          key={index}
          position={wall.position as [number, number, number]}
          castShadow
          receiveShadow
        >
          <boxGeometry args={wall.size as [number, number, number]} />
          <meshStandardMaterial
            color="#38465c"
            roughness={0.9}
            transparent
            opacity={0.62}
          />
        </mesh>
      ))}

      {/* Corner posts rising to ceiling height. They imply a ceiling without
          drawing one, which is what stops ceiling-mounted fans and lights from
          looking like they are floating in mid-air. */}
      {[
        [room.x[0], room.z[0]],
        [room.x[0], room.z[1]],
        [room.x[1], room.z[0]],
        [room.x[1], room.z[1]],
      ].map(([px, pz], index) => (
        <mesh key={index} position={[px, CEILING_HEIGHT / 2, pz]}>
          <boxGeometry args={[0.07, CEILING_HEIGHT, 0.07]} />
          <meshStandardMaterial color="#46556e" transparent opacity={0.45} />
        </mesh>
      ))}
    </group>
  );
}

// --------------------------------------------------------------------------- //
// Furniture
// --------------------------------------------------------------------------- //

const FURNITURE_COLOUR: Record<FurnitureSpec["kind"], string> = {
  counter: "#37445a",
  sofa: "#3c4a63",
  bed: "#3e4a62",
  desk: "#3a4659",
  "tv-stand": "#333f53",
  rug: "#2a3a48",
};

function Furniture({ item }: { item: FurnitureSpec }) {
  const colour = FURNITURE_COLOUR[item.kind] ?? "#374357";
  return (
    <RoundedBox
      args={item.size}
      radius={Math.min(0.06, item.size[1] / 2.2)}
      smoothness={2}
      position={item.position}
      rotation={[0, item.rotation ?? 0, 0]}
      castShadow
      receiveShadow
    >
      <meshStandardMaterial color={colour} roughness={0.9} metalness={0.05} />
    </RoundedBox>
  );
}

// --------------------------------------------------------------------------- //
// One appliance
// --------------------------------------------------------------------------- //

interface ApplianceNodeProps {
  appliance: ApplianceFrame;
  position: [number, number, number];
  rotation: number;
  showTruth: boolean;
  selected: boolean;
  onSelect: (id: string) => void;
  onToggle: (appliance: ApplianceFrame) => void;
}

function ApplianceNode({
  appliance,
  position,
  rotation,
  showTruth,
  selected,
  onSelect,
  onToggle,
}: ApplianceNodeProps) {
  const [hovered, setHovered] = useState(false);
  const group = useRef<THREE.Group>(null);

  const Model = applianceModel(appliance.id);
  const modelProps: ModelProps = {
    active: appliance.detected,
    power: appliance.estimated_power_w,
    ratedPower: appliance.rated_power_w,
    colour: appliance.colour,
  };

  // A detection error: the model and the simulator disagree about this
  // appliance right now.
  const missed = showTruth && appliance.actually_on && !appliance.detected;
  const falsePositive = showTruth && !appliance.actually_on && appliance.detected;

  const labelHeight = (MODEL_HEIGHT[appliance.id] ?? 0.5) + 0.45;

  useFrame((state) => {
    if (!group.current) return;
    // Gentle lift on hover, and a slow bob while selected, so the pointer
    // target is unambiguous without a separate outline pass.
    const target = hovered || selected ? 0.09 : 0;
    const bob = selected ? Math.sin(state.clock.elapsedTime * 3) * 0.02 : 0;
    group.current.position.y = THREE.MathUtils.lerp(
      group.current.position.y,
      position[1] + target + bob,
      0.18,
    );
  });

  return (
    <group position={position}>
      {/* Status ring on the floor beneath the appliance. */}
      <mesh position={[0, -position[1] + 0.012, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.32, 0.42, 28]} />
        <meshBasicMaterial
          color={
            missed
              ? "#ef4444"
              : falsePositive
                ? "#f59e0b"
                : appliance.detected
                  ? appliance.colour
                  : "#2a3547"
          }
          transparent
          opacity={missed || falsePositive ? 0.85 : appliance.detected ? 0.5 : 0.22}
          side={THREE.DoubleSide}
        />
      </mesh>

      <group
        ref={group}
        rotation={[0, rotation, 0]}
        onClick={(event) => {
          event.stopPropagation();
          onSelect(appliance.id);
          onToggle(appliance);
        }}
        onPointerOver={(event) => {
          event.stopPropagation();
          setHovered(true);
          document.body.style.cursor = "pointer";
        }}
        onPointerOut={() => {
          setHovered(false);
          document.body.style.cursor = "auto";
        }}
      >
        <Model {...modelProps} />
      </group>

      {/* Floating label. Shown for anything running, anything the detector got
          wrong, and whatever the pointer is over — showing all twelve at once
          would be unreadable. */}
      {appliance.detected || hovered || selected || missed || falsePositive ? (
        <Html
          position={[0, labelHeight, 0]}
          center
          distanceFactor={11}
          zIndexRange={[20, 0]}
          style={{ pointerEvents: "none" }}
        >
          <div
            className="whitespace-nowrap rounded-md border px-2 py-1 text-center backdrop-blur-md"
            style={{
              borderColor: missed
                ? "rgba(239,68,68,0.55)"
                : falsePositive
                  ? "rgba(245,158,11,0.55)"
                  : `${appliance.colour}66`,
              background: "rgba(8,13,22,0.82)",
            }}
          >
            <div
              className="text-[11px] font-semibold leading-tight"
              style={{ color: appliance.detected ? appliance.colour : "#94a3b8" }}
            >
              {appliance.name}
            </div>
            <div className="font-mono text-[13px] font-bold leading-tight text-white">
              {appliance.detected
                ? `${formatPower(appliance.estimated_power_w).value} ${formatPower(appliance.estimated_power_w).unit}`
                : "off"}
            </div>
            {missed ? (
              <div className="text-[10px] font-medium text-red-400">missed</div>
            ) : null}
            {falsePositive ? (
              <div className="text-[10px] font-medium text-amber-400">
                false positive
              </div>
            ) : null}
          </div>
        </Html>
      ) : null}
    </group>
  );
}

// --------------------------------------------------------------------------- //
// Room power labels
// --------------------------------------------------------------------------- //

function RoomLabel({ room, watts }: { room: RoomSpec; watts: number }) {
  const cx = (room.x[0] + room.x[1]) / 2;
  const cz = (room.z[0] + room.z[1]) / 2;
  const formatted = formatPower(watts);

  return (
    <Html
      position={[cx, 0.06, cz]}
      center
      distanceFactor={16}
      zIndexRange={[10, 0]}
      style={{ pointerEvents: "none" }}
    >
      <div className="select-none text-center">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400/80">
          {room.name}
        </div>
        {watts > 0.5 ? (
          <div className="font-mono text-[15px] font-bold text-cyan-300/90">
            {formatted.value} {formatted.unit}
          </div>
        ) : null}
      </div>
    </Html>
  );
}

// --------------------------------------------------------------------------- //
// Lighting driven by the simulated clock
// --------------------------------------------------------------------------- //

function SceneLighting({ hour }: { hour: number }) {
  const light = daylight(hour);
  return (
    <>
      <ambientLight intensity={light.ambient} />
      <hemisphereLight
        intensity={light.ambient * 0.6}
        color={light.skyColour}
        groundColor="#0a0f18"
      />
      <directionalLight
        position={light.sunPosition}
        intensity={light.sun}
        color={light.sunColour}
        castShadow
        shadow-mapSize={[1024, 1024]}
        shadow-camera-left={-14}
        shadow-camera-right={14}
        shadow-camera-top={14}
        shadow-camera-bottom={-14}
        shadow-bias={-0.0004}
      />
      {/* Fill light so the faces pointing away from the sun do not go flat
          black. Never shadow-casting — it exists purely to lift the shadows. */}
      <directionalLight position={[-10, 8, 12]} intensity={light.ambient * 0.45} />
    </>
  );
}

// --------------------------------------------------------------------------- //
// The scene
// --------------------------------------------------------------------------- //

interface HouseSceneProps {
  appliances: ApplianceFrame[];
  /** Hour of the simulated day, drives the lighting. */
  hour: number;
  showTruth: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onToggle: (appliance: ApplianceFrame) => void;
  cameraPosition: [number, number, number];
}

/** Smoothly flies the camera to a new preset instead of snapping. */
function CameraRig({ target }: { target: [number, number, number] }) {
  const desired = useRef(new THREE.Vector3(...target));
  desired.current.set(...target);

  useFrame((state) => {
    // Only drive the camera while it is meaningfully away from the preset, so
    // the user's own orbiting is never fought by this rig.
    if (state.camera.position.distanceTo(desired.current) > 0.05) {
      state.camera.position.lerp(desired.current, 0.06);
      state.camera.lookAt(-0.5, 0.6, -1);
    }
  });
  return null;
}

function SceneContents({
  appliances,
  hour,
  showTruth,
  selectedId,
  onSelect,
  onToggle,
}: Omit<HouseSceneProps, "cameraPosition">) {
  const byId = useMemo(
    () => Object.fromEntries(appliances.map((a) => [a.id, a])),
    [appliances],
  );

  const roomWatts = useMemo(() => {
    const totals: Record<string, number> = {};
    for (const room of ROOMS) totals[room.id] = 0;
    for (const appliance of appliances) {
      const roomId = ROOM_OF_APPLIANCE[appliance.id];
      if (roomId && appliance.detected) {
        totals[roomId] = (totals[roomId] ?? 0) + appliance.estimated_power_w;
      }
    }
    return totals;
  }, [appliances]);

  const busiestRoom = useMemo(() => {
    let best: string | null = null;
    let bestWatts = 60; // don't highlight a room over a trivial standby load
    for (const [roomId, watts] of Object.entries(roomWatts)) {
      if (watts > bestWatts) {
        bestWatts = watts;
        best = roomId;
      }
    }
    return best;
  }, [roomWatts]);

  return (
    <>
      <SceneLighting hour={hour} />

      {/* ground plane the house sits on */}
      <mesh position={[-0.5, -0.02, -1]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[34, 34]} />
        <meshStandardMaterial color="#070b13" roughness={1} />
      </mesh>

      {ROOMS.map((room) => (
        <Room key={room.id} room={room} highlight={busiestRoom === room.id} />
      ))}

      {FURNITURE.map((item, index) => (
        <Furniture key={index} item={item} />
      ))}

      {PLACEMENTS.map((placement) => {
        const appliance = byId[placement.id];
        if (!appliance) return null;
        return (
          <ApplianceNode
            key={placement.id}
            appliance={appliance}
            position={placement.position}
            rotation={placement.rotation ?? 0}
            showTruth={showTruth}
            selected={selectedId === placement.id}
            onSelect={onSelect}
            onToggle={onToggle}
          />
        );
      })}

      {ROOMS.map((room) => (
        <RoomLabel key={room.id} room={room} watts={roomWatts[room.id] ?? 0} />
      ))}
    </>
  );
}

export function HouseScene(props: HouseSceneProps) {
  return (
    <Canvas
      // three r186 removed PCFSoftShadowMap; "percentage" maps to PCFShadowMap,
      // which is what the default silently falls back to anyway.
      shadows="percentage"
      dpr={[1, 1.75]}
      camera={{ position: props.cameraPosition, fov: 38, near: 0.1, far: 120 }}
      gl={{
        antialias: true,
        powerPreference: "high-performance",
        // ACES tone mapping (the R3F default) rolls off highlights hard; a
        // little extra exposure keeps the lit appliances reading as lit.
        toneMappingExposure: 1.15,
      }}
      style={{ background: "transparent" }}
    >
      <Suspense fallback={null}>
        <SceneContents {...props} />
      </Suspense>
      <CameraRig target={props.cameraPosition} />
      <OrbitControls
        makeDefault
        target={[-0.5, 0.6, -1]}
        enablePan
        minDistance={6}
        maxDistance={34}
        // Keep the camera above the floor plane; orbiting underneath the house
        // shows the underside of the ground and looks broken.
        maxPolarAngle={Math.PI / 2.15}
        minPolarAngle={0.12}
        enableDamping
        dampingFactor={0.08}
      />
    </Canvas>
  );
}
