/**
 * Floor plan of the virtual house.
 *
 * Coordinates are metres in Three.js convention: X to the right, Y up, Z toward
 * the viewer. The house footprint is 11 m × 10 m, centred near the origin so the
 * camera orbits about the middle of the building.
 *
 * This file is the single source of truth for where things are. The scene reads
 * it; nothing here imports Three.js, so the layout can be reasoned about (and
 * unit-tested) as plain data.
 */

export interface RoomSpec {
  id: string;
  name: string;
  /** Floor rectangle: [minX, maxX] and [minZ, maxZ]. */
  x: [number, number];
  z: [number, number];
  /** Floor tint, kept muted so appliance colour is what draws the eye. */
  colour: string;
}

export interface AppliancePlacement {
  /** Matches the appliance id from the backend catalogue. */
  id: string;
  roomId: string;
  /** Centre of the appliance body. */
  position: [number, number, number];
  /** Y-rotation in radians, for wall-facing items. */
  rotation?: number;
  /** Mounted on the ceiling — gets a drop rod and an overhead light. */
  ceiling?: boolean;
  /** Mounted high on a wall. */
  wall?: boolean;
}

export interface FurnitureSpec {
  kind: "counter" | "sofa" | "bed" | "desk" | "tv-stand" | "rug";
  position: [number, number, number];
  size: [number, number, number];
  rotation?: number;
}

export const WALL_HEIGHT = 1.45;
export const WALL_THICKNESS = 0.12;
export const CEILING_HEIGHT = 2.5;

export const ROOMS: RoomSpec[] = [
  {
    id: "kitchen",
    name: "Kitchen",
    x: [-6, 0],
    z: [-6, -1],
    colour: "#2a3947",
  },
  {
    id: "bedroom",
    name: "Bedroom",
    x: [0, 5],
    z: [-6, -1],
    colour: "#313147",
  },
  {
    id: "living",
    name: "Living Room",
    x: [-6, 0],
    z: [-1, 4],
    colour: "#2b3a41",
  },
  {
    id: "study",
    name: "Study",
    x: [0, 5],
    z: [-1, 1.5],
    colour: "#2e3b4c",
  },
  {
    id: "utility",
    name: "Utility",
    x: [0, 5],
    z: [1.5, 4],
    colour: "#283644",
  },
];

export const ROOMS_BY_ID: Record<string, RoomSpec> = Object.fromEntries(
  ROOMS.map((room) => [room.id, room]),
);

/**
 * Where each of the twelve catalogue appliances lives.
 *
 * Placement is not arbitrary: appliances are grouped the way a real household
 * groups them, because the point of the 3-D view is to make "which *room* is
 * costing me money" legible at a glance.
 */
export const PLACEMENTS: AppliancePlacement[] = [
  // --- Living room ---------------------------------------------------- //
  { id: "fan", roomId: "living", position: [-3.0, 2.15, 1.5], ceiling: true },
  { id: "led_light", roomId: "living", position: [-4.7, 2.25, 3.1], ceiling: true },
  { id: "tv", roomId: "living", position: [-5.45, 0.95, 1.5], rotation: Math.PI / 2 },

  // --- Kitchen ---------------------------------------------------------- //
  { id: "tube_light", roomId: "kitchen", position: [-3.0, 2.3, -3.5], ceiling: true },
  { id: "refrigerator", roomId: "kitchen", position: [-5.25, 0, -5.2] },
  { id: "microwave", roomId: "kitchen", position: [-3.55, 0.95, -5.4] },
  { id: "mixer", roomId: "kitchen", position: [-2.25, 0.95, -5.4] },
  { id: "induction_stove", roomId: "kitchen", position: [-0.95, 0.93, -5.4] },

  // --- Bedroom ----------------------------------------------------------- //
  {
    id: "air_conditioner",
    roomId: "bedroom",
    position: [2.5, 1.95, -5.75],
    wall: true,
  },
  { id: "mobile_charger", roomId: "bedroom", position: [4.35, 0.56, -2.2] },

  // --- Study ------------------------------------------------------------- //
  { id: "laptop", roomId: "study", position: [2.4, 0.76, 0.15], rotation: -0.25 },

  // --- Utility ----------------------------------------------------------- //
  { id: "washing_machine", roomId: "utility", position: [3.6, 0, 2.9] },
];

