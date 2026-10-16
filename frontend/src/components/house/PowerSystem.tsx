/**
 * The electrical side of the house: the incoming supply, the SCT-013 clamp on
 * it, the main distribution board, and the cables from each breaker to every
 * device.
 *
 * It exists to make the project's one physical idea visible: *everything* the
 * house draws flows through a single cable, and the clamp on that cable is the
 * only sensor there is. Cables to devices that are running carry moving
 * pulses, the supply pulses faster as the total current rises, and the clamp
 * label shows the live reading the whole dashboard is derived from.
 */

import { Html, Line, RoundedBox } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useRef, useState } from "react";
import * as THREE from "three";
import type { Line2 } from "three-stdlib";

import type { Point3, Wiring } from "@/components/house/layout";
import type { ApplianceFrame } from "@/types";

const IDLE_CABLE = "#334155";
const LIVE_CABLE = "#22d3ee";
const SUPPLY_CABLE = "#f59e0b";
const CLAMP_BLUE = "#1d4ed8";
/** Where the clamp's label hangs, relative to the clamp: down, left, forward. */
const CLAMP_LABEL_OFFSET: Point3 = [-0.62, -0.38, 0.4];

// --------------------------------------------------------------------------- //
// A cable that shows current flowing through it
// --------------------------------------------------------------------------- //

function FlowLine({
  points,
  active,
  colour,
  speed = 1,
  width = 2,
}: {
  points: Point3[];
  active: boolean;
  colour: string;
  /** Dash travel speed, in metres per second. */
  speed?: number;
  width?: number;
}) {
  const ref = useRef<Line2>(null);

  useFrame((_, delta) => {
    const material = ref.current?.material;
    if (active && material) material.dashOffset -= delta * speed;
  });

  if (points.length < 2) return null;
  return (
    <>
      {/* The cable itself. */}
      <Line points={points} color={active ? colour : IDLE_CABLE} lineWidth={width} transparent opacity={active ? 0.35 : 0.55} />
      {/* Pulses travelling along it while current flows. */}
      {active ? (
        <Line
          ref={ref}
          points={points}
          color={colour}
          lineWidth={width + 0.8}
          dashed
          dashSize={0.18}
          gapSize={0.32}
        />
      ) : null}
    </>
  );
}

// --------------------------------------------------------------------------- //
// The board
// --------------------------------------------------------------------------- //

