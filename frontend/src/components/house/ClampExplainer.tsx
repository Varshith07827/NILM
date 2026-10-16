/**
 * "What does the clamp do?" — a short, animated explanation, opened by
 * clicking the SCT-013 clamp in the 3-D house.
 *
 * Six plain-language steps walk from the cable to the AI, each highlighting
 * one part of a single diagram. The numbers in it are live: the current in
 * the cable, the tiny current the clamp passes on, and the waveform the meter
 * is actually sampling right now.
 */

import { ChevronLeft, ChevronRight, Pause, Play, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn, formatPower } from "@/lib/utils";
import type { LiveFrame } from "@/types";

/** SCT-013-000: 100 A primary to 50 mA secondary, a 2000:1 current ratio. */
const TURNS_RATIO = 2000;
const STEP_MS = 6000;

type Part = "wire" | "field" | "clamp" | "lead" | "meter" | "ai";

interface Step {
  title: string;
  parts: Part[];
  body: (live: Live) => React.ReactNode;
}

interface Live {
  currentA: number;
  powerW: number;
  sampleRate: number;
  running: { name: string; watts: number; colour: string }[];
}

const STEPS: Step[] = [
  {
    title: "One wire carries it all",
    parts: ["wire"],
    body: ({ currentA, powerW }) => (
      <>
        Every appliance in the house gets its electricity through the one main
        cable coming in from the street. Right now it is carrying{" "}
        <Num>{currentA.toFixed(2)} A</Num> ({formatWatts(powerW)}).
      </>
    ),
  },
  {
    title: "Current makes magnetism",
    parts: ["wire", "field"],
    body: () => (
      <>
        Electricity flowing in a wire makes an invisible magnetic field around
        it. Mains current flips direction 50 times a second, so the field flips
        with it. (Slowed right down here.)
      </>
    ),
  },
  {
    title: "The clamp catches the field",
    parts: ["field", "clamp"],
    body: () => (
      <>
        The clamp is a ring of magnetic material wrapped in thin wire, a coil.
        It snaps around the cable like a clothes peg: nothing is cut, and
        nothing touches the live wire. That is what makes it{" "}
        <em>non-intrusive</em>.
      </>
    ),
  },
  {
    title: "A tiny copy comes out",
    parts: ["clamp", "lead"],
    body: ({ currentA }) => (
      <>
        The flipping field pushes a small current round the coil, the same shape
        as the real one but about {TURNS_RATIO.toLocaleString()} times smaller:{" "}
        <Num>{currentA.toFixed(2)} A</Num> in the cable becomes{" "}
        <Num>{((currentA / TURNS_RATIO) * 1000).toFixed(2)} mA</Num> in the
        clamp's lead. Safe to measure.
      </>
    ),
  },
  {
    title: "The meter reads its shape",
    parts: ["lead", "meter"],
    body: ({ sampleRate }) => (
      <>
        The edge meter (an ESP32) measures that tiny signal{" "}
        <Num>{sampleRate.toLocaleString()} times a second</Num>. This is the
        live shape it is seeing now: two mains cycles.
      </>
    ),
  },
  {
    title: "AI tells the appliances apart",
    parts: ["meter", "ai"],
    body: ({ running }) => (
      <>
        A fan, a TV and a fridge each bend that shape in their own way. The
        model reads the shape and works out what is running, all from this one
        clamp.
        {running.length ? (
          <span className="mt-2 flex flex-wrap gap-1.5">
            {running.map((device) => (
              <span
                key={device.name}
                className="rounded-md border px-1.5 py-0.5 text-[0.66rem]"
                style={{ borderColor: `${device.colour}66`, color: device.colour }}
              >
                {device.name} · {formatWatts(device.watts)}
              </span>
            ))}
          </span>
        ) : null}
      </>
    ),
  },
];

function formatWatts(watts: number) {
  const formatted = formatPower(watts);
  return `${formatted.value} ${formatted.unit}`;
}

function Num({ children }: { children: React.ReactNode }) {
  return <span className="font-mono font-semibold text-foreground">{children}</span>;
}

// --------------------------------------------------------------------------- //
// The diagram
// --------------------------------------------------------------------------- //

/** The clamp ring, an ellipse round the cable, split into halves. */
const RING_FRONT = "M330 43 A34 72 0 0 0 330 187";
const RING_BACK = "M330 43 A34 72 0 0 1 330 187";