export const PLACEMENTS_BY_ID: Record<string, AppliancePlacement> =
  Object.fromEntries(PLACEMENTS.map((placement) => [placement.id, placement]));

export const ROOM_OF_APPLIANCE: Record<string, string> = Object.fromEntries(
  PLACEMENTS.map((placement) => [placement.id, placement.roomId]),
);

/** Static props that make the space read as a home rather than a floor plan. */
export const FURNITURE: FurnitureSpec[] = [
  // Kitchen counter running along the back wall.
  { kind: "counter", position: [-2.6, 0.45, -5.4], size: [6.4, 0.9, 0.7] },
  // Living room.
  { kind: "sofa", position: [-2.6, 0.3, 2.9], size: [2.6, 0.6, 1.0] },
  { kind: "tv-stand", position: [-5.6, 0.22, 1.5], size: [0.45, 0.45, 1.8] },
  { kind: "rug", position: [-3.2, 0.01, 1.6], size: [3.4, 0.02, 2.2] },
  // Bedroom.
  { kind: "bed", position: [2.6, 0.28, -3.3], size: [2.2, 0.55, 2.8] },
  { kind: "desk", position: [4.35, 0.26, -2.2], size: [0.9, 0.52, 0.5] },
  // Study.
  { kind: "desk", position: [2.4, 0.38, 0.1], size: [2.0, 0.75, 0.75] },
];

/** Camera framing presets offered by the view controls. */
export const CAMERA_PRESETS: Record<string, [number, number, number]> = {
  isometric: [9.6, 8.0, 9.6],
  front: [-0.5, 5.5, 13],
  top: [-0.4, 15, -0.95],
  kitchen: [-6.5, 5.5, 2.5],
  living: [-3, 5, 10],
};

/**
 * Sun colour and intensity for a given hour of the simulated day.
 *
 * Intensities are tuned for three.js r155+ *physically-correct* lighting, which
 * is now the only mode. Light intensity is in photometric units there, so the
 * conventional "0.5 ambient, 1.0 sun" values from older three examples render
 * an almost black scene — the numbers below are roughly 3x those, which is the
 * correction factor that mode implies.
 *
 * The scene lighting follows the simulated clock, so running the Night scenario
 * genuinely darkens the house and the only illumination left is whatever
 * appliances are actually switched on. That is the single most effective way to
 * show a viewer what the detector is looking at.
 */
export function daylight(hour: number): {
  ambient: number;
  sun: number;
  sunColour: string;
  skyColour: string;
  sunPosition: [number, number, number];
} {
  // Smooth 0..1 daylight curve peaking at noon, zero between 19:00 and 05:00.
  const t = Math.max(0, Math.sin(((hour - 5.5) / 13) * Math.PI));

  const sunAngle = ((hour - 6) / 12) * Math.PI;
  const sunPosition: [number, number, number] = [
    Math.cos(sunAngle) * 18,
    Math.max(3, Math.sin(sunAngle) * 20),
    8,
  ];

  if (t <= 0.02) {
    // Night: moonlight only. Dim enough that appliance glow dominates, bright
    // enough that the building is still readable.
    return {
      ambient: 1.25,
      sun: 0.9,
      sunColour: "#6f86bd",
      skyColour: "#0a0f1c",
      sunPosition,
    };
  }

  // Warm at dawn and dusk, neutral at midday.
  const warmth = 1 - t;
  const red = Math.round(255 - warmth * 10);
  const green = Math.round(245 - warmth * 60);
  const blue = Math.round(225 - warmth * 110);

  return {
    ambient: 1.65 + t * 1.15,
    sun: 1.5 + t * 3.0,
    sunColour: `rgb(${red}, ${green}, ${blue})`,
    skyColour: t > 0.5 ? "#0b1626" : "#0a0f1c",
    sunPosition,
  };
}
