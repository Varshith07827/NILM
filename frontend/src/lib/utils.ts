import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format a power value with the right unit and sensible precision. */
export function formatPower(watts: number): { value: string; unit: string } {
  if (Math.abs(watts) >= 1000) {
    return { value: (watts / 1000).toFixed(2), unit: "kW" };
  }
  return { value: watts.toFixed(watts < 10 ? 1 : 0), unit: "W" };
}

export function formatEnergy(wh: number): { value: string; unit: string } {
  if (Math.abs(wh) >= 1000) {
    return { value: (wh / 1000).toFixed(3), unit: "kWh" };
  }
  return { value: wh.toFixed(wh < 10 ? 2 : 1), unit: "Wh" };
}

export function formatCurrency(amount: number, symbol = "₹"): string {
  const abs = Math.abs(amount);
  const decimals = abs < 10 ? 2 : abs < 1000 ? 2 : 0;
  return `${symbol}${amount.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`;
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (hours < 24) return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}

/** "18:04:21" from an ISO timestamp, without dragging in a date library. */
export function formatClock(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleTimeString("en-GB", { hour12: false });
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** Convert a hex colour to `rgba()` so charts can use translucent fills. */
export function hexToRgba(hex: string, alpha: number): string {
  const cleaned = hex.replace("#", "");
  const full =
    cleaned.length === 3
      ? cleaned
          .split("")
          .map((c) => c + c)
          .join("")
      : cleaned;
  const int = Number.parseInt(full, 16);
  const r = (int >> 16) & 255;
  const g = (int >> 8) & 255;
  const b = int & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export const percent = (value: number, digits = 1) =>
  `${(value * 100).toFixed(digits)}%`;