/** Live scope samples as an SVG path inside a box. */
function scopePath(samples: number[], x: number, y: number, w: number, h: number) {
  if (samples.length < 2) return "";
  const peak = Math.max(...samples.map(Math.abs), 1e-6);
  return samples
    .map((value, index) => {
      const px = x + (index / (samples.length - 1)) * w;
      const py = y + h / 2 - (value / peak) * (h / 2) * 0.9;
      return `${index === 0 ? "M" : "L"}${px.toFixed(1)},${py.toFixed(1)}`;
    })
    .join(" ");
}

function Diagram({ step, frame }: { step: Step; frame: LiveFrame | null }) {
  const on = (part: Part) => step.parts.includes(part);
  const dim = (part: Part) => cn("transition-opacity duration-500", on(part) ? "opacity-100" : "opacity-20");
  const samples = frame?.scope.current;
  const scope = useMemo(() => scopePath(samples ?? [], 452, 158, 120, 44), [samples]);

  return (
    <svg viewBox="0 0 640 250" className="clamp-diagram h-auto w-full" role="img" aria-label={step.title}>
      {/* --- back half of the clamp ring, behind the cable ------------- */}
      <g className={dim("clamp")}>
        <path d={RING_BACK} fill="none" stroke="#1e3a8a" strokeWidth="16" strokeLinecap="round" />
      </g>

      {/* --- the mains cable ----------------------------------------- */}
      <g className={dim("wire")}>
        <rect x="0" y="104" width="640" height="22" rx="11" fill="#78350f" />
        <rect x="0" y="108" width="640" height="14" rx="7" fill="#d97706" />
        {/* current flowing back and forth */}
        <line
          x1="0"
          y1="115"
          x2="640"
          y2="115"
          stroke="#fde68a"
          strokeWidth="4"
          strokeDasharray="10 22"
          className="flow-ac"
        />
        <text x="12" y="94" className="fill-slate-400 text-[11px]">
          main cable · from the street
        </text>
      </g>

      {/* --- the magnetic field around the wire ----------------------- */}
      <g className={dim("field")}>
        {[0, 1, 2].map((ring) => (
          <ellipse
            key={ring}
            cx="180"
            cy="115"
            rx={14 + ring * 9}
            ry={34 + ring * 20}
            fill="none"
            stroke="#a78bfa"
            strokeWidth="2"
            className="field-ring"
            style={{ animationDelay: `${ring * 0.18}s` }}
          />
        ))}
        <text x="140" y="30" className="fill-violet-300 text-[11px]">
          magnetic field
        </text>
      </g>

      {/* --- the clamp: a ring with a coil, closed round the cable ---- */}
      <g className={dim("clamp")}>
        <path d={RING_FRONT} fill="none" stroke="#1d4ed8" strokeWidth="16" strokeLinecap="round" />
        <path d={RING_FRONT} fill="none" stroke="#3b82f6" strokeWidth="5" strokeLinecap="round" className="clamp-glow" />
        {/* coil turns on the core */}
        {Array.from({ length: 9 }).map((_, index) => (
          <line
            key={index}
            x1={304 + index * 6.5}
            y1="34"
            x2={300 + index * 6.5}
            y2="56"
            stroke="#e2e8f0"
            strokeWidth="2"
          />
        ))}
        <text x="290" y="20" className="fill-blue-300 text-[11px]">
          SCT-013 clamp
        </text>
      </g>

      {/* --- the lead to the meter: a tiny copy of the current -------- */}
      <g className={dim("lead")}>
        <path d="M330 187 L330 222 L440 222" fill="none" stroke="#0f172a" strokeWidth="5" />
        <path
          d="M330 187 L330 222 L440 222"
          fill="none"
          stroke="#93c5fd"
          strokeWidth="2"
          strokeDasharray="4 10"
          className="flow-ac"
        />
        <text x="342" y="214" className="fill-sky-300 text-[10px]">
          tiny copy (÷{TURNS_RATIO})
        </text>
      </g>

      {/* --- the edge meter with the live waveform -------------------- */}
      <g className={dim("meter")}>
        <rect x="440" y="140" width="144" height="94" rx="10" fill="#1e293b" stroke="#334155" />
        <rect x="452" y="154" width="120" height="52" rx="4" fill="#082f49" />
        <path d={scope} fill="none" stroke="#22d3ee" strokeWidth="1.8" />
        <text x="452" y="224" className="fill-cyan-300 text-[10px]">
          edge meter · ESP32
        </text>
      </g>

      {/* --- the AI ---------------------------------------------------- */}
      <g className={dim("ai")}>
        <path d="M584 187 L612 187 L612 120" fill="none" stroke="#c084fc" strokeWidth="2" strokeDasharray="3 5" />
        <circle cx="612" cy="98" r="20" fill="#3b0764" stroke="#c084fc" strokeWidth="2" />
        <text x="612" y="103" textAnchor="middle" className="fill-fuchsia-200 text-[12px] font-semibold">
          AI
        </text>
      </g>
    </svg>
  );
}

