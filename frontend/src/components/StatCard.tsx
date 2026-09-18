import type { LucideIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Card } from "@/components/ui/card";
import { InfoTip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface StatCardProps {
  label: string;
  value: string;
  unit?: string;
  icon: LucideIcon;
  /** Accent colour for the icon chip and the sparkline. */
  accent?: string;
  hint?: string;
  sub?: React.ReactNode;
  /** 0..1, renders a thin progress rail along the bottom of the card. */
  fill?: number;
  className?: string;
}

/**
 * A headline metric.
 *
 * The value flashes briefly whenever it changes. That is doing real work on a
 * dashboard where several numbers update at different rates: without it, a
 * viewer cannot tell which figures are live and which are static totals.
 */
export function StatCard({
  label,
  value,
  unit,
  icon: Icon,
  accent = "hsl(var(--primary))",
  hint,
  sub,
  fill,
  className,
}: StatCardProps) {
  const [flash, setFlash] = useState(false);
  const previous = useRef(value);

  useEffect(() => {
    if (previous.current === value) return;
    previous.current = value;
    setFlash(true);
    const timer = window.setTimeout(() => setFlash(false), 320);
    return () => window.clearTimeout(timer);
  }, [value]);

  const body = (
    <Card
      className={cn(
        "group relative overflow-hidden p-4 transition-transform duration-200 hover:-translate-y-0.5",
        className,
      )}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -right-8 -top-10 h-24 w-24 rounded-full opacity-[0.11] blur-2xl transition-opacity group-hover:opacity-20"
        style={{ background: accent }}
      />

      <div className="flex items-start justify-between gap-2">
        <span className="label-muted">{label}</span>
        <span
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
          style={{ background: `${accent}1f`, color: accent }}
        >
          <Icon className="h-3.5 w-3.5" />
        </span>
      </div>

      <div className="mt-2.5 flex items-baseline gap-1.5">
        <span
          className={cn(
            "stat-value transition-colors duration-200",
            flash && "text-primary",
          )}
        >
          {value}
        </span>
        {unit ? (
          <span className="text-xs font-medium text-muted-foreground">
            {unit}
          </span>
        ) : null}
      </div>

      {sub ? (
        <div className="mt-1 text-[0.7rem] leading-tight text-muted-foreground">
          {sub}
        </div>
      ) : null}

      {fill !== undefined ? (
        <div className="absolute inset-x-0 bottom-0 h-[3px] bg-secondary/60">
          <div
            className="h-full rounded-r-full transition-[width] duration-500 ease-out"
            style={{
              width: `${Math.min(100, Math.max(0, fill * 100))}%`,
              background: accent,
            }}
          />
        </div>
      ) : null}
    </Card>
  );

  if (!hint) return body;
  return (
    <InfoTip label={hint}>
      <div>{body}</div>
    </InfoTip>
  );
}