function MainBoard({
  wiring,
  circuits,
  mainOn,
  onToggle,
}: {
  wiring: Wiring;
  /** One entry per breaker: its room's name and whether anything in it is on. */
  circuits: { name: string; live: boolean }[];
  mainOn: boolean;
  onToggle?: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const [width, height] = wiring.boardSize;
  const [bx, by, bz] = wiring.board;
  const breakerWidth = Math.min(0.12, (width - 0.45) / Math.max(circuits.length, 1));
  const firstX = -width / 2 + 0.2;

  return (
    <group
      position={[bx, by, bz]}
      onClick={(event) => {
        event.stopPropagation();
        onToggle?.();
      }}
      onPointerOver={(event) => {
        event.stopPropagation();
        setHovered(true);
        if (onToggle) document.body.style.cursor = "pointer";
      }}
      onPointerOut={() => {
        setHovered(false);
        document.body.style.cursor = "auto";
      }}
    >
      {/* enclosure */}
      <RoundedBox args={[width, height, 0.14]} radius={0.03} smoothness={2} castShadow>
        <meshStandardMaterial
          color={hovered ? "#e8edf5" : "#d6dbe3"}
          emissive={hovered ? "#1e3a8a" : "#000000"}
          emissiveIntensity={hovered ? 0.25 : 0}
          roughness={0.6}
          metalness={0.15}
        />
      </RoundedBox>
      {/* DIN rail */}
      <mesh position={[0, 0.02, 0.075]}>
        <boxGeometry args={[width - 0.14, 0.05, 0.01]} />
        <meshStandardMaterial color="#9aa3b2" metalness={0.6} roughness={0.35} />
      </mesh>

      {/* main switch: wider, red, its handle up when on and down when off */}
      <group position={[width / 2 - 0.16, 0.02, 0.1]}>
        <mesh>
          <boxGeometry args={[0.16, 0.26, 0.06]} />
          <meshStandardMaterial color="#b91c1c" roughness={0.5} />
        </mesh>
        <mesh position={[0, mainOn ? 0.06 : -0.06, 0.045]}>
          <boxGeometry args={[0.07, 0.07, 0.04]} />
          <meshStandardMaterial color="#111827" />
        </mesh>
      </group>

      {/* one breaker per room circuit; its indicator lights while it carries load */}
      {circuits.map((circuit, index) => {
        const x = firstX + index * (breakerWidth + 0.015) + breakerWidth / 2;
        return (
          <group key={index} position={[x, 0.02, 0.1]}>
            <mesh>
              <boxGeometry args={[breakerWidth, 0.24, 0.06]} />
              <meshStandardMaterial color="#f1f5f9" roughness={0.55} />
            </mesh>
            <mesh position={[0, 0.06, 0.032]}>
              <boxGeometry args={[breakerWidth * 0.5, 0.05, 0.008]} />
              <meshStandardMaterial color="#111827" />
            </mesh>
            <mesh position={[0, -0.075, 0.032]}>
              <boxGeometry args={[breakerWidth * 0.45, 0.025, 0.006]} />
              <meshStandardMaterial
                color={circuit.live ? "#22c55e" : "#334155"}
                emissive={circuit.live ? "#22c55e" : "#000000"}
                emissiveIntensity={circuit.live ? 1.6 : 0}
              />
            </mesh>
          </group>
        );
      })}

      <Html
        position={[0, height / 2 + 0.16, 0]}
        center
        distanceFactor={11}
        zIndexRange={[15, 0]}
        style={{ pointerEvents: onToggle ? "auto" : "none" }}
      >
        <button
          type="button"
          data-label-priority={70}
          disabled={!onToggle}
          onClick={onToggle}
          aria-label={`Main switch: turn ${mainOn ? "off" : "on"}`}
          className={
            "block cursor-pointer whitespace-nowrap rounded-md border px-2 py-0.5 text-center backdrop-blur-md transition-colors disabled:cursor-default " +
            (mainOn
              ? "border-slate-500/40 bg-slate-950/80 hover:border-slate-300/70"
              : "border-red-500/60 bg-red-950/80 hover:border-red-400")
          }
        >
          <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-300">
            Main board · {circuits.length} circuits ·{" "}
            <span className={mainOn ? "text-emerald-400" : "text-red-400"}>
              {mainOn ? "on" : "off"}
            </span>
          </div>
          {onToggle ? (
            <div className="text-[9px] text-slate-400">
              click to switch {mainOn ? "off" : "on"}
            </div>
          ) : null}
        </button>
      </Html>
    </group>
  );
}

// --------------------------------------------------------------------------- //
// The SCT-013 clamp and the edge meter
// --------------------------------------------------------------------------- //

function SctClamp({
  position,
  currentA,
  onSelect,
}: {
  position: Point3;
  currentA: number;
  onSelect?: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const ring = useRef<THREE.Mesh>(null);

  // A faint pulse at mains-like pace so the clamp reads as "live".
  useFrame((state) => {
    if (!ring.current) return;
    const pulse = 1 + Math.sin(state.clock.elapsedTime * 6) * 0.04 * Math.min(1, currentA / 5);
    ring.current.scale.setScalar(hovered ? 1.12 : pulse);
  });

  return (
    <group position={position}>
      <group
        onClick={(event) => {
          event.stopPropagation();
          onSelect?.();
        }}
        onPointerOver={(event) => {
          event.stopPropagation();
          setHovered(true);
          if (onSelect) document.body.style.cursor = "pointer";
        }}
        onPointerOut={() => {
          setHovered(false);
          document.body.style.cursor = "auto";
        }}
      >
        {/* the split ferrite core, closed around the cable */}
        <mesh ref={ring} rotation={[Math.PI / 2, 0, 0]} castShadow>
          <torusGeometry args={[0.075, 0.03, 12, 32]} />
          <meshStandardMaterial color={CLAMP_BLUE} roughness={0.45} metalness={0.1} />
        </mesh>
        {/* the moulded body with the hinge and the lead */}
        <mesh position={[0.1, 0, 0]} castShadow>
          <boxGeometry args={[0.09, 0.07, 0.07]} />
          <meshStandardMaterial color="#0f172a" roughness={0.6} />
        </mesh>
        {/* generous invisible hit target */}
        <mesh>
          <boxGeometry args={[0.35, 0.3, 0.3]} />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} />
        </mesh>
      </group>

      {/* The label sits off to one side with a leader line, so it never
          covers the clamp it is describing. */}
      <Line
        points={[[0, 0, 0], CLAMP_LABEL_OFFSET]}
        color="#60a5fa"
        lineWidth={1}
        transparent
        opacity={0.7}
      />
      <Html
        position={CLAMP_LABEL_OFFSET}
        center
        distanceFactor={10}
        zIndexRange={[25, 0]}
        // The label is the easy thing to click; the clamp itself is small.
        style={{ pointerEvents: onSelect ? "auto" : "none" }}
      >
        <button
          type="button"
          disabled={!onSelect}
          onClick={onSelect}
          onPointerEnter={() => setHovered(true)}
          onPointerLeave={() => setHovered(false)}
          aria-label="SCT-013 clamp: how it works"
          data-label-priority={80}
          className="block cursor-pointer whitespace-nowrap rounded-md border px-2 py-1 text-center backdrop-blur-md transition-colors disabled:cursor-default"
          style={{
            borderColor: hovered ? "rgba(96,165,250,0.9)" : "rgba(96,165,250,0.45)",
            background: hovered ? "rgba(23,37,84,0.9)" : "rgba(8,13,22,0.85)",
          }}
        >
          <div className="text-[10px] font-semibold uppercase tracking-wider text-blue-300">
            SCT-013 clamp
          </div>
          <div className="font-mono text-[13px] font-bold leading-tight text-white">
            {currentA.toFixed(2)} A
          </div>
          {onSelect ? (
            <div className="text-[9px] text-slate-400">click: how it works</div>
          ) : null}
        </button>
      </Html>
    </group>
  );
}

function EdgeMeter({ position, powerW }: { position: Point3; powerW: number }) {
  return (
    <group position={position}>
      <RoundedBox args={[0.32, 0.34, 0.1]} radius={0.02} smoothness={2} castShadow>
        <meshStandardMaterial color="#1e293b" roughness={0.55} />
      </RoundedBox>
      {/* status screen */}
      <mesh position={[0, 0.04, 0.052]}>
        <planeGeometry args={[0.22, 0.12]} />
        <meshStandardMaterial color="#0e7490" emissive="#22d3ee" emissiveIntensity={0.9} />
      </mesh>
      <Html
        position={[0.05, -0.42, 0.06]}
        center
        distanceFactor={11}
        zIndexRange={[15, 0]}
        style={{ pointerEvents: "none" }}
      >
        <div
          data-label-priority={60}
          className="whitespace-nowrap rounded-md border border-cyan-500/30 bg-slate-950/80 px-2 py-0.5 text-center backdrop-blur-md"
        >
          <div className="text-[9px] font-semibold uppercase tracking-wider text-cyan-300">
            Edge meter · ESP32
          </div>
          <div className="font-mono text-[11px] font-bold text-white">
            {powerW >= 1000 ? `${(powerW / 1000).toFixed(2)} kW` : `${powerW.toFixed(0)} W`}
          </div>
        </div>
      </Html>
    </group>
  );
}

// --------------------------------------------------------------------------- //
// Everything together
// --------------------------------------------------------------------------- //

export function PowerSystem({
  wiring,
  roomNames,
  appliances,
  currentA,
  powerW,
  mainOn,
  onSelectClamp,
  onToggleMain,
}: {
  wiring: Wiring;
  roomNames: Record<string, string>;
  appliances: ApplianceFrame[];
  /** RMS current measured at the mains — the clamp's reading. */
  currentA: number;
  powerW: number;
  mainOn: boolean;
  onSelectClamp?: () => void;
  onToggleMain?: () => void;
}) {
  const byId = Object.fromEntries(appliances.map((a) => [a.id, a]));
  const liveRooms = new Set(appliances.filter((a) => a.detected).map((a) => a.room_id));
  // Faster pulses for more current, within a readable range.
  const supplySpeed = 0.4 + Math.min(2.6, currentA / 4);

  return (
    <group>
      <FlowLine
        points={wiring.supply}
        active={currentA > 0.05}
        colour={SUPPLY_CABLE}
        speed={supplySpeed}
        width={4}
      />
      <Line points={wiring.sensorLead} color="#0f172a" lineWidth={1.5} />

      <MainBoard
        wiring={wiring}
        circuits={wiring.circuits.map((circuit) => ({
          name: roomNames[circuit.roomId] ?? circuit.roomId,
          live: mainOn && liveRooms.has(circuit.roomId),
        }))}
        mainOn={mainOn}
        onToggle={onToggleMain}
      />
      <SctClamp position={wiring.clamp} currentA={currentA} onSelect={onSelectClamp} />
      <EdgeMeter position={wiring.meter} powerW={powerW} />

      {wiring.circuits.map((circuit) => (
        <FlowLine
          key={circuit.roomId}
          points={circuit.points}
          active={liveRooms.has(circuit.roomId)}
          colour={LIVE_CABLE}
          speed={1.2}
          width={2.2}
        />
      ))}

      {wiring.branches.map((branch) => {
        const device = byId[branch.deviceId];
        return (
          <FlowLine
            key={branch.deviceId}
            points={branch.points}
            active={Boolean(device?.detected)}
            colour={device?.colour ?? LIVE_CABLE}
            speed={0.9}
            width={1.6}
          />
        );
      })}
    </group>
  );
}