// --------------------------------------------------------------------------- //
// The panel
// --------------------------------------------------------------------------- //

export function ClampExplainer({
  frame,
  onClose,
}: {
  frame: LiveFrame | null;
  onClose: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(true);
  const step = STEPS[index];

  useEffect(() => {
    if (!playing) return;
    const timer = window.setTimeout(
      () => setIndex((value) => (value + 1) % STEPS.length),
      STEP_MS,
    );
    return () => window.clearTimeout(timer);
  }, [index, playing]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowRight") setIndex((value) => Math.min(STEPS.length - 1, value + 1));
      if (event.key === "ArrowLeft") setIndex((value) => Math.max(0, value - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const live: Live = {
    currentA: frame?.measurement.current_a ?? 0,
    powerW: frame?.measurement.power_w ?? 0,
    sampleRate: frame?.scope.sample_rate_hz ?? 2000,
    running: (frame?.appliances ?? [])
      .filter((device) => device.detected)
      .sort((a, b) => b.estimated_power_w - a.estimated_power_w)
      .slice(0, 6)
      .map((device) => ({
        name: device.name,
        watts: device.estimated_power_w,
        colour: device.colour,
      })),
  };

  const go = (next: number) => {
    setPlaying(false);
    setIndex(Math.max(0, Math.min(STEPS.length - 1, next)));
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/70 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="clamp-explainer-title"
    >
      <style>{`
        .clamp-diagram .flow-ac { animation: clamp-ac 1.2s ease-in-out infinite alternate; }
        .clamp-diagram .field-ring { animation: clamp-field 1.2s ease-in-out infinite alternate; transform-origin: 180px 115px; transform-box: view-box; }
        .clamp-diagram .clamp-glow { animation: clamp-glow 1.2s ease-in-out infinite alternate; }
        @keyframes clamp-ac { from { stroke-dashoffset: 0; } to { stroke-dashoffset: 64; } }
        @keyframes clamp-field { from { opacity: 0.15; transform: scale(0.9); } to { opacity: 1; transform: scale(1.06); } }
        @keyframes clamp-glow { from { opacity: 0.2; } to { opacity: 1; } }
        @media (prefers-reduced-motion: reduce) {
          .clamp-diagram .flow-ac, .clamp-diagram .field-ring, .clamp-diagram .clamp-glow { animation: none; }
        }
      `}</style>

      <div
        className="w-full max-w-2xl rounded-xl border border-border/70 bg-card p-5 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="label-muted">
              How the clamp works · {index + 1} of {STEPS.length}
            </p>
            <h2 id="clamp-explainer-title" className="mt-0.5 text-base font-bold tracking-tight">
              {step.title}
            </h2>
          </div>
          <Button size="icon-sm" variant="ghost" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="mt-3 rounded-lg border border-border/50 bg-background/60 p-2">
          <Diagram step={step} frame={frame} />
        </div>

        <p className="mt-3 min-h-[4.5rem] text-[0.8rem] leading-relaxed text-muted-foreground">
          {step.body(live)}
        </p>

        <div className="mt-3 flex items-center justify-between gap-2">
          <div className="flex gap-1.5">
            {STEPS.map((item, position) => (
              <button
                key={item.title}
                type="button"
                onClick={() => go(position)}
                aria-label={`Step ${position + 1}: ${item.title}`}
                className={cn(
                  "h-1.5 rounded-full transition-all",
                  position === index ? "w-6 bg-primary" : "w-1.5 bg-muted-foreground/40 hover:bg-muted-foreground",
                )}
              />
            ))}
          </div>
          <div className="flex gap-1.5">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setPlaying((value) => !value)}
              aria-label={playing ? "Pause" : "Play"}
            >
              {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            </Button>
            <Button size="sm" variant="outline" disabled={index === 0} onClick={() => go(index - 1)}>
              <ChevronLeft className="h-3.5 w-3.5" />
              Back
            </Button>
            <Button
              size="sm"
              disabled={index === STEPS.length - 1}
              onClick={() => go(index + 1)}
            >
              Next
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
