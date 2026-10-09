/**
 * Floor plan of the virtual house.
 *
 * Coordinates are metres in Three.js convention: X to the right, Y up, Z toward
 * the viewer. The original house footprint is 11 m × 10 m, centred near the
 * origin; rooms added from the admin pages extend it eastward.
 *
 * The five original rooms and the twelve original appliances keep their
 * hand-placed positions. Everything else -- new rooms, a fan in every room,
 * a second TV -- is placed by {@link layoutHouse}, which puts each device in a
 * free slot of the kind its type needs (ceiling, wall, floor or a small
 * table). Nothing here imports Three.js, so the layout can be reasoned about
 * (and unit-tested) as plain data.
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

const DEFAULT_ROOMS: RoomSpec[] = [
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

const DEFAULT_ROOMS_BY_ID: Record<string, RoomSpec> = Object.fromEntries(
  DEFAULT_ROOMS.map((room) => [room.id, room]),
);

/**
 * Where each of the twelve original appliances lives, by device id (which for
 * them is the catalogue type id).
 *
 * Placement is not arbitrary: appliances are grouped the way a real household
 * groups them, because the point of the 3-D view is to make "which *room* is
 * costing me money" legible at a glance.
 */
const HAND_PLACEMENTS: AppliancePlacement[] = [
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

const HAND_PLACEMENTS_BY_ID: Record<string, AppliancePlacement> =
  Object.fromEntries(HAND_PLACEMENTS.map((placement) => [placement.id, placement]));

/** Props that make the original rooms read as a home rather than a floor plan. */
const DEFAULT_FURNITURE: (FurnitureSpec & { roomId: string })[] = [
  // Kitchen counter running along the back wall.
  { roomId: "kitchen", kind: "counter", position: [-2.6, 0.45, -5.4], size: [6.4, 0.9, 0.7] },
  // Living room.
  { roomId: "living", kind: "sofa", position: [-2.6, 0.3, 2.9], size: [2.6, 0.6, 1.0] },
  { roomId: "living", kind: "tv-stand", position: [-5.6, 0.22, 1.5], size: [0.45, 0.45, 1.8] },
  { roomId: "living", kind: "rug", position: [-3.2, 0.01, 1.6], size: [3.4, 0.02, 2.2] },
  // Bedroom.
  { roomId: "bedroom", kind: "bed", position: [2.6, 0.28, -3.3], size: [2.2, 0.55, 2.8] },
  { roomId: "bedroom", kind: "desk", position: [4.35, 0.26, -2.2], size: [0.9, 0.52, 0.5] },
  // Study.
  { roomId: "study", kind: "desk", position: [2.4, 0.38, 0.1], size: [2.0, 0.75, 0.75] },
];

// --------------------------------------------------------------------------- //
// Laying out any house
// --------------------------------------------------------------------------- //

/** What the layout needs to know about a device. */
export interface DeviceRef {
  id: string;
  type_id: string;
  room_id: string;
}

export interface RoomRefLike {
  id: string;
  name: string;
}

export interface HouseLayout {
  rooms: RoomSpec[];
  placements: AppliancePlacement[];
  furniture: FurnitureSpec[];
  /** Centre of the floor plan, for the camera to orbit. */
  centre: [number, number, number];
  /** Rough radius of the house, for camera distance. */
  radius: number;
}

/** Extra rooms continue the house eastward in a grid of these cells. */
const EXTRA_ROOM_WIDTH = 4.5;
const EXTRA_ROOM_ROWS: [number, number][] = [
  [-6, -1],
  [-1, 4],
];
const EXTRA_ROOM_START_X = 5;
const EXTRA_ROOM_COLOURS = ["#2c3a4a", "#30344a", "#2a3b42", "#2f3a4d"];

type SlotKind = "ceiling" | "wall" | "floor" | "table";

/** How each catalogue type is mounted, and at what height. */
const MOUNT: Record<string, { kind: SlotKind; y: number }> = {
  fan: { kind: "ceiling", y: 2.15 },
  led_light: { kind: "ceiling", y: 2.25 },
  tube_light: { kind: "ceiling", y: 2.3 },
  air_conditioner: { kind: "wall", y: 1.95 },
  refrigerator: { kind: "floor", y: 0 },
  washing_machine: { kind: "floor", y: 0 },
  tv: { kind: "table", y: 0.95 },
  microwave: { kind: "table", y: 0.95 },
  mixer: { kind: "table", y: 0.95 },
  induction_stove: { kind: "table", y: 0.93 },
  laptop: { kind: "table", y: 0.76 },
  mobile_charger: { kind: "table", y: 0.56 },
};

/** Minimum spacing between two devices on the same level, in metres. */
const MIN_SPACING = 1.0;

function extraRoomRect(index: number): Pick<RoomSpec, "x" | "z"> {
  const column = Math.floor(index / EXTRA_ROOM_ROWS.length);
  const row = EXTRA_ROOM_ROWS[index % EXTRA_ROOM_ROWS.length];
  const x0 = EXTRA_ROOM_START_X + column * EXTRA_ROOM_WIDTH;
  return { x: [x0, x0 + EXTRA_ROOM_WIDTH], z: row };
}

/** Candidate positions of one kind inside a room, best first. */
function candidates(room: RoomSpec, kind: SlotKind, y: number): {
  position: [number, number, number];
  rotation?: number;
}[] {
  const [x0, x1] = room.x;
  const [z0, z1] = room.z;
  const cx = (x0 + x1) / 2;
  const cz = (z0 + z1) / 2;
  const inset = 0.65;
  const fractions = [0.5, 0.25, 0.75, 0.15, 0.85];

  if (kind === "ceiling") {
    const points: [number, number][] = [[cx, cz]];
    for (const fx of [0.3, 0.7]) {
      for (const fz of [0.3, 0.7]) points.push([x0 + (x1 - x0) * fx, z0 + (z1 - z0) * fz]);
    }
    return points.map(([x, z]) => ({ position: [x, y, z] }));
  }
  if (kind === "wall") {
    return fractions.map((f) => ({ position: [x0 + (x1 - x0) * f, y, z0 + 0.25] }));
  }
  if (kind === "floor") {
    return [
      [x0 + inset, z0 + inset],
      [x1 - inset, z0 + inset],
      [x1 - inset, z1 - inset],
      [x0 + inset, z1 - inset],
    ].map(([x, z]) => ({ position: [x, y, z] as [number, number, number] }));
  }
  // Tables: along the back wall, then along the front wall facing in.
  return [
    ...fractions.map((f) => ({
      position: [x0 + (x1 - x0) * f, y, z0 + 0.5] as [number, number, number],
    })),
    ...fractions.map((f) => ({
      position: [x0 + (x1 - x0) * f, y, z1 - 0.5] as [number, number, number],
      rotation: Math.PI,
    })),
  ];
}

function distanceXZ(a: [number, number, number], b: [number, number, number]): number {
  return Math.hypot(a[0] - b[0], a[2] - b[2]);
}

/** Ceiling items and floor-standing items do not collide with each other. */
function sameLevel(a: SlotKind, b: SlotKind): boolean {
  return (a === "ceiling") === (b === "ceiling");
}

/**
 * Rooms, appliance positions and furniture for whatever the house currently
 * contains. Deterministic: the same configuration always lays out the same way.
 */
export function layoutHouse(roomRefs: RoomRefLike[], devices: DeviceRef[]): HouseLayout {
  let extraIndex = 0;
  const rooms: RoomSpec[] = roomRefs.map((ref) => {
    const preset = DEFAULT_ROOMS_BY_ID[ref.id];
    if (preset) return { ...preset, name: ref.name };
    const index = extraIndex++;
    return {
      id: ref.id,
      name: ref.name,
      ...extraRoomRect(index),
      colour: EXTRA_ROOM_COLOURS[index % EXTRA_ROOM_COLOURS.length],
    };
  });
  const roomsById = Object.fromEntries(rooms.map((room) => [room.id, room]));

  const furniture: FurnitureSpec[] = DEFAULT_FURNITURE.filter(
    (item) => roomsById[item.roomId] && DEFAULT_ROOMS_BY_ID[item.roomId],
  ).map(({ roomId: _roomId, ...item }) => item);

  const occupied: { position: [number, number, number]; kind: SlotKind; roomId: string }[] = [];
  const placements: AppliancePlacement[] = [];
  const pending: DeviceRef[] = [];

  // Original devices in their original rooms keep their hand-made spots.
  for (const device of devices) {
    const hand = HAND_PLACEMENTS_BY_ID[device.id];
    if (hand && hand.roomId === device.room_id && roomsById[device.room_id]) {
      placements.push(hand);
      occupied.push({
        position: hand.position,
        kind: MOUNT[device.type_id]?.kind ?? "floor",
        roomId: device.room_id,
      });
    } else {
      pending.push(device);
    }
  }
  // Counters and desks already in the original rooms count as tables.
  for (const item of DEFAULT_FURNITURE) {
    if (item.kind === "rug" || !roomsById[item.roomId]) continue;
    occupied.push({ position: item.position, kind: "floor", roomId: item.roomId });
  }

  for (const device of pending) {
    const room = roomsById[device.room_id];
    if (!room) continue;
    const mount = MOUNT[device.type_id] ?? { kind: "floor" as SlotKind, y: 0 };
    const options = candidates(room, mount.kind, mount.y);
    const free =
      options.find((option) =>
        occupied.every(
          (other) =>
            other.roomId !== room.id ||
            !sameLevel(other.kind, mount.kind) ||
            distanceXZ(other.position, option.position) >= MIN_SPACING,
        ),
      ) ?? options[placements.length % options.length];

    placements.push({
      id: device.id,
      roomId: room.id,
      position: free.position,
      rotation: free.rotation,
      ceiling: mount.kind === "ceiling",
      wall: mount.kind === "wall",
    });
    occupied.push({ position: free.position, kind: mount.kind, roomId: room.id });
    if (mount.kind === "table") {
      const height = Math.max(0.3, mount.y - 0.05);
      furniture.push({
        kind: "desk",
        position: [free.position[0], height / 2, free.position[2]],
        size: [0.9, height, 0.6],
      });
    }
  }

  const xs = rooms.flatMap((room) => room.x);
  const zs = rooms.flatMap((room) => room.z);
  const minX = xs.length ? Math.min(...xs) : -6;
  const maxX = xs.length ? Math.max(...xs) : 5;
  const minZ = zs.length ? Math.min(...zs) : -6;
  const maxZ = zs.length ? Math.max(...zs) : 4;
  return {
    rooms,
    placements,
    furniture,
    centre: [(minX + maxX) / 2, 0.6, (minZ + maxZ) / 2],
    radius: Math.max(maxX - minX, maxZ - minZ) / 2,
  };
}

/** Camera framing presets, relative to the house as currently laid out. */
export const CAMERA_PRESET_NAMES = ["isometric", "front", "top"] as const;
export type CameraPreset = (typeof CAMERA_PRESET_NAMES)[number];

export function cameraPosition(
  preset: CameraPreset,
  layout: Pick<HouseLayout, "centre" | "radius">,
): [number, number, number] {
  const [cx, , cz] = layout.centre;
  // The original 11 m house reads well from these offsets; scale for larger.
  const scale = Math.max(1, layout.radius / 5.5);
  switch (preset) {
    case "front":
      return [cx, 5.5 * scale, cz + 14 * scale];
    case "top":
      return [cx, 15 * scale, cz + 0.05];
    default:
      return [cx + 10.1 * scale, 8 * scale, cz + 10.6 * scale];
  }
}

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
